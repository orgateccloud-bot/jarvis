import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createWebSpeechEngine } from '../lib/voice/webspeech.js'
import { createEchoFilter } from '../lib/voice/echo.js'
import { createSentenceSplitter } from '../lib/voice/sentences.js'
import { routeHeard } from '../lib/voice/route.js'
import { corrigirTermos } from '../lib/voice/termos.js'
import { acaoDoSol, modoDoServico } from '../lib/voice/servico.js'

const SILENCE_MS = 12000
const WAKE_KEY = 'jarvis-ouvir-jarvis'
const MUTE_KEY = 'jarvis-mudo'
// modo fone: microfone aberto durante a fala para interromper por voz (com alto-falante, o JARVIS se ouviria)
const BARGE_KEY = 'jarvis-interromper-por-voz'

const readFlag = key => { try { return localStorage.getItem(key) === '1' } catch { return false } }
const writeFlag = (key, v) => { try { localStorage.setItem(key, v ? '1' : '0') } catch { /* armazenamento indisponível */ } }

/**
 * Conversa por voz, mãos livres. Estados (mode):
 *   off     — nada ouvindo
 *   wake    — ouvindo em segundo plano só pela palavra "Jarvis" (opcional, desligado por padrão)
 *   active  — conversa aberta: ouve → envia → fala em streaming → volta a ouvir; 12 s de silêncio encerra
 *
 * deps: { send(text, opts) → Promise, approve(id, ok), energyRef, busy, externo }
 *   externo: { estado, comando(acao) } quando o serviço de voz local é o dono do microfone e do alto-falante
 *   (Etapa 2): aí o navegador não ouve nem fala; o sol, o mudo e o Esc viram comandos para o serviço.
 */
export function useConversation(deps) {
  const d = useRef(deps)
  useEffect(() => { d.current = deps })
  const externo = deps.externo || null
  const engine = useMemo(() => {
    const e = createWebSpeechEngine()
    e.setHalfDuplex(!readFlag(BARGE_KEY))
    return e
  }, [])
  const [mode, setMode] = useState(() => (readFlag(WAKE_KEY) ? 'wake' : 'off'))
  const [wakeEnabled, setWakeEnabled] = useState(() => readFlag(WAKE_KEY))
  const [muted, setMuted] = useState(() => readFlag(MUTE_KEY))
  const [bargeIn, setBargeIn] = useState(() => readFlag(BARGE_KEY))
  const echo = useMemo(() => createEchoFilter(), [])
  const [speaking, setSpeaking] = useState(false)
  const [caption, setCaption] = useState('')
  const [error, setError] = useState('')
  const modeRef = useRef(mode)
  const mutedRef = useRef(muted)
  const pendingApproval = useRef(null)
  const silenceTimer = useRef(0)
  useEffect(() => { modeRef.current = mode }, [mode])
  useEffect(() => { mutedRef.current = muted }, [muted])

  const restMode = useCallback(() => (readFlag(WAKE_KEY) ? 'wake' : 'off'), [])

  const armSilence = useCallback(() => {
    clearTimeout(silenceTimer.current)
    if (modeRef.current !== 'active') return
    const tick = () => {
      if (modeRef.current !== 'active') return
      // só encerra se ninguém estiver falando nem esperando resposta; senão reagenda
      if (!engine.speaking && !d.current.busy && !pendingApproval.current) {
        setMode(restMode())
        setCaption('')
      } else {
        silenceTimer.current = setTimeout(tick, SILENCE_MS)
      }
    }
    silenceTimer.current = setTimeout(tick, SILENCE_MS)
  }, [engine, restMode])

  const say = useCallback(text => {
    if (mutedRef.current || d.current.externo) return  // o serviço local fala por ele mesmo
    echo.remember(text)
    engine.speak(text)
  }, [engine, echo])

  /** Envia um pedido e fala a resposta frase a frase enquanto ela chega. */
  const ask = useCallback(text => {
    setCaption('')
    const splitter = createSentenceSplitter(say)
    return d.current.send(text, {
      onText: delta => splitter.push(delta),
      onDone: () => { splitter.flush(); armSilence() },
      onApproval: data => {
        splitter.flush()
        pendingApproval.current = data.id
        say(`Confirma: ${data.resumo}? Diga sim ou não.`)
      },
    })
  }, [say, armSilence])

  const onResult = useCallback((raw, isFinal) => {
    if (!raw) return
    const text = corrigirTermos(raw)  // "Graves, ..." → "Jarvis, ...", "c t n" → "CTN"
    armSilence()
    const r = routeHeard(text, isFinal, {
      mode: modeRef.current, speaking: engine.speaking, busy: d.current.busy,
      pendingApproval: !!pendingApproval.current, isEcho: echo.isEcho,
    })
    switch (r.action) {
      case 'cancel':
        engine.cancel()
        if (modeRef.current !== 'active') setMode('active')
        setCaption('')
        break
      case 'approve':
        d.current.approve(pendingApproval.current, r.ok)
        pendingApproval.current = null
        setCaption('')
        break
      case 'wake':
        setMode('active')
        if (r.ask) ask(r.ask)
        else if (r.greet) say('Pois não?')
        break
      case 'caption':
        setCaption(text)
        break
      case 'ask':
        ask(text)
        break
      default:
    }
  }, [engine, echo, armSilence, ask, say])

  useEffect(() => {
    engine.on({
      result: (t, f) => onResult(t, f),
      speakStart: () => setSpeaking(true),
      speakEnd: () => { echo.ended(); setSpeaking(false); armSilence() },
      boundary: () => { d.current.energyRef.current = 1 },
      error: msg => { setError(msg); setMode('off') },
    })
  }, [engine, echo, onResult, armSilence])

  // liga/desliga o microfone conforme o modo; em "wake" pausa quando a aba fica oculta (privacidade)
  const externoAtivo = !!externo
  useEffect(() => {
    const apply = () => {
      if (externoAtivo) { engine.stopListening(); engine.cancel(); return }  // um só dono do microfone
      const hiddenWake = mode === 'wake' && document.hidden
      if (mode === 'off' || hiddenWake) engine.stopListening()
      else engine.listen()
    }
    apply()
    if (mode === 'active') armSilence()
    document.addEventListener('visibilitychange', apply)
    return () => document.removeEventListener('visibilitychange', apply)
  }, [mode, engine, armSilence, externoAtivo])

  useEffect(() => () => { engine.stopListening(); engine.cancel(); clearTimeout(silenceTimer.current) }, [engine])

  /** Abre/fecha a conversa (clique no sol ou no microfone). Se estiver falando, só interrompe. */
  const toggle = useCallback(() => {
    const ext = d.current.externo
    if (ext) { ext.comando(acaoDoSol(ext.estado)); return }
    if (engine.speaking) { engine.cancel(); return }
    setError('')
    setMode(m => (m === 'active' ? restMode() : 'active'))
    setCaption('')
  }, [engine, restMode])

  const toggleWake = useCallback(() => {
    setWakeEnabled(on => {
      const next = !on
      writeFlag(WAKE_KEY, next)
      setMode(m => (m === 'active' ? m : next ? 'wake' : 'off'))
      return next
    })
  }, [])

  const toggleBargeIn = useCallback(() => {
    setBargeIn(on => {
      const next = !on
      writeFlag(BARGE_KEY, next)
      engine.setHalfDuplex(!next)
      return next
    })
  }, [engine])

  const toggleMute = useCallback(() => {
    setMuted(v => {
      const next = !v
      writeFlag(MUTE_KEY, next)
      if (next) engine.cancel()
      d.current.externo?.comando(next ? 'mudo' : 'som')
      return next
    })
  }, [engine])

  // diagnóstico em dev: estado da conversa visível no console
  useEffect(() => {
    if (import.meta.env.DEV) {
      window.__conv = { mode, speaking, engineSpeaking: engine.speaking, muted }
      window.__voiceInject = onResult // simula o reconhecimento de fala (testes sem microfone)
    }
  })

  // com o serviço local no comando, o estado mostrado é o dele (ouvindo, processando, falando)
  const ext = externo
  return {
    supported: ext ? { ...engine.supported, listen: true } : engine.supported,
    mode: ext ? modoDoServico(ext.estado) : mode,
    speaking: ext ? ext.estado === 'falando' : speaking,
    wakeEnabled, muted, bargeIn, caption: ext ? '' : caption, error,
    listening: ext ? ext.estado === 'ouvindo' : mode === 'active' && !speaking,
    toggle, toggleWake, toggleMute, toggleBargeIn, ask, say,
    stop: () => { if (d.current.externo) d.current.externo.comando('parar'); else engine.cancel() },
    clearApproval: () => { pendingApproval.current = null },
  }
}
