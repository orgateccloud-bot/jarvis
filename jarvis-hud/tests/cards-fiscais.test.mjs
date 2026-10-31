// Renderização dos cards tributário e do cliente: o JSX é carregado pelo próprio Vite (ssrLoadModule) e vira HTML
// com o react-dom/server. Rode: npm test
import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const HOJE = new Date(2026, 9, 31, 10, 0)
let vite
let cards

before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'silent' })
  cards = await vite.ssrLoadModule('/src/components/FiscalCards.jsx')
})
after(() => vite?.close())

const html = (componente, props) => renderToStaticMarkup(createElement(componente, props))

const PAINEL = {
  atualizado_em: '2026-10-31T09:00:00',
  gerado_em: '2026-10-31T10:00:00',
  cliente_id: 7,
  fontes: [
    { id: 'receita_agenda', nome: 'Receita Federal · Agenda Tributária', ok: true, ligada: true },
    { id: 'sefaz_to', nome: 'SEFAZ-TO · Notícias', ok: false, ligada: true, erro: 'FonteIndisponivel: timeout',
      ultima_coleta: '2026-10-31T09:00:00', ultimo_sucesso: '2026-10-30T15:00:00' },
    { id: 'planalto', nome: 'Planalto', ok: null, ligada: false },
  ],
  grupos: {
    prazos: [{ id: 'p1', grupo: 'prazos', titulo: 'EFD-Contribuições (PJ)', data: '2026-11-13', tipo_data: 'vencimento',
      fonte_nome: 'Receita Federal · Agenda Tributária', origem: 'oficial', severidade: 'info',
      fonte_url: 'https://www.gov.br/receitafederal/pt-br/assuntos/agenda-tributaria/2026/Novembro/dia-13-11-2026' }],
    legislacao: [{ id: 'l1', grupo: 'legislacao', titulo: 'CONVÊNIO ICMS 121/26', data: '2026-10-14', tipo_data: 'publicacao',
      fonte_nome: 'CONFAZ · Convênios ICMS', origem: 'oficial', severidade: 'info',
      fonte_url: 'https://www.confaz.fazenda.gov.br/legislacao/convenios/2026/CV121_26' }],
    situacao: [{ id: 's1', grupo: 'situacao', titulo: 'CND federal: vencida', data: '2026-10-20', tipo_data: 'vigencia',
      fonte_nome: 'banco do JARVIS', fonte_url: null, origem: 'interna', severidade: 'critico' }],
    interno: [{ id: 'i1', grupo: 'interno', titulo: 'Honorários R$ 1.500,00 – Assessoria', data: '2026-11-10',
      tipo_data: 'vencimento', fonte_nome: 'planilha clientes.csv', fonte_url: null, origem: 'interna', severidade: 'info' }],
  },
}

test('card tributário: os quatro grupos, link e data de cada item, origem interna e a hora da atualização', () => {
  const h = html(cards.TributarioCard, { painel: PAINEL, onAtualizar: () => {}, hoje: HOJE })
  for (const g of ['Obrigações e prazos fiscais', 'Legislação e reforma tributária', 'Situação do cliente',
    'Vencimentos e pendências internas']) assert.ok(h.includes(g), g)
  assert.ok(h.includes('Atualizado em 31/10 09:00'))
  assert.ok(h.includes('href="https://www.confaz.fazenda.gov.br/legislacao/convenios/2026/CV121_26"'))
  assert.ok(h.includes('target="_blank" rel="noopener noreferrer"'))
  assert.ok(h.includes('vence 13/11/2026 (em 13 d)') && h.includes('publicado 14/10/2026'))
  assert.ok(!h.includes('fonte oficial') && h.includes('>interno<'))      // o selo só aparece fora das fontes oficiais
  assert.ok(h.includes('>CONFAZ<') && h.includes('title="CONFAZ · Convênios ICMS: https://'))
  assert.ok(h.includes('planilha clientes.csv') && h.includes('sev-critico'))
})

test('card tributário: fonte que falhou vira aviso com os últimos dados; fonte desligada não', () => {
  const h = html(cards.TributarioCard, { painel: PAINEL, onAtualizar: () => {}, hoje: HOJE })
  assert.ok(h.includes('SEFAZ-TO · Notícias falhou na coleta de 31/10 09:00'))
  assert.ok(h.includes('mostrando os últimos dados válidos, de 30/10 15:00'))
  assert.ok(!h.includes('Planalto falhou'))
  const semNucleo = html(cards.TributarioCard, { painel: PAINEL, erro: 'núcleo sem resposta', onAtualizar: () => {}, hoje: HOJE })
  assert.ok(semNucleo.includes('Sem resposta do núcleo (núcleo sem resposta)') && semNucleo.includes('CONVÊNIO ICMS 121/26'))
})

test('grupo longo mostra 4 itens e o botão para ver todos', () => {
  const muitos = Array.from({ length: 9 }, (_, n) => ({ ...PAINEL.grupos.prazos[0], id: `p${n}`, titulo: `Prazo ${n}` }))
  const h = html(cards.TributarioCard, { painel: { ...PAINEL, grupos: { ...PAINEL.grupos, prazos: muitos } },
    onAtualizar: () => {}, hoje: HOJE })
  assert.equal((h.match(/Prazo \d/g) || []).length, 4)
  assert.ok(h.includes('Ver todos (9)'))
})

test('card tributário antes da primeira resposta não quebra', () => {
  assert.ok(html(cards.TributarioCard, { painel: null, onAtualizar: () => {} }).includes('Aguardando o núcleo'))
})

const CLIENTE = {
  id: 7, gerado_em: '2026-10-31T10:00:00',
  campos: {
    razao_social: { valor: 'ALFA COMERCIO LTDA', fonte: 'portais', fonte_nome: 'SERPRO · Consulta CNPJ (Receita)', antigo: false },
    documento: { valor: '11222333000181', fonte: 'indice', fonte_nome: 'cadastro do cliente', antigo: false },
    regime_tributario: { valor: 'lucro_presumido', fonte: 'banco', fonte_nome: 'banco do JARVIS', antigo: false },
    cnae_principal: { valor: '4711-3/02', fonte: 'erp', fonte_nome: 'ERP (API)', antigo: true },
    contato: { valor: { nome: 'Maria' }, fonte: 'banco', fonte_nome: 'banco do JARVIS', antigo: false },
  },
  conflitos: [{ campo: 'razao_social', valores: { portais: 'ALFA COMERCIO LTDA', banco: 'Alfa Comércio Ltda' } }],
  fontes: [{ id: 'cliente_erp', nome: 'ERP (API)', ok: false, ligada: true, ultima_coleta: '2026-10-31T08:00:00',
    ultimo_sucesso: '2026-10-30T08:00:00' }],
}

test('card do cliente: campos com a fonte de cada um, dado antigo, conflito e aviso da fonte', () => {
  const h = html(cards.ClienteCard, { clientes: [{ id: 7, nome: 'Alfa', documento_mascarado: '11.***.***/0001-**' }],
    clienteId: 7, onEscolher: () => {}, cliente: CLIENTE })
  assert.ok(h.includes('11.222.333/0001-81') && h.includes('Lucro Presumido'))
  assert.ok(h.includes('SERPRO · Consulta CNPJ (Receita)') && h.includes('banco do JARVIS'))
  assert.ok(h.includes('ERP (API) · último dado válido') && h.includes('class="antigo"'))
  assert.ok(h.includes('fontes divergem'))
  assert.ok(h.includes('ERP (API) falhou na coleta de 31/10 08:00'))
  assert.ok(h.includes('Alfa · 11.***.***/0001-**'))
})

test('card do cliente sem clientes explica como cadastrar', () => {
  const h = html(cards.ClienteCard, { clientes: [], clienteId: null, onEscolher: () => {}, cliente: null })
  assert.ok(h.includes('Nenhum cliente cadastrado') && h.includes('POST /painel/clientes'))
})
