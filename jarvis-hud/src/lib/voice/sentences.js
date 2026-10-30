// Corta o texto que chega em streaming em frases faláveis, para a voz começar antes da resposta terminar.
// Pula blocos de código e tabelas; remove marcações de markdown; junta frases muito curtas.

const MIN_CHARS = 28

function clean(text) {
  return text
    .replace(/^\s*([-*•]|\d+[.)])\s+/, '')   // marcador de lista
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1') // links/imagens → só o texto
    .replace(/[#*_`~>|]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function createSentenceSplitter(emit) {
  let buf = ''
  let pending = ''
  let inCode = false

  const out = (text, force = false) => {
    const c = clean(text)
    if (!c) return
    // ao juntar trechos curtos, garante uma pausa entre eles (itens de lista não têm ponto final)
    pending = pending ? `${pending}${/[.!?…;:,]$/.test(pending) ? '' : '.'} ${c}` : c
    if (force || pending.length >= MIN_CHARS) {
      emit(pending)
      pending = ''
    }
  }

  const line = (l, force) => {
    if (/^\s*```/.test(l)) { inCode = !inCode; return }
    if (inCode || /^\s*\|/.test(l)) return
    out(l, force)
  }

  return {
    push(delta) {
      buf += delta
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        line(buf.slice(0, nl), false)
        buf = buf.slice(nl + 1)
      }
      if (inCode || /^\s*(```|\|)/.test(buf)) return
      // frases completas na linha corrente: pontuação seguida de espaço e mais texto
      let m
      while ((m = /^([\s\S]*?[.!?…;:])\s+(?=\S)/.exec(buf))) {
        out(m[1])
        buf = buf.slice(m[0].length)
      }
    },
    flush() {
      if (buf.trim()) line(buf, true)
      else if (pending) out('', true)
      if (pending) { emit(pending); pending = '' }
      buf = ''
      inCode = false
    },
  }
}

// Gatilhos de voz
// Interromper por voz só com comando curto no começo da fala: "Jarvis, pare", "Jarvis, silêncio" ou "pare".
// "para", "espera" e "chega" saíram: aparecem em frases comuns e no eco da própria voz.
const STOP_COMMAND = /^(?:jarvis[\s,!.]+(?:pare|sil[eê]ncio)|pare)(?![\p{L}\p{N}])/iu
export function isStopCommand(text) {
  const t = (text || '').trim()
  return !!t && t.split(/\s+/).length <= 3 && STOP_COMMAND.test(t)
}
export const WAKE_WORD = /\bjarvis\b/i
export const YES = /^\s*(sim|pode|pode sim|confirmo|confirma|autorizo|aprovado|aprovo|ok|claro|manda)\b/i
export const NO = /^\s*(n[aã]o|cancela|cancelar|negado|nega|nem pensar)\b/i

/** Remove a palavra de ativação e devolve o pedido que veio junto ("Jarvis, que horas são?"). */
export function afterWakeWord(text) {
  const i = text.search(WAKE_WORD)
  if (i < 0) return null
  return text.slice(i).replace(WAKE_WORD, '').replace(/^[\s,.!?:;-]+/, '').trim()
}
