import { useCallback, useEffect, useRef, useState } from 'react'
import CosmosScene from './cosmos/CosmosScene.jsx'
import TopBar from './components/TopBar.jsx'
import { CostCard, NeuralCard, VitalsCard } from './components/Cards.jsx'
import Transcript from './components/Transcript.jsx'
import CommandDock from './components/CommandDock.jsx'
import { BootIgnition, Toasts } from './components/Overlays.jsx'
import { useJarvis } from './hooks/useJarvis.js'
import { useVoice } from './hooks/useVoice.js'
import { ROUTE_TO_TIER, TIERS } from './lib/tiers.js'

const REST_AFTER_MS = 30000 // depois de 30 s em espera, o sol volta a ser o Sol (G2V)

export default function App() {
  const j = useJarvis()
  const { setPhase, sendMessage, energyRef } = j
  const [mode, setMode] = useState('auto')
  const [interim, setInterim] = useState('')
  const [panelsOpen, setPanelsOpen] = useState(false)
  const [resting, setResting] = useState(true)
  const speakRef = useRef(null)
  const devStats = useRef(null) // só em dev: expõe window.__cosmosStill para capturas determinísticas

  const send = useCallback(text => {
    const msg = mode === 'auto' ? text : `/${mode} ${text}`
    setResting(false)
    return sendMessage(msg, { display: text, mode: mode === 'auto' ? null : mode, onDone: full => speakRef.current?.(full) })
  }, [mode, sendMessage])

  const voice = useVoice({
    onInterim: setInterim,
    onFinal: text => { setInterim(''); send(text) },
    onListenChange: on => { if (on) setPhase('listening'); else setPhase(p => (p === 'listening' ? 'idle' : p)) },
    onSpeakStart: () => setPhase('speaking'),
    onSpeakEnd: () => setPhase(p => (p === 'speaking' ? 'idle' : p)),
    onBoundary: () => { energyRef.current = 1 },
  })
  useEffect(() => { speakRef.current = voice.speak }, [voice.speak])

  // Esc interrompe a fala
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') voice.stop() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [voice])

  // o sol mantém a classe de quem respondeu e, em repouso, volta a G2V
  useEffect(() => {
    if (j.phase !== 'idle') return
    const id = setTimeout(() => setResting(true), REST_AFTER_MS)
    return () => clearTimeout(id)
  }, [j.phase, j.neural])

  const activeTier = resting ? 'regras' : ROUTE_TO_TIER[j.neural?.rota] || 'regras'
  const alert = j.alertFlash || j.costs?.estado === 'teto'
  const uiTier = alert ? 'alerta' : activeTier

  return (
    <>
      <CosmosScene state={j.phase} tier={activeTier} alert={alert} energyRef={energyRef}
        statsRef={import.meta.env.DEV ? devStats : undefined} />
      <BootIgnition />
      <div className="app" style={{ '--tier': TIERS[uiTier].ui }}>
        <TopBar
          phase={j.phase} tier={uiTier} online={j.online}
          muted={voice.muted} onToggleMute={voice.toggleMute}
          panelsOpen={panelsOpen} onTogglePanels={() => setPanelsOpen(o => !o)}
        />
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
            <Transcript messages={j.messages} />
            <CommandDock
              onSend={send} busy={j.busy} mode={mode} onMode={setMode}
              listening={voice.listening} interim={interim} onToggleListen={voice.toggleListen}
              voiceSupported={voice.supported} showSuggestions={!j.messages.length}
            />
          </main>
        </div>
      </div>
      <Toasts toasts={j.toasts} onDismiss={j.dismissToast} />
    </>
  )
}
