// Testes do HUD com o serviço de voz local no comando (Etapa 2, Decisão A). Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FASE_DO_SERVICO, acaoDoSol, avisoDaVoz, modoDoServico } from '../src/lib/voice/servico.js'

test('o sol e o microfone viram comandos para o serviço: abrem em repouso, param com a conversa aberta', () => {
  assert.equal(acaoDoSol('repouso'), 'ouvir')
  assert.equal(acaoDoSol('parado'), 'ouvir')
  for (const e of ['ouvindo', 'processando', 'falando']) assert.equal(acaoDoSol(e), 'parar')
})

test('o estado do serviço vira a fase visual e o modo da conversa no HUD', () => {
  assert.deepEqual(FASE_DO_SERVICO, { ouvindo: 'listening', processando: 'thinking', falando: 'speaking' })
  assert.equal(FASE_DO_SERVICO.repouso, undefined)       // repouso: a fase vem do resto do HUD
  assert.equal(modoDoServico('ouvindo'), 'active')
  assert.equal(modoDoServico('repouso'), 'off')
})

test('aviso: nada com a flag desligada ou o serviço vivo; oferece o microfone do navegador quando ele para', () => {
  assert.equal(avisoDaVoz(null, false), null)                                    // JARVIS_VOZ_LOCAL=0
  assert.equal(avisoDaVoz({ estado: 'ouvindo', situacao: 'rodando' }, false), null)
  assert.equal(avisoDaVoz({ estado: 'parado', situacao: 'reiniciando' }, false).acao, 'pegar')
  assert.equal(avisoDaVoz({ estado: 'repouso', situacao: 'falhou' }, false).acao, 'pegar')
  const emUso = avisoDaVoz({ estado: 'parado', situacao: 'falhou' }, true)
  assert.equal(emUso.acao, 'devolver')
  assert.match(emUso.texto, /servidor/)                                         // deixa claro que o áudio sai
})
