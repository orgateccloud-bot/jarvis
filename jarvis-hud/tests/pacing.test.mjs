// Testes do ritmo de quadros do cosmos. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FPS_ATIVO, FPS_REPOUSO, fpsAlvo, proximoQuadro } from '../src/cosmos/pacing.js'

test('60 fps pensando ou falando; 30 fps em repouso e escutando', () => {
  assert.equal(fpsAlvo('thinking'), FPS_ATIVO)
  assert.equal(fpsAlvo('speaking'), FPS_ATIVO)
  assert.equal(fpsAlvo('idle'), FPS_REPOUSO)
  assert.equal(fpsAlvo('listening'), FPS_REPOUSO)
  assert.equal(fpsAlvo(undefined), FPS_REPOUSO)
})

// simula o rAF de um monitor de `hz` por 10 s (com jitter) e devolve os quadros desenhados por segundo
function desenhados(hz, fps) {
  let marca = -Infinity
  let n = 0
  for (let i = 0; i < hz * 10; i++) {
    const now = i * (1000 / hz) + (i % 2 ? 0.4 : -0.4)
    const prox = proximoQuadro(now, marca, fps)
    if (prox !== null) { marca = prox; n++ }
  }
  return n / 10
}

test('monitor de 60 Hz: 30 fps em repouso e 60 fps ativo', () => {
  assert.ok(Math.abs(desenhados(60, 30) - 30) <= 0.2)
  assert.ok(Math.abs(desenhados(60, 60) - 60) <= 0.2)
})

test('monitor de 144 Hz: mantém a média do alvo sem passar dele', () => {
  for (const fps of [30, 60]) {
    const n = desenhados(144, fps)
    assert.ok(n <= fps + 0.2 && n >= fps - 1, `${fps} fps → ${n}`)
  }
})

test('depois de pausa longa reancora, sem rajada de quadros atrasados', () => {
  const marca = proximoQuadro(5000, 1000, 30)
  assert.equal(marca, 5000)
  assert.equal(proximoQuadro(5010, marca, 30), null)
})
