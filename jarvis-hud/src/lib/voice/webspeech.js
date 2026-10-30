// Motor de voz do navegador (WebSpeech). Interface pequena para a F4 trocar por Whisper + Piper locais:
//   listen() / stopListening() / speak(trecho) em fila / cancel() / on({ ... }) / supported / speaking
// Atenção à privacidade: no Chrome/Edge o reconhecimento envia o áudio ao servidor do navegador.
// Half-duplex: enquanto fala, o microfone pausa (o alto-falante não vira "pergunta"); volta TAIL_MS depois.

// Só em dev, com ?voz=simulada: reconhecedor sem áudio (as frases chegam por window.__voiceInject).
class SimulatedRecognition {
  start() { setTimeout(() => this.onstart?.(), 0) }
  stop() { setTimeout(() => this.onend?.(), 0) }
}

export const TAIL_MS = 1500

// io: injeção para testes ({ SR, synth, Utterance }); no navegador vem de window.
export function createWebSpeechEngine(io = {}) {
  const env = import.meta.env || {}
  const simulated = env.DEV && typeof location !== 'undefined'
    && new URLSearchParams(location.search).get('voz') === 'simulada'
  const SR = io.SR || (simulated ? SimulatedRecognition
    : typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition))
  const synth = io.synth || (typeof window !== 'undefined' ? window.speechSynthesis : null)
  const Utterance = io.Utterance || (typeof SpeechSynthesisUtterance !== 'undefined' ? SpeechSynthesisUtterance : null)
  let h = {}
  let rec = null
  let wantListening = false
  let restartTimer = 0
  let queued = 0
  let current = ''
  let voice = null
  let watchdog = 0
  let halfDuplex = true
  let paused = false   // microfone pausado pela fala; wantListening guarda o desejo de ouvir
  let resumeTimer = 0

  const pauseMic = () => {
    if (!halfDuplex || paused) return
    paused = true
    clearTimeout(resumeTimer)
    clearTimeout(restartTimer)
    if (wantListening) { try { rec?.stop() } catch { /* já parado */ } }
  }
  // cauda: o reconhecimento entrega o fim da frase com atraso; só reabre depois que o eco assentar
  const resumeMic = () => {
    if (!paused) return
    clearTimeout(resumeTimer)
    resumeTimer = setTimeout(() => {
      paused = false
      if (wantListening) { try { rec?.start() } catch { /* já ativo */ } }
    }, TAIL_MS)
  }
  const ended = () => { h.speakEnd?.(); resumeMic() }

  // Vigia da fila: o navegador pode bloquear a fala (sem interação do usuário, aba oculta) sem disparar
  // onend/onerror — a fila ficaria "falando" para sempre e travaria a conversa. Zera se não começar em 4 s
  // ou se o sintetizador esvaziar sem avisar.
  const resetQueue = () => {
    clearInterval(watchdog)
    watchdog = 0
    if (queued > 0) {
      queued = 0
      current = ''
      synth.cancel()
      ended()
    }
  }
  const armWatchdog = () => {
    if (watchdog) return
    const started = Date.now()
    watchdog = setInterval(() => {
      if (queued === 0) { clearInterval(watchdog); watchdog = 0; return }
      const idle = !synth.speaking && !synth.pending
      if ((!current && Date.now() - started > 4000) || (current && idle)) resetQueue()
    }, 1000)
  }

  const pickVoice = () => {
    if (!synth) return
    const vs = synth.getVoices()
    voice = vs.find(v => /pt-BR/i.test(v.lang) && /natural|neural|online/i.test(v.name))
      || vs.find(v => /pt-BR/i.test(v.lang)) || vs.find(v => /^pt/i.test(v.lang)) || null
  }
  if (synth) {
    pickVoice()
    synth.addEventListener?.('voiceschanged', pickVoice)
  }

  const build = () => {
    const r = new SR()
    r.lang = 'pt-BR'
    r.continuous = true
    r.interimResults = true
    r.onresult = e => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        h.result?.(res[0].transcript.trim(), res.isFinal)
      }
    }
    r.onstart = () => h.listenState?.(true)
    r.onerror = e => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        wantListening = false
        h.error?.('Microfone bloqueado: permita o acesso ao microfone para conversar por voz.')
      }
    }
    r.onend = () => {
      h.listenState?.(false)
      // o Chrome encerra a escuta contínua sozinho (silêncio/tempo): religa enquanto a conversa estiver ativa
      if (wantListening && !paused) {
        clearTimeout(restartTimer)
        restartTimer = setTimeout(() => { try { r.start() } catch { /* já ativo */ } }, 250)
      }
    }
    return r
  }

  return {
    supported: { listen: !!SR, speak: !!synth },
    on(handlers) { h = handlers },

    listen() {
      if (!SR || wantListening) return
      wantListening = true
      rec = rec || build()
      if (paused) return  // a cauda da fala religa
      try { rec.start() } catch { /* já ativo */ }
    },

    stopListening() {
      wantListening = false
      clearTimeout(restartTimer)
      try { rec?.stop() } catch { /* já parado */ }
    },

    /** false = microfone aberto durante a fala (só com fone; permite interromper por voz). */
    setHalfDuplex(on) { halfDuplex = !!on },

    speak(text) {
      if (!synth || !Utterance || !text) return
      const u = new Utterance(text)
      u.lang = 'pt-BR'
      if (voice) u.voice = voice
      u.rate = 1.05
      u.pitch = 0.92
      u.onstart = () => { current = text }
      u.onboundary = () => h.boundary?.()
      u.onend = u.onerror = () => {
        queued = Math.max(0, queued - 1)
        if (queued === 0) { current = ''; ended() }
      }
      if (queued === 0) { pauseMic(); h.speakStart?.() }
      queued += 1
      synth.speak(u)
      armWatchdog()
    },

    cancel() {
      if (!synth) return
      clearInterval(watchdog)
      watchdog = 0
      const had = queued > 0
      queued = 0
      current = ''
      synth.cancel()
      if (had) ended()
    },

    get speaking() { return queued > 0 },
    get micPaused() { return paused },
    get currentText() { return current },
  }
}
