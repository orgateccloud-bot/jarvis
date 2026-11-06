// Números vivos: as faixas de atenção dos anéis e o caminho de um número até o valor novo. Puro, para ser testável.

/** 0 normal, 1 atenção (a partir de 75%), 2 crítico (a partir de 90%). */
export const faixa = v => (v >= 90 ? 2 : v >= 75 ? 1 : 0)

const suave = p => 1 - (1 - p) ** 3 // começa rápido e assenta devagar, como a curva --ease do CSS

/** Valor entre `de` e `para` no progresso `p` (0 a 1; fora disso, fica no limite). */
export function interpolar(de, para, p) {
  return de + (para - de) * suave(Math.min(1, Math.max(0, p)))
}
