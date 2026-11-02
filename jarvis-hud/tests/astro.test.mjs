// Astro do centro do HUD: sol no JARVIS principal, um planeta em cada um dos outros. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ASTRO, ASTROS, astroDe } from '../src/lib/astro.js'
import { fragDoAstro } from '../src/cosmos/shaders.js'

test('cada astro tem um id próprio, e o deste JARVIS existe', () => {
  const ids = Object.values(ASTROS).map(a => a.id)
  assert.equal(new Set(ids).size, ids.length)
  assert.ok(ASTROS[ASTRO], `ASTRO desconhecido: ${ASTRO}`)
  assert.equal(ASTROS.sol.id, 0) // o shader trata 0 como o sol
})

test('chave desconhecida cai no sol', () => {
  assert.equal(astroDe('pulsar'), ASTROS.sol)
  assert.equal(astroDe('anelado').nome, 'Saturno')
})

test('o #define do astro vem logo depois do #version, que tem de ser a primeira linha', () => {
  for (const { id } of Object.values(ASTROS)) {
    const [primeira, segunda] = fragDoAstro(id).split('\n')
    assert.equal(primeira, '#version 300 es')
    assert.equal(segunda, `#define ASTRO ${id}`)
  }
})

test('o shader tem o sol e um bloco para cada planeta', () => {
  const frag = fragDoAstro(0)
  assert.match(frag, /#if ASTRO == 0\s+\/\/ ── 3\. sol flamejante/)
  // Marte (1) e Saturno (2) têm bloco próprio; Netuno (3) é o #else, então um 4º planeta exigiria mexer no shader
  assert.match(frag, /#if ASTRO == 1\b/)
  assert.match(frag, /#elif ASTRO == 2\b/)
  assert.deepEqual(Object.values(ASTROS).map(a => a.id).sort(), [0, 1, 2, 3])
})
