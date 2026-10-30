// Testes do divisor de frases (voz em streaming) e dos gatilhos de voz. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { NO, YES, afterWakeWord, createSentenceSplitter, isStopCommand } from '../src/lib/voice/sentences.js'

function run(chunks) {
  const out = []
  const sp = createSentenceSplitter(s => out.push(s))
  for (const c of chunks) sp.push(c)
  sp.flush()
  return out
}

test('streaming caractere a caractere: frases na ordem, sem markdown, código ou tabela', () => {
  const text = 'O Sol perde **4 milhões** de toneladas por segundo. Mesmo assim, deve durar mais 5 bilhões de anos.\n\n'
    + '| Café | Chá |\n|---|---|\n| forte | leve |\n\n```python\nprint(1)\n```\n'
    + '- Primeiro item da lista com bastante texto\n- Segundo item\n\nEm resumo, o valor é 3.5 vezes maior.'
  const out = run([...text])
  assert.equal(out[0], 'O Sol perde 4 milhões de toneladas por segundo.')
  assert.ok(out.every(s => !/[|*`#]/.test(s)))
  assert.ok(!out.some(s => s.includes('print')))
  assert.ok(out.some(s => s.includes('3.5 vezes')))
  assert.ok(out.some(s => s === 'Segundo item. Em resumo, o valor é 3.5 vezes maior.'))
})

test('frases curtas são juntadas para a fala não picotar', () => {
  assert.deepEqual(run(['Sim. ', 'Feito. ', 'O lembrete está criado para amanhã.']),
    ['Sim. Feito. O lembrete está criado para amanhã.'])
})

test('palavra de ativação e respostas sim/não', () => {
  assert.equal(afterWakeWord('Jarvis, que horas são?'), 'que horas são?')
  assert.equal(afterWakeWord('ok jarvis'), '')
  assert.equal(afterWakeWord('olá mundo'), null)
  assert.ok(isStopCommand('Jarvis, pare') && !isStopCommand('Jarvis para'))
  assert.ok(YES.test('sim pode abrir') && NO.test('não, cancela') && !YES.test('não'))
})
