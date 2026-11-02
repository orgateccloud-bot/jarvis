// Avisos proativos (02/11/2026): saudação, alertas e lembretes saem da conversa e vão para o card Avisos,
// no lado direito; o centro da tela fica só com a conversa.

export const MAX_AVISOS = 20

const doisDigitos = n => String(n).padStart(2, '0')

/** Evento de /events → aviso do card. A hora é a da chegada no HUD. */
export function novoAviso(ev, id, agora = new Date()) {
  return {
    id,
    kind: ev.kind,
    nivel: ev.nivel || 'info',
    titulo: ev.titulo || 'Aviso',
    texto: ev.texto || '',
    hora: `${doisDigitos(agora.getHours())}:${doisDigitos(agora.getMinutes())}`,
  }
}

/** O mais novo fica em cima; guarda só os últimos `max`. */
export function acrescentarAviso(lista, aviso, max = MAX_AVISOS) {
  return [aviso, ...lista].slice(0, max)
}
