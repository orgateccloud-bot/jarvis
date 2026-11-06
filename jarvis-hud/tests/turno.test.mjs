// Turno na tela: os eventos do stream viram mensagens e estado, no digitado e no espelhado da voz. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { comAprovacaoDecidida, criarTurno } from '../src/lib/turno.js'

function telaFalsa() {
  const t = { msgs: [], neural: null, fase: 'thinking', atividade: null, toasts: [], alertas: 0, n: 0 }
  const aplicar = campo => v => { t[campo] = typeof v === 'function' ? v(t[campo]) : v }
  t.tela = {
    uid: () => `x${t.n++}`, setMessages: aplicar('msgs'), setNeural: aplicar('neural'), setPhase: aplicar('fase'),
    setAtividade: aplicar('atividade'), pushToast: (texto, tipo) => t.toasts.push([texto, tipo]),
    flashAlert: () => { t.alertas++ }, energyRef: { current: 0 },
  }
  t.msgs = [{ id: 'u', role: 'user', text: 'oi' }, { id: 'j', role: 'jarvis', text: '', streaming: true, tools: [] }]
  return t
}

test('texto acumula na bolha, tira a legenda da ferramenta e guarda a resposta inteira', () => {
  const t = telaFalsa()
  const turno = criarTurno('j', t.tela)
  turno.aplicar({ type: 'tool', data: { fase: 'inicio', nome: 'web_search', resumo: 'Buscando na web' } })
  assert.equal(t.atividade, 'Buscando na web')
  turno.aplicar({ type: 'text', data: 'Olá, ' })
  turno.aplicar({ type: 'text', data: 'Senhor.' })
  assert.equal(t.msgs[1].text, 'Olá, Senhor.')
  assert.equal(turno.full, 'Olá, Senhor.')
  assert.equal(t.fase, 'speaking')
  assert.equal(t.atividade, null)
})

test('o fim da ferramenta substitui o início', () => {
  const t = telaFalsa()
  const turno = criarTurno('j', t.tela)
  turno.aplicar({ type: 'tool', data: { fase: 'inicio', nome: 'custos', resumo: 'a' } })
  turno.aplicar({ type: 'tool', data: { fase: 'fim', nome: 'custos', resumo: 'b', ok: true } })
  assert.deepEqual(t.msgs[1].tools, [{ fase: 'fim', nome: 'custos', resumo: 'b', ok: true }])
})

test('aprovação entra como card e o texto seguinte vai para uma bolha nova', () => {
  const t = telaFalsa()
  const avisados = []
  const turno = criarTurno('j', t.tela, { onApproval: d => avisados.push(d.id) })
  turno.aplicar({ type: 'text', data: 'Antes.' })
  turno.aplicar({ type: 'approval', data: { id: 'a1', nome: 'mover', resumo: 'mover', expira_s: 60 } })
  turno.aplicar({ type: 'text', data: 'Depois.' })
  assert.deepEqual(t.msgs.map(m => m.role), ['user', 'jarvis', 'approval', 'jarvis'])
  assert.equal(t.msgs[1].text, 'Antes.')
  assert.equal(t.msgs[2].status, 'pendente')
  assert.equal(t.msgs[3].text, 'Depois.')
  assert.deepEqual(avisados, ['a1'])
  assert.equal(turno.full, 'Antes.Depois.')
})

test('aviso não pisca o alerta; erro pisca', () => {
  const t = telaFalsa()
  const turno = criarTurno('j', t.tela)
  turno.aplicar({ type: 'aviso', data: 'escalando' })
  assert.deepEqual(t.toasts, [['escalando', 'warn']])
  assert.equal(t.alertas, 0)
  turno.aplicar({ type: 'error', data: 'caiu' })
  assert.deepEqual(t.toasts[1], ['caiu', 'danger'])
  assert.equal(t.alertas, 1)
})

test('rota de conversa nova põe o marco antes da pergunta', () => {
  const t = telaFalsa()
  const turno = criarTurno('j', t.tela)
  turno.aplicar({ type: 'route', data: { rota: 'media', modelo: 'claude-sonnet-5-5', nova_conversa: true } })
  assert.deepEqual(t.msgs.map(m => m.role), ['marco', 'user', 'jarvis'])
  assert.equal(t.msgs[2].tier, 'media')
})

test('encerrar tira a bolha vazia; com ferramenta ou texto, ela fica', () => {
  const vazia = telaFalsa()
  criarTurno('j', vazia.tela).encerrar()
  assert.deepEqual(vazia.msgs.map(m => m.role), ['user'])
  const comTexto = telaFalsa()
  const turno = criarTurno('j', comTexto.tela)
  turno.aplicar({ type: 'text', data: 'Pronto.' })
  turno.encerrar()
  assert.equal(comTexto.msgs[1].streaming, false)
})

test('falhar mantém o que chegou; sem nada, mostra a mensagem', () => {
  const t = telaFalsa()
  criarTurno('j', t.tela).falhar('sem núcleo')
  assert.equal(t.msgs[1].text, 'sem núcleo')
  const parcial = telaFalsa()
  const turno = criarTurno('j', parcial.tela)
  turno.aplicar({ type: 'text', data: 'Meio' })
  turno.falhar('sem núcleo')
  assert.equal(parcial.msgs[1].text, 'Meio')
})

test('decisão da aprovação vale para o card em aberto e não reabre o que já terminou', () => {
  const msgs = [
    { role: 'approval', approvalId: 'a', status: 'pendente' },
    { role: 'approval', approvalId: 'b', status: 'aprovando' },
    { role: 'approval', approvalId: 'c', status: 'expirado' },
    { role: 'jarvis', approvalId: 'a', status: 'pendente' },
  ]
  assert.equal(comAprovacaoDecidida(msgs, { id: 'a', aprovado: false })[0].status, 'negado')
  assert.equal(comAprovacaoDecidida(msgs, { id: 'b', aprovado: true })[1].status, 'aprovado')
  assert.equal(comAprovacaoDecidida(msgs, { id: 'c', aprovado: true })[2].status, 'expirado')
  assert.equal(comAprovacaoDecidida(msgs, { id: 'a', aprovado: true })[3].status, 'pendente')
})
