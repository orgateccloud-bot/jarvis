// Corta o texto que chega em streaming em frases faláveis, para a voz começar antes da resposta terminar.
// Pula blocos de código e tabelas; remove marcações de markdown; junta frases curtas e quebra as longas.
// Corta só em . ! ? … e quebra de linha: ":" e ";" no meio da frase picotavam a voz em utterances curtos.

const MIN_CHARS = 80
const MAX_CHARS = 220

// ponto de corte de um trecho longo: a vírgula mais próxima do teto; sem vírgula, o último espaço
function cutPoint(text) {
  const comma = text.lastIndexOf(', ', MAX_CHARS)
  if (comma >= MIN_CHARS / 2) return comma + 1
  const after = text.indexOf(', ', MAX_CHARS)
  if (after >= 0 && after < MAX_CHARS * 1.5) return after + 1
  const space = text.lastIndexOf(' ', MAX_CHARS)
  return space > 0 ? space : MAX_CHARS
}

// último segmento de um caminho, sem a pontuação da frase que vem colada ("c.txt;" → "c.txt")
const lastSegment = path => {
  const [, body, tail] = /^(.*?)([.,;:!?)]*)$/.exec(path)
  return (body.split(/[\\/]/).filter(Boolean).pop() || 'o caminho') + tail
}

/**
 * Deixa o texto falável: caminhos e URLs lidos letra a letra viram o nome final e o domínio;
 * "_" vira espaço; aspas de código saem; "R$" e "%" vão por extenso.
 */
export function paraFala(text) {
  return text
    .replace(/\bhttps?:\/\/(?:www\.)?([^\s/?#)]+)[^\s)]*/gi, '$1')   // URL → domínio
    .replace(/\bwww\.([^\s/?#)]+)[^\s)]*/gi, '$1')
    .replace(/(?:\b[A-Za-z]:\\|\\\\)[^\s"'`<>|*?]*/g, m => lastSegment(m))   // C:\..., \\servidor\...
    .replace(/(?:^|(?<=\s))(?:~|\.{1,2})?\/[\w.-]+(?:\/[\w.-]*)+/g, m => lastSegment(m))   // /home/..., ~/...
    .replace(/R\$\s?(\d[\d.]*(?:,\d{1,2})?)(\s(?:mil|milh(?:ão|ões)|bilh(?:ão|ões)))?/g, '$1$2 reais')
    .replace(/(\d(?:[\d.,]*\d)?)\s?%/g, '$1 por cento')
    .replace(/_/g, ' ')
    .replace(/["“”`]/g, '')
}

function clean(text) {
  return paraFala(text
    .replace(/^\s*([-*•]|\d+[.)])\s+/, '')   // marcador de lista
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')) // links/imagens → só o texto
    .replace(/[#*~>|]/g, '')
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
    while (pending.length > MAX_CHARS) {
      const i = cutPoint(pending)
      emit(pending.slice(0, i).trim())
      pending = pending.slice(i).trim()
    }
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
      while ((m = /^([\s\S]*?[.!?…])\s+(?=\S)/.exec(buf))) {
        out(m[1])
        buf = buf.slice(m[0].length)
      }
      // frase longa sem ponto ainda chegando: fala até a vírgula para a voz não esperar o fim
      while (buf.length > MAX_CHARS * 1.5) {
        const i = cutPoint(buf)
        out(buf.slice(0, i))
        buf = buf.slice(i).replace(/^\s+/, '')
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
