/**
 * AURA API client — connects React dashboard to Flask backend.
 *
 * Uses Vite proxy: /api/* → http://127.0.0.1:5000/api/*
 * Or set VITE_API_URL to override (e.g. for production).
 */

const BASE = import.meta.env.VITE_API_URL || '/api'

async function request(path, opts = {}) {
  const url = `${BASE}${path}`
  const res = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...opts.headers },
  })
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  getStatus() {
    return request('/status')
  },

  getMetrics() {
    return request('/metrics')
  },

  getHistory(hours = 24) {
    return request(`/history?hours=${hours}`)
  },

  panic() {
    return request('/panic', { method: 'POST' })
  },

  getConfig() {
    return request('/config')
  },
}
