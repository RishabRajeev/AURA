/**
 * AURA API client — connects React dashboard to Flask backend.
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
  getStatus: () => request('/status'),
  getMetrics: () => request('/metrics'),
  getHistory: (hours = 24) => request(`/history?hours=${hours}`),
  panic: () => request('/panic', { method: 'POST' }),
  recalibrate: () => request('/recalibrate', { method: 'POST' }),
  getConfig: () => request('/config'),
  postConfig: (data) => request('/config', { method: 'POST', body: JSON.stringify(data) }),
  getSunburn: () => request('/sunburn'),
  getPostmortem: (days = 7) => request(`/postmortem?days=${days}`),
  getRecovery: () => request('/recovery'),
  grayscale: (enable) => request('/grayscale', { method: 'POST', body: JSON.stringify({ enable }) }),
  getTodos: () => request('/todos'),
  addTodo: (title, effort = 2, impact = 2) =>
    request('/todos', { method: 'POST', body: JSON.stringify({ title, effort, impact }) }),
  toggleTodo: (id) => request(`/todos/${id}`, { method: 'PATCH' }),
  deleteTodo: (id) => request(`/todos/${id}`, { method: 'DELETE' }),
}
