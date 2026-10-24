import { useCallback, useEffect, useRef, useState } from 'react'

const MUTE_KEY = 'jarvis-mudo'

// Texto falável: sem blocos de código, tabelas e marcações de markdown.
function speakable(text) {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\s*\|.*\|\s*$/gm, ' ')
    .replace(/[#*_`~>|]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 700)
}

/**
 * Voz pelo WebSpeech do navegador (a voz local fica para a F4).
 * Callbacks: onInterim(texto), onFinal(texto), onListenChange(bool), onSpeakStart(), onSpeakEnd(), onBoundary()
 */
export function useVoice(callbacks) {
  const cb = useRef(callbacks)
  useEffect(() => { cb.current = callbacks })
  const recRef = useRef(null)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [muted, setMuted] = useState(() => {
    try { return localStorage.getItem(MUTE_KEY) === '1' } catch { return false }
  })
  const supported = typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition)

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    const rec = new SR()
    rec.lang = 'pt-BR'
    rec.continuous = false
    rec.interimResults = true
    rec.onresult = e => {
      const text = Array.from(e.results).map(r => r[0].transcript).join('')
      const final = Array.from(e.results).every(r => r.isFinal)
      if (final) cb.current.onFinal?.(text)
      else cb.current.onInterim?.(text)
    }
    const end = () => { setListening(false); cb.current.onListenChange?.(false) }
    rec.onend = end
    rec.onerror = end
    recRef.current = rec
    return () => rec.abort()
  }, [])

  const toggleListen = useCallback(() => {
    const rec = recRef.current
    if (!rec) return
    if (listening) {
      rec.stop()
      return
    }
    window.speechSynthesis?.cancel()
    try {
      rec.start()
      setListening(true)
      cb.current.onListenChange?.(true)
    } catch { /* já estava ouvindo */ }
  }, [listening])

  const stop = useCallback(() => {
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    cb.current.onSpeakEnd?.()
  }, [])

  const speak = useCallback(text => {
    if (muted || !window.speechSynthesis || !text) return
    window.speechSynthesis.cancel()
    const utt = new SpeechSynthesisUtterance(speakable(text))
    utt.lang = 'pt-BR'
    const voice = window.speechSynthesis.getVoices().find(v => v.lang?.toLowerCase().startsWith('pt'))
    if (voice) utt.voice = voice
    utt.rate = 1.04
    utt.pitch = 0.9
    utt.onstart = () => { setSpeaking(true); cb.current.onSpeakStart?.() }
    utt.onboundary = () => cb.current.onBoundary?.()
    utt.onend = () => { setSpeaking(false); cb.current.onSpeakEnd?.() }
    utt.onerror = utt.onend
    window.speechSynthesis.speak(utt)
  }, [muted])

  const toggleMute = useCallback(() => {
    setMuted(m => {
      const next = !m
      try { localStorage.setItem(MUTE_KEY, next ? '1' : '0') } catch { /* armazenamento indisponível */ }
      if (next) window.speechSynthesis?.cancel()
      return next
    })
  }, [])

  return { supported, listening, speaking, muted, toggleListen, toggleMute, speak, stop }
}
