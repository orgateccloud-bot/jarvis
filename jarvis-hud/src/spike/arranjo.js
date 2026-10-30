// SPIKE: posição do sol e do painel de CPU nos dois estados (repouso e modo palco). Funções puras.
import { PALCO_ESCALA, PALCO_X } from './params.js'

// alvo do sol em uv do shader (x e y em fração da altura, a partir do centro da tela)
export function alvoSol({ palco, W, H, r, y }) {
  if (!palco) return { x: 0, y, r }
  return { x: (PALCO_X - 0.5) * (W / H), y, r: r * PALCO_ESCALA }
}

// sol em pixels de tela
export function solPx({ x, y, r }, W, H) {
  return { cx: W / 2 + x * H, cy: H / 2 - y * H, rp: r * H }
}

// painel de CPU à esquerda do sol: a borda direita entra 30% do raio no disco, como no vídeo
export function painelCPU({ sol, W, H, escala = 1 }) {
  const w = Math.round(Math.min(0.29 * W, 600))
  const h = Math.round(Math.min(0.58 * H, 560))
  const { cx, cy, rp } = solPx(sol, W, H)
  const direita = cx - rp * 0.7
  return { w, h, left: Math.round(direita - w * escala), top: Math.round(cy - h * escala * 0.48), escala }
}
