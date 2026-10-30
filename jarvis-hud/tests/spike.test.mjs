// SPIKE da fase 0: funções puras do arranjo e do limite das chamas. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FLAME_ABS, flameLim } from '../src/spike/params.js'
import { alvoSol, painelCPU, solPx } from '../src/spike/arranjo.js'

test('sem "abs", as chamas vão até 4,5 raios como no main', () => {
  assert.equal(flameLim(0.105, false), 4.5)
  assert.equal(flameLim(0.2, false), 4.5)
})

test('com "abs", sol maior mantém a área absoluta das chamas de hoje', () => {
  assert.equal(flameLim(0.105, true), 4.5)
  assert.ok(Math.abs(flameLim(0.2, true) * 0.2 - FLAME_ABS) < 1e-9)
  assert.equal(flameLim(0.05, true), 4.5) // sol menor não passa do limite de hoje
})

test('em repouso o sol fica no centro; no modo palco vai para 24% da largura e encolhe', () => {
  assert.deepEqual(alvoSol({ palco: false, W: 1920, H: 945, r: 0.2, y: 0.13 }), { x: 0, y: 0.13, r: 0.2 })
  const p = alvoSol({ palco: true, W: 1920, H: 945, r: 0.2, y: 0.13 })
  assert.ok(Math.abs(solPx(p, 1920, 945).cx - 0.24 * 1920) < 1e-6)
  assert.ok(Math.abs(p.r - 0.11) < 1e-9)
})

test('o painel entra 30% do raio no disco do sol e cabe na tela nos dois estados', () => {
  const W = 1920, H = 945
  for (const palco of [false, true]) {
    const sol = alvoSol({ palco, W, H, r: 0.2, y: 0.13 })
    const escala = palco ? 0.55 : 1
    const p = painelCPU({ sol, W, H, escala })
    const { cx, rp } = solPx(sol, W, H)
    assert.ok(Math.abs(p.left + p.w * escala - (cx - rp * 0.7)) <= 1)
    assert.ok(p.left >= 0 && p.top >= 0, `${palco ? 'palco' : 'repouso'}: ${p.left},${p.top}`)
  }
})
