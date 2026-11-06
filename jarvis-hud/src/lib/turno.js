// Um turno na tela: aplica cada evento do stream às mensagens e ao estado do HUD. Vale para o turno digitado e para o
// espelhado da voz. Sem React, para ser testável: `tela` traz os setters e o que mais o turno movimenta.
import { ROUTE_TO_TIER } from './tiers.js'
import { comMarcoDeConversaNova } from './telaLimpa.js'
import { faseDepoisDaFerramenta, rotuloDaFerramenta } from './atividade.js'

/** opts: { onText(delta), onApproval(data) } — só o turno digitado usa, porque na voz quem fala é o serviço. */
export function criarTurno(jidInicial, tela, opts = {}) {
  const { uid, setMessages, setNeural, setPhase, setAtividade, pushToast, flashAlert, energyRef } = tela
  let jid = jidInicial
  let full = ''
  let segment = ''
  let thinking = ''
  let tier = null
  const patch = (id, fields) => setMessages(m => m.map(x => (
    x.id === id ? { ...x, ...(typeof fields === 'function' ? fields(x) : fields) } : x)))

  function aplicar(ev) {
    if (ev.type === 'route') {
      tier = ROUTE_TO_TIER[ev.data.rota] || 'regras'
      setNeural({ ...ev.data, thinking: '' })
      patch(jid, { tier, modelo: ev.data.modelo })
      if (ev.data.nova_conversa) setMessages(m => comMarcoDeConversaNova(m, uid()))
    } else if (ev.type === 'thinking') {
      thinking += ev.data
      setNeural(n => ({ ...n, thinking }))
    } else if (ev.type === 'text') {
      full += ev.data
      segment += ev.data
      patch(jid, { text: segment })
      setAtividade(null) // ferramenta de servidor só termina no fim da resposta: o texto já é o sinal de que voltou
      setPhase('speaking')
      energyRef.current = Math.min(1, energyRef.current + 0.45)
      opts.onText?.(ev.data)
    } else if (ev.type === 'tool') {
      const d = ev.data
      setAtividade(d.fase === 'inicio' ? rotuloDaFerramenta(d.nome) : null)
      setPhase(p => faseDepoisDaFerramenta(p, d))
      energyRef.current = Math.max(energyRef.current, d.fase === 'inicio' ? 0.7 : 0.45) // cada ferramenta dá um pulso
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
      setAtividade(null)
      setPhase('waiting')
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
    } else if (ev.type === 'aviso') {
      pushToast(ev.data, 'warn')
    } else if (ev.type === 'error') {
      pushToast(ev.data, 'danger')
      flashAlert()
    }
  }

  return {
    aplicar,
    /** Fim do stream: tira a bolha que ficou vazia e para o cursor. */
    encerrar() {
      setMessages(m => m.filter(x => !(x.id === jid && !x.text && !(x.tools || []).length))
        .map(x => (x.id === jid ? { ...x, streaming: false } : x)))
    },
    /** A conexão caiu no meio: fica o que já chegou; sem nada, a mensagem de falha. */
    falhar(mensagem) {
      patch(jid, { streaming: false, text: segment || mensagem })
    },
    get full() { return full },
  }
}

/** Decisão de uma aprovação vinda do espelho: vale para o card que ainda não terminou (por voz ou por clique). */
export function comAprovacaoDecidida(mensagens, { id, aprovado }) {
  return mensagens.map(x => (x.role === 'approval' && x.approvalId === id && ['pendente', 'aprovando', 'negando'].includes(x.status)
    ? { ...x, status: aprovado ? 'aprovado' : 'negado' } : x))
}
