import { useState, useEffect, useRef, useCallback } from 'react'
import CosmicCore from './CosmicCore.jsx'
import './App.css'

const API = import.meta.env.VITE_JARVIS_API || 'http://127.0.0.1:8000'

// Token da API local (dados/.token). Vem do .env.local (VITE_JARVIS_TOKEN) ou é pedido uma vez.
function getToken() {
  let token = import.meta.env.VITE_JARVIS_TOKEN || ''
  try { token = token || localStorage.getItem('jarvis-token') || '' } catch { /* armazenamento ou JSON indisponível: segue sem */ }
  if (!token) {
    token = (window.prompt('Token do JARVIS (arquivo dados/.token):') || '').trim()
    try { if (token) localStorage.setItem('jarvis-token', token) } catch { /* armazenamento ou JSON indisponível: segue sem */ }
  }
  return token
}

function authFetch(path, options = {}) {
  return fetch(`${API}${path}`, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${getToken()}` },
  }).then(r => {
    if (r.status === 401) { try { localStorage.removeItem('jarvis-token') } catch { /* armazenamento ou JSON indisponível: segue sem */ } }
    return r
  })
}

// ===================== HOLOGRAPHIC ORB (Canvas) =====================
// ===================== SYSTEM METRICS PANEL =====================
function SystemPanel({ metrics }) {
  if (!metrics) return null

  const bars = [
    { label: 'CPU', value: metrics.cpu_percent, color: metrics.cpu_percent > 80 ? '#ff4444' : '#00e5ff' },
    { label: 'RAM', value: metrics.ram_percent, color: metrics.ram_percent > 85 ? '#ff4444' : '#00e5ff' },
    { label: 'DISK', value: metrics.disk_percent, color: metrics.disk_percent > 90 ? '#ff4444' : '#00e5ff' },
  ]

  return (
    <div className="panel system-panel">
      <div className="panel-header">
        <span className="panel-dot" />
        SYSTEM METRICS
      </div>
      {bars.map(b => (
        <div key={b.label} className="metric-row">
          <span className="metric-label">{b.label}</span>
          <div className="metric-bar-bg">
            <div className="metric-bar-fill" style={{ width: `${b.value}%`, background: b.color }} />
          </div>
          <span className="metric-value">{b.value?.toFixed(0)}%</span>
        </div>
      ))}
      <div className="metric-info">
        <span>Processes: {metrics.process_count}</span>
        <span>Uptime: {metrics.uptime_hours?.toFixed(1)}h</span>
      </div>
    </div>
  )
}

// ===================== NEURAL PANEL (rota, pensamento, último turno) =====================
function NeuralPanel({ neural }) {
  if (!neural) return null
  return (
    <div className="panel consciousness-panel">
      <div className="panel-header">
        <span className="panel-dot pulse" />
        NEURAL
      </div>
      <div className="consciousness-grid">
        <div className="con-item">
          <span className="con-label">Rota</span>
          <span className="con-value">{neural.rota?.toUpperCase() || '—'}</span>
        </div>
        <div className="con-item">
          <span className="con-label">Modelo</span>
          <span className="con-value">{neural.modelo || '—'}</span>
        </div>
        <div className="con-item">
          <span className="con-label">Turno</span>
          <span className="con-value">{neural.custo != null ? `US$ ${neural.custo.toFixed(4)}` : '—'}</span>
        </div>
      </div>
      {neural.thinking && <div className="con-topics"><span className="topic-tag">{neural.thinking.slice(-280)}</span></div>}
    </div>
  )
}

// ===================== COST PANEL =====================
function CostPanel({ costs }) {
  if (!costs) return null
  const pct = Math.min(100, costs.uso_pct || 0)
  const color = costs.estado === 'normal' ? '#00e5ff' : costs.estado === 'economia' ? '#ffb300' : '#ff4444'
  return (
    <div className="panel memory-panel">
      <div className="panel-header">
        <span className="panel-dot" />
        CUSTO CLAUDE
      </div>
      <div className="metric-row">
        <span className="metric-label">MÊS</span>
        <div className="metric-bar-bg">
          <div className="metric-bar-fill" style={{ width: `${pct}%`, background: color }} />
        </div>
        <span className="metric-value">{pct.toFixed(0)}%</span>
      </div>
      <div className="memory-stats cost-stats">
        <div className="mem-item">
          <span className="mem-num">${costs.hoje_usd.toFixed(2)}</span>
          <span className="mem-label">Hoje</span>
        </div>
        <div className="mem-item">
          <span className="mem-num">${costs.mes_usd.toFixed(2)}</span>
          <span className="mem-label">de ${costs.teto_usd}</span>
        </div>
        <div className="mem-item">
          <span className="mem-num">{costs.cache_hit_pct}%</span>
          <span className="mem-label">Cache</span>
        </div>
      </div>
      <div className="metric-info">
        <span>Modo: {costs.estado.toUpperCase()}</span>
        <span>Turnos: {costs.turnos_claude_mes}</span>
      </div>
    </div>
  )
}

// ===================== CHAT HISTORY =====================
function ChatHistory({ messages }) {
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  return (
    <div className="chat-history">
      {messages.map((msg, i) => (
        <div key={i} className={`chat-msg ${msg.role}`}>
          <span className="chat-role">{msg.role === 'user' ? '>' : 'JARVIS'}</span>
          <span className="chat-text">{msg.text}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}

// ===================== MAIN APP =====================
export default function App() {
  const [state, setState] = useState('idle')
  const [emotion] = useState('neutral')
  const [input, setInput] = useState('')
  const [streamText, setStreamText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [messages, setMessages] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [neural, setNeural] = useState(null)
  const [costs, setCosts] = useState(null)
  const [alertFlash, setAlertFlash] = useState(false)
  const energyRef = useRef(0)
  const [isListening, setIsListening] = useState(false)
  const [bootComplete, setBoot] = useState(false)
  const [scanLine, setScanLine] = useState(0)
  const inputRef = useRef(null)
  const recognitionRef = useRef(null)

  // --- Boot animation ---
  useEffect(() => {
    const timer = setTimeout(() => setBoot(true), 2200)
    return () => clearTimeout(timer)
  }, [])

  // --- Scan line ---
  useEffect(() => {
    const interval = setInterval(() => {
      setScanLine(prev => (prev + 1) % 100)
    }, 50)
    return () => clearInterval(interval)
  }, [])

  // --- Fetch system data periodically ---
  useEffect(() => {
    const fetchData = async () => {
      try {
        const okJson = r => (r.ok ? r.json() : null)
        const [sysRes, costRes] = await Promise.all([
          authFetch('/system/status').then(okJson).catch(() => null),
          authFetch('/costs').then(okJson).catch(() => null),
        ])
        if (sysRes) setMetrics(sysRes)
        if (costRes) setCosts(costRes)
      } catch { /* armazenamento ou JSON indisponível: segue sem */ }
    }
    fetchData()
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [])

  // --- Speech Recognition ---
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) return
    const recognition = new SpeechRecognition()
    recognition.lang = 'pt-BR'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (e) => {
      const transcript = Array.from(e.results).map(r => r[0].transcript).join('')
      setInput(transcript)
    }
    recognition.onend = () => setIsListening(false)
    recognition.onerror = () => setIsListening(false)
    recognitionRef.current = recognition
  }, [])

  const toggleVoice = useCallback(() => {
    if (!recognitionRef.current) return
    if (isListening) {
      recognitionRef.current.stop()
      setIsListening(false)
    } else {
      recognitionRef.current.start()
      setIsListening(true)
      setState('listening')
    }
  }, [isListening])

  // --- TTS ---
  const speak = useCallback((text) => {
    window.speechSynthesis.cancel()
    const clean = text.replace(/[#*_`~]/g, '').slice(0, 500)
    const utt = new SpeechSynthesisUtterance(clean)
    utt.lang = 'pt-BR'
    utt.pitch = 0.85
    utt.rate = 1.05
    utt.onstart = () => setState('speaking')
    utt.onboundary = () => { energyRef.current = 1 }  // cada palavra falada pulsa o núcleo
    utt.onend = () => setState('idle')
    window.speechSynthesis.speak(utt)
  }, [])

  // --- Send message (SSE streaming) ---
  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return

    setMessages(prev => [...prev, { role: 'user', text }])
    setInput('')
    setIsStreaming(true)
    setStreamText('')
    setState('thinking')

    try {
      const res = await authFetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: 'hud' }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let fullText = ''
      let thinking = ''
      let buffer = ''

      const handle = (ev) => {
        if (ev.type === 'route') setNeural({ rota: ev.data.rota, modelo: ev.data.modelo, thinking: '' })
        else if (ev.type === 'thinking') {
          thinking += ev.data
          setNeural(n => ({ ...n, thinking }))
        } else if (ev.type === 'text') {
          fullText += ev.data
          setStreamText(fullText)
          setState('speaking')
          energyRef.current = Math.min(1, energyRef.current + 0.45)
        } else if (ev.type === 'usage') {
          setNeural(n => ({ ...n, modelo: ev.data.modelo, custo: ev.data.custo_usd }))
        } else if (ev.type === 'error') {
          setAlertFlash(true)
          setTimeout(() => setAlertFlash(false), 2500)
          fullText += `\n[${ev.data}]\n`
          setStreamText(fullText)
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        // eventos SSE podem chegar partidos entre chunks: só processa linhas completas
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try { handle(JSON.parse(line.slice(6))) } catch { /* armazenamento ou JSON indisponível: segue sem */ }
          }
        }
      }

      setMessages(prev => [...prev, { role: 'jarvis', text: fullText }])
      speak(fullText)
    } catch {
      const errMsg = 'Falha de comunicacao com o servidor.'
      setStreamText(errMsg)
      setMessages(prev => [...prev, { role: 'jarvis', text: errMsg }])
      setState('idle')
    } finally {
      setIsStreaming(false)
    }
  }, [input, isStreaming, speak])

  const handleSubmit = (e) => {
    e.preventDefault()
    sendMessage()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  // --- Boot screen ---
  if (!bootComplete) {
    return (
      <div className="boot-screen">
        <div className="boot-logo">J.A.R.V.I.S.</div>
        <div className="boot-line">Initializing consciousness matrix...</div>
        <div className="boot-bar"><div className="boot-fill" /></div>
        <div className="boot-sub">v4.0 // Haiku · Sonnet · Opus online</div>
      </div>
    )
  }

  return (
    <div className="jarvis-hud">
      {/* Scan line overlay */}
      <div className="scan-line" style={{ top: `${scanLine}%` }} />

      {/* Corner decorations */}
      <div className="corner tl" /><div className="corner tr" />
      <div className="corner bl" /><div className="corner br" />

      {/* Header */}
      <header className="hud-header">
        <div className="hud-title">J.A.R.V.I.S.</div>
        <div className="hud-subtitle">Just A Rather Very Intelligent System // v4.0</div>
        <div className={`hud-status ${state}`}>
          <span className="status-dot" />
          {state.toUpperCase()} {emotion !== 'neutral' && `// ${emotion.toUpperCase()}`}
        </div>
      </header>

      {/* Main grid */}
      <div className="hud-grid">
        {/* LEFT PANELS */}
        <aside className="hud-left">
          <SystemPanel metrics={metrics} />
          <CostPanel costs={costs} />
        </aside>

        {/* CENTER - ORB + CHAT */}
        <main className="hud-center">
          <div className="orb-container">
            <CosmicCore
              state={state}
              tier={{ local: 'regras', simples: 'simples', media: 'media', complexa: 'complexa' }[neural?.rota] || 'regras'}
              alert={alertFlash || costs?.estado === 'teto'}
              energyRef={energyRef}
              size={400}
            />
          </div>

          <div className="response-area">
            {isStreaming ? (
              <div className="streaming-text">
                {streamText}
                <span className="cursor-blink">|</span>
              </div>
            ) : messages.length > 0 ? (
              <ChatHistory messages={messages} />
            ) : (
              <div className="welcome-text">
                Sistemas online. Aguardando comandos, senhor.
              </div>
            )}
          </div>

          {/* Command input */}
          <form className="command-bar" onSubmit={handleSubmit}>
            <span className="prompt-symbol">&gt;</span>
            <input
              ref={inputRef}
              type="text"
              placeholder={isListening ? 'Ouvindo...' : 'Digite um comando...'}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => !isStreaming && setState('listening')}
              onBlur={() => state === 'listening' && setState('idle')}
              disabled={isStreaming}
              autoFocus
            />
            <button type="button" className={`voice-btn ${isListening ? 'active' : ''}`} onClick={toggleVoice}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
            <button type="submit" className="send-btn" disabled={isStreaming || !input.trim()}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </form>
        </main>

        {/* RIGHT PANELS */}
        <aside className="hud-right">
          <NeuralPanel neural={neural} />

          {/* Quick Actions */}
          <div className="panel actions-panel">
            <div className="panel-header">
              <span className="panel-dot" />
              QUICK ACTIONS
            </div>
            <div className="quick-actions">
              {[
                { label: 'Status', cmd: 'status do sistema' },
                { label: 'Hora', cmd: 'que horas são?' },
                { label: 'Bom dia', cmd: 'bom dia' },
              ].map(a => (
                <button
                  key={a.cmd}
                  className="action-btn"
                  onClick={() => { setInput(a.cmd); setTimeout(sendMessage, 100) }}
                  disabled={isStreaming}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>

          {/* Vision Status */}
          <div className="panel vision-panel">
            <div className="panel-header">
              <span className="panel-dot" />
              SUBSYSTEMS
            </div>
            <div className="subsystem-list">
              <div className="subsystem-item">
                <span className={`sub-dot ${costs?.estado === 'teto' ? 'warning' : 'online'}`} /> Cérebro (Haiku · Sonnet · Opus)
              </div>
              <div className="subsystem-item">
                <span className="sub-dot online" /> Voz (WebSpeech — local na F4)
              </div>
              <div className="subsystem-item">
                <span className="sub-dot offline" /> Memória longa (F2)
              </div>
              <div className="subsystem-item">
                <span className="sub-dot offline" /> Ferramentas (F3)
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* Footer */}
      <footer className="hud-footer">
        <span>JARVIS COGNITIVE ARCHITECTURE v3.0</span>
        <span>{new Date().toLocaleString('pt-BR')}</span>
        <span>STREAMING: {isStreaming ? 'ACTIVE' : 'STANDBY'}</span>
      </footer>
    </div>
  )
}
