// Dados da categoria "Custos" do palco: custo do mês por modelo, vindo da telemetria de /costs (real).
import { MODEL_TO_TIER, TIERS } from '../../lib/tiers.js'

const usd = v => `US$ ${(v ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** chave estável: a cena só é recriada quando um valor muda, não a cada consulta de 3 s */
export const chaveCustos = costs => JSON.stringify({
  m: costs?.telemetria?.por_modelo || [], p: costs?.telemetria?.projecao_mes_usd ?? null,
  t: costs?.teto_usd ?? null, mes: costs?.mes_usd ?? null,
})

export function dadosCustos(chave) {
  const { m, p, t, mes } = JSON.parse(chave)
  const itens = [...m].sort((a, b) => b.custo_usd - a.custo_usd).map(x => {
    const tier = TIERS[MODEL_TO_TIER[x.modelo]]
    const nome = tier?.label || x.modelo
    return {
      id: x.modelo, nome, rotulo: `${nome} · ${usd(x.custo_usd)}`, valor: x.custo_usd, cor: tier?.ui || '#8fd3ff',
      requisicoes: x.requisicoes, fatia: x.fatia_custo_pct, media: x.media_usd,
    }
  })
  return { categoria: 'custos', itens, projecao: p, teto: t, mes }
}
