import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CosmosScene from './cosmos/CosmosScene.jsx'
import HoloSpike from './spike/HoloSpike.jsx'
import { SPIKE } from './spike/params.js'
import { alvoSol } from './spike/arranjo.js'
import './spike/spike.css'
import TopBar from './components/TopBar.jsx'
import { NOME } from './lib/marca.js'
import { CostCard, NeuralCard, VitalsCard } from './components/Cards.jsx'
import Transcript from './components/Transcript.jsx'
import CommandDock from './components/CommandDock.jsx'
import { BootIgnition, Caption, SunButton, Toasts } from './components/Overlays.jsx'
import { useJarvis } from './hooks/useJarvis.js'
import { useConversation } from './hooks/useConversation.js'
import { useVozLocal } from './hooks/useVozLocal.js'
import { FASE_DO_SERVICO, avisoDaVoz } from './lib/voice/servico.js'
import { ROUTE_TO_TIER, TIERS } from './lib/tiers.js'

const REST_AFTER_MS = 30000 // depois de 30 s em espera, o sol volta a ser o Sol (G2V)

export default function App() {
  const sayRef = useRef(null)
  const vozEventoRef = useRef(null)
  const j = useJarvis({
    // avisos e lembretes falados (a voz respeita o modo mudo; com a voz local, quem fala é o serviço)
    onProactive: ev => { if (ev.falar) sayRef.current?.(ev.texto) },
    onVoz: estado => vozEventoRef.current?.(estado),
  })
  // Etapa 2: com JARVIS_VOZ_LOCAL=1 o serviço local é o dono do microfone e do alto-falante (Decisão A)
  const vozLocal = useVozLocal({ online: j.online, authOk: j.authOk })
  useEffect(() => { vozEventoRef.current = vozLocal.aoEvento }, [vozLocal.aoEvento])
  const aviso = avisoDaVoz(vozLocal.voz, vozLocal.doHud)
  const { sendMessage, energyRef, approve, pushToast } = j
  const [mode, setMode] = useState('auto')
  const [panelsOpen, setPanelsOpen] = useState(false)
  const [resting, setResting] = useState(true)
  const devStats = useRef(null) // só em dev: expõe window.__cosmosStill para capturas determinísticas

  // SPIKE: modo palco (tecla P ou window.__spikePalco), tamanho da tela para posicionar sol e painel e
  // troca de variante sem recarregar (window.__spikeSet({ holo, sunR, flameAbs })) para medição pareada
  const [palco, setPalco] = useState(false)
  const [view, setView] = useState(() => ({ W: window.innerWidth, H: window.innerHeight }))
  const [sp, setSp] = useState(() => ({ ...SPIKE }))
  useEffect(() => { document.documentElement.classList.toggle('holo-on', sp.holo) }, [sp.holo])
  useEffect(() => {
    const onResize = () => setView({ W: window.innerWidth, H: window.innerHeight })
    const onKey = e => {
      if (SPIKE.holo && (e.key === 'p' || e.key === 'P') && !e.target.closest?.('input, textarea')) setPalco(v => !v)
    }
    window.__spikePalco = v => setPalco(Boolean(v))
    window.__spikeSet = novo => {
      Object.assign(SPIKE, novo) // o cosmos lê SPIKE.flameAbs a cada quadro
      setSp({ ...SPIKE })
    }
    window.addEventListener('resize', onResize)
    window.addEventListener('keydown', onKey)
    return () => {
      delete window.__spikePalco
      delete window.__spikeSet
      window.removeEventListener('resize', onResize)
      window.removeEventListener('keydown', onKey)
    }
  }, [])
  const sun = useMemo(
    () => alvoSol({ palco: sp.holo && palco, W: view.W, H: view.H, r: sp.sunR, y: sp.sunY }),
    [palco, view, sp.holo, sp.sunR, sp.sunY],
  )

  const send = useCallback((text, opts = {}) => {
    const msg = mode === 'auto' ? text : `/${mode} ${text}`
    setResting(false)
    return sendMessage(msg, { display: text, mode: mode === 'auto' ? null : mode, ...opts })
  }, [mode, sendMessage])

  const externo = vozLocal.ativo ? { estado: vozLocal.voz.estado, comando: vozLocal.comando } : null
  const conv = useConversation({ send, approve, energyRef, busy: j.busy, externo })
  const { say, ask, stop, clearApproval, error: voiceError } = conv
  useEffect(() => { sayRef.current = say }, [say])

  // texto digitado segue o mesmo caminho da voz (e é falado se a voz estiver ligada)
  const decide = useCallback((id, ok) => { clearApproval(); approve(id, ok) }, [clearApproval, approve])

  // Esc interrompe a fala
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') stop() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stop])

  useEffect(() => { if (voiceError) pushToast(voiceError, 'danger') }, [voiceError, pushToast])

  // fase visual: a voz manda quando está falando; senão o stream; senão a escuta
  const phase = (externo && FASE_DO_SERVICO[externo.estado]) || (conv.speaking ? 'speaking'
    : j.phase !== 'idle' ? j.phase
      : conv.mode === 'active' ? 'listening' : 'idle')

  // o sol mantém a classe de quem respondeu e, em repouso, volta a G2V
  useEffect(() => {
    if (phase !== 'idle') return
    const id = setTimeout(() => setResting(true), REST_AFTER_MS)
    return () => clearTimeout(id)
  }, [phase, j.neural])

  const activeTier = resting ? 'regras' : ROUTE_TO_TIER[j.neural?.rota] || 'regras'
  const alert = j.alertFlash || j.costs?.estado === 'teto'
  const uiTier = alert ? 'alerta' : activeTier

  return (
    <>
      <CosmosScene state={phase} tier={activeTier} alert={alert} energyRef={energyRef} sun={sun}
        statsRef={import.meta.env.DEV ? devStats : undefined} />
      <SunButton mode={conv.mode} speaking={conv.speaking} onClick={conv.toggle} disabled={!conv.supported.listen} />
      <Caption mode={conv.mode} phase={phase} caption={conv.caption} />
      <BootIgnition />
      <div className={`app ${sp.holo ? 'holo' : ''}`} style={{ '--tier': TIERS[uiTier].ui }}>
        <TopBar
          phase={phase} convMode={conv.mode} tier={uiTier} online={j.online}
          muted={conv.muted} onToggleMute={conv.toggleMute}
          wake={conv.wakeEnabled} onToggleWake={conv.toggleWake} voiceSupported={conv.supported.listen}
          bargeIn={conv.bargeIn} onToggleBargeIn={conv.toggleBargeIn}
          panelsOpen={panelsOpen} onTogglePanels={() => setPanelsOpen(o => !o)}
        />
        {j.online === false && (
          <div className="offline glass" role="alert">
            <strong>Núcleo offline.</strong> A API do {NOME} não responde em {window.location.host || '127.0.0.1:8003'}.
            Rode <code>start-jarvis.bat</code> (ou <code>.venv\Scripts\python -m jarvis</code>) — o HUD reconecta sozinho.
          </div>
        )}
        {j.online && j.authOk && aviso && (
          <div className="offline glass" role="alert">
            <strong>{aviso.titulo}</strong> {aviso.texto}{' '}
            <button className="chip" type="button"
              onClick={aviso.acao === 'pegar' ? vozLocal.pegarMicrofone : vozLocal.devolver}>
              {aviso.botao}
            </button>
          </div>
        )}
        {j.online && !j.authOk && (
          <div className="offline glass" role="alert">
            <strong>Token recusado.</strong> O HUD não tem o token da API.
            Abra o HUD pelo endereço da API (<code>http://127.0.0.1:8000</code>), que entrega o token sozinho.
          </div>
        )}
        <div className="stage">
          <div className={`panels ${panelsOpen ? 'open' : ''}`}>
            <aside className="side side-left" aria-label="Sistema e custos">
              <VitalsCard vitals={j.vitals} history={j.history} />
              <CostCard costs={j.costs} />
            </aside>
            <aside className="side side-right" aria-label="Estado neural">
              <NeuralCard neural={j.neural} />
            </aside>
          </div>
          <main className="center">
            <Transcript messages={j.messages} onDecide={decide} />
            <CommandDock
              onSend={ask} busy={j.busy} mode={mode} onMode={setMode}
              convMode={conv.mode} onToggleConversation={conv.toggle}
              voiceSupported={conv.supported.listen} showSuggestions={!j.messages.some(m => m.role === 'user')}
            />
          </main>
        </div>
      </div>
      {sp.holo && <HoloSpike vitals={j.vitals} history={j.history} palco={palco} view={view} />}
      <Toasts toasts={j.toasts} onDismiss={j.dismissToast} />
    </>
  )
}
