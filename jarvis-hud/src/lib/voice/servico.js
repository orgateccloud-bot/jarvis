// Serviço de voz local (Etapa 2, Decisão A). Com JARVIS_VOZ_LOCAL=1 ele é o dono do microfone e do alto-falante:
// o HUD não ouve nem fala, só mostra o estado do serviço e manda comandos (ouvir, parar, mudo, som).
// Puro (sem React), para ser testável no npm test.

const ATIVOS = ['ouvindo', 'processando', 'falando']

// estado do serviço → fase visual do cosmos (a mesma que a voz do navegador produziria)
export const FASE_DO_SERVICO = { ouvindo: 'listening', processando: 'thinking', falando: 'speaking' }

/** O sol e o microfone: com a conversa aberta, param; em repouso, abrem a conversa (como o toggle do HUD). */
export const acaoDoSol = estado => (ATIVOS.includes(estado) ? 'parar' : 'ouvir')

/** Modo da conversa como o HUD o entende (useConversation): 'active' ou 'off'. */
export const modoDoServico = estado => (ATIVOS.includes(estado) ? 'active' : 'off')

/**
 * Aviso no topo quando o serviço para: o usuário pode pegar o microfone do navegador (o Chrome envia o áudio ao
 * servidor dele) e devolver depois. null = nada a avisar.
 */
export function avisoDaVoz(voz, doHud) {
  if (!voz) return null
  if (doHud) {
    return { titulo: 'Microfone do navegador em uso.', texto: 'O Chrome envia o áudio ao servidor dele.',
      botao: 'Devolver ao serviço local', acao: 'devolver' }
  }
  if (voz.estado === 'parado' || voz.situacao === 'falhou') {
    return { titulo: 'Escuta local parada.', texto: 'O serviço de voz não responde.',
      botao: 'Usar o microfone do navegador', acao: 'pegar' }
  }
  return null
}
