// Painel fiscal: formatação e regras de exibição dos cards tributário e do cliente (funções puras, testáveis).

export const GRUPOS = [
  { chave: 'prazos', titulo: 'Obrigações e prazos fiscais', vazio: 'Nenhum prazo nos próximos 45 dias.' },
  { chave: 'legislacao', titulo: 'Legislação e reforma tributária', vazio: 'Sem novidades coletadas.' },
  { chave: 'situacao', titulo: 'Situação do cliente', vazio: 'Escolha um cliente para ver a situação.' },
  { chave: 'interno', titulo: 'Vencimentos e pendências internas', vazio: 'Nada pendente para este cliente.' },
]

export const ROTULO_DATA = {
  vencimento: 'vence', publicacao: 'publicado', vigencia: 'vigência', competencia: 'competência', ato: 'ato',
}

export const ROTULO_ORIGEM = { oficial: 'fonte oficial', integracao: 'integração', interna: 'interno' }

const ORDEM_SEVERIDADE = { critico: 0, atencao: 1, info: 2 }

/** "2026-11-13" → "13/11/2026" (sem fuso: a data vem sem hora). */
export function dataBR(iso) {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return `${d}/${m}/${a}`
}

/** "2026-10-31T09:00:00" → "31/10 09:00". */
export function dataHoraBR(iso) {
  if (!iso) return '—'
  const [data, hora = ''] = String(iso).split('T')
  const [, m, d] = data.split('-')
  return `${d}/${m} ${hora.slice(0, 5)}`.trim()
}

export function diasAte(iso, hoje = new Date()) {
  const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number)
  const alvo = Date.UTC(a, m - 1, d)
  const base = Date.UTC(hoje.getFullYear(), hoje.getMonth(), hoje.getDate())
  return Math.round((alvo - base) / 86400000)
}

/** Prazo: a severidade é recalculada pela data de hoje (o dado pode ter horas). Os outros mantêm a do servidor. */
export function severidade(item, hoje = new Date()) {
  if (item.grupo !== 'prazos' || item.tipo_data !== 'vencimento') return item.severidade || 'info'
  const dias = diasAte(item.data, hoje)
  return dias <= 2 ? 'critico' : dias <= 7 ? 'atencao' : 'info'
}

export function textoPrazo(item, hoje = new Date()) {
  if (item.tipo_data !== 'vencimento') return `${ROTULO_DATA[item.tipo_data] || 'data'} ${dataBR(item.data)}`
  const dias = diasAte(item.data, hoje)
  const quando = dias === 0 ? 'hoje' : dias === 1 ? 'amanhã' : dias < 0 ? `há ${-dias} d` : `em ${dias} d`
  return `vence ${dataBR(item.data)} (${quando})`
}

export function ordenar(itens, hoje = new Date()) {
  return [...itens].sort((a, b) => ORDEM_SEVERIDADE[severidade(a, hoje)] - ORDEM_SEVERIDADE[severidade(b, hoje)])
}

/** Fontes ligadas cuja última coleta falhou: o card avisa e segue com os últimos dados válidos. */
export function fontesComProblema(fontes = []) {
  return fontes.filter(f => f.ligada !== false && f.ok === false)
}

// Campos do card do cliente, na ordem de exibição.
export const CAMPOS_CLIENTE = [
  ['razao_social', 'Razão social'],
  ['documento', 'CNPJ/CPF'],
  ['regime_tributario', 'Regime'],
  ['situacao_cadastral', 'Situação cadastral'],
  ['cnae_principal', 'CNAE principal'],
  ['cnaes_secundarios', 'CNAEs secundários'],
  ['atividades', 'Atividades'],
  ['uf_sede', 'UF da sede'],
  ['ufs_operacao', 'Estados de operação'],
  ['obrigacoes', 'Obrigações acessórias'],
  ['certidoes', 'Certidões'],
  ['contratos', 'Contrato e honorários'],
  ['contato', 'Contato responsável'],
]

const REGIMES = {
  simples: 'Simples Nacional', mei: 'MEI', lucro_presumido: 'Lucro Presumido', lucro_real: 'Lucro Real',
  pessoa_fisica: 'Pessoa física', produtor_rural: 'Produtor rural',
}

export function documentoFormatado(doc = '') {
  const d = String(doc)
  if (d.length === 14) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`
  if (d.length === 11) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`
  return d
}

export const brl = v => `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** Valor de um campo do cliente em texto de uma linha. */
export function formatarCampo(campo, valor) {
  if (valor == null || valor === '') return '—'
  switch (campo) {
    case 'documento': return documentoFormatado(valor)
    case 'regime_tributario': return REGIMES[valor] || String(valor)
    case 'cnaes_secundarios': case 'ufs_operacao': case 'obrigacoes': return [].concat(valor).join(', ')
    case 'contato': return [valor.nome, valor.email, valor.telefone].filter(Boolean).join(' · ') || '—'
    case 'certidoes': return [].concat(valor).map(c => `${c.tipo}: ${c.situacao.replaceAll('_', ' ')}${c.validade ? ` até ${dataBR(c.validade)}` : ''}`).join('; ')
    case 'contratos': return [].concat(valor).map(c => [c.descricao, c.honorario_mensal != null && brl(c.honorario_mensal), c.vencimento_dia && `dia ${c.vencimento_dia}`].filter(Boolean).join(' · ')).join('; ')
    default: return String(valor)
  }
}
