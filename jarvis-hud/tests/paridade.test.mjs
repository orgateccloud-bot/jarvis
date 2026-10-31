// Paridade com o serviço de voz local (jarvis/voz/texto.py): os mesmos casos rodam no pytest. Rode: npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { createEchoFilter } from '../src/lib/voice/echo.js'
import { NO, YES, afterWakeWord, createSentenceSplitter, isStopCommand, paraFala } from '../src/lib/voice/sentences.js'
import { corrigirTermos } from '../src/lib/voice/termos.js'

const casos = JSON.parse(readFileSync(new URL('../../tests/fixtures/voz/casos.json', import.meta.url), 'utf8'))

test('corrigirTermos: mesma saída do serviço de voz local', () => {
  for (const [entrada, saida] of casos.corrigirTermos) assert.equal(corrigirTermos(entrada), saida, entrada)
})

test('afterWakeWord: mesma saída do serviço de voz local', () => {
  for (const [entrada, saida] of casos.afterWakeWord) assert.equal(afterWakeWord(entrada), saida, entrada)
})

test('isStopCommand: mesma saída do serviço de voz local', () => {
  for (const [entrada, saida] of casos.isStopCommand) assert.equal(isStopCommand(entrada), saida, entrada)
})

test('paraFala, divisor de frases, sim/não e filtro de eco: mesma saída do serviço de voz local', () => {
  for (const [entrada, saida] of casos.paraFala) assert.equal(paraFala(entrada), saida, entrada)
  for (const [trechos, frases] of casos.divisor) {
    const out = []
    const sp = createSentenceSplitter(s => out.push(s))
    for (const t of trechos) {
      if (t.startsWith('*')) for (const c of t.slice(1)) sp.push(c)
      else sp.push(t)
    }
    sp.flush()
    assert.deepEqual(out, frases)
  }
  for (const [texto, sim, nao] of casos.simNao) assert.deepEqual([YES.test(texto), NO.test(texto)], [sim, nao], texto)
  for (const c of casos.eco) {
    let agora = 1_000_000
    const f = createEchoFilter({ now: () => agora })
    for (const l of c.lembrar) f.remember(l)
    if (c.terminou) f.ended()
    agora += c.passa_ms
    assert.equal(f.isEcho(c.ouvido, { answer: !!c.resposta }), c.eco, c.ouvido)
  }
})
