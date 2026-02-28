# AURA — Cognitive Burnout Monitor

Privacy-first, AI-powered Desktop Monitor that detects cognitive burnout and focus decay through behavioral biometrics.

## Quick Start

### 1. Backend (Python Flask)

```bash
cd AURA/backend
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python server/app.py
```

Backend runs at **http://127.0.0.1:5000**

**Note:** On Windows, run the terminal as Administrator if keystroke capture fails (pynput may require elevation). On macOS, grant Accessibility permissions.

### 2. Frontend (React + Vite)

```bash
cd AURA/frontend
npm install
npm run dev
```

Dashboard runs at **http://localhost:3000**

### 3. Connect

The Vite dev server proxies `/api/*` to `http://127.0.0.1:5000`, so the React dashboard automatically talks to the backend. Just keep both running.

---

## API Endpoints

| Method | Endpoint        | Description                              |
|--------|-----------------|------------------------------------------|
| GET    | `/api/status`   | Health check                             |
| GET    | `/api/metrics`  | Current fatigue & context-switch metrics |
| GET    | `/api/history?hours=24` | Historical metrics (DuckDB)    |
| POST   | `/api/panic`    | Emergency 15-min override                 |
| GET    | `/api/config`   | Enforcement level, baseline minutes       |

---

## Detection Logic (Fatigue Signature)

- **Keystroke latency (std dev)**: Rising variance between keypresses indicates inconsistent motor control (cognitive decay).
- **Error rate proxy**: Backspace / delete frequency as a proxy for typing errors.
- **Context switches**: App/window changes per minute → fragmented attention.
- **Baseline calibration**: First 30 minutes of each session establish a "fresh state"; deviations above threshold increase the fatigue score.

---

## Project Structure

```
AURA/
├── backend/
│   ├── requirements.txt
│   └── server/
│       ├── app.py      # Flask API
│       └── monitor.py  # Fatigue Signature + Context-Switch tracker
├── frontend/
│   ├── package.json
│   ├── vite.config.js  # Proxy /api → Flask
│   └── src/
│       ├── api.js      # API client
│       ├── App.jsx     # Dashboard UI
│       └── ...
└── README.md
```

---

## Data & Privacy

- All metrics stored locally in `~/.aura/aura.duckdb` (or `%USERPROFILE%\.aura\` on Windows).
- No telemetry or external calls.
- Keystroke timing only; no key content or text is logged.
