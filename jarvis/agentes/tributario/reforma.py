"""Reforma Tributária: cronograma de transição (dado versionado no repositório) e a calculadora atual × pós-Reforma.

Os números saem daqui, nunca do modelo: o Claude só comenta o que a calculadora entregou. O modelo é simplificado e
declara as premissas e os limites em cada resposta.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..contratos import ParametrosCenario

ARQUIVO = Path(__file__).resolve().parent / "regras" / "cronograma_reforma.json"
ULTIMO_ANO = 2033

# Padrões quando o pedido não traz a alíquota (vão nas premissas, marcados como padrão)
PIS_COFINS = {"lucro_presumido": 0.0365, "lucro_real": 0.0925}   # cumulativo 0,65% + 3%; não cumulativo 1,65% + 7,6%
ICMS_PADRAO, ISS_PADRAO, IPI_PADRAO = 0.19, 0.05, 0.0

LIMITACOES = [
    ("Base de cálculo única (o faturamento) para todos os tributos: ignora ICMS por dentro e a exclusão do ICMS da "
     "base do PIS/Cofins."),
    "Crédito simplificado: a fração informada de compras gera crédito à mesma alíquota.",
    ("Não cobre o Simples Nacional, regimes diferenciados (reduções de 30% e 60%, cesta básica), Imposto Seletivo, "
     "substituição tributária, ZFM nem o efeito de caixa do split payment."),
]


@lru_cache
def cronograma() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))


def fase(ano: int) -> dict:
    """Regras do ano; depois de 2033 vale o regime pleno."""
    anos = cronograma()["anos"]
    return {"ano": ano, **anos[str(min(max(ano, 2026), ULTIMO_ANO))]}


def resumo_cronograma() -> str:
    """Texto curto do cronograma para o prompt do agente."""
    c = cronograma()
    linhas = [f"{ano}: {regra['observacao']}" for ano, regra in c["anos"].items()]
    return f"Cronograma da Reforma (versão {c['versao']}; fontes: {'; '.join(c['fontes'])})\n" + "\n".join(linhas)


def _r(v: float) -> float:
    return round(v, 2)


def _pct(v: float, casas: int = 2) -> str:
    return f"{v * 100:.{casas}f}%".replace(".", ",")


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def calcular(p: ParametrosCenario) -> dict:
    """Tributos sobre o consumo hoje × no ano pedido, com as premissas usadas."""
    c = cronograma()
    f = fase(p.ano)
    if p.regime == "simples":
        return {"suportado": False, "ano": p.ano, "fase": f,
                "motivo": "A calculadora não cobre o Simples Nacional (DAS, opção pelo regime regular de IBS/CBS). "
                          "Use a análise qualitativa ou a skill do Simples híbrido.",
                "limitacoes": LIMITACOES}

    fat, compras = p.faturamento_anual, p.faturamento_anual * p.compras_creditaveis_pct
    premissas = [f"Faturamento anual de {_brl(fat)}; compras que geram crédito: {_pct(p.compras_creditaveis_pct, 0)}."]

    def aliquota(valor: float | None, padrao: float, nome: str) -> float:
        if valor is None:
            premissas.append(f"{nome}: {_pct(padrao)} (padrão do JARVIS; informe a alíquota real).")
            return padrao
        premissas.append(f"{nome}: {_pct(valor)} (informada).")
        return valor

    pis_cofins = PIS_COFINS[p.regime]
    premissas.append(f"PIS/Cofins: {_pct(pis_cofins)} "
                     f"({'cumulativo' if p.regime == 'lucro_presumido' else 'não cumulativo'}).")
    icms = aliquota(p.aliquota_icms, ICMS_PADRAO, "ICMS") if p.atividade != "servicos" else 0.0
    iss = aliquota(p.aliquota_iss, ISS_PADRAO, "ISS") if p.atividade == "servicos" else 0.0
    ipi = aliquota(p.aliquota_ipi, IPI_PADRAO, "IPI") if p.atividade == "industria" else 0.0
    ref = p.aliquota_referencia
    if ref is None:
        ref = c["aliquota_referencia_estimada"]
        premissas.append(f"IBS + CBS: {_pct(ref)} (ESTIMATIVA; a alíquota de referência ainda não foi fixada).")
    else:
        premissas.append(f"IBS + CBS: {_pct(ref)} (informada).")
    part_cbs = c["participacao_cbs_estimada"]
    premissas.append(f"Divisão estimada: CBS {_pct(part_cbs, 0)} e IBS {_pct(1 - part_cbs, 0)} da referência.")

    credito_pc = compras if p.regime == "lucro_real" else 0.0   # presumido: PIS/Cofins cumulativo, sem crédito

    def tributos(fator_pc: float, fator_ipi: float, fator_icms_iss: float, cbs: float, ibs: float) -> dict:
        t = {
            "pis_cofins": (fat - credito_pc) * pis_cofins * fator_pc,
            "icms": (fat - compras) * icms * fator_icms_iss,
            "iss": fat * iss * fator_icms_iss,
            "ipi": (fat - compras) * ipi * fator_ipi,
            "cbs": (fat - compras) * cbs,
            "ibs": (fat - compras) * ibs,
        }
        t = {k: _r(max(v, 0.0)) for k, v in t.items()}
        t["total"] = _r(sum(t.values()))
        t["carga_pct"] = round(100 * t["total"] / fat, 2)
        return t

    atual = tributos(1.0, 1.0, 1.0, 0.0, 0.0)
    if f["fase"] == "teste":
        cbs = ibs = 0.0   # 0,9% + 0,1% compensáveis com PIS/Cofins: sem efeito líquido
    elif f["fase"] == "cbs":
        cbs, ibs = ref * part_cbs - f["ibs_fixo"], f["ibs_fixo"]
    else:
        cbs, ibs = ref * part_cbs, ref * (1 - part_cbs) * (1 - f["icms_iss"])
    pos = tributos(f["pis_cofins"], f["ipi"], f["icms_iss"], cbs, ibs)
    return {
        "suportado": True,
        "ano": p.ano,
        "fase": f,
        "aliquotas_no_ano": {"cbs": round(cbs, 4), "ibs": round(ibs, 4), "icms_iss_fator": f["icms_iss"]},
        "atual": atual,
        "pos_reforma": pos,
        "diferenca": {"valor": _r(pos["total"] - atual["total"]),
                      "pct": round(100 * (pos["total"] - atual["total"]) / atual["total"], 2) if atual["total"] else None},
        "premissas": premissas,
        "limitacoes": LIMITACOES,
        "cronograma_versao": c["versao"],
    }
