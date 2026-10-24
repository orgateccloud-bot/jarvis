import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import CosmosScene from './cosmos/CosmosScene.jsx'
import { TIERS } from './lib/tiers.js'
import './styles/tokens.css'

// Bancada do cosmos: troca estado, classe estelar, alerta e ignição sem precisar da API.
// Parâmetros de URL: ?estado=thinking&camada=complexa&alerta=1
const STATES = { idle: 'Ocioso', listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando' }

// eslint-disable-next-line react-refresh/only-export-components
function Bancada() {
  const params = new URLSearchParams(location.search)
  const [state, setState] = useState(params.get('estado') || 'idle')
  const [tier, setTier] = useState(params.get('camada') || 'regras')
  const [alert, setAlert] = useState(params.get('alerta') === '1')
  const [seed, setSeed] = useState(0)
  const energyRef = useRef(0)
  const statsRef = useRef({ fps: 0, scale: 0 })
  const [stats, setStats] = useState({ fps: 0, scale: 0 })

  useEffect(() => {
    if (state !== 'speaking') return
    const id = setInterval(() => { energyRef.current = 0.6 + Math.random() * 0.4 }, 160 + Math.random() * 140)
    return () => clearInterval(id)
  }, [state])

  useEffect(() => {
    const id = setInterval(() => setStats({ ...statsRef.current }), 1000)
    return () => clearInterval(id)
  }, [])

  const chip = (active, onClick, label, key) => (
    <button key={key || label} onClick={onClick} className={`bench-chip ${active ? 'on' : ''}`}>{label}</button>
  )

  return (
    <>
      <CosmosScene key={seed} state={state} tier={tier} alert={alert} energyRef={energyRef} statsRef={statsRef} />
      <div className="bench glass">
        <div className="bench-row">{Object.entries(STATES).map(([k, v]) => chip(state === k, () => setState(k), v, k))}</div>
        <div className="bench-row">
          {['regras', 'simples', 'media', 'complexa'].map(k => chip(tier === k, () => setTier(k), TIERS[k].label, k))}
          {chip(alert, () => setAlert(a => !a), 'Alerta')}
          {chip(false, () => setSeed(s => s + 1), 'Ignição')}
        </div>
        <div className="bench-row mono bench-stats">
          {TIERS[alert ? 'alerta' : tier].classe} · {TIERS[alert ? 'alerta' : tier].temp.toLocaleString('pt-BR')} K
          · {stats.fps} fps · escala {stats.scale?.toFixed?.(2)}
        </div>
      </div>
      <style>{`
        .bench { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); z-index: 2;
          padding: 12px 14px; display: grid; gap: 8px; width: min(640px, calc(100vw - 32px)); }
        .bench-row { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
        .bench-chip { background: rgba(255,255,255,.04); border: 1px solid var(--hairline); border-radius: 999px;
          padding: 6px 12px; cursor: pointer; color: var(--text-muted); }
        .bench-chip.on { background: var(--aurora); color: #fff; border-color: transparent; }
        .bench-stats { color: var(--text-muted); font-size: 12px; }
      `}</style>
    </>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><Bancada /></StrictMode>)
