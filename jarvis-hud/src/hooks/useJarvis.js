import { useCallback, useEffect, useRef, useState } from 'react'
import { decideApproval, getJson, streamChat, streamEvents } from '../lib/api.js'
import { ROUTE_TO_TIER } from '../lib/tiers.js'

const HISTORY = 60
let seq = 0
const uid = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`

/**
 * Estado do JARVIS: conversa em streaming (com ferramentas e aprovações), eventos proativos,
 * sinais vitais, custos e alertas. `phase` reflete só o stream (thinking/speaking/idle);
 * a voz e a escuta compõem a fase visual no App.
 * callbacks: { onProactive(ev) } — ex.: falar avisos e lembretes.
 */
export function useJarvis(callbacks = {}) {
  const cb = useRef(callbacks)
  useEffect(() => { cb.current = callbacks })
  const [phase, setPhase] = useState('idle')
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [neural, setNeural] = useState(null)
  const [vitals, setVitals] = useState(null)
  const [history, setHistory] = useState({ cpu: [], ram: [] })
  const [costs, setCosts] = useState(null)
  const [online, setOnline] = useState(null)
  const [authOk, setAuthOk] = useState(true)
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

  const patch = (id, fields) => setMessages(m => m.map(x => (x.id === id ? { ...x, ...(typeof fields === 'function' ? fields(x) : fields) } : x)))

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
      let unauthorized = false
      const guard = e => { if (e.status === 401) unauthorized = true; return null }
      const [sys, cost] = await Promise.all([
        getJson('/system/status').catch(guard),
        getJson('/costs').catch(guard),
      ])
      if (!alive) return
      setAuthOk(!unauthorized)
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

  // eventos proativos: saudação (só na 1ª conexão da página), alertas e lembretes; reconecta sozinho
  const greetedRef = useRef(false)
  useEffect(() => {
    if (!online || !authOk) return
    const ctrl = new AbortController()
    let stopped = false
    const loop = async () => {
      while (!stopped) {
        try {
          const greeting = !greetedRef.current
          for await (const ev of streamEvents({ greeting, signal: ctrl.signal })) {
            if (ev.kind === 'saudacao') greetedRef.current = true
            setMessages(m => [...m, {
              id: uid(), role: 'jarvis', kind: ev.kind === 'saudacao' ? 'saudacao' : 'aviso',
              nivel: ev.nivel, titulo: ev.titulo, text: ev.texto, tier: ev.nivel === 'critico' ? 'alerta' : 'regras',
            }])
            if (ev.nivel !== 'info') pushToast(`${ev.titulo}: ${ev.texto}`, ev.nivel === 'critico' ? 'danger' : 'warn')
            if (ev.nivel === 'critico') flashAlert()
            cb.current.onProactive?.(ev)
          }
        } catch { /* conexão caiu ou foi abortada */ }
        if (!stopped) await new Promise(r => setTimeout(r, 3000))
      }
    }
    loop()
    return () => { stopped = true; ctrl.abort() }
  }, [online, authOk, pushToast, flashAlert])

  /** Aprova ou nega uma ação pendente (clique no card ou "sim"/"não" por voz). */
  const approve = useCallback(async (id, ok) => {
    setMessages(m => m.map(x => (x.role === 'approval' && x.approvalId === id && x.status === 'pendente'
      ? { ...x, status: ok ? 'aprovando' : 'negando' } : x)))
    const sent = await decideApproval(id, ok)
    setMessages(m => m.map(x => (x.role === 'approval' && x.approvalId === id
      ? { ...x, status: sent ? (ok ? 'aprovado' : 'negado') : 'expirado' } : x)))
  }, [])

  /**
   * Envia o texto exato recebido. opts: { display, mode, onText(delta), onDone(full), onApproval(data) }
   */
  const sendMessage = useCallback(async (raw, opts = {}) => {
    const text = (raw || '').trim()
    if (!text || busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setPhase('thinking')
    let jid = uid()
    const shown = (opts.display || text).trim() // o balão mostra o texto do usuário, sem o prefixo /opus etc.
    setMessages(m => [...m, { id: uid(), role: 'user', text: shown, mode: opts.mode },
      { id: jid, role: 'jarvis', text: '', streaming: true, tools: [] }])
    let full = ''
    let segment = ''
    let thinking = ''
    let tier = null
    try {
      for await (const ev of streamChat(text)) {
        if (ev.type === 'route') {
          tier = ROUTE_TO_TIER[ev.data.rota] || 'regras'
          setNeural({ ...ev.data, thinking: '' })
          patch(jid, { tier, modelo: ev.data.modelo })
        } else if (ev.type === 'thinking') {
          thinking += ev.data
          setNeural(n => ({ ...n, thinking }))
        } else if (ev.type === 'text') {
          full += ev.data
          segment += ev.data
          patch(jid, { text: segment })
          setPhase('speaking')
          energyRef.current = Math.min(1, energyRef.current + 0.45)
          opts.onText?.(ev.data)
        } else if (ev.type === 'tool') {
          const d = ev.data
          patch(jid, x => {
            const tools = [...(x.tools || [])]
            const i = tools.findIndex(t => t.nome === d.nome && t.fase === 'inicio')
            if (d.fase === 'fim' && i >= 0) tools[i] = d
            else tools.push(d)
            return { tools }
          })
          if (d.negado) {
            setMessages(m => m.map(x => (x.role === 'approval' && x.nome === d.nome && x.status === 'pendente'
              ? { ...x, status: 'expirado' } : x)))
          }
        } else if (ev.type === 'approval') {
          // o card entra na conversa; o texto seguinte do modelo vai para uma nova bolha abaixo dele
          patch(jid, { streaming: false })
          const nid = uid()
          setMessages(m => [...m,
            { id: uid(), role: 'approval', approvalId: ev.data.id, nome: ev.data.nome, resumo: ev.data.resumo,
              expiraEm: Date.now() + ev.data.expira_s * 1000, status: 'pendente', detalhes: ev.data.detalhes },
            { id: nid, role: 'jarvis', text: '', streaming: true, tools: [], tier }])
          jid = nid
          segment = ''
          opts.onApproval?.(ev.data)
        } else if (ev.type === 'usage') {
          setNeural(n => ({ ...n, uso: ev.data }))
          patch(jid, { custo: ev.data.custo_usd, modelo: ev.data.modelo })
        } else if (ev.type === 'error') {
          pushToast(ev.data, 'danger')
          flashAlert()
        }
      }
      setMessages(m => m.filter(x => !(x.id === jid && !x.text && !(x.tools || []).length))
        .map(x => (x.id === jid ? { ...x, streaming: false } : x)))
      opts.onDone?.(full)
    } catch (e) {
      patch(jid, { streaming: false, text: segment || 'Não consegui falar com o núcleo do JARVIS.' })
      pushToast(`Falha de comunicação: ${e.message}`, 'danger')
      flashAlert()
      opts.onDone?.(full)
    } finally {
      busyRef.current = false
      setBusy(false)
      setPhase('idle')
    }
  }, [pushToast, flashAlert])

  return {
    phase, messages, busy, neural, vitals, history, costs, online, authOk,
    toasts, dismissToast, pushToast, alertFlash, energyRef, sendMessage, approve,
  }
}
