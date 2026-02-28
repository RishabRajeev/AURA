"""
AURA Flask API - Backend for React Dashboard

Endpoints:
- GET /api/status     - Health check
- GET /api/metrics    - Current fatigue & context-switch metrics
- GET /api/history    - Historical metrics (from DuckDB)
- POST /api/panic     - Emergency escape hatch (15 min override)
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, jsonify, request
from flask_cors import CORS

from monitor import AuraMonitor, FatigueMetrics

# ---- DuckDB (optional, graceful degradation if not installed) ----
try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

# ---- Paths ----
DATA_DIR = Path(os.environ.get("AURA_DATA_DIR", Path.home() / ".aura"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "aura.duckdb"

# ---- Flask app ----
app = Flask(__name__)
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"])

# ---- Global monitor (started on first request or explicitly) ----
_monitor: AuraMonitor | None = None
_monitor_lock = threading.Lock()
_panic_until: datetime | None = None


def _get_monitor() -> AuraMonitor:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = AuraMonitor(baseline_mode_minutes=30)
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
            is_baseline BOOLEAN
        )
    """)
    con.close()


def _store_metrics(m: FatigueMetrics):
    if not DUCKDB_AVAILABLE:
        return
    try:
        con = duckdb.connect(str(DB_PATH))
        con.execute(
            """
            INSERT INTO metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ],
        )
        con.close()
    except Exception:
        pass


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"status": "ok", "monitor": "running"})


@app.route("/api/metrics", methods=["GET"])
def metrics():
    m = _get_monitor().get_metrics()
    _store_metrics(m)
    global _panic_until
    panic_active = _panic_until is not None and datetime.utcnow() < _panic_until
    return jsonify({
        "fatigue_score": m.fatigue_score,
        "keystroke_latency_std_ms": m.keystroke_latency_std,
        "keystroke_latency_mean_ms": m.keystroke_latency_mean,
        "error_rate_proxy": m.error_rate_proxy,
        "total_keystrokes": m.total_keystrokes,
        "backspace_count": m.backspace_count,
        "context_switches_per_min": m.context_switches_per_min,
        "last_window": m.last_window,
        "is_baseline_mode": m.is_baseline_mode,
        "panic_override_active": panic_active,
        "panic_until": _panic_until.isoformat() if _panic_until else None,
    })


@app.route("/api/history", methods=["GET"])
def history():
    if not DUCKDB_AVAILABLE:
        return jsonify({"history": [], "error": "DuckDB not available"})
    try:
        hours = max(1, min(168, int(request.args.get("hours", 24))))
        con = duckdb.connect(str(DB_PATH), read_only=True)
        # Use validated hours (1-168) for safe query construction
        rows = con.execute(
            f"""
            SELECT ts, fatigue_score, latency_std, context_switches_per_min
            FROM metrics
            WHERE ts >= current_timestamp - INTERVAL '{hours} hours'
            ORDER BY ts DESC
            LIMIT 500
            """
        ).fetchall()
        con.close()
        history = [
            {
                "ts": r[0],
                "fatigue_score": r[1],
                "latency_std": r[2],
                "context_switches_per_min": r[3],
            }
            for r in rows
        ]
        return jsonify({"history": history})
    except Exception as e:
        return jsonify({"history": [], "error": str(e)}), 500


@app.route("/api/panic", methods=["POST"])
def panic():
    """Emergency escape hatch: 15-minute override of interventions."""
    global _panic_until
    _panic_until = datetime.utcnow() + timedelta(minutes=15)
    return jsonify({
        "ok": True,
        "panic_until": _panic_until.isoformat(),
        "message": "Override active for 15 minutes",
    })


@app.route("/api/config", methods=["GET"])
def config():
    """Current enforcement level / config (stub for MVP)."""
    return jsonify({
        "enforcement_level": "medium",
        "baseline_minutes": 30,
    })


# ---- Startup ----
if __name__ == "__main__":
    _init_db()
    print("AURA Backend starting at http://127.0.0.1:5000")
    print("API: GET /api/metrics, /api/history, POST /api/panic")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
