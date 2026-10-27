// Correção dos termos que o reconhecimento de voz do navegador costuma errar (pt-BR), aplicada a cada texto
// reconhecido antes da palavra de ativação e do envio ao JARVIS.

// Variantes de "Jarvis" só valem no começo da fala (vocativo): "graves" e "Jarbas" no meio de uma frase são
// palavras comuns e não podem acordar o assistente.
const VARIANTES = 'jarvis|jarbas|jarvas|jarves|jervis|javis|jarvi|jarviz|djarvis|garvis|graves|travis|jar vis'
const VOCATIVO = new RegExp(`^(\\s*(?:ei|ok|oi|hey|ol[aá])[\\s,]+)?(?:${VARIANTES})\\b`, 'i')

// [padrão, troca] — siglas soletradas ou em minúsculas e nomes próprios
const TERMOS = [
  [/\b(?:d[aá]bli[ou]|w)[\s.]*(?:esse|s)[\s.]*(?:ele|l)\b/gi, 'WSL'],
  [/\bo\.?\s?a\.?\s?b\b\.?/gi, 'OAB'],
  [/\bc\.?\s?t\.?\s?n\b\.?/gi, 'CTN'],
  [/\bi\.?\s?c\.?\s?m\.?\s?s\b\.?/gi, 'ICMS'],
  [/\bi\.?\s?b\.?\s?s\b\.?/gi, 'IBS'],
  [/\bc\.?\s?b\.?\s?s\b\.?/gi, 'CBS'],
  [/\bp\.?\s?g\.?\s?f\.?\s?n\b\.?/gi, 'PGFN'],
  [/\bmei\b/gi, 'MEI'],
  [/\bIBS (?:barra|e) CBS\b/g, 'IBS/CBS'],
  [/\bvel+o[sz]+o\b/gi, 'Veloso'],
]

export function corrigirTermos(texto) {
  if (!texto) return texto
  let t = texto.replace(VOCATIVO, (_, pre = '') => `${pre}Jarvis`)
  for (const [padrao, troca] of TERMOS) t = t.replace(padrao, troca)
  return t
}
