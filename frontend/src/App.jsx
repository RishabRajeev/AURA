import { useState, useEffect, useCallback } from 'react'
import { api } from './api'
import './App.css'

export default function App() {
  const [metrics, setMetrics] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(null)
  const [panicCooldown, setPanicCooldown] = useState(null)

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await api.getMetrics()
      setMetrics(data)
      setError(null)
    } catch (err) {
      setError(err.message || 'Could not reach AURA backend')
    }
  }, [])

  const fetchHistory = useCallback(async () => {
    try {
      const data = await api.getHistory(24)
      setHistory(data.history || [])
    } catch {
      setHistory([])
    }
  }, [])

  useEffect(() => {
    fetchMetrics()
    fetchHistory()
    const t = setInterval(fetchMetrics, 3000)
    const h = setInterval(fetchHistory, 30000)
    return () => {
      clearInterval(t)
      clearInterval(h)
    }
  }, [fetchMetrics, fetchHistory])

  const handlePanic = async () => {
    try {
      const data = await api.panic()
      setPanicCooldown(data.panic_until)
    } catch (err) {
      setError(err.message)
    }
  }

  const fatigueLevel = metrics?.fatigue_score ?? 0
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
            <div className="gauge-visual">
              <div
                className="gauge-fill"
                style={{ width: `${Math.min(100, fatigueLevel)}%` }}
              />
              <span className="gauge-value">{fatigueLevel.toFixed(1)}</span>
            </div>
            <p className="gauge-label">
              {metrics.is_baseline_mode
                ? 'Calibrating baseline (first 30 min)...'
                : level === 'healthy'
                  ? 'You’re in good shape'
                  : level === 'moderate'
                    ? 'Consider a short break'
                    : 'High fatigue — rest recommended'}
            </p>
          </section>

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
              <span className="metric-value">{metrics.total_keystrokes}</span>
              <span className="metric-label">Total Keystrokes</span>
            </div>
          </section>

          <section className="current-window">
            <span className="window-label">Active window:</span>
            <span className="window-title">
              {metrics.last_window || '(unknown)'}
            </span>
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

          <section className="actions">
            <button
              className="panic-btn"
              onClick={handlePanic}
              disabled={!!panicCooldown}
              title="15-minute override of interventions"
            >
              {panicCooldown ? 'Override active' : 'Panic Button (15 min)'}
            </button>
          </section>
        </main>
      )}
    </div>
  )
}
