import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createWebSpeechEngine } from '../lib/voice/webspeech.js'
import { NO, STOP_WORDS, WAKE_WORD, YES, afterWakeWord, createSentenceSplitter } from '../lib/voice/sentences.js'
import { corrigirTermos } from '../lib/voice/termos.js'

const SILENCE_MS = 12000
const WAKE_KEY = 'jarvis-ouvir-jarvis'
const MUTE_KEY = 'jarvis-mudo'

const readFlag = key => { try { return localStorage.getItem(key) === '1' } catch { return false } }
const writeFlag = (key, v) => { try { localStorage.setItem(key, v ? '1' : '0') } catch { /* armazenamento indisponível */ } }

/**
 * Conversa por voz, mãos livres. Estados (mode):
 *   off     — nada ouvindo
 *   wake    — ouvindo em segundo plano só pela palavra "Jarvis" (opcional, desligado por padrão)
 *   active  — conversa aberta: ouve → envia → fala em streaming → volta a ouvir; 12 s de silêncio encerra
 *
 * deps: { send(text, opts) → Promise, approve(id, ok), energyRef, busy }
 */
export function useConversation(deps) {
  const d = useRef(deps)
  useEffect(() => { d.current = deps })
  const engine = useMemo(() => createWebSpeechEngine(), [])
  const [mode, setMode] = useState(() => (readFlag(WAKE_KEY) ? 'wake' : 'off'))
  const [wakeEnabled, setWakeEnabled] = useState(() => readFlag(WAKE_KEY))
  const [muted, setMuted] = useState(() => readFlag(MUTE_KEY))
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
    if (!mutedRef.current) engine.speak(text)
  }, [engine])

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
    const m = modeRef.current
    armSilence()

    // falando: só interrompe com gatilho explícito (ignora o eco do próprio alto-falante)
    if (engine.speaking) {
      const echo = STOP_WORDS.test(engine.currentText) && STOP_WORDS.test(text)
      if (STOP_WORDS.test(text) && !echo) {
        engine.cancel()
        if (m !== 'active') setMode('active')
        setCaption('')
      }
      return
    }

    // aprovação pendente: "sim"/"não" por voz
    if (pendingApproval.current && isFinal) {
      if (YES.test(text) || NO.test(text)) {
        const ok = YES.test(text) && !NO.test(text)
        d.current.approve(pendingApproval.current, ok)
        pendingApproval.current = null
        setCaption('')
        return
      }
    }

    if (m === 'wake') {
      if (!WAKE_WORD.test(text)) return
      const rest = afterWakeWord(text)
      setMode('active')
      if (isFinal && rest && rest.length > 2) ask(rest)
      else if (isFinal) say('Pois não?')
      return
    }

    if (m === 'active') {
      if (d.current.busy) return
      if (!isFinal) { setCaption(text); return }
      ask(text)
    }
  }, [engine, armSilence, ask, say])

  useEffect(() => {
    engine.on({
      result: (t, f) => onResult(t, f),
      speakStart: () => setSpeaking(true),
      speakEnd: () => { setSpeaking(false); armSilence() },
      boundary: () => { d.current.energyRef.current = 1 },
      error: msg => { setError(msg); setMode('off') },
    })
  }, [engine, onResult, armSilence])

  // liga/desliga o microfone conforme o modo; em "wake" pausa quando a aba fica oculta (privacidade)
  useEffect(() => {
    const apply = () => {
      const hiddenWake = mode === 'wake' && document.hidden
      if (mode === 'off' || hiddenWake) engine.stopListening()
      else engine.listen()
    }
    apply()
    if (mode === 'active') armSilence()
    document.addEventListener('visibilitychange', apply)
    return () => document.removeEventListener('visibilitychange', apply)
  }, [mode, engine, armSilence])

  useEffect(() => () => { engine.stopListening(); engine.cancel(); clearTimeout(silenceTimer.current) }, [engine])

  /** Abre/fecha a conversa (clique no sol ou no microfone). Se estiver falando, só interrompe. */
  const toggle = useCallback(() => {
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

  const toggleMute = useCallback(() => {
    setMuted(v => {
      const next = !v
      writeFlag(MUTE_KEY, next)
      if (next) engine.cancel()
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

  return {
    supported: engine.supported, mode, wakeEnabled, muted, speaking, caption, error,
    listening: mode === 'active' && !speaking,
    toggle, toggleWake, toggleMute, ask, say, stop: () => engine.cancel(),
    clearApproval: () => { pendingApproval.current = null },
  }
}
