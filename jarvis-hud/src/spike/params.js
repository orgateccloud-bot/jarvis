// SPIKE da fase 0 (descartável): variantes ligadas pela query string.
// Sem parâmetros, o HUD fica idêntico ao main (sol 0,105 a 0,13 de altura, chamas até 4,5 raios, sem painel).
//   ?holo=1        painel de vidro de CPU e RAM; os cards 2D somem
//   &sol=0.2       raio do sol (fração da altura da tela)
//   &suny=0.13     altura do centro do sol (fração da altura, acima do meio)
//   &lim=abs       região das chamas presa à área absoluta de hoje (4,5 × 0,105 da altura)
//   &wc=toggle     will-change na transição do modo palco: toggle | always | never
//   tecla P        alterna o modo palco (sol e painel para a esquerda, menores)
const q = new URLSearchParams(typeof location === 'undefined' ? '' : location.search)
const num = (k, d) => {
  const v = parseFloat(q.get(k))
  return Number.isFinite(v) ? v : d
}

export const SPIKE = {
  holo: q.get('holo') === '1',
  sunR: num('sol', 0.105),
  sunY: num('suny', 0.13),
  flameAbs: q.get('lim') === 'abs',
  wc: ['toggle', 'always', 'never'].includes(q.get('wc')) ? q.get('wc') : 'toggle',
}

export const FLAME_RAIOS = 4.5 // limite de hoje, em raios do sol
export const FLAME_ABS = FLAME_RAIOS * 0.105 // a mesma área em fração da altura da tela

// limite da região das chamas, em raios: com "abs", sol maior não aumenta a área calculada
export const flameLim = (r, abs = SPIKE.flameAbs) => (abs ? Math.min(FLAME_RAIOS, FLAME_ABS / r) : FLAME_RAIOS)

export const PALCO_X = 0.24 // centro do sol no modo palco, em fração da largura
export const PALCO_ESCALA = 0.55 // sol e painéis encolhem para 55% no modo palco
export const TRANSICAO_MS = 700
