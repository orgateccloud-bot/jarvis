// Testes da legenda do que o JARVIS está fazendo. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { faseDepoisDaFerramenta, rotuloDaFerramenta } from '../src/lib/atividade.js'

test('cada ferramenta conhecida tem o seu rótulo; a desconhecida cai em "Trabalhando"', () => {
  assert.equal(rotuloDaFerramenta('buscar_conhecimento'), 'Consultando a base')
  assert.equal(rotuloDaFerramenta('analisar_espaco'), 'Analisando o disco')
  assert.equal(rotuloDaFerramenta('trilhum_agenda'), 'Abrindo a agenda de estudos')
  assert.equal(rotuloDaFerramenta('comandar_agente'), 'Acionando o agente')
  assert.equal(rotuloDaFerramenta('ferramenta_nova'), 'Trabalhando')
  assert.equal(rotuloDaFerramenta(undefined), 'Trabalhando')
})

test('ferramenta que começa volta a ser trabalho, mesmo depois de já ter vindo texto', () => {
  assert.equal(faseDepoisDaFerramenta('speaking', { fase: 'inicio' }), 'thinking')
  assert.equal(faseDepoisDaFerramenta('waiting', { fase: 'inicio' }), 'thinking')
})

test('ferramenta que termina só libera a espera de aprovação (negada ou expirada)', () => {
  assert.equal(faseDepoisDaFerramenta('waiting', { fase: 'fim', negado: true }), 'thinking')
  assert.equal(faseDepoisDaFerramenta('speaking', { fase: 'fim', ok: true }), 'speaking')
  assert.equal(faseDepoisDaFerramenta('thinking', { fase: 'fim', ok: true }), 'thinking')
})
