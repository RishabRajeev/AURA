# AURA — Cognitive Burnout Monitor

A privacy-first, AI-powered desktop monitor that detects cognitive burnout and focus decay through behavioral biometrics. Unlike standard timers, AURA identifies the "Fatigue Signature" (motor and cognitive decay) and uses "Positive Friction" interventions to protect the user's mental energy.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Tech Stack](#tech-stack)
3. [Architecture Overview](#architecture-overview)
4. [Detection Features (The AI Brain)](#detection-features-the-ai-brain)
5. [Intervention Features](#intervention-features)
6. [Recovery & Productivity Features](#recovery--productivity-features)
7. [Ethics & Privacy](#ethics--privacy)
8. [Data Model & Storage](#data-model--storage)
9. [API Reference](#api-reference)
10. [Frontend Implementation](#frontend-implementation)
11. [Project Structure](#project-structure)
12. [Deferred / Future Work](#deferred--future-work)

---

## Quick Start

### Backend (Python Flask)

```bash
cd AURA/backend
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python server/app.py
```

Backend runs at **http://127.0.0.1:5000**

**Permissions:** On Windows, run as Administrator if keystroke capture fails. On macOS, grant Accessibility permissions in System Preferences.

### Frontend (React + Vite)

```bash
cd AURA/frontend
npm install
npm run dev
```

Dashboard runs at **http://localhost:3000**

The Vite dev server proxies `/api/*` to the Flask backend automatically—no CORS configuration needed.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.x, Flask 3+, Flask-CORS |
| **Input Capture** | pynput (keyboard + mouse) |
| **Window Tracking** | pywinctl (fallback: pygetwindow) |
| **Database** | DuckDB (embedded, file-based) |
| **Frontend** | React 18, Vite 5 |
| **Data Dir** | `~/.aura/` (or `%USERPROFILE%\.aura\` on Windows) |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  React Dashboard (localhost:3000)                                │
│  - Polls /api/metrics every 3s                                   │
│  - Browser notifications when fatigue ≥ 70                       │
│  - Vite proxy: /api → http://127.0.0.1:5000                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────────┐
│  Flask API (port 5000)                                            │
│  - Lazy-starts AuraMonitor on first /api/metrics                  │
│  - Stores metrics to DuckDB on each request                      │
│  - Runs interventions (webhook, auto-grayscale, sludge)          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  AuraMonitor (monitor.py)                                         │
│  - pynput: keyboard on_press/on_release, mouse on_scroll/on_click  │
│  - pywinctl: active window poll every 2s                          │
│  - Threaded: fatigue, hold, scroll, context, idle                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  DuckDB (aura.duckdb) + config.json + todos.json                  │
└───────────────────────────────────────────────────────────────────┘
```

---

## Detection Features (The AI Brain)

All detection runs locally. No keystroke content is logged—only timing and aggregate counts.

### 1. Fatigue Signature

**Purpose:** Detect cognitive and motor decay through typing rhythm and error rate.

**Implementation:**
- **`FatigueSignatureTracker`** (`monitor.py`): Listens to `keyboard.Listener(on_press)`. Records inter-keystroke intervals (ms) in a rolling deque of 50 samples.
- **Modifier filtering:** Ctrl, Alt, Shift, Win are excluded from latency—chord combos (e.g. Ctrl+C) distort typing rhythm.
- **Latency window:** Only intervals between 20 ms and 2000 ms are counted (filters outliers).
- **Metrics computed:** `std_dev(latencies)`, `mean(latencies)`, `error_rate = backspaces / total_keystrokes`.
- **Fatigue contribution:** When `std_dev` exceeds 1.2× baseline → up to +30. When `error_rate` exceeds 1.5× baseline → up to +20.

### 2. Hold Duration

**Purpose:** Key press-to-release timing indicates motor fatigue (slower finger release).

**Implementation:**
- **`HoldDurationTracker`**: Uses `keyboard.Listener(on_press, on_release)`. Stores press time per key; on release, computes hold duration.
- Holds between 10 ms and 2000 ms are kept; rolling window of 50.
- **Fatigue contribution:** If `hold_std` exceeds 1.3× baseline hold std → up to +10.

### 3. Context-Switch Tracking

**Purpose:** High app/window switching = fragmented attention.

**Implementation:**
- **`ContextSwitchTracker`**: Polls `pywinctl.getActiveWindow().title` every 2 seconds in `_poll_loop`.
- When window title changes, appends timestamp to deque. Counts switches in last 60 seconds.
- **Fatigue contribution:** If switches/min > 8 → up to +20 (scaled).

### 4. Micro-Scroll Trap

**Purpose:** "Zombie mode"—lots of scrolling without meaningful interaction.

**Implementation:**
- **`MicroScrollTrapTracker`**: `mouse.Listener(on_scroll)` records scroll events. Rolling 2-minute window.
- Threshold: 25 scrolls/minute = trap detected. Keystrokes/clicks don't reset scroll count but indicate engagement (we don't subtract).
- **Fatigue contribution:** +12 when trap is active.

### 5. Cognitive Load Index

**Purpose:** Classify active app as high/medium/passive load for fuel-gauge weighting.

**Implementation:**
- Window title is matched against keyword lists:
  - **High:** VS Code, Cursor, PyCharm, terminal, Notion, Obsidian, Jupyter, MATLAB, Postman, etc.
  - **Passive:** YouTube, Netflix, Twitter, Reddit, Instagram, TikTok, Spotify, etc.
  - **Medium:** Slack, Chrome, Gmail, Figma, etc.
- **User overrides:** Config JSON supports `cognitive_load_overrides: { "Figma": "medium", "MyApp": "high" }`. Overrides take precedence.
- Returns load index 0–1 and label. Used in `_compute_fuel_gauge()`.

### 6. Idle / Absence Detection

**Purpose:** No input for 10+ minutes = zoning out or deep reading.

**Implementation:**
- **`IdleTracker`**: `on_activity()` called on every key press, scroll, or click. Stores `_last_activity`.
- `is_idle_detected()` when elapsed > 600 seconds (10 min).
- **Fatigue contribution:** +10 when idle detected.

### 7. Session Duration

**Purpose:** Long sessions increase fatigue score (cumulative load).

**Implementation:**
- `session_active_minutes = (now - _session_start) / 60`.
- **Fatigue contribution:** 60–120 min → up to +8; 120+ min → up to +15.

### 8. Time-of-Day Weighting

**Purpose:** Circadian low (late night) amplifies fatigue.

**Implementation:**
- **`_get_time_of_day_factor()`**: Returns 1.0 (10–18h), 1.05 (6–10h, 18–22h), 1.25 (22–6h).
- Final fatigue score is multiplied by this factor.

### 9. Baseline Calibration

**Purpose:** Personalize thresholds; avoid fixed cutoffs.

**Implementation:**
- First N minutes (default 5, configurable) after startup with no stored baseline: `is_baseline_mode = True`, fatigue score = 0.
- When elapsed ≥ baseline_minutes: stores `latency_std`, `error_rate`, `hold_std` as baseline.
- Baseline is persisted to DuckDB `baseline` table and loaded on restart.
- **Recalibrate:** `POST /api/recalibrate` clears baseline and restarts monitor.

### 10. Fuel Gauge

**Purpose:** Single "energy" metric (0–100%).

**Implementation:**
- `base = 100 - fatigue_score*0.35 - cognitive_load*18 - session_decrement`.
- Depletes with fatigue, high-load apps, and long sessions.

---

## Intervention Features

### 1. Grayscale Mode

**Purpose:** Reduce dopamine from colored interfaces; "positive friction" at critical fatigue.

**Implementation:**
- **Toggle:** `POST /api/grayscale` with `{ "enable": true/false }`. Uses `pynput` to send Win+Ctrl+C (Windows Color Filters toggle).
- **Requirement:** User must enable Color Filters in Settings → Accessibility and select Grayscale.
- **Auto-trigger:** `_maybe_auto_grayscale()` runs on each `/api/metrics`. Conditions: enforcement not "low", fatigue ≥ threshold (80 for high, 90 for medium), no panic override, grayscale currently off, cooldown 30 min.

### 2. Digital Sludge (Artificial Latency)

**Purpose:** Make the dashboard feel sluggish when overloaded—signals "slow down."

**Implementation:**
- In `/api/metrics`: when enforcement=high, fatigue≥70, no panic, not baseline → `time.sleep(1.0)` before returning.
- Only affects the AURA dashboard (API response delay). Other apps unchanged.
- Frontend shows `sludge_active` banner when true.

### 3. Social PACT (Webhook)

**Purpose:** Notify a buddy when fatigue is critical or user hits panic.

**Implementation:**
- **Config:** `webhook_url` in config.json.
- **Critical fatigue:** When fatigue ≥ 85, `_maybe_fire_webhook()` POSTs `{ event, fatigue_score, timestamp }`. Rate-limited: max once per 10 minutes (600 s cooldown).
- **Panic:** On `POST /api/panic`, always POSTs `{ event: "aura_panic_used", message, timestamp }` (no cooldown).

### 4. Panic Button (Emergency Override)

**Purpose:** 15-minute escape for high-stakes situations, with accountability.

**Implementation:**
- `POST /api/panic` sets `_panic_until = now + 15 min`. During override: auto-grayscale and sludge are suppressed.
- **Social tax:** Webhook fired to buddy.
- **Financial tax:** Each panic use logged in `panic_events` table. Digital Sunburn adds +5% per panic to tomorrow's predicted productivity loss.

---

## Recovery & Productivity Features

### 1. Predictive Digital Sunburn

**Purpose:** Estimate tomorrow's productivity loss from today's overwork.

**Implementation:**
- Queries DuckDB: today's avg fatigue, session duration (first_ts → last_ts), panic count.
- **Formula:** `loss` from (a) session > 6h + fatigue > 50, (b) fatigue > 70, (c) panic_count × 5. Capped at 40%.
- Returns `predicted_loss_pct`, `avg_fatigue_today`, `session_hours_today`, `panic_uses_today`.

### 2. Contextual Recovery Prescriptions

**Purpose:** Suggest breaks based on fatigue type.

**Implementation:**
- `GET /api/recovery` calls `get_metrics()` and returns up to 3 prescriptions:
  - Micro-scroll trap → "Analog Break"
  - Context switches > 10/min → "Single-Focus Task"
  - Error rate > 0.12 → "Hand & Eye Rest"
  - Fatigue > 60 → "Short Break"
  - Else → "On Track"

### 3. Energy-Based To-Do List

**Purpose:** Re-order tasks by current cognitive capacity.

**Implementation:**
- **`todos.py`:** JSON file at `~/.aura/todos.json`. Each task has `id`, `title`, `effort` (1–3), `impact` (1–3), `done`.
- **Sort logic:** When `fatigue < 50` and `fuel > 50` → show high-impact, low-effort first. When tired → show low-effort (easy wins) first.
- API: `GET /api/todos` (re-ordered), `POST /api/todos` (add), `PATCH /api/todos/:id` (toggle), `DELETE /api/todos/:id`.

### 4. Post-Mortem Dashboard

**Purpose:** Weekly view of KPM, hours worked, avg fatigue—"cost of overwork."

**Implementation:**
- `GET /api/postmortem?days=7`: Groups by date, sums keystrokes, computes duration (min→max ts), KPM = keystrokes/60/duration_hours, avg fatigue.
- Returns array of `{ date, keystrokes, hours_worked, kpm, avg_fatigue }`.

### 5. Proactive Notifications

**Purpose:** Alert user when fatigue is high even if dashboard tab is in background.

**Implementation:**
- **Frontend:** On mount, `Notification.requestPermission()`. On each `fetchMetrics`, if `fatigue_score ≥ 70` and not baseline → `maybeShowFatigueNotification()`.
- **Cooldown:** Max one notification per 15 minutes when fatigue stays high. Resets when fatigue drops below 70.
- Uses browser `Notification` API—works when tab is in background if permission granted.

---

## Ethics & Privacy

### Enforcement Levels

| Level | Auto-Grayscale | Digital Sludge |
|-------|----------------|---------------|
| Low | Never | Never |
| Medium | Fatigue ≥ 90 | Never |
| High | Fatigue ≥ 80 | Fatigue ≥ 70 |

Stored in config; applied in `_maybe_auto_grayscale()` and `sludge_active` check.

### Recalibrate

`POST /api/recalibrate` stops the monitor, creates a fresh `AuraMonitor` with no baseline, starts it. User types for 5 min to set new baseline.

### Data Privacy

- All data in `~/.aura/`: DuckDB, config.json, todos.json.
- No telemetry. No external calls except optional webhook.
- Keystroke timing only; no key content or text logged.
- Window titles stored (for cognitive load and context); user can avoid sensitive window names.

---

## Data Model & Storage

### DuckDB Schema

**`metrics`** (snapshot per `/api/metrics` call):
- ts, fatigue_score, latency_std, latency_mean, error_rate
- context_switches_per_min, total_keystrokes, backspace_count
- last_window, is_baseline, cognitive_load, fuel_gauge

**`baseline`** (one row per calibration):
- ts, latency_std, error_rate

**`panic_events`** (one row per panic press):
- ts

### Config (`config.json`)

- `enforcement_level`: "low" | "medium" | "high"
- `baseline_minutes`: 1–60
- `webhook_url`: string
- `grayscale_enabled`: boolean
- `cognitive_load_overrides`: { "pattern": "high"|"medium"|"passive" }

### Todos (`todos.json`)

Array of `{ id, title, effort, impact, done }`.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Health check |
| GET | `/api/metrics` | Current metrics; triggers storage, webhook, auto-grayscale, sludge |
| GET | `/api/history?hours=24` | Historical metrics (DuckDB) |
| GET | `/api/sunburn` | Digital sunburn prediction |
| GET | `/api/postmortem?days=7` | Weekly KPM / hours |
| GET | `/api/recovery` | Recovery prescriptions |
| GET | `/api/todos` | Energy-ordered todos |
| GET | `/api/config` | Settings |
| POST | `/api/panic` | 15-min override; webhook; stores panic event |
| POST | `/api/recalibrate` | Reset baseline |
| POST | `/api/config` | Update settings |
| POST | `/api/todos` | Add task |
| PATCH | `/api/todos/:id` | Toggle done |
| DELETE | `/api/todos/:id` | Delete task |
| POST | `/api/grayscale` | Toggle grayscale (Win+Ctrl+C) |

---

## Frontend Implementation

- **Framework:** React 18, functional components, hooks.
- **Build:** Vite 5, port 3000, proxy `/api` → backend.
- **API client:** `api.js` – fetch wrapper, all endpoints.
- **Polling:** Metrics every 3s, history 30s, sunburn 60s, recovery 15s, postmortem 60s, todos 10s.
- **Notifications:** `maybeShowFatigueNotification()` on metrics response; 15-min cooldown; threshold 70.
- **UI sections:** Fuel gauge (fatigue + fuel bars), metric cards, current window, recovery prescriptions, sunburn, todos, history chart, post-mortem table, actions (panic, recalibrate, grayscale, config). Config panel: enforcement, webhook URL, cognitive load overrides JSON textarea.
- **Error handling:** Banner when backend unreachable.

---

## Project Structure

```
AURA/
├── backend/
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── grayscale_on.ps1   # Registry-based (legacy; grayscale uses key combo now)
│   │   └── grayscale_off.ps1
│   └── server/
│       ├── app.py             # Flask API, interventions, DuckDB
│       ├── monitor.py         # AuraMonitor, all detection trackers
│       └── todos.py           # Energy-based todo CRUD
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── App.css
│       ├── api.js
│       └── index.css
└── README.md
```

---

## Deferred / Future Work

- **Tab-level context switching:** Would require a browser extension; currently only window-level.
- **System-wide page-load delays:** Would require proxy or extension; current sludge only affects `/api/metrics`.
- **System tray / native notifications:** Proactive alerts via Electron/Tauri for when dashboard tab is closed.
- **Native Desktop Wrapper:** Utilizing **Tauri** (via Rust) to wrap the React UI into a lightweight, cross-platform OS window, replacing the need for browser-based localhost access.
- **Sidecar Bundling:** Using **PyInstaller** to freeze the Python telemetry engine into a standalone executable that Tauri silently launches in the background, eliminating the need for users to manage Python environments or dependencies.
