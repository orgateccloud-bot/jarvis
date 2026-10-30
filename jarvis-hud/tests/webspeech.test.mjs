// Testes do motor de voz com reconhecedor e sintetizador falsos (half-duplex). Rode: npm test
import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { TAIL_MS, createWebSpeechEngine } from '../src/lib/voice/webspeech.js'

function fakes() {
  const log = []
  class SR {
    constructor() { this.active = false; SR.last = this }
    start() { if (this.active) throw new Error('já ativo'); this.active = true; log.push('start') }
    stop() { if (!this.active) return; this.active = false; log.push('stop'); this.onend?.() }
  }
  const spoken = []
  const synth = {
    speaking: false, pending: false,
    getVoices: () => [],
    speak(u) { spoken.push(u) },
    cancel() { spoken.length = 0 },
  }
  class Utterance { constructor(text) { this.text = text } }
  return { log, SR, synth, Utterance, spoken }
}

test('microfone pausa no speakStart e volta ~1,5 s após speakEnd; o desejo de ouvir é preservado', () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] })
  try {
    const f = fakes()
    const engine = createWebSpeechEngine(f)
    const events = []
    engine.on({ speakStart: () => events.push('speakStart'), speakEnd: () => events.push('speakEnd') })
    engine.listen()
    assert.deepEqual(f.log, ['start'])

    engine.speak('Primeira frase da resposta.')
    engine.speak('Segunda frase da resposta.')
    assert.deepEqual(f.log, ['start', 'stop'])
    assert.ok(engine.micPaused)

    mock.timers.tick(1000)  // o onend do reconhecedor não religa durante a fala
    assert.deepEqual(f.log, ['start', 'stop'])

    for (const u of [...f.spoken]) { u.onstart?.(); u.onend?.() }
    assert.deepEqual(events, ['speakStart', 'speakEnd'])
    mock.timers.tick(TAIL_MS - 10)
    assert.equal(f.log.length, 2, 'ainda na cauda')
    mock.timers.tick(20)
    assert.deepEqual(f.log, ['start', 'stop', 'start'])
    assert.ok(!engine.micPaused)
  } finally { mock.timers.reset() }
})

test('parar de ouvir durante a fala: a cauda não religa o microfone', () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] })
  try {
    const f = fakes()
    const engine = createWebSpeechEngine(f)
    engine.listen()
    engine.speak('Uma resposta.')
    engine.stopListening()
    engine.cancel()
    mock.timers.tick(TAIL_MS * 2)
    assert.deepEqual(f.log, ['start', 'stop'])
  } finally { mock.timers.reset() }
})

test('voz: prefere a pt-BR local; sem local, a natural/online', () => {
  const voz = (name, lang, localService) => ({ name, lang, localService })
  const online = voz('Microsoft Francisca Online (Natural)', 'pt-BR', false)
  const local = voz('Microsoft Maria', 'pt-BR', true)
  const escolhida = vozes => {
    const f = fakes()
    f.synth.getVoices = () => vozes
    const engine = createWebSpeechEngine(f)
    engine.speak('Teste.')
    const v = f.spoken[0].voice
    engine.cancel()
    return v
  }
  assert.equal(escolhida([online, local, voz('Joana', 'pt-PT', true)]), local)
  assert.equal(escolhida([voz('Google português do Brasil', 'pt-BR', false), online]), online)
  assert.equal(escolhida([voz('Joana', 'pt-PT', true)]).name, 'Joana')
})

test('listen() durante a fala espera a cauda; sem half-duplex o microfone fica aberto', () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] })
  try {
    const f = fakes()
    const engine = createWebSpeechEngine(f)
    engine.speak('Olá.')
    engine.listen()
    assert.deepEqual(f.log, [])
    engine.cancel()
    mock.timers.tick(TAIL_MS)
    assert.deepEqual(f.log, ['start'])

    const g = fakes()
    const fone = createWebSpeechEngine(g)
    fone.setHalfDuplex(false)
    fone.listen()
    fone.speak('Com fone de ouvido.')
    assert.deepEqual(g.log, ['start'])
    assert.ok(!fone.micPaused)
    fone.cancel()
  } finally { mock.timers.reset() }
})
