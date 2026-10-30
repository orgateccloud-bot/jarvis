// Arranjo dos painéis de vidro em volta do sol (funções puras, testadas em tests/arranjo.test.mjs).
// Como no vídeo de referência: painéis grandes e parados, os dois mais próximos entram um pouco na borda do
// sol (só gráficos ficam sobre o disco), e nada cobre a conversa nem o dock.
import { solPx } from '../cosmos/sol.js'

export const MARGEM = 24
export const TOPO = 76 // abaixo da barra superior
export const VAO = 18
export const SOBRE = 0.3 // fração do raio que os painéis vizinhos entram no disco do sol

const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

// o vidro só aparece em telas largas; nas demais fica o layout plano de hoje (cards e gaveta)
export const holoAtivo = (W, H) => W >= 1280 && H >= 680 && W / H >= 1.45

// conversa e dock: coluna central na parte de baixo (largura min(780px, 52vw), como no CSS do modo vidro)
export function zonaConversa(W, H) {
  const meia = Math.min(390, 0.26 * W) + 16
  return { x0: W / 2 - meia, x1: W / 2 + meia, y0: Math.round(0.58 * H) }
}

const ret = (x, y, w, h, rot) => ({ x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h), rot })

/**
 * Retângulos (x, y, largura, altura em px, rotação em graus no eixo Y) de cada painel em repouso.
 * Painéis sem espaço suficiente voltam como null.
 */
export function arranjoRepouso({ W, H, sol }) {
  const { cx, rp } = solPx(sol, W, H)
  const conv = zonaConversa(W, H)
  const sobre = SOBRE * rp

  // CPU e RAM: à esquerda do sol, acima da conversa
  const cpuDir = cx - rp + sobre
  const cpuW = Math.min(clamp(0.25 * W, 380, 560), cpuDir - MARGEM)
  const cpuH = Math.min(conv.y0 - VAO - TOPO, 0.52 * H)
  const cpu = ret(cpuDir - cpuW, TOPO, cpuW, cpuH, -8)

  // decorativo: fino e muito inclinado, à esquerda do CPU, só se couber
  const livre = cpu.x - MARGEM - VAO
  const deco = livre >= 150 ? ret(cpu.x - VAO - Math.min(170, livre), TOPO + 40, Math.min(170, livre), cpu.h - 80, -58) : null

  // custo: canto inferior esquerdo, ao lado da conversa
  const custoY = cpu.y + cpu.h + VAO
  const custo = ret(MARGEM, custoY, Math.min(520, conv.x0 - VAO - MARGEM), H - MARGEM - custoY, -6)

  // modelos: à direita do sol, entrando na borda dele, acima da conversa
  const modX = cx + rp - sobre
  const modW = clamp(0.16 * W, 240, 320)
  const modelos = ret(modX, TOPO + 10, modW, Math.min(conv.y0 - VAO - TOPO - 10, 0.45 * H), 8)

  // neural e último turno: coluna da direita, sempre à direita da conversa (pode descer até o rodapé)
  const nx = Math.max(modelos.x + modelos.w, conv.x1) + VAO
  const nw = W - MARGEM - nx
  const neural = nw >= 240 ? ret(nx, TOPO, nw, Math.min(0.5 * H, H - MARGEM - TOPO - 150 - VAO), 8) : null
  const turno = neural ? ret(nx, neural.y + neural.h + VAO, nw, Math.min(150, H - MARGEM - (neural.y + neural.h + VAO)), 6) : null

  return { cpu, deco, custo, modelos, neural, turno }
}

// ── modo palco: a câmera recua, o sol vai para a esquerda e encolhe, o palco ocupa o centro ──
export const PALCO_SOL_X = 0.14 // centro do sol, em fração da largura
export const PALCO_SOL_ESCALA = 0.55
export const BLOCO_H = 92 // blocos compactos: escala 1 e texto de pelo menos 12 px (na fase 0, encolher os
// painéis grandes para 0,55 deixava texto de 7 px)

export const alvoSolPalco = (sol, W, H) => ({ x: (PALCO_SOL_X - 0.5) * (W / H), y: sol.y, r: sol.r * PALCO_SOL_ESCALA })

export function arranjoPalco({ W, H, sol }) {
  const s = alvoSolPalco(sol, W, H)
  const { cy, rp } = solPx(s, W, H)
  const conv = zonaConversa(W, H)
  const esq = 0.3 * W
  const blocoW = Math.min(300, conv.x0 - VAO - MARGEM, esq - VAO - MARGEM)
  let y = cy + rp + 28
  const bloco = () => {
    const r = ret(MARGEM, y, blocoW, BLOCO_H, -6)
    y += BLOCO_H + 12
    return r
  }
  const cpu = bloco()
  const custo = bloco()
  const modelo = bloco()
  const detX = 0.78 * W + VAO
  return {
    sol: s, cpu, custo, modelo,
    palco: ret(esq, TOPO, 0.78 * W - esq, conv.y0 - VAO - TOPO, 0),
    detalhes: ret(detX, TOPO, W - MARGEM - detX, H - MARGEM - TOPO, 6),
  }
}

// trilho de categorias: no repouso, no alto entre os painéis; no palco, sobre a borda de cima do palco
export const TRILHO = { w: 160, wPalco: 220, h: 34 }
export function trilho({ W, palco }) {
  if (palco) return ret(palco.x + palco.w / 2 - TRILHO.wPalco / 2, palco.y + 10, TRILHO.wPalco, TRILHO.h, 0)
  return ret(W / 2 - TRILHO.w / 2, TOPO - 4, TRILHO.w, TRILHO.h, 0)
}

// sobreposição entre dois retângulos (sem contar a rotação, que é pequena nos painéis com texto)
export const cruza = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
