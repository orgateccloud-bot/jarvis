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
