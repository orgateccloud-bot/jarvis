// Avisos proativos no card do lado direito, fora da conversa. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { MAX_AVISOS, acrescentarAviso, novoAviso } from '../src/lib/avisos.js'

test('o evento vira aviso com a hora da chegada', () => {
  const ev = { kind: 'saudacao', nivel: 'aviso', titulo: 'Bom dia', texto: 'Bom dia, Senhor. Sistemas online.' }
  assert.deepEqual(novoAviso(ev, 'a1', new Date(2026, 10, 2, 8, 5)), {
    id: 'a1', kind: 'saudacao', nivel: 'aviso', titulo: 'Bom dia', texto: 'Bom dia, Senhor. Sistemas online.', hora: '08:05',
  })
})

test('sem nível, título ou texto, o aviso usa o padrão', () => {
  const a = novoAviso({ kind: 'lembrete' }, 'a2', new Date(2026, 10, 2, 14, 30))
  assert.equal(a.nivel, 'info')
  assert.equal(a.titulo, 'Aviso')
  assert.equal(a.texto, '')
})

test('o mais novo fica em cima e a lista guarda só os últimos', () => {
  let lista = []
  for (let i = 0; i < MAX_AVISOS + 5; i++) lista = acrescentarAviso(lista, { id: i })
  assert.equal(lista.length, MAX_AVISOS)
  assert.equal(lista[0].id, MAX_AVISOS + 4)
  assert.equal(lista.at(-1).id, 5)
  assert.deepEqual(acrescentarAviso([{ id: 1 }], { id: 2 }, 1), [{ id: 2 }])
})
