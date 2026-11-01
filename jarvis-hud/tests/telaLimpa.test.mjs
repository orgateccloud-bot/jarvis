// Tela limpa: cards minimizados (lembrados no navegador) e conversa limpa da tela. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { alternar, alternarTodos, lerMinimizados, mensagensQueFicam, salvarMinimizados } from '../src/lib/telaLimpa.js'

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
