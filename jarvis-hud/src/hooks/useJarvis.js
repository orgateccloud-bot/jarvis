import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { decideApproval, getJson, lerMensagens, streamChat, streamEvents, streamTurnos } from '../lib/api.js'
import { lerLimpeza, mensagensParaRepor, mensagensQueFicam, salvarLimpeza } from '../lib/telaLimpa.js'
import { acrescentarAviso, novoAviso } from '../lib/avisos.js'
import { comAprovacaoDecidida, criarTurno } from '../lib/turno.js'

const HISTORY = 60
let seq = 0
const uid = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`

/**
 * Estado do JARVIS: conversa em streaming (com ferramentas e aprovações), eventos proativos,
 * sinais vitais, custos e alertas. `phase` reflete só o stream (thinking/speaking/waiting/idle; waiting é a espera de
 * uma aprovação); `atividade` diz o que a ferramenta em curso está fazendo. A voz e a escuta compõem a fase visual no App.
 * callbacks: { onProactive(ev) } — ex.: falar avisos e lembretes.
 */
export function useJarvis(callbacks = {}) {
  const cb = useRef(callbacks)
  useEffect(() => { cb.current = callbacks })
  const [phase, setPhase] = useState('idle')
  const [atividade, setAtividade] = useState(null)
  const [messages, setMessages] = useState([])
  const [avisos, setAvisos] = useState([])
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

  const tela = useMemo(() => ({
    uid, setMessages, setNeural, setPhase, setAtividade, pushToast, flashAlert, energyRef,
  }), [pushToast, flashAlert])

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
            // Etapa 2 (voz local): estado do serviço e "Ok Jarvis" (nova conversa) não viram mensagem
            if (ev.kind === 'voz') { cb.current.onVoz?.(ev.texto); continue }
            if (ev.kind === 'nova_conversa') { setMessages([]); continue }
            if (ev.kind === 'saudacao') greetedRef.current = true
            // vão para o card Avisos, não para a conversa: o centro da tela fica livre
            setAvisos(a => acrescentarAviso(a, novoAviso(ev, uid())))
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

  // espelho do turno pedido pela voz (só com JARVIS_VOZ_LOCAL=1): aparece como um turno digitado, inclusive o card de
  // aprovação clicável. Quem fala é o serviço, então nada aqui vai para a voz do navegador.
  useEffect(() => {
    if (!online || !authOk) return
    const ctrl = new AbortController()
    let stopped = false
    let turno = null
    const fechar = () => {
      if (!turno) return
      turno.encerrar()
      turno = null
      busyRef.current = false
      setBusy(false)
      setPhase('idle')
      setAtividade(null)
    }
    const abrir = pergunta => {
      const jid = uid()
      setMessages(m => [...m, ...(pergunta ? [{ id: uid(), role: 'user', text: pergunta, mode: 'voz' }] : []),
        { id: jid, role: 'jarvis', text: '', streaming: true, tools: [] }])
      busyRef.current = true
      setBusy(true)
      setPhase('thinking')
      turno = criarTurno(jid, tela)
    }
    const loop = async () => {
      while (!stopped) {
        try {
          for await (const ev of streamTurnos({ signal: ctrl.signal })) {
            if (ev.type === 'aprovacao') {
              setMessages(m => comAprovacaoDecidida(m, ev.data))
              setPhase(p => (p === 'waiting' ? 'thinking' : p))
            } else if (ev.type === 'done') {
              fechar()
            } else if (ev.type === 'pergunta') {
              fechar()
              abrir(ev.data)
            } else {
              if (!turno) abrir(null) // HUD aberto no meio do turno: mostra o resto da resposta
              turno.aplicar(ev)
            }
          }
        } catch (e) {
          if (e.status === 404) return // sem a voz local não há espelho
        }
        fechar()
        if (!stopped) await new Promise(r => setTimeout(r, 3000))
      }
    }
    loop()
    return () => { stopped = true; ctrl.abort(); fechar() }
  }, [online, authOk, tela])

  // ao abrir, repõe a conversa guardada na API, menos o que já foi limpo da tela
  const repostaRef = useRef(false)
  useEffect(() => {
    if (!online || !authOk || repostaRef.current) return
    repostaRef.current = true
    lerMensagens().then(r => {
      const repor = mensagensParaRepor(r, lerLimpeza()).map(m => ({ ...m, id: uid() }))
      setMessages(atuais => (atuais.length ? atuais : repor))
    }).catch(() => { /* API sem a rota ou fora do ar: a tela só começa vazia */ })
  }, [online, authOk])

  /** Aprova ou nega uma ação pendente (clique no card ou "sim"/"não" por voz). */
  const approve = useCallback(async (id, ok) => {
    setMessages(m => m.map(x => (x.role === 'approval' && x.approvalId === id && x.status === 'pendente'
      ? { ...x, status: ok ? 'aprovando' : 'negando' } : x)))
    setPhase(p => (p === 'waiting' ? 'thinking' : p))
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
    const jid = uid()
    const shown = (opts.display || text).trim() // o balão mostra o texto do usuário, sem o prefixo /opus etc.
    setMessages(m => [...m, { id: uid(), role: 'user', text: shown, mode: opts.mode },
      { id: jid, role: 'jarvis', text: '', streaming: true, tools: [] }])
    const turno = criarTurno(jid, tela, opts)
    try {
      for await (const ev of streamChat(text)) turno.aplicar(ev)
      turno.encerrar()
      opts.onDone?.(turno.full)
    } catch (e) {
      turno.falhar('Não consegui falar com o núcleo do JARVIS.')
      pushToast(`Falha de comunicação: ${e.message}`, 'danger')
      flashAlert()
      opts.onDone?.(turno.full)
    } finally {
      busyRef.current = false
      setBusy(false)
      setPhase('idle')
      setAtividade(null)
    }
  }, [tela, pushToast, flashAlert])

  // tela limpa: tira as mensagens da tela; o histórico da sessão na API continua (o contexto do JARVIS não muda).
  // Guarda até onde limpou, senão tudo voltaria no F5.
  const limparTela = useCallback(() => {
    setMessages(mensagensQueFicam)
    lerMensagens(1).then(r => salvarLimpeza({ conversa: r.conversa, ate: r.total })).catch(() => {})
  }, [])
  const limparAvisos = useCallback(() => setAvisos([]), [])

  return {
    phase, atividade, messages, avisos, busy, neural, vitals, history, costs, online, authOk,
    toasts, dismissToast, pushToast, alertFlash, energyRef, sendMessage, approve, limparTela, limparAvisos,
  }
}
