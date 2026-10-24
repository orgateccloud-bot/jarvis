import { useCallback, useEffect, useRef, useState } from 'react'
import { getJson, streamChat } from '../lib/api.js'
import { ROUTE_TO_TIER } from '../lib/tiers.js'

const HISTORY = 60
let seq = 0
const uid = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`

/** Estado do JARVIS: conversa em streaming, sinais vitais, custos, alertas e a fase visual do cosmos. */
export function useJarvis() {
  const [phase, setPhase] = useState('idle') // idle | listening | thinking | speaking
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [neural, setNeural] = useState(null)
  const [vitals, setVitals] = useState(null)
  const [history, setHistory] = useState({ cpu: [], ram: [] })
  const [costs, setCosts] = useState(null)
  const [online, setOnline] = useState(null)
  const [toasts, setToasts] = useState([])
  const [alertFlash, setAlertFlash] = useState(false)
  const energyRef = useRef(0)
  const busyRef = useRef(false)

  const dismissToast = useCallback(id => setToasts(t => t.filter(x => x.id !== id)), [])
  const pushToast = useCallback((text, kind = 'warn') => {
    const id = uid()
    setToasts(t => [...t.slice(-3), { id, text, kind }])
    setTimeout(() => dismissToast(id), 6000)
  }, [dismissToast])

  const flashAlert = useCallback(() => {
    setAlertFlash(true)
    setTimeout(() => setAlertFlash(false), 3000)
  }, [])

  // polling de saúde, sinais vitais e custos
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        await getJson('/health', { auth: false })
        if (alive) setOnline(true)
      } catch {
        if (alive) setOnline(false)
        return
      }
      const [sys, cost] = await Promise.all([
        getJson('/system/status').catch(() => null),
        getJson('/costs').catch(() => null),
      ])
      if (!alive) return
      if (sys) {
        setVitals(sys)
        setHistory(h => ({
          cpu: [...h.cpu, sys.cpu_percent].slice(-HISTORY),
          ram: [...h.ram, sys.ram_percent].slice(-HISTORY),
        }))
      }
      if (cost) setCosts(cost)
    }
    tick()
    const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const patch = (id, fields) => setMessages(m => m.map(x => (x.id === id ? { ...x, ...fields } : x)))

  /** Envia o texto exato recebido (corrige o bug antigo das ações rápidas, que liam um estado velho). */
  const sendMessage = useCallback(async (raw, { onDone, display, mode } = {}) => {
    const text = (raw || '').trim()
    if (!text || busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setPhase('thinking')
    const jid = uid()
    const shown = (display || text).trim() // o balão mostra o texto do usuário, sem o prefixo /opus etc.
    setMessages(m => [...m, { id: uid(), role: 'user', text: shown, mode }, { id: jid, role: 'jarvis', text: '', streaming: true }])
    let full = ''
    let thinking = ''
    try {
      for await (const ev of streamChat(text)) {
        if (ev.type === 'route') {
          setNeural({ ...ev.data, thinking: '' })
          patch(jid, { tier: ROUTE_TO_TIER[ev.data.rota] || 'regras', modelo: ev.data.modelo })
        } else if (ev.type === 'thinking') {
          thinking += ev.data
          setNeural(n => ({ ...n, thinking }))
        } else if (ev.type === 'text') {
          full += ev.data
          patch(jid, { text: full })
          setPhase('speaking')
          energyRef.current = Math.min(1, energyRef.current + 0.45)
        } else if (ev.type === 'usage') {
          setNeural(n => ({ ...n, uso: ev.data }))
          patch(jid, { custo: ev.data.custo_usd, modelo: ev.data.modelo })
        } else if (ev.type === 'error') {
          pushToast(ev.data, 'danger')
          flashAlert()
        }
      }
      patch(jid, { streaming: false })
      onDone?.(full)
    } catch (e) {
      patch(jid, { streaming: false, text: full || 'Não consegui falar com o núcleo do JARVIS.' })
      pushToast(`Falha de comunicação: ${e.message}`, 'danger')
      flashAlert()
    } finally {
      busyRef.current = false
      setBusy(false)
      setPhase(p => (p === 'thinking' || p === 'speaking' ? 'idle' : p))
    }
  }, [pushToast, flashAlert])

  return {
    phase, setPhase, messages, busy, neural, vitals, history, costs, online,
    toasts, dismissToast, alertFlash, energyRef, sendMessage,
  }
}
