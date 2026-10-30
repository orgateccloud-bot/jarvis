// Filtro de eco: lembra as últimas frases que o JARVIS falou e reconhece quando o microfone devolve uma delas.
// O reconhecimento chega atrasado, então a comparação vale para a fala em curso e por WINDOW_MS após o fim.

const MAX = 6
const WINDOW_MS = 8000
const OVERLAP = 0.6
// palavras que aparecem em quase toda frase: não contam na sobreposição
const COMUNS = new Set(['que', 'para', 'com', 'uma', 'por', 'mais', 'como', 'dos', 'das', 'nos', 'nas', 'seu', 'sua',
  'isso', 'esse', 'essa', 'este', 'esta', 'tem', 'foi', 'ser', 'sao', 'nao', 'mas', 'ele', 'ela', 'voce'])

export function tokens(text) {
  return (text || '').toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim().split(' ').filter(Boolean)
}

const content = ts => {
  const c = ts.filter(t => t.length >= 3 && !COMUNS.has(t))
  return c.length ? c : ts
}

// maior subsequência comum (em palavras)
function lcs(a, b) {
  let prev = new Array(b.length + 1).fill(0)
  for (const x of a) {
    const cur = [0]
    for (let j = 0; j < b.length; j++) cur.push(x === b[j] ? prev[j] + 1 : Math.max(prev[j + 1], cur[j]))
    prev = cur
  }
  return prev[b.length]
}

export function createEchoFilter({ max = MAX, windowMs = WINDOW_MS, now = Date.now } = {}) {
  let said = []  // { toks, line, endedAt } — endedAt null enquanto a fala não terminou

  const recent = () => {
    const t = now()
    said = said.filter(s => s.endedAt === null || t - s.endedAt <= windowMs)
    return said
  }

  return {
    remember(text) {
      const toks = tokens(text)
      if (!toks.length) return
      said.push({ toks, line: ` ${toks.join(' ')} `, endedAt: null })
      if (said.length > max) said = said.slice(-max)
    },
    /** A fala terminou (fim natural, cancel ou watchdog): começa a contar a janela. */
    ended() {
      const t = now()
      for (const s of said) if (s.endedAt === null) s.endedAt = t
    },
    /**
     * answer: o texto parece resposta "sim"/"não" a uma confirmação. Aí só conta o eco literal com 3+ palavras
     * ("sim ou não"), para não engolir o "sim" do usuário logo depois de "Diga sim ou não".
     */
    isEcho(text, { answer = false } = {}) {
      const heard = tokens(text)
      if (!heard.length || (answer && heard.length < 3)) return false
      const line = ` ${heard.join(' ')} `
      const list = recent()
      // o eco pode emendar o fim de uma frase com o começo da seguinte
      const pairs = list.map((s, i) => (i ? ` ${list[i - 1].line.trim()}${s.line}` : s.line))
      if (pairs.some(l => l.includes(line))) return true
      if (answer || heard.length < 3) return false
      // sobreposição na mesma ordem (o eco preserva a ordem; a pergunta nova que reaproveita palavras, não)
      const h = content(heard)
      return list.some((s, i) => lcs(h, content(i ? [...list[i - 1].toks, ...s.toks] : s.toks)) / h.length >= OVERLAP)
    },
    clear() { said = [] },
  }
}
