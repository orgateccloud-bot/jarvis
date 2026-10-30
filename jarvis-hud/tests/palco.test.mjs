// Palco holográfico: estado e comandos de texto e voz. Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { CATEGORIAS, PALCO_INICIAL, comandoPalco, palcoReducer } from '../src/holo/palco.js'

test('abrir, selecionar, trocar a seleção e fechar', () => {
  let s = palcoReducer(PALCO_INICIAL, { type: 'abrir', categoria: 'projetos' })
  assert.deepEqual(s, { aberto: true, categoria: 'projetos', selecionado: null })
  s = palcoReducer(s, { type: 'selecionar', id: 'jarvis' })
  assert.equal(s.selecionado, 'jarvis')
  assert.equal(palcoReducer(s, { type: 'selecionar', id: 'jarvis' }).selecionado, null) // clicar de novo desmarca
  assert.equal(palcoReducer(s, { type: 'abrir', categoria: 'projetos' }), s) // mesma categoria: nada muda
  assert.deepEqual(palcoReducer(s, { type: 'fechar' }), PALCO_INICIAL)
})

test('categoria desconhecida e ações com o palco fechado não mudam nada', () => {
  assert.equal(palcoReducer(PALCO_INICIAL, { type: 'abrir', categoria: 'inexistente' }), PALCO_INICIAL)
  assert.equal(palcoReducer(PALCO_INICIAL, { type: 'selecionar', id: 'x' }), PALCO_INICIAL)
  assert.equal(palcoReducer(PALCO_INICIAL, { type: 'passo', dir: 1 }), PALCO_INICIAL)
  assert.equal(palcoReducer(PALCO_INICIAL, { type: 'fechar' }), PALCO_INICIAL)
})

test('alternar abre a primeira categoria e fecha de novo', () => {
  const s = palcoReducer(PALCO_INICIAL, { type: 'alternar' })
  assert.equal(s.categoria, CATEGORIAS[0].id)
  assert.deepEqual(palcoReducer(s, { type: 'alternar' }), PALCO_INICIAL)
})

test('comandos de texto e voz que abrem e fecham o palco', () => {
  for (const t of ['/holo', '/holo projetos', 'mostra os projetos', 'Jarvis, mostra os projetos.', 'abre os projetos',
    'me mostra os meus projetos', 'Mostre os projetos no palco', 'exibir projetos']) {
    assert.equal(comandoPalco(t)?.type, 'abrir', t)
    assert.equal(comandoPalco(t)?.categoria, 'projetos', t)
  }
  for (const t of ['/holo fechar', 'fecha o palco', 'Fechar o holograma', 'esconde os projetos', 'sai do palco']) {
    assert.equal(comandoPalco(t)?.type, 'fechar', t)
  }
})

test('perguntas sobre projetos seguem para o núcleo', () => {
  for (const t of ['quais projetos usam FastAPI?', 'mostra os projetos que usam FastAPI', 'o que é o palco?',
    '/holo inexistente', 'abre o Chrome', 'projetos', '']) {
    assert.equal(comandoPalco(t), null, t)
  }
})

test('custos: comandos e troca de categoria com as setas', () => {
  for (const t of ['/holo custos', 'mostra os custos', 'me mostra os gastos', 'abre os custos no palco']) {
    assert.equal(comandoPalco(t)?.categoria, 'custos', t)
  }
  assert.equal(comandoPalco('fecha os custos')?.type, 'fechar')
  assert.equal(comandoPalco('quanto gastei com o Opus?'), null)
  let s = palcoReducer(PALCO_INICIAL, { type: 'abrir', categoria: 'projetos' })
  s = palcoReducer(s, { type: 'passo', dir: 1 })
  assert.equal(s.categoria, 'custos')
  s = palcoReducer(s, { type: 'passo', dir: 1 })
  assert.equal(s.categoria, 'projetos')
  assert.equal(palcoReducer(s, { type: 'passo', dir: -1 }).categoria, 'custos')
})

test('custos: barras do maior para o menor, rótulo com o valor e lista vazia sem erro', async () => {
  const { chaveCustos, dadosCustos } = await import('../src/holo/conteudo/custos.js')
  const costs = {
    teto_usd: 15, mes_usd: 14.11,
    telemetria: {
      projecao_mes_usd: 14.59,
      por_modelo: [
        { modelo: 'claude-sonnet-5-5', custo_usd: 2.15, requisicoes: 40, fatia_custo_pct: 15.3, media_usd: 0.05 },
        { modelo: 'claude-opus-5-5', custo_usd: 10.27, requisicoes: 90, fatia_custo_pct: 72.7, media_usd: 0.11 },
        { modelo: 'modelo-desconhecido', custo_usd: 0.25, requisicoes: 3, fatia_custo_pct: 1.8, media_usd: 0.08 },
      ],
    },
  }
  const d = dadosCustos(chaveCustos(costs))
  assert.deepEqual(d.itens.map(i => i.id), ['claude-opus-5-5', 'claude-sonnet-5-5', 'modelo-desconhecido'])
  assert.equal(d.itens[0].nome, 'Opus')
  assert.match(d.itens[0].rotulo, /^Opus · US\$ 10,27$/)
  assert.equal(d.itens[2].nome, 'modelo-desconhecido') // sem camada conhecida: mostra o id
  assert.equal(d.projecao, 14.59)
  assert.equal(chaveCustos(costs), chaveCustos({ ...costs })) // mesma chave entre consultas iguais
  assert.deepEqual(dadosCustos(chaveCustos(null)).itens, [])
})
