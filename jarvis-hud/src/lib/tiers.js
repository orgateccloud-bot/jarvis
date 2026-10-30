// Camadas de raciocínio do JARVIS e a classe estelar que cada uma assume no sol.
// temp: temperatura da fotosfera (K) → cor por corpo negro no shader.
// galaxy: tonalidade da galáxia ao redor. ui: cor de destaque na interface.
export const TIERS = {
  regras: {
    label: 'Regras', model: 'resposta instantânea', classe: 'G2V · o Sol', temp: 5800,
    galaxy: '#4D7CFF', ui: '#FFC861', giant: 0,
  },
  simples: {
    label: 'Haiku', model: 'claude-haiku-5-5', classe: 'Classe B · azul-branca', temp: 16000,
    galaxy: '#22D3EE', ui: '#8EC5FF', giant: 0,
  },
  media: {
    label: 'Sonnet', model: 'claude-sonnet-5-5', classe: 'Classe A · branco-pérola', temp: 7800,
    galaxy: '#A78BFA', ui: '#D9CCFF', giant: 0.15,
  },
  complexa: {
    label: 'Opus', model: 'claude-opus-5-5', classe: 'Classe K · gigante laranja', temp: 4300,
    galaxy: '#FB7A3C', ui: '#FF8A3D', giant: 1,
  },
  fable: {
    label: 'Fable', model: 'claude-fable-5-1', classe: 'Classe O · supergigante azul', temp: 30000,
    galaxy: '#818CF8', ui: '#A5B4FC', giant: 1,
  },
  alerta: {
    label: 'Alerta', model: '—', classe: 'Classe M · ejeção coronal', temp: 3000,
    galaxy: '#FF3B30', ui: '#FF4D4D', giant: 0.6,
  },
}

// Rota vinda do backend (evento "route") → chave de camada.
export const ROUTE_TO_TIER = { local: 'regras', simples: 'simples', media: 'media', complexa: 'complexa', fable: 'fable' }

export const ROUTE_LABEL = {
  local: 'Regras', simples: 'Simples', media: 'Intermediária', complexa: 'Complexa', fable: 'Topo',
}

// Modelo da API → camada (para a telemetria de custos por modelo).
export const MODEL_TO_TIER = Object.fromEntries(
  Object.entries(TIERS).filter(([, t]) => t.model.startsWith('claude-')).map(([k, t]) => [t.model, k]),
)

export const hexToRgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
