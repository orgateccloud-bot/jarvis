// Acesso à API local do JARVIS (127.0.0.1, token obrigatório).
// Buildado, o HUD é servido pela própria API (mesma origem); no `npm run dev` (porta 5299) a API fica na 8000.
export const API = import.meta.env.VITE_JARVIS_API ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')

const TOKEN_KEY = 'jarvis-token'

let asked = false

// Token da API local. Servido pela API, ele vem injetado na página (window.__JARVIS_TOKEN__); em dev o Vite
// injeta VITE_JARVIS_TOKEN (lido de dados/.token); senão usa o salvo no navegador e, como último recurso,
// pede UMA vez por carregamento.
export function getToken() {
  let token = window.__JARVIS_TOKEN__ || import.meta.env.VITE_JARVIS_TOKEN || ''
  try { token = token || localStorage.getItem(TOKEN_KEY) || '' } catch { /* armazenamento indisponível */ }
  if (!token && !asked) {
    asked = true
    token = (window.prompt('Token do JARVIS (arquivo dados/.token):') || '').trim()
    try { if (token) localStorage.setItem(TOKEN_KEY, token) } catch { /* armazenamento indisponível */ }
  }
  return token
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* armazenamento indisponível */ }
}

export async function authFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) clearToken()
  return res
}

export class HttpError extends Error {
  constructor(status) {
    super(status === 401 ? 'token inválido' : `HTTP ${status}`)
    this.status = status
  }
}

export async function getJson(path, { auth = true } = {}) {
  const res = auth ? await authFetch(path) : await fetch(`${API}${path}`)
  if (!res.ok) throw new HttpError(res.status)
  return res.json()
}

// Lê um corpo SSE e devolve cada evento "data:" já em JSON (ignora comentários de keepalive).
async function* readSSE(res, signal) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      // eventos podem chegar partidos entre pedaços: só processa linhas completas
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try { yield JSON.parse(line.slice(6)) } catch { /* linha SSE inválida: ignora */ }
      }
    }
  } finally {
    reader.cancel().catch(() => {})
  }
}

/** Envia uma mensagem e devolve os eventos SSE do turno (route, thinking, text, tool, approval, usage, error, done). */
export async function* streamChat(message, sessionId = 'hud') {
  const res = await authFetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!res.ok) throw new HttpError(res.status)
  yield* readSSE(res)
}

/** Eventos proativos (saudação, alertas, lembretes). Fica aberto até o signal abortar. */
export async function* streamEvents({ greeting = true, signal } = {}) {
  const res = await authFetch(`/events?saudacao=${greeting ? 'true' : 'false'}`, { signal })
  if (!res.ok) throw new HttpError(res.status)
  yield* readSSE(res, signal)
}

/** Decide uma aprovação pendente (ação com efeito pedida pelo modelo). */
export async function decideApproval(id, aprovar) {
  const res = await authFetch(`/approvals/${encodeURIComponent(id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ aprovar }),
  })
  return res.ok
}
