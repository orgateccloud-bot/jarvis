// Tela limpa (01/11/2026): cards minimizados (só o título fica) e conversa limpa da tela.
// Os cards minimizados são preferência de quem olha o HUD, então ficam no navegador; o JARVIS não precisa saber.

const CHAVE = 'jarvis.cards.minimizados'

/** Ids dos cards minimizados guardados no navegador ([] se não houver, ou se o navegador recusar). */
export function lerMinimizados(armazem = globalThis.localStorage) {
  try {
    const v = JSON.parse(armazem?.getItem(CHAVE) || '[]')
    return Array.isArray(v) ? v.filter(x => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function salvarMinimizados(ids, armazem = globalThis.localStorage) {
  try {
    armazem?.setItem(CHAVE, JSON.stringify(ids))
  } catch {
    // janela privada ou dados do site bloqueados: só não lembra na próxima vez
  }
}

/** Minimiza o card se estava aberto, e abre se estava minimizado. */
export function alternar(minimizados, id) {
  return minimizados.includes(id) ? minimizados.filter(x => x !== id) : [...minimizados, id]
}

/** Botão da barra de cima: com algum card aberto, minimiza todos; com todos minimizados, abre todos. */
export function alternarTodos(minimizados, ids) {
  if (ids.length && ids.every(id => minimizados.includes(id))) return minimizados.filter(x => !ids.includes(x))
  return [...new Set([...minimizados, ...ids])]
}

/** O que fica ao limpar a conversa: confirmações ainda sem resposta (senão não dá mais para aprovar) e a resposta
 *  que ainda está chegando. O contexto do JARVIS não muda: para recomeçar do zero, "Ok, Jarvis". */
export function mensagensQueFicam(mensagens) {
  return mensagens.filter(m => (m.role === 'approval' && m.status === 'pendente') || m.streaming)
}
