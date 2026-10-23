import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import CosmicCore from './CosmicCore.jsx'
import './App.css'

// Bancada de testes do núcleo cósmico: troca estado, camada e alerta sem precisar da API.
const STATES = ['idle', 'listening', 'thinking', 'speaking']
const TIERS = ['regras', 'simples', 'media', 'complexa']
const LABEL = { regras: 'Regras', simples: 'Haiku', media: 'Sonnet', complexa: 'Opus' }

// entrada da página de demonstração: componente local, sem exports (HMR recarrega a página)
// eslint-disable-next-line react-refresh/only-export-components
function Demo() {
  const params = new URLSearchParams(location.search)
  const [state, setState] = useState(params.get('estado') || 'idle')
  const [tier, setTier] = useState(params.get('camada') || 'regras')
  const [alert, setAlert] = useState(params.get('alerta') === '1')
  const energyRef = useRef(0)

  // simula a cadência das palavras enquanto "fala"
  useEffect(() => {
    if (state !== 'speaking') return
    const id = setInterval(() => { energyRef.current = 0.6 + Math.random() * 0.4 }, 180 + Math.random() * 120)
    return () => clearInterval(id)
  }, [state])

  const btn = (active, onClick, text) => (
    <button key={text} className={`action-btn ${active ? 'active' : ''}`} onClick={onClick}
      style={active ? { borderColor: '#4d7cff', color: '#fff' } : undefined}>{text}</button>
  )

  return (
    <div style={{ minHeight: '100vh', background: '#02040a', display: 'grid', placeItems: 'center', padding: 16 }}>
      <div style={{ display: 'grid', justifyItems: 'center', gap: 16 }}>
        <CosmicCore state={state} tier={tier} alert={alert} energyRef={energyRef} size={520} />
        <div className="quick-actions" style={{ justifyContent: 'center' }}>
          {STATES.map(s => btn(state === s, () => setState(s), s))}
        </div>
        <div className="quick-actions" style={{ justifyContent: 'center' }}>
          {TIERS.map(t => btn(tier === t, () => setTier(t), LABEL[t]))}
          {btn(alert, () => setAlert(a => !a), 'alerta')}
        </div>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><Demo /></StrictMode>)
