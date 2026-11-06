// Testes dos números vivos. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { faixa, interpolar } from '../src/lib/contador.js'

test('as faixas mudam em 75% e em 90%', () => {
  assert.equal(faixa(0), 0)
  assert.equal(faixa(74.9), 0)
  assert.equal(faixa(75), 1)
  assert.equal(faixa(89.9), 1)
  assert.equal(faixa(90), 2)
  assert.equal(faixa(100), 2)
})

test('o número vai de um valor ao outro, sem passar do alvo', () => {
  assert.equal(interpolar(10, 20, 0), 10)
  assert.equal(interpolar(10, 20, 1), 20)
  assert.equal(interpolar(20, 10, 1), 10)
  const meio = interpolar(10, 20, 0.5)
  assert.ok(meio > 15 && meio < 20, `a curva assenta devagar: ${meio}`)
})

test('progresso fora de 0 a 1 fica no limite', () => {
  assert.equal(interpolar(10, 20, -1), 10)
  assert.equal(interpolar(10, 20, 2), 20)
})
