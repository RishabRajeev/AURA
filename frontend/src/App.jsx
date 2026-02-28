import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './api'
import './App.css'

const NOTIFICATION_COOLDOWN_MS = 15 * 60 * 1000
const FATIGUE_NOTIFY_THRESHOLD = 70

export default function App() {
  const [metrics, setMetrics] = useState(null)
  const [history, setHistory] = useState([])
  const [sunburn, setSunburn] = useState(null)
  const [postmortem, setPostmortem] = useState([])
  const [recovery, setRecovery] = useState([])
  const [todos, setTodos] = useState([])
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)
  const [panicCooldown, setPanicCooldown] = useState(null)
  const [newTodo, setNewTodo] = useState('')
  const [showConfig, setShowConfig] = useState(false)
  const lastNotificationRef = useRef(0)
  const notifiedAboveRef = useRef(false)

  const maybeShowFatigueNotification = useCallback((fatigueScore) => {
    if (fatigueScore < FATIGUE_NOTIFY_THRESHOLD) {
      notifiedAboveRef.current = false
      return
    }
    if (!('Notification' in window)) return
    if (Notification.permission !== 'granted') return
    const now = Date.now()
    const shouldNotify = !notifiedAboveRef.current || (now - lastNotificationRef.current > NOTIFICATION_COOLDOWN_MS)
    if (!shouldNotify) return
    try {
      new Notification('AURA — Fatigue Alert', {
        body: `Fatigue at ${Math.round(fatigueScore)}%. Consider taking a break.`,
      })
      lastNotificationRef.current = now
      notifiedAboveRef.current = true
    } catch {
      /* ignore */
    }
  }, [])

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await api.getMetrics()
      setMetrics(data)
      setError(null)
      if (data?.fatigue_score != null && !data?.is_baseline_mode) {
        maybeShowFatigueNotification(data.fatigue_score)
      }
    } catch (err) {
      setError(err.message || 'Could not reach AURA backend')
    }
  }, [maybeShowFatigueNotification])

  const fetchHistory = useCallback(async () => {
    try {
      const data = await api.getHistory(24)
      setHistory(data.history || [])
    } catch {
      setHistory([])
    }
  }, [])

  const fetchSunburn = useCallback(async () => {
    try {
      const data = await api.getSunburn()
      setSunburn(data)
    } catch {
      setSunburn(null)
    }
  }, [])

  const fetchPostmortem = useCallback(async () => {
    try {
      const data = await api.getPostmortem(7)
      setPostmortem(data.postmortem || [])
    } catch {
      setPostmortem([])
    }
  }, [])

  const fetchRecovery = useCallback(async () => {
    try {
      const data = await api.getRecovery()
      setRecovery(data.prescriptions || [])
    } catch {
      setRecovery([])
    }
  }, [])

  const fetchTodos = useCallback(async () => {
    try {
      const data = await api.getTodos()
      setTodos(data.todos || [])
    } catch {
      setTodos([])
    }
  }, [])

  const fetchConfig = useCallback(async () => {
    try {
      const data = await api.getConfig()
      setConfig(data)
    } catch {
      setConfig(null)
    }
  }, [])

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  useEffect(() => {
    fetchMetrics()
    fetchHistory()
    fetchSunburn()
    fetchRecovery()
    fetchConfig()
    const t = setInterval(fetchMetrics, 3000)
    const h = setInterval(fetchHistory, 30000)
    const s = setInterval(fetchSunburn, 60000)
    const r = setInterval(fetchRecovery, 15000)
    return () => {
      clearInterval(t)
      clearInterval(h)
      clearInterval(s)
      clearInterval(r)
    }
  }, [fetchMetrics, fetchHistory, fetchSunburn, fetchRecovery, fetchConfig])

  useEffect(() => {
    fetchPostmortem()
    fetchTodos()
    const p = setInterval(fetchPostmortem, 60000)
    const u = setInterval(fetchTodos, 10000)
    return () => {
      clearInterval(p)
      clearInterval(u)
    }
  }, [fetchPostmortem, fetchTodos])

  const handlePanic = async () => {
    try {
      const data = await api.panic()
      setPanicCooldown(data.panic_until)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleRecalibrate = async () => {
    try {
      await api.recalibrate()
      fetchMetrics()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleGrayscale = async (enable) => {
    try {
      await api.grayscale(enable)
      fetchConfig()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleAddTodo = async (e) => {
    e.preventDefault()
    if (!newTodo.trim()) return
    try {
      await api.addTodo(newTodo.trim())
      setNewTodo('')
      fetchTodos()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleToggleTodo = async (id) => {
    try {
      await api.toggleTodo(id)
      fetchTodos()
    } catch {
      /* ignore */
    }
  }

  const handleDeleteTodo = async (id) => {
    try {
      await api.deleteTodo(id)
      fetchTodos()
    } catch {
      /* ignore */
    }
  }

  const fatigueLevel = metrics?.fatigue_score ?? 0
  const fuelLevel = metrics?.fuel_gauge ?? 100
  const level =
    fatigueLevel < 30 ? 'healthy' : fatigueLevel < 60 ? 'moderate' : 'critical'

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">AURA</h1>
        <span className="tagline">Cognitive Burnout Monitor</span>
      </header>

      {error && (
        <div className="banner error">
          {error} — Is the backend running at <code>http://127.0.0.1:5000</code>?
        </div>
      )}

      {metrics && (
        <main className="main">
          <section className={`fuel-gauge ${level}`}>
            <h2>Fatigue Signature</h2>
            <div className="gauge-row">
              <div className="gauge-visual">
                <div
                  className="gauge-fill"
                  style={{ width: `${Math.min(100, fatigueLevel)}%` }}
                />
                <span className="gauge-value">{fatigueLevel.toFixed(1)}</span>
              </div>
              <span className="gauge-sublabel">fatigue</span>
            </div>
            <div className="gauge-row fuel-row">
              <div className="gauge-visual fuel-gauge-bar">
                <div
                  className="gauge-fill fuel-fill"
                  style={{ width: `${Math.min(100, fuelLevel)}%` }}
                />
              </div>
              <span className="gauge-sublabel">fuel {fuelLevel.toFixed(0)}%</span>
            </div>
            <p className="gauge-label">
              {metrics.is_baseline_mode
                ? 'Calibrating baseline (first 5 min)...'
                : level === 'healthy'
                  ? 'You’re in good shape'
                  : level === 'moderate'
                    ? 'Consider a short break'
                    : 'High fatigue — rest recommended'}
              {(metrics.time_of_day_factor ?? 1) > 1.1 && (
                <span className="time-badge"> Late-night factor ×{metrics.time_of_day_factor}</span>
              )}
            </p>
          </section>

          {metrics.micro_scroll_trap_detected && (
            <div className="banner warning">
              Zombie scroll detected — {metrics.scroll_rate_per_min?.toFixed(0)} scrolls/min. Consider a break.
            </div>
          )}

          {metrics.idle_detected && (
            <div className="banner warning">
              Idle {metrics.idle_minutes?.toFixed(0)} min — No input detected. Reading or zoning out?
            </div>
          )}

          {metrics.sludge_active && (
            <div className="banner sludge">
              Digital Sludge — Dashboard slowed by 1s to signal overload. Consider a break.
            </div>
          )}

          <section className="metrics-grid">
            <div className="metric-card">
              <span className="metric-value">
                {metrics.keystroke_latency_std_ms} ms
              </span>
              <span className="metric-label">Keystroke Latency (σ)</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.error_rate_proxy}</span>
              <span className="metric-label">Error Rate Proxy</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">
                {metrics.context_switches_per_min}
              </span>
              <span className="metric-label">Context Switches / min</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.cognitive_load_label}</span>
              <span className="metric-label">Cognitive Load</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.session_active_minutes ?? 0} min</span>
              <span className="metric-label">Session Duration</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.hold_duration_mean_ms ?? 0} ms</span>
              <span className="metric-label">Key Hold (mean)</span>
            </div>
          </section>

          <section className="current-window">
            <span className="window-label">Active window:</span>
            <span className="window-title">
              {metrics.last_window || '(unknown)'}
            </span>
          </section>

          {recovery.length > 0 && (
            <section className="recovery">
              <h3>Recovery Prescriptions</h3>
              <ul>
                {recovery.map((p, i) => (
                  <li key={i} className={`prescription prescription-${p.type}`}>
                    <strong>{p.title}</strong> — {p.description}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {sunburn?.predicted_loss_pct > 0 && (
            <section className="sunburn">
              <h3>Digital Sunburn</h3>
              <p>
                Predicted productivity loss tomorrow: <strong>{sunburn.predicted_loss_pct}%</strong>
                {sunburn.session_hours_today > 0 && (
                  <span className="sunburn-meta">
                    {' '}({sunburn.session_hours_today}h today, avg fatigue {sunburn.avg_fatigue_today})
                  </span>
                )}
                {sunburn.panic_uses_today > 0 && (
                  <span className="sunburn-meta"> • Panic overrides today: +{sunburn.panic_uses_today * 5}% debt</span>
                )}
              </p>
            </section>
          )}

          <section className="todos-section">
            <h3>Energy-Based To-Do</h3>
            <form onSubmit={handleAddTodo} className="todo-form">
              <input
                type="text"
                value={newTodo}
                onChange={(e) => setNewTodo(e.target.value)}
                placeholder="Add task..."
                className="todo-input"
              />
              <button type="submit" className="todo-add">Add</button>
            </form>
            <ul className="todo-list">
              {todos.filter((t) => !t.done).map((t) => (
                <li key={t.id} className="todo-item">
                  <input
                    type="checkbox"
                    checked={!!t.done}
                    onChange={() => handleToggleTodo(t.id)}
                  />
                  <span>{t.title}</span>
                  <button
                    className="todo-delete"
                    onClick={() => handleDeleteTodo(t.id)}
                    aria-label="Delete"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {history.length > 0 && (
            <section className="history">
              <h3>Fatigue Over Time</h3>
              <div className="history-chart">
                {history.slice(0, 48).map((p, i) => (
                  <div
                    key={i}
                    className="history-bar"
                    style={{
                      height: `${Math.min(100, p.fatigue_score)}%`,
                      minHeight: p.fatigue_score > 0 ? '4px' : 0,
                    }}
                    title={`${p.fatigue_score} @ ${p.ts}`}
                  />
                ))}
              </div>
            </section>
          )}

          {postmortem.length > 0 && (
            <section className="postmortem">
              <h3>Post-Mortem (This Week)</h3>
              <div className="postmortem-table">
                <div className="postmortem-row header">
                  <span>Date</span>
                  <span>Hours</span>
                  <span>KPM</span>
                  <span>Avg Fatigue</span>
                </div>
                {postmortem.slice(0, 7).map((r, i) => (
                  <div key={i} className="postmortem-row">
                    <span>{r.date}</span>
                    <span>{r.hours_worked}</span>
                    <span>{r.kpm}</span>
                    <span>{r.avg_fatigue}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="actions">
            <button
              className="panic-btn"
              onClick={handlePanic}
              disabled={!!panicCooldown}
              title="15-minute override"
            >
              {panicCooldown ? 'Override active' : 'Panic Button'}
            </button>
            <button className="recalibrate-btn" onClick={handleRecalibrate}>
              Recalibrate
            </button>
            <button
              className={`grayscale-btn ${config?.grayscale_enabled ? 'on' : ''}`}
              onClick={() => handleGrayscale(!config?.grayscale_enabled)}
            >
              {config?.grayscale_enabled ? 'Grayscale On' : 'Grayscale Off'}
            </button>
            <button className="config-btn" onClick={() => setShowConfig(!showConfig)}>
              Config
            </button>
          </section>

          {showConfig && config && (
            <section className="config-panel">
              <h4>Enforcement Level</h4>
              <select
                value={config.enforcement_level}
                onChange={(e) =>
                  api.postConfig({ enforcement_level: e.target.value }).then(fetchConfig)
                }
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <h4>Social PACT Webhook</h4>
              <p className="config-hint">POST to this URL when fatigue exceeds 85 (wellness check)</p>
              <input
                type="url"
                placeholder="https://..."
                defaultValue={config.webhook_url || ''}
                onBlur={(e) => {
                  const v = e.target.value.trim()
                  if (v !== (config.webhook_url || ''))
                    api.postConfig({ webhook_url: v }).then(fetchConfig)
                }}
              />
              <h4>Cognitive Load Overrides</h4>
              <p className="config-hint">Custom app→load mapping. Pattern (partial match) → high | medium | passive</p>
              <textarea
                className="config-overrides"
                placeholder={'{"Figma": "medium", "My App": "high"}'}
                defaultValue={JSON.stringify(config.cognitive_load_overrides || {}, null, 2)}
                onBlur={(e) => {
                  try {
                    const v = JSON.parse(e.target.value || '{}')
                    if (typeof v === 'object' && v !== null) {
                      api.postConfig({ cognitive_load_overrides: v }).then(fetchConfig)
                    }
                  } catch {
                    /* invalid JSON, ignore */
                  }
                }}
                rows={4}
              />
            </section>
          )}
        </main>
      )}
    </div>
  )
}
