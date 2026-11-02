// Astro do centro do HUD (02/11/2026): o sol fica só no JARVIS principal; cada um dos outros tem um planeta.
// O planeta é iluminado pela estrela da camada que respondeu (cor de TIERS), então a classe estelar mostrada na
// barra de cima e no card Neural continua valendo: é a estrela que ilumina o planeta.
// `id` vira o `#define ASTRO` do shader (cosmos/shaders.js); `chamado` entra nas dicas ("Clique no sol/planeta").

export const ASTROS = {
  sol: { id: 0, nome: 'Sol', chamado: 'sol', abertura: 'Ignição estelar' },
  rochoso: { id: 1, nome: 'Marte', chamado: 'planeta', abertura: 'Formação planetária' },
  anelado: { id: 2, nome: 'Saturno', chamado: 'planeta', abertura: 'Formação planetária' },
  gelado: { id: 3, nome: 'Netuno', chamado: 'planeta', abertura: 'Formação planetária' },
}

/** O astro deste JARVIS: o principal (branch main) fica com o sol. */
export const ASTRO = 'rochoso' // JARVIS-TRILHUM: Marte

/** Dados do astro pela chave; chave desconhecida cai no sol. */
export const astroDe = (chave = ASTRO) => ASTROS[chave] || ASTROS.sol
