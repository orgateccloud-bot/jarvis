// Palco holográfico: estado (aberto, categoria, item selecionado) e comandos de texto e voz.
// Funções puras, testadas em tests/palco.test.mjs.

export const CATEGORIAS = [
  { id: 'projetos', nome: 'Projetos', fala: 'os projetos' },
  { id: 'custos', nome: 'Custos', fala: 'os custos por modelo' },
]

export const PALCO_INICIAL = { aberto: false, categoria: null, selecionado: null }

const existe = id => CATEGORIAS.some(c => c.id === id)

export function palcoReducer(s, a) {
  switch (a.type) {
    case 'abrir':
      if (!existe(a.categoria) || (s.aberto && s.categoria === a.categoria)) return s
      return { aberto: true, categoria: a.categoria, selecionado: null }
    case 'fechar':
      return s.aberto ? PALCO_INICIAL : s
    case 'alternar':
      return s.aberto ? PALCO_INICIAL : { aberto: true, categoria: CATEGORIAS[0].id, selecionado: null }
    case 'passo': {
      if (!s.aberto || CATEGORIAS.length < 2) return s
      const n = CATEGORIAS.length
      const i = CATEGORIAS.findIndex(c => c.id === s.categoria)
      return { aberto: true, categoria: CATEGORIAS[(i + a.dir + n) % n].id, selecionado: null }
    }
    case 'selecionar':
      return s.aberto ? { ...s, selecionado: s.selecionado === a.id ? null : a.id } : s
    default:
      return s
  }
}

// sinônimos falados de cada categoria
const NOMES = { projetos: 'projetos', projeto: 'projetos', custos: 'custos', custo: 'custos', gastos: 'custos' }

const normaliza = t => t.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/[.!?,;:]+/g, ' ').replace(/\s+/g, ' ').trim()
  .replace(/^jarvis /, '')

/**
 * Comando do palco no texto digitado ou falado, ou null. Só frases inteiras e curtas casam
 * ("mostra os projetos", "fecha o palco", "/holo projetos"); perguntas sobre projetos seguem para o núcleo.
 * Devolve { type, categoria?, fala } — fala é a confirmação curta dita pela voz.
 */
export function comandoPalco(texto) {
  const t = normaliza(texto || '')
  const barra = t.match(/^\/holo(?: (\S+))?$/)
  if (barra) {
    const arg = barra[1]
    if (!arg) return { type: 'abrir', categoria: CATEGORIAS[0].id, fala: `Abrindo ${CATEGORIAS[0].fala}.` }
    if (/^(fechar|sair|fecha)$/.test(arg)) return { type: 'fechar', fala: 'Fechando o palco.' }
    const cat = NOMES[arg]
    return cat ? { type: 'abrir', categoria: cat, fala: `Abrindo ${CATEGORIAS.find(c => c.id === cat).fala}.` } : null
  }
  const abrir = t.match(/^(?:me )?(?:mostr[ae]|mostrar|abr[ae]|abrir|exib[ae]|exibir)(?: (?:o|os|a|as))?(?: (?:meu|meus|minha|minhas))? (\S+)(?: (?:no palco|em holograma))?$/)
  if (abrir && NOMES[abrir[1]]) {
    const cat = NOMES[abrir[1]]
    return { type: 'abrir', categoria: cat, fala: `Abrindo ${CATEGORIAS.find(c => c.id === cat).fala}.` }
  }
  if (/^(?:fech[ae]|fechar|esconde|esconder|sai[ar]? d[oa])(?: (?:o|a|os|as))? (?:palco|holograma|hologramas|projetos|custos|gastos)$/.test(t)) {
    return { type: 'fechar', fala: 'Fechando o palco.' }
  }
  return null
}
