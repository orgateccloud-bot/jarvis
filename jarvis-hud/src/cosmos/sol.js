// Posição e raio do sol em uv do shader: fração da altura da tela, medida a partir do centro
// (x para a direita, y para cima). Compartilhado entre o cosmos, a área clicável e o arranjo dos painéis.
export const SOL = { x: 0, y: 0.13, r: 0.105 }
export const SOL_MOBILE = { x: 0, y: 0.17, r: 0.085 } // telas em pé (aspecto < 0,85)

export const telaEmPe = (W, H) => W / H < 0.85

// sol em pixels de tela: centro (cx, cy) e raio (rp)
export const solPx = ({ x, y, r }, W, H) => ({ cx: W / 2 + x * H, cy: H / 2 - y * H, rp: r * H })
