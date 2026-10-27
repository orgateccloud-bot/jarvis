// Testes da correção de termos da voz. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { WAKE_WORD, afterWakeWord } from '../src/lib/voice/sentences.js'
import { corrigirTermos } from '../src/lib/voice/termos.js'

test('variantes de "Jarvis" no começo da fala viram a palavra de ativação', () => {
  assert.equal(corrigirTermos('Graves, que horas são?'), 'Jarvis, que horas são?')
  assert.equal(corrigirTermos('ok jarbas abre o chrome'), 'ok Jarvis abre o chrome')
  assert.equal(corrigirTermos('Jarvas me lembra amanhã'), 'Jarvis me lembra amanhã')
  const t = corrigirTermos('Jarbas, me lembra de ligar amanhã')
  assert.ok(WAKE_WORD.test(t))
  assert.equal(afterWakeWord(t), 'me lembra de ligar amanhã')
})

test('no meio da frase, palavras comuns ficam como estão (não acordam o JARVIS)', () => {
  for (const frase of ['os problemas são graves', 'o Jarbas ligou ontem', 'nos confins do meio', 'isso é tudo'])
    assert.equal(corrigirTermos(frase), frase)
  assert.ok(!WAKE_WORD.test(corrigirTermos('são falhas graves no sistema')))
})

test('siglas soletradas e nomes próprios', () => {
  assert.equal(corrigirTermos('o que diz o c t n sobre decadência'), 'o que diz o CTN sobre decadência')
  assert.equal(corrigirTermos('desliga o dabliu esse ele'), 'desliga o WSL')
  assert.equal(corrigirTermos('desliga o w s l'), 'desliga o WSL')
  assert.equal(corrigirTermos('quanto é o icms e o ibs barra cbs'), 'quanto é o ICMS e o IBS/CBS')
  assert.equal(corrigirTermos('estudo para a prova da o a b'), 'estudo para a prova da OAB')
  assert.equal(corrigirTermos('o mei paga das'), 'o MEI paga das')
  assert.equal(corrigirTermos('bom dia senhor velozo'), 'bom dia senhor Veloso')
  assert.equal(corrigirTermos(''), '')
})
