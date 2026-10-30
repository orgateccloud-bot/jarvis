// Decide o que fazer com um texto reconhecido. Puro (sem React), para o fluxo da conversa ser testável.
//   ctx: { mode, speaking, busy, pendingApproval, isEcho(text, { answer }) }
//   devolve { action: 'ignore' | 'cancel' | 'approve' | 'wake' | 'caption' | 'ask', ... }
import { NO, WAKE_WORD, YES, afterWakeWord, isStopCommand } from './sentences.js'

export function routeHeard(text, isFinal, ctx) {
  // eco da própria voz (frase em curso ou recente): descarta antes de tudo; nunca vira pergunta nem interrupção
  const answer = ctx.pendingApproval && (YES.test(text) || NO.test(text))
  if (!isStopCommand(text) && ctx.isEcho?.(text, { answer })) return { action: 'ignore', echo: true }

  // falando: só um comando curto e explícito interrompe; o resto é eco do alto-falante ou conversa paralela
  if (ctx.speaking) return isStopCommand(text) ? { action: 'cancel' } : { action: 'ignore' }

  // aprovação pendente: "sim"/"não" por voz
  if (ctx.pendingApproval && isFinal && (YES.test(text) || NO.test(text)))
    return { action: 'approve', ok: YES.test(text) && !NO.test(text) }

  if (ctx.mode === 'wake') {
    if (!WAKE_WORD.test(text)) return { action: 'ignore' }
    const rest = afterWakeWord(text)
    if (isFinal && rest && rest.length > 2 && !isStopCommand(text)) return { action: 'wake', ask: rest }
    return { action: 'wake', greet: isFinal && !isStopCommand(text) }
  }

  if (ctx.mode === 'active') {
    if (ctx.busy) return { action: 'ignore' }
    if (!isFinal) return { action: 'caption' }
    if (isStopCommand(text)) return { action: 'ignore' }  // "pare" com nada falando não vira pergunta
    return { action: 'ask' }
  }
  return { action: 'ignore' }
}
