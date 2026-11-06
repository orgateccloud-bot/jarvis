// Tela limpa: cards minimizados (lembrados no navegador) e conversa limpa da tela. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  alternar, alternarTodos, comMarcoDeConversaNova, lerLimpeza, lerMinimizados, mensagensParaRepor, mensagensQueFicam,
  salvarLimpeza, salvarMinimizados,
} from '../src/lib/telaLimpa.js'

function armazemFalso() {
  const dados = new Map()
  return { getItem: k => dados.get(k) ?? null, setItem: (k, v) => dados.set(k, String(v)) }
}

test('um card minimiza e volta; os outros não mudam', () => {
  assert.deepEqual(alternar([], 'Sistema'), ['Sistema'])
  assert.deepEqual(alternar(['Sistema', 'Neural'], 'Sistema'), ['Neural'])
})

test('o botão da barra de cima minimiza todos e, com todos minimizados, abre todos', () => {
  const ids = ['Sistema', 'Custo Claude', 'Neural']
  assert.deepEqual(alternarTodos(['Neural'], ids).sort(), [...ids].sort())   // algum aberto: minimiza todos
  assert.deepEqual(alternarTodos(ids, ids), [])                             // todos minimizados: abre todos
  assert.deepEqual(alternarTodos(['Antigo'], []), ['Antigo'])               // sem cards na tela: nada muda
})

test('a escolha fica guardada no navegador e sobrevive a dado estragado ou navegador que recusa', () => {
  const a = armazemFalso()
  assert.deepEqual(lerMinimizados(a), [])
  salvarMinimizados(['Sistema', 'Neural'], a)
  assert.deepEqual(lerMinimizados(a), ['Sistema', 'Neural'])
  a.setItem('jarvis.cards.minimizados', '{quebrado')
  assert.deepEqual(lerMinimizados(a), [])
  a.setItem('jarvis.cards.minimizados', JSON.stringify(['Sistema', 7, null]))
  assert.deepEqual(lerMinimizados(a), ['Sistema'])
  const recusa = { getItem() { throw new Error('bloqueado') }, setItem() { throw new Error('bloqueado') } }
  assert.deepEqual(lerMinimizados(recusa), [])
  assert.doesNotThrow(() => salvarMinimizados(['Sistema'], recusa))
  assert.deepEqual(lerMinimizados(undefined), [])
})

test('limpar a conversa tira tudo, menos confirmação sem resposta e resposta ainda chegando', () => {
  const msgs = [
    { id: 1, role: 'user', text: 'que horas são?' },
    { id: 2, role: 'jarvis', text: 'São 10h.' },
    { id: 3, role: 'approval', status: 'aprovado' },
    { id: 4, role: 'approval', status: 'pendente' },
    { id: 5, role: 'jarvis', text: 'Abrindo', streaming: true },
  ]
  assert.deepEqual(mensagensQueFicam(msgs).map(m => m.id), [4, 5])
  assert.deepEqual(mensagensQueFicam([]), [])
})

test('a marca de limpeza fica no navegador e sobrevive a dado estragado', () => {
  const a = armazemFalso()
  assert.equal(lerLimpeza(a), null)
  salvarLimpeza({ conversa: 'abc', ate: 6 }, a)
  assert.deepEqual(lerLimpeza(a), { conversa: 'abc', ate: 6 })
  a.setItem('jarvis.conversa.limpa', '{quebrado')
  assert.equal(lerLimpeza(a), null)
  a.setItem('jarvis.conversa.limpa', JSON.stringify({ conversa: 'abc', ate: 'seis' }))
  assert.equal(lerLimpeza(a), null)
  const recusa = { getItem() { throw new Error('bloqueado') }, setItem() { throw new Error('bloqueado') } }
  assert.equal(lerLimpeza(recusa), null)
  assert.doesNotThrow(() => salvarLimpeza({ conversa: 'abc', ate: 1 }, recusa))
})

test('depois do F5 volta só o que veio depois da limpeza', () => {
  const mensagens = ['a', 'b', 'c', 'd']                                        // as 4 últimas de 10
  const resposta = { conversa: 'abc', total: 10, mensagens }
  assert.deepEqual(mensagensParaRepor(resposta, null), mensagens)               // nunca limpou
  assert.deepEqual(mensagensParaRepor(resposta, { conversa: 'abc', ate: 8 }), ['c', 'd'])
  assert.deepEqual(mensagensParaRepor(resposta, { conversa: 'abc', ate: 3 }), mensagens) // limpou antes da janela
  assert.deepEqual(mensagensParaRepor(resposta, { conversa: 'abc', ate: 10 }), [])       // limpou tudo
  assert.deepEqual(mensagensParaRepor(resposta, { conversa: 'xyz', ate: 10 }), mensagens) // limpeza de outra conversa
})

test('o marco de conversa nova entra antes da pergunta que a abriu', () => {
  const msgs = [{ id: 1, role: 'user' }, { id: 2, role: 'jarvis' }, { id: 3, role: 'user' }, { id: 4, role: 'jarvis' }]
  assert.deepEqual(comMarcoDeConversaNova(msgs, 9).map(m => m.id), [1, 2, 9, 3, 4])
  assert.equal(comMarcoDeConversaNova(msgs, 9)[2].role, 'marco')
})
