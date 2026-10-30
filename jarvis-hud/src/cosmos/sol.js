// Posição e raio do sol em uv do shader: fração da altura da tela, medida a partir do centro
// (x para a direita, y para cima). Compartilhado entre o cosmos, a área clicável e o arranjo dos painéis.
export const SOL = { x: 0, y: 0.13, r: 0.105 } // layout plano (telas menores)
export const SOL_HOLO = { x: 0, y: 0.13, r: 0.2 } // painéis de vidro: sol grande, como no vídeo de referência
export const SOL_MOBILE = { x: 0, y: 0.17, r: 0.085 } // telas em pé (aspecto < 0,85)

export const TRANSICAO_MS = 700 // o sol anda até um novo alvo nesse tempo (mesma curva do CSS dos painéis)

export const telaEmPe = (W, H) => W / H < 0.85

// sol em pixels de tela: centro (cx, cy) e raio (rp)
export const solPx = ({ x, y, r }, W, H) => ({ cx: W / 2 + x * H, cy: H / 2 - y * H, rp: r * H })

// As chamas são a parte cara do shader e eram calculadas até 4,5 raios. Com o sol maior, essa região
// cobriria mais de 80% da tela; o limite mantém a mesma área absoluta do sol de 0,105 (fase 0: com o
// limite, o sol de 0,2 custou ~0,4 W a mais falando; sem ele, até 4 W).
export const CHAMAS_RAIOS = 4.5
export const CHAMAS_AREA = CHAMAS_RAIOS * 0.105
export const limiteChamas = r => Math.min(CHAMAS_RAIOS, CHAMAS_AREA / r)
