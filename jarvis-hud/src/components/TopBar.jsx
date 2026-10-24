import { useEffect, useState } from 'react'
import { TIERS } from '../lib/tiers.js'

const PHASE = { idle: 'Em espera', listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Respondendo' }

function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 15000)
    return () => clearInterval(id)
  }, [])
  return now
}

const Icon = ({ d, label }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-label={label} role="img">{d}</svg>
)

export default function TopBar({ phase, convMode, tier, online, muted, onToggleMute, wake, onToggleWake, voiceSupported,
  panelsOpen, onTogglePanels }) {
  const now = useClock()
  const t = TIERS[tier] || TIERS.regras
  const label = phase === 'idle' && convMode === 'wake' ? 'Aguardando “Jarvis”' : PHASE[phase] || phase
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">JARVIS</span>
        <span className="brand-sub">v4 · Claude</span>
      </div>

      <div className={`status glass phase-${phase}`} aria-live="polite">
        <span className="status-dot" aria-hidden="true" />
        <span className="status-phase">{label}</span>
        <span className="status-sep" aria-hidden="true" />
        <span className="status-model">{t.label}</span>
        <span className="status-class">{t.classe}</span>
      </div>

      <div className="topbar-right">
        <span className={`net ${online ? 'on' : online === false ? 'off' : ''}`}
          title={online ? 'Núcleo online' : online === false ? 'Núcleo offline' : 'Conectando…'}>
          <span className="net-dot" aria-hidden="true" />
          <span className="net-label">{online ? 'online' : online === false ? 'offline' : '…'}</span>
        </span>
        {voiceSupported && (
          <button className={`icon-btn wake-btn ${wake ? 'on' : ''}`} onClick={onToggleWake} aria-pressed={wake}
            title={wake ? 'Parar de ouvir “Jarvis” em segundo plano' : 'Ouvir a palavra “Jarvis” em segundo plano'}>
            <Icon label="palavra de ativação" d={<><path d="M6 8.5a6 6 0 1 1 10.5 4c-1.2 1.4-2 2.3-2 4a3 3 0 0 1-5.5 1.6" />
              <path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-1.5 2-1.5 3.5" /></>} />
          </button>
        )}
        <button className="icon-btn" onClick={onToggleMute} aria-pressed={muted}
          title={muted ? 'Ativar voz do JARVIS' : 'Silenciar voz do JARVIS'}>
          {muted
            ? <Icon label="voz desligada" d={<><path d="M11 5 6 9H3v6h3l5 4V5z" /><path d="m22 9-6 6M16 9l6 6" /></>} />
            : <Icon label="voz ligada" d={<><path d="M11 5 6 9H3v6h3l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /></>} />}
        </button>
        <button className="icon-btn panels-btn" onClick={onTogglePanels} aria-expanded={panelsOpen} title="Painéis">
          <Icon label="painéis" d={<><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>} />
        </button>
        <time className="clock mono" dateTime={now.toISOString()}>
          {now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
        </time>
      </div>
    </header>
  )
}
