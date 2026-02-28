"""
AURA Flask API - Backend for React Dashboard

Endpoints:
- GET  /api/status, /api/metrics, /api/history
- POST /api/panic, /api/recalibrate
- GET  /api/config, /api/sunburn, /api/postmortem, /api/recovery
- POST /api/config, /api/grayscale
"""

import os
import json
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, jsonify, request
from flask_cors import CORS

from monitor import AuraMonitor, FatigueMetrics

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

# ---- Paths ----
DATA_DIR = Path(os.environ.get("AURA_DATA_DIR", Path.home() / ".aura"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "aura.duckdb"
CONFIG_PATH = DATA_DIR / "config.json"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"])

_monitor: AuraMonitor | None = None
_monitor_lock = threading.Lock()
_panic_until: datetime | None = None
_last_auto_grayscale: float = 0
_last_critical_webhook: float = 0
_config: dict = {}


def _load_config() -> dict:
    global _config
    if not CONFIG_PATH.exists():
        _config = {
            "enforcement_level": "medium",
            "baseline_minutes": 5,
            "webhook_url": "",
            "grayscale_enabled": False,
            "cognitive_load_overrides": {},
        }
        return _config
    try:
        with open(CONFIG_PATH) as f:
            _config = json.load(f)
    except Exception:
        _config = {}
    return _config


def _save_config(c: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(c, f, indent=2)


def _load_baseline() -> tuple[float | None, float | None]:
    if not DUCKDB_AVAILABLE:
        return None, None
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        row = con.execute(
            "SELECT latency_std, error_rate FROM baseline ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        con.close()
        if row:
            return float(row[0]), float(row[1])
    except Exception:
        pass
    return None, None


def _store_baseline(latency_std: float, error_rate: float):
    if not DUCKDB_AVAILABLE:
        return
    try:
        con = duckdb.connect(str(DB_PATH))
        con.execute(
            "INSERT INTO baseline (ts, latency_std, error_rate) VALUES (?, ?, ?)",
            [datetime.utcnow().isoformat(), latency_std, error_rate],
        )
        con.close()
    except Exception:
        pass


def _on_baseline_complete(latency_std: float, error_rate: float):
    _store_baseline(latency_std, error_rate)


def _get_monitor() -> AuraMonitor:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            bl_std, bl_err = _load_baseline()
            cfg = _load_config()
            _monitor = AuraMonitor(
                baseline_mode_minutes=cfg.get("baseline_minutes", 5),
                baseline_latency_std=bl_std,
                baseline_error_rate=bl_err,
                cognitive_load_overrides=lambda: _load_config().get("cognitive_load_overrides", {}),
            )
            _monitor._on_baseline_complete = _on_baseline_complete
            _monitor.start()
        return _monitor


def _init_db():
    if not DUCKDB_AVAILABLE:
        return
    con = duckdb.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            ts TIMESTAMP,
            fatigue_score REAL,
            latency_std REAL,
            latency_mean REAL,
            error_rate REAL,
            context_switches_per_min REAL,
            total_keystrokes INT,
            backspace_count INT,
            last_window VARCHAR,
            is_baseline BOOLEAN,
            cognitive_load REAL,
            fuel_gauge REAL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS baseline (
            ts TIMESTAMP,
            latency_std REAL,
            error_rate REAL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS panic_events (
            ts TIMESTAMP
        )
    """)
    # Migration: add columns to existing metrics table if missing
    for col in ("cognitive_load", "fuel_gauge"):
        try:
            con.execute(f"ALTER TABLE metrics ADD COLUMN {col} REAL")
        except Exception:
            pass
    con.close()


def _store_metrics(m: FatigueMetrics):
    if not DUCKDB_AVAILABLE:
        return
    try:
        con = duckdb.connect(str(DB_PATH))
        con.execute(
            """
            INSERT INTO metrics
            (ts, fatigue_score, latency_std, latency_mean, error_rate,
             context_switches_per_min, total_keystrokes, backspace_count,
             last_window, is_baseline, cognitive_load, fuel_gauge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                datetime.utcnow().isoformat(),
                m.fatigue_score,
                m.keystroke_latency_std,
                m.keystroke_latency_mean,
                m.error_rate_proxy,
                m.context_switches_per_min,
                m.total_keystrokes,
                m.backspace_count,
                m.last_window,
                m.is_baseline_mode,
                m.cognitive_load_index,
                m.fuel_gauge,
            ],
        )
        con.close()
    except Exception:
        pass


def _fire_webhook(url: str, payload: dict):
    if not url:
        return
    try:
        import urllib.request
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


WEBHOOK_COOLDOWN_SEC = 600

def _maybe_fire_webhook(m: FatigueMetrics):
    global _last_critical_webhook
    cfg = _load_config()
    url = cfg.get("webhook_url", "").strip()
    if not url or m.fatigue_score < 85 or m.is_baseline_mode:
        return
    now = time.time()
    if now - _last_critical_webhook < WEBHOOK_COOLDOWN_SEC:
        return
    _fire_webhook(url, {
        "event": "aura_critical_fatigue",
        "fatigue_score": m.fatigue_score,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _last_critical_webhook = now


def _trigger_grayscale_key():
    """Send Win+Ctrl+C to toggle Color Filters."""
    try:
        from pynput.keyboard import Key, Controller
        ctrl = Controller()
        with ctrl.pressed(Key.cmd, Key.ctrl):
            ctrl.press("c")
            ctrl.release("c")
        return True
    except Exception:
        return False


def _maybe_auto_grayscale(m: FatigueMetrics):
    """Auto-enable grayscale at critical fatigue (respects enforcement level)."""
    global _last_auto_grayscale
    cfg = _load_config()
    if cfg.get("grayscale_enabled"):
        return
    level = cfg.get("enforcement_level", "medium")
    if level == "low":
        return
    threshold = 80 if level == "high" else 90
    if m.fatigue_score < threshold or m.is_baseline_mode:
        return
    if _panic_until and datetime.utcnow() < _panic_until:
        return
    now = time.time()
    if now - _last_auto_grayscale < 1800:
        return
    if _trigger_grayscale_key():
        _last_auto_grayscale = now
        cfg["grayscale_enabled"] = True
        _save_config(cfg)


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"status": "ok", "monitor": "running"})


@app.route("/api/metrics", methods=["GET"])
def metrics():
    m = _get_monitor().get_metrics()
    _store_metrics(m)
    global _panic_until
    panic_active = _panic_until is not None and datetime.utcnow() < _panic_until
    _maybe_fire_webhook(m)
    _maybe_auto_grayscale(m)

    cfg = _load_config()
    sludge_active = (
        not panic_active
        and cfg.get("enforcement_level") == "high"
        and m.fatigue_score >= 70
        and not m.is_baseline_mode
    )
    if sludge_active:
        time.sleep(1.0)

    out = {
        "fatigue_score": m.fatigue_score,
        "keystroke_latency_std_ms": m.keystroke_latency_std,
        "keystroke_latency_mean_ms": m.keystroke_latency_mean,
        "error_rate_proxy": m.error_rate_proxy,
        "total_keystrokes": m.total_keystrokes,
        "backspace_count": m.backspace_count,
        "context_switches_per_min": m.context_switches_per_min,
        "last_window": m.last_window,
        "is_baseline_mode": m.is_baseline_mode,
        "cognitive_load_index": m.cognitive_load_index,
        "cognitive_load_label": m.cognitive_load_label,
        "micro_scroll_trap_detected": m.micro_scroll_trap_detected,
        "scroll_rate_per_min": m.scroll_rate_per_min,
        "fuel_gauge": m.fuel_gauge,
        "idle_detected": m.idle_detected,
        "idle_minutes": m.idle_minutes,
        "session_active_minutes": m.session_active_minutes,
        "hold_duration_mean_ms": m.hold_duration_mean_ms,
        "hold_duration_std_ms": m.hold_duration_std_ms,
        "time_of_day_factor": m.time_of_day_factor,
        "panic_override_active": panic_active,
        "panic_until": _panic_until.isoformat() if _panic_until else None,
        "sludge_active": sludge_active,
    }
    return jsonify(out)


@app.route("/api/history", methods=["GET"])
def history():
    if not DUCKDB_AVAILABLE:
        return jsonify({"history": [], "error": "DuckDB not available"})
    try:
        hours = max(1, min(168, int(request.args.get("hours", 24))))
        con = duckdb.connect(str(DB_PATH), read_only=True)
        rows = con.execute(
            f"""
            SELECT ts, fatigue_score, latency_std, context_switches_per_min, fuel_gauge
            FROM metrics
            WHERE ts >= current_timestamp - INTERVAL '{hours} hours'
            ORDER BY ts DESC
            LIMIT 500
            """
        ).fetchall()
        con.close()
        history = [
            {
                "ts": str(r[0]),
                "fatigue_score": r[1],
                "latency_std": r[2],
                "context_switches_per_min": r[3],
                "fuel_gauge": r[4],
            }
            for r in rows
        ]
        return jsonify({"history": history})
    except Exception as e:
        return jsonify({"history": [], "error": str(e)}), 500


def _store_panic_event():
    if not DUCKDB_AVAILABLE:
        return
    try:
        con = duckdb.connect(str(DB_PATH))
        con.execute(
            "INSERT INTO panic_events (ts) VALUES (?)",
            [datetime.utcnow().isoformat()],
        )
        con.close()
    except Exception:
        pass


@app.route("/api/panic", methods=["POST"])
def panic():
    global _panic_until
    _panic_until = datetime.utcnow() + timedelta(minutes=15)
    _store_panic_event()
    cfg = _load_config()
    url = cfg.get("webhook_url", "").strip()
    _fire_webhook(url, {
        "event": "aura_panic_used",
        "message": "User activated 15-min override",
        "timestamp": datetime.utcnow().isoformat(),
    })
    return jsonify({
        "ok": True,
        "panic_until": _panic_until.isoformat(),
        "message": "Override active for 15 minutes (Social tax: buddy pinged if webhook set)",
    })


@app.route("/api/recalibrate", methods=["POST"])
def recalibrate():
    """Clear baseline and force a new 5-min calibration."""
    global _monitor
    with _monitor_lock:
        if _monitor:
            _monitor.stop()
            _monitor = None
        cfg = _load_config()
        _monitor = AuraMonitor(
            baseline_mode_minutes=cfg.get("baseline_minutes", 5),
            baseline_latency_std=None,
            baseline_error_rate=None,
            cognitive_load_overrides=lambda: _load_config().get("cognitive_load_overrides", {}),
        )
        _monitor._on_baseline_complete = _on_baseline_complete
        _monitor.start()
    return jsonify({"ok": True, "message": "Recalibrating. Use the app for 5 min to set new baseline."})


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = _load_config()
    return jsonify({
        "enforcement_level": cfg.get("enforcement_level", "medium"),
        "baseline_minutes": cfg.get("baseline_minutes", 5),
        "webhook_url": cfg.get("webhook_url", ""),
        "grayscale_enabled": cfg.get("grayscale_enabled", False),
        "cognitive_load_overrides": cfg.get("cognitive_load_overrides", {}),
    })


@app.route("/api/config", methods=["POST"])
def post_config():
    cfg = _load_config()
    data = request.get_json() or {}
    for k in ("enforcement_level", "webhook_url", "cognitive_load_overrides"):
        if k in data:
            v = data[k]
            cfg[k] = v if k != "cognitive_load_overrides" or isinstance(v, dict) else {}
    if "baseline_minutes" in data:
        cfg["baseline_minutes"] = max(1, min(60, int(data["baseline_minutes"])))
    _save_config(cfg)
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/sunburn", methods=["GET"])
def sunburn():
    """Predictive Digital Sunburn: tomorrow's productivity loss from today's overwork."""
    if not DUCKDB_AVAILABLE:
        return jsonify({"predicted_loss_pct": 0, "error": "DuckDB not available"})
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        rows = con.execute("""
            SELECT AVG(fatigue_score) as avg_fatigue,
                   COUNT(*) as samples,
                   MIN(ts) as first_ts,
                   MAX(ts) as last_ts
            FROM metrics
            WHERE ts >= current_date
              AND is_baseline = 0
        """).fetchone()
        panic_count = 0
        try:
            panic_count = con.execute("""
                SELECT COUNT(*) FROM panic_events
                WHERE ts >= current_date
            """).fetchone()[0] or 0
        except Exception:
            pass
        con.close()
        if not rows or rows[1] < 10:
            return jsonify({"predicted_loss_pct": 0, "message": "Not enough data today"})
        avg_fatigue, samples, first_ts, last_ts = rows
        duration_hours = (last_ts - first_ts).total_seconds() / 3600 if first_ts and last_ts else 0
        loss = 0.0
        if duration_hours > 6 and avg_fatigue > 50:
            loss += min(15, (duration_hours - 6) * 2)
        if avg_fatigue > 70:
            loss += min(20, (avg_fatigue - 70) * 0.5)
        loss += panic_count * 5
        return jsonify({
            "predicted_loss_pct": round(min(40, loss), 1),
            "avg_fatigue_today": round(float(avg_fatigue or 0), 1),
            "session_hours_today": round(float(duration_hours or 0), 1),
            "panic_uses_today": panic_count,
        })
    except Exception as e:
        return jsonify({"predicted_loss_pct": 0, "error": str(e)})


@app.route("/api/postmortem", methods=["GET"])
def postmortem():
    """Post-mortem: KPM, hours worked, cost of overwork."""
    if not DUCKDB_AVAILABLE:
        return jsonify({"error": "DuckDB not available"})
    try:
        days = max(1, min(7, int(request.args.get("days", 7))))
        con = duckdb.connect(str(DB_PATH), read_only=True)
        rows = con.execute(f"""
            SELECT DATE(ts) as d,
                   SUM(total_keystrokes) as keys,
                   MIN(ts) as first_ts,
                   MAX(ts) as last_ts,
                   AVG(fatigue_score) as avg_fatigue
            FROM metrics
            WHERE ts >= current_date - INTERVAL '{days} days'
            GROUP BY DATE(ts)
            ORDER BY d DESC
        """).fetchall()
        con.close()
        result = []
        for r in rows:
            d, keys, first_ts, last_ts, avg_fat = r
            duration_h = (last_ts - first_ts).total_seconds() / 3600 if first_ts and last_ts else 0
            kpm = (keys / 60) / duration_h if duration_h > 0.1 else 0
            result.append({
                "date": str(d),
                "keystrokes": int(keys or 0),
                "hours_worked": round(float(duration_h or 0), 2),
                "kpm": round(float(kpm), 1),
                "avg_fatigue": round(float(avg_fat or 0), 1),
            })
        return jsonify({"postmortem": result})
    except Exception as e:
        return jsonify({"postmortem": [], "error": str(e)}), 500


@app.route("/api/recovery", methods=["GET"])
def recovery():
    """Contextual recovery prescriptions based on fatigue type."""
    m = _get_monitor().get_metrics()
    prescriptions = []
    if m.micro_scroll_trap_detected:
        prescriptions.append({
            "type": "analog_break",
            "title": "Analog Break",
            "description": "You're in scroll mode. Step away from the screen for 5 minutes.",
        })
    if m.context_switches_per_min > 10:
        prescriptions.append({
            "type": "single_focus",
            "title": "Single-Focus Task",
            "description": "High context switching. Pick one task and stick to it for 25 min.",
        })
    if m.error_rate_proxy > 0.12:
        prescriptions.append({
            "type": "hand_rest",
            "title": "Hand & Eye Rest",
            "description": "High error rate. Rest your hands, blink, look at something 20ft away.",
        })
    if m.fatigue_score > 60:
        prescriptions.append({
            "type": "short_break",
            "title": "Short Break",
            "description": "Fatigue detected. Take a 10-minute break—walk, stretch, or hydrate.",
        })
    if not prescriptions:
        prescriptions.append({
            "type": "ok",
            "title": "On Track",
            "description": "No specific recovery needed right now.",
        })
    return jsonify({"prescriptions": prescriptions[:3]})


@app.route("/api/todos", methods=["GET"])
def todos_list():
    """Energy-based to-do list, re-ordered by current capacity."""
    from todos import get_todos as _get_todos
    m = _get_monitor().get_metrics()
    items = _get_todos(m.fatigue_score, m.fuel_gauge)
    return jsonify({"todos": items})


@app.route("/api/todos", methods=["POST"])
def post_todo():
    from todos import add_todo
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    t = add_todo(
        title,
        effort=data.get("effort", 2),
        impact=data.get("impact", 2),
    )
    return jsonify({"ok": True, "todo": t})


@app.route("/api/todos/<todo_id>", methods=["PATCH"])
def toggle_todo(todo_id):
    from todos import toggle_todo as _toggle
    if _toggle(todo_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/todos/<todo_id>", methods=["DELETE"])
def delete_todo(todo_id):
    from todos import delete_todo as _delete
    if _delete(todo_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/grayscale", methods=["POST"])
def grayscale():
    """
    Toggle grayscale via Win+Ctrl+C (Windows Color Filters).
    """
    data = request.get_json() or {}
    enable = data.get("enable", True)
    cfg = _load_config()
    old_state = cfg.get("grayscale_enabled", False)

    if enable != old_state and _trigger_grayscale_key():
        cfg["grayscale_enabled"] = bool(enable)
        _save_config(cfg)
    elif enable != old_state:
        return jsonify({"ok": False, "error": "Could not toggle grayscale"}), 500

    return jsonify({"ok": True, "grayscale_enabled": cfg.get("grayscale_enabled", False)})


if __name__ == "__main__":
    _init_db()
    _load_config()
    print("AURA Backend at http://127.0.0.1:5000")
    print("API: /api/metrics, /api/history, /api/panic, /api/recalibrate")
    print("     /api/sunburn, /api/postmortem, /api/recovery, /api/grayscale")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
