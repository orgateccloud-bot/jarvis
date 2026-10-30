// Testes da decisão sobre o texto reconhecido (interromper, aprovar, perguntar). Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isStopCommand } from '../src/lib/voice/sentences.js'
import { routeHeard } from '../src/lib/voice/route.js'

const falando = { mode: 'active', speaking: true, busy: false, pendingApproval: false }
const ouvindo = { mode: 'active', speaking: false, busy: false, pendingApproval: false }

test('"Jarvis, pare" curto interrompe; "o script para iniciar no logon" não', () => {
  for (const t of ['Jarvis, pare', 'jarvis pare', 'Jarvis, silêncio', 'pare', 'Pare!', 'pare agora'])
    assert.equal(routeHeard(t, true, falando).action, 'cancel', t)
  for (const t of ['o script para iniciar no logon', 'espera um pouco', 'chega disso', 'Jarvis',
    'para', 'parece que o Jarvis pare de funcionar', 'Jarvis, pare de usar o tom formal comigo'])
    assert.equal(routeHeard(t, true, falando).action, 'ignore', t)
})

test('comando de parar só no começo e em frase curta', () => {
  assert.ok(isStopCommand('Jarvis, pare.'))
  assert.ok(!isStopCommand('agora pare'))
  assert.ok(!isStopCommand('parede branca'))
  assert.ok(!isStopCommand(''))
})

test('ouvindo: pergunta final vai para ask(), parcial vira legenda, "pare" sozinho é ignorado', () => {
  assert.equal(routeHeard('que horas são', true, ouvindo).action, 'ask')
  assert.equal(routeHeard('que hor', false, ouvindo).action, 'caption')
  assert.equal(routeHeard('pare', true, ouvindo).action, 'ignore')
  assert.equal(routeHeard('que horas são', true, { ...ouvindo, busy: true }).action, 'ignore')
})

test('aprovação e palavra de ativação', () => {
  assert.deepEqual(routeHeard('sim, pode', true, { ...ouvindo, pendingApproval: true }), { action: 'approve', ok: true })
  assert.deepEqual(routeHeard('não', true, { ...ouvindo, pendingApproval: true }), { action: 'approve', ok: false })
  const wake = { ...ouvindo, mode: 'wake' }
  assert.deepEqual(routeHeard('Jarvis, que horas são?', true, wake), { action: 'wake', ask: 'que horas são?' })
  assert.deepEqual(routeHeard('Jarvis', true, wake), { action: 'wake', greet: true })
  assert.equal(routeHeard('bom dia', true, wake).action, 'ignore')
})
