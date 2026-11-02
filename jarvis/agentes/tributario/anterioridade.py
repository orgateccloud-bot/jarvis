"""Anterioridade anual e noventena: a partir de quando a lei que cria ou aumenta um tributo pode ser cobrada.

As regras e as exceções saem do texto compilado da Constituição conferido no Planalto em 02/11/2026: art. 150, III, a,
b e c, e §1º (redação da EC 42/2003, que a EC 132/2023 não mudou), art. 195, §6º, art. 62, §§2º e 3º, art. 155, §4º,
IV, c, art. 177, §4º, I, b, e ADCT, art. 130, §1º. A contagem dos 90 dias segue a LC 95/1998, art. 8º, §1º, por
analogia. A jurisprudência citada está na biblioteca jurídica da base local. Como na calculadora da Reforma, a data
sai daqui e o Claude só comenta.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from ..contratos import ParametrosAnterioridade

TEXTO_CONFERIDO = "02/11/2026"
NOVENTA_DIAS = timedelta(days=90)   # LC 95, art. 8º, §1º: conta o dia da publicação e o último; vale no seguinte


class Regime(NamedTuple):
    nome: str
    anual: bool                 # art. 150, III, b
    noventena: bool             # art. 150, III, c, ou art. 195, §6º
    fundamento: str
    imposto: bool = False       # art. 62, §2º: MP que cria ou aumenta imposto
    seguridade: bool = False    # a noventena vem do art. 195, §6º


_GERAL = "CF, art. 150, III, b e c"
_SO_NOVENTENA = "CF, art. 150, §1º (fora da anterioridade anual)"
_SO_ANUAL = "CF, art. 150, §1º (fora da noventena)"
_NENHUMA = "CF, art. 150, §1º (fora das duas)"
_SEGURIDADE = "CF, art. 195, §6º (só noventena)"

TRIBUTOS: dict[str, Regime] = {
    # regra geral: as duas
    "icms": Regime("ICMS", True, True, _GERAL, imposto=True),
    "iss": Regime("ISS", True, True, _GERAL, imposto=True),
    "ibs": Regime("IBS", True, True, f"{_GERAL}; art. 156-A", imposto=True),
    "imposto_seletivo": Regime("Imposto Seletivo", True, True, f"{_GERAL}; art. 153, VIII (fora das exceções do §1º)",
                               imposto=True),
    "itcmd": Regime("ITCMD", True, True, _GERAL, imposto=True),
    "itbi": Regime("ITBI", True, True, _GERAL, imposto=True),
    "itr": Regime("ITR", True, True, _GERAL, imposto=True),
    "ipva": Regime("IPVA", True, True, _GERAL, imposto=True),
    "iptu": Regime("IPTU", True, True, _GERAL, imposto=True),
    "taxa": Regime("Taxa", True, True, _GERAL),
    "contribuicao_melhoria": Regime("Contribuição de melhoria", True, True, _GERAL),
    "cide": Regime("CIDE", True, True, f"{_GERAL}; art. 149"),
    "cosip": Regime("Contribuição de iluminação pública", True, True, f"{_GERAL}; art. 149-A"),
    "outra_contribuicao": Regime("Contribuição do art. 149", True, True, f"{_GERAL}; art. 149"),
    "emprestimo_compulsorio_investimento": Regime("Empréstimo compulsório para investimento", True, True,
                                                  "CF, art. 148, II; art. 150, III, b e c"),
    # só noventena
    "ipi": Regime("IPI", False, True, _SO_NOVENTENA, imposto=True),
    "cbs": Regime("CBS", False, True, "CF, art. 195, V, e §6º (só noventena)", seguridade=True),
    "pis_cofins": Regime("PIS/Cofins", False, True, _SEGURIDADE, seguridade=True),
    "csll": Regime("CSLL", False, True, _SEGURIDADE, seguridade=True),
    "contribuicao_previdenciaria": Regime("Contribuição previdenciária", False, True, _SEGURIDADE, seguridade=True),
    "icms_combustivel_restabelecimento": Regime("ICMS monofásico de combustível (restabelecer alíquota reduzida)",
                                                False, True, "CF, art. 155, §4º, IV, c", imposto=True),
    "cide_combustivel_restabelecimento": Regime("CIDE-Combustíveis (restabelecer alíquota reduzida)", False, True,
                                                "CF, art. 177, §4º, I, b"),
    # só anual
    "ir": Regime("Imposto de Renda", True, False, _SO_ANUAL, imposto=True),
    "ipva_base_calculo": Regime("IPVA (fixação da base de cálculo)", True, False, _SO_ANUAL, imposto=True),
    "iptu_base_calculo": Regime("IPTU (fixação da base de cálculo)", True, False, _SO_ANUAL, imposto=True),
    "aliquota_referencia_ibs_cbs": Regime("Alíquotas de referência do IBS e da CBS", True, False,
                                          "ADCT, art. 130, §1º (fixadas no ano anterior, sem noventena)"),
    # nenhuma das duas
    "ii": Regime("Imposto de Importação", False, False, _NENHUMA, imposto=True),
    "ie": Regime("Imposto de Exportação", False, False, _NENHUMA, imposto=True),
    "iof": Regime("IOF", False, False, _NENHUMA, imposto=True),
    "emprestimo_compulsorio_calamidade_guerra": Regime("Empréstimo compulsório (calamidade ou guerra)", False, False,
                                                       "CF, art. 148, I; art. 150, §1º"),
    "imposto_extraordinario_guerra": Regime("Imposto extraordinário de guerra", False, False,
                                            "CF, art. 154, II; art. 150, §1º", imposto=True),
}

# Jurisprudência da biblioteca jurídica da base local (D:\JARVIS-Conhecimento\juridico), conferida em 02/11/2026
SV_50 = "Súmula Vinculante 50: mudar o prazo de recolhimento não se sujeita à anterioridade (base local, sv-stf)."
ARE_1468509 = ("ARE 1.468.509 AgR (STF, 2ª T, 2024), na jurisprudência da SV 50: a anterioridade não incide quando a "
               "mudança não aumenta a carga; sem aumento novo na lei de conversão, os 90 dias correm da MP.")
TEMA_278 = ("Tema 278 (STF, repercussão geral): se o aumento só veio na lei de conversão da MP, os 90 dias contam da "
            "publicação dessa lei (base local, rg-stf).")
TEMA_1383 = ("Tema 1383 (STF, repercussão geral, 2025): a anterioridade geral e a nonagesimal valem para reduzir ou "
             "suprimir benefício que aumente o tributo de forma indireta, com as exceções de cada tributo (base local, "
             "rg-stf).")
TEMA_1108 = ("Tema 1108 (STF, repercussão geral, 2025): reduzir ou revogar o REINTEGRA é majoração indireta do "
             "PIS/Cofins e segue só a noventena do art. 195, §6º (base local, rg-stf).")
SUMULA_615 = ("A Súmula 615 do STF (a anualidade não se aplica à revogação de isenção do ICM) consta como vigente na "
              "base, mas é da Constituição anterior; o Tema 1383 (2025) manda aplicar a anterioridade.")

NATUREZA = {"instituicao_ou_majoracao": "cria ou aumenta o tributo",
            "revogacao_de_beneficio": "reduz ou revoga benefício (majoração indireta)",
            "reducao_ou_extincao": "reduz ou extingue o tributo", "alteracao_de_prazo": "muda o prazo de recolhimento"}

LIMITACOES = [
    "Não confere se o veículo pode criar ou aumentar o tributo (lei complementar, MP, decreto) nem a competência do ente.",
    "Não decide se a mudança é majoração indireta: a natureza informada é premissa.",
    (f"Regras conferidas no texto compilado da Constituição em {TEXTO_CONFERIDO}; emenda posterior pode mudar as "
     "exceções."),
]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def calcular(p: ParametrosAnterioridade) -> dict:
    """Data a partir da qual o tributo pode ser cobrado, com a regra que decidiu, os fundamentos e as premissas."""
    r = TRIBUTOS[p.tributo]
    mp = p.veiculo == "medida_provisoria"
    aumenta = p.natureza in ("instituicao_ou_majoracao", "revogacao_de_beneficio")
    fundamentos, jurisprudencia, alertas = [r.fundamento], [], []
    premissas = [f"A norma {NATUREZA[p.natureza]} (informado).",
                 "Fatos geradores anteriores à data seguem a lei antiga (CF, art. 150, III, a)."]
    pendente = None

    if not aumenta:
        motivo = "não se aplica: a mudança não aumenta a carga"
        fundamentos = [f"CF, art. 150, III, b e c (não se aplicam quando a norma {NATUREZA[p.natureza]})"]
        jurisprudencia.append(SV_50 if p.natureza == "alteracao_de_prazo" else ARE_1468509)
        anual = {"aplica": False, "data": None, "fundamento": motivo}
        noventena = {"aplica": False, "data": None, "contada_desde": None, "fundamento": motivo}
    else:
        if p.natureza == "revogacao_de_beneficio":
            jurisprudencia.append(TEMA_1383)
            if p.tributo == "pis_cofins":
                jurisprudencia.append(TEMA_1108)
            if p.tributo == "icms":
                alertas.append(SUMULA_615)
        anual = {"aplica": r.anual, "data": None, "fundamento": "CF, art. 150, III, b" if r.anual else r.fundamento}
        if r.anual:
            premissas.append("Exercício financeiro = ano civil (Lei 4.320/1964, art. 34).")
            if mp and r.imposto:
                anual["fundamento"] = "CF, art. 62, §2º; art. 150, III, b"
                fundamentos.append("CF, art. 62, §2º")
                if p.data_conversao is None:
                    pendente = ("MP que cria ou aumenta imposto só produz efeitos no exercício seguinte ao da conversão "
                                "em lei (CF, art. 62, §2º): informe a data da conversão.")
                else:
                    anual["data"] = _iso(date(p.data_conversao.year + 1, 1, 1))
            else:
                anual["data"] = _iso(date(p.data_publicacao.year + 1, 1, 1))
        desde = p.data_conversao if p.majoracao_so_na_conversao else p.data_publicacao
        noventena = {"aplica": r.noventena, "data": None, "contada_desde": None,
                     "fundamento": r.fundamento if not r.noventena
                     else "CF, art. 195, §6º" if r.seguridade else "CF, art. 150, III, c"}
        if r.noventena:
            noventena |= {"data": _iso(desde + NOVENTA_DIAS), "contada_desde": _iso(desde)}
            fundamentos.append("LC 95/1998, art. 8º, §1º (contagem dos 90 dias, por analogia)")
            premissas.append("90 dias contados pela LC 95/1998, art. 8º, §1º: inclui o dia da publicação e o último e "
                             "vale no dia seguinte; pelo art. 132 do Código Civil seria um dia depois.")
            if mp:
                jurisprudencia.append(TEMA_278 if p.majoracao_so_na_conversao else ARE_1468509)

    if mp and p.data_conversao is None:
        alertas.append("A MP perde a eficácia desde a edição se não for convertida em lei em 60 dias, prorrogáveis por "
                       "mais 60 (CF, art. 62, §3º).")

    exigivel, determinante = None, []
    if pendente is None:
        limites = {k: date.fromisoformat(v["data"]) for k, v in
                   (("anterioridade_anual", anual), ("noventena", noventena)) if v["data"]}
        if limites:
            exigivel = max(limites.values())
            determinante = [k for k, v in limites.items() if v == exigivel]
            if p.vigencia_lei and p.vigencia_lei < exigivel:
                alertas.append(f"A lei fixou vigência em {p.vigencia_lei:%d/%m/%Y}, antes do que a Constituição permite "
                               f"para cobrar: vale {exigivel:%d/%m/%Y}.")
        else:
            exigivel, determinante = p.data_publicacao, ["publicacao"]
        if p.vigencia_lei and p.vigencia_lei > exigivel:
            exigivel, determinante = p.vigencia_lei, ["vigencia_da_lei"]

    return {
        "tributo": p.tributo,
        "tributo_nome": r.nome,
        "natureza": p.natureza,
        "veiculo": p.veiculo,
        "data_publicacao": _iso(p.data_publicacao),
        "data_conversao": _iso(p.data_conversao),
        "vigencia_lei": _iso(p.vigencia_lei),
        "exigivel_a_partir_de": _iso(exigivel),
        "determinante": determinante,
        "pendente": pendente,
        "anterioridade_anual": anual,
        "noventena": noventena,
        "fundamentos": fundamentos,
        "jurisprudencia": jurisprudencia,
        "premissas": premissas,
        "alertas": alertas,
        "limitacoes": LIMITACOES,
        "texto_conferido_em": TEXTO_CONFERIDO,
    }
