// Testes das regras de exibição do painel fiscal. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  dataBR, dataHoraBR, diasAte, documentoFormatado, fontesComProblema, formatarCampo, ordenar, severidade, textoPrazo,
} from '../src/lib/fiscal.js'

const HOJE = new Date(2026, 9, 31, 10, 0) // 31/10/2026, hora local
const prazo = (data, extra = {}) => ({ grupo: 'prazos', tipo_data: 'vencimento', data, severidade: 'info', ...extra })

test('datas no formato brasileiro, sem deslocar o dia pelo fuso', () => {
  assert.equal(dataBR('2026-11-13'), '13/11/2026')
  assert.equal(dataHoraBR('2026-10-31T09:05:00'), '31/10 09:05')
  assert.equal(dataBR(null), '—')
  assert.equal(diasAte('2026-11-02', HOJE), 2)
  assert.equal(diasAte('2026-10-30', HOJE), -1)
})

test('severidade do prazo pela data de hoje; os outros grupos mantêm a do servidor', () => {
  assert.equal(severidade(prazo('2026-11-02'), HOJE), 'critico')
  assert.equal(severidade(prazo('2026-11-06'), HOJE), 'atencao')
  assert.equal(severidade(prazo('2026-11-30'), HOJE), 'info')
  assert.equal(severidade({ grupo: 'situacao', severidade: 'critico', tipo_data: 'vigencia', data: '2027-01-01' }, HOJE), 'critico')
})

test('texto da data diz quanto falta ou o tipo da data', () => {
  assert.equal(textoPrazo(prazo('2026-10-31'), HOJE), 'vence 31/10/2026 (hoje)')
  assert.equal(textoPrazo(prazo('2026-11-01'), HOJE), 'vence 01/11/2026 (amanhã)')
  assert.equal(textoPrazo(prazo('2026-11-13'), HOJE), 'vence 13/11/2026 (em 13 d)')
  assert.equal(textoPrazo({ tipo_data: 'publicacao', data: '2026-10-14' }, HOJE), 'publicado 14/10/2026')
  assert.equal(textoPrazo({ tipo_data: 'ato', data: '2025-01-16' }, HOJE), 'ato 16/01/2025')
})

test('críticos primeiro', () => {
  const itens = [prazo('2026-11-30', { id: 'c' }), prazo('2026-11-01', { id: 'a' }), prazo('2026-11-06', { id: 'b' })]
  assert.deepEqual(ordenar(itens, HOJE).map(i => i.id), ['a', 'b', 'c'])
})

test('só fontes ligadas que falharam viram aviso', () => {
  const fontes = [{ id: 'a', ok: true }, { id: 'b', ok: false }, { id: 'c', ok: false, ligada: false }, { id: 'd', ok: null }]
  assert.deepEqual(fontesComProblema(fontes).map(f => f.id), ['b'])
})

test('campos do cliente em uma linha', () => {
  assert.equal(documentoFormatado('11222333000181'), '11.222.333/0001-81')
  assert.equal(formatarCampo('regime_tributario', 'lucro_presumido'), 'Lucro Presumido')
  assert.equal(formatarCampo('ufs_operacao', ['GO', 'TO']), 'GO, TO')
  assert.equal(formatarCampo('contato', { nome: 'Maria', email: 'maria@exemplo.com' }), 'Maria · maria@exemplo.com')
  assert.equal(formatarCampo('certidoes', [{ tipo: 'CND federal', situacao: 'positiva_efeito_negativa', validade: '2026-12-01' }]),
    'CND federal: positiva efeito negativa até 01/12/2026')
  assert.match(formatarCampo('contratos', [{ descricao: 'Assessoria', honorario_mensal: 1500, vencimento_dia: 10 }]),
    /^Assessoria · R\$\s1\.500,00 · dia 10$/)
  assert.equal(formatarCampo('cnae_principal', null), '—')
})
