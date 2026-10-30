// Ritmo de quadros do cosmos: 60 fps só quando o JARVIS pensa ou fala; no resto (repouso, escuta), 30 fps.

export const FPS_ATIVO = 60
export const FPS_REPOUSO = 30

export const fpsAlvo = state => (state === 'thinking' || state === 'speaking' ? FPS_ATIVO : FPS_REPOUSO)

// folga de ~2 ms: o rAF oscila em torno de 16,7 ms e, sem ela, 30 fps viraria 20 fps em monitor de 60 Hz
const FOLGA_MS = 2

/**
 * Cadência do próximo quadro. `marca` é a marca do último quadro desenhado (ms do rAF).
 * Devolve null se ainda não é hora de desenhar; senão, a nova marca. A marca avança em passos fixos
 * (monitor de 144 Hz chega a 60 fps, não a 48) e, depois de um atraso longo, reancora em `now`.
 */
export function proximoQuadro(now, marca, fps) {
  const ms = 1000 / fps
  if (now - marca < ms - FOLGA_MS) return null
  return now - marca > ms * 2 ? now : marca + ms
}
