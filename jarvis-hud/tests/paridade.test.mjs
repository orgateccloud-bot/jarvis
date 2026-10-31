// Paridade com o serviço de voz local (jarvis/voz/texto.py): os mesmos casos rodam no pytest. Rode: npm test
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { afterWakeWord, isStopCommand } from '../src/lib/voice/sentences.js'
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
