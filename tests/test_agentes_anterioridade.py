"""Calculadora de anterioridade e noventena (CF, art. 150, III, b e c): a data sai do código, nunca do modelo.

Datas esperadas contadas à mão: 90 dias pela LC 95/1998, art. 8º, §1º (inclui o dia da publicação e o último;
vale no dia seguinte), ou seja, publicação + 90 dias. Ex.: 01/10/2026 → 30/12/2026.
"""

import json
from datetime import date
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jarvis.agentes.contratos import ParametrosAnterioridade, PedidoTarefa, TributoAnterioridade
from jarvis.agentes.tributario import anterioridade
from jarvis.agentes.tributario.agente import AgenteTributario
from tests.conftest import text_turn, tool_turn
from tests.test_agentes_api import AUTH, _app
from tests.test_agentes_jarvis import _conv
from tests.test_agentes_tributario_claude import CONSULTA, montar  # noqa: F401 — fixture
from tests.test_tools import run_turn, tool_results


def _calc(tributo, publicacao, **kw):
    return anterioridade.calcular(ParametrosAnterioridade(tributo=tributo, data_publicacao=publicacao, **kw))


# ── regra geral e exceções do art. 150, §1º ─────────────────
@pytest.mark.parametrize(("tributo", "publicacao", "exigivel", "determinante"), [
    ("icms", date(2026, 10, 1), date(2027, 1, 1), ["anterioridade_anual"]),       # noventena em 30/12
    ("icms", date(2026, 12, 15), date(2027, 3, 15), ["noventena"]),               # anual em 01/01
    ("icms", date(2026, 10, 3), date(2027, 1, 1), ["anterioridade_anual", "noventena"]),   # empate
    ("imposto_seletivo", date(2026, 12, 15), date(2027, 3, 15), ["noventena"]),   # fora das exceções
    ("ipi", date(2026, 10, 1), date(2026, 12, 30), ["noventena"]),                # só noventena
    ("cbs", date(2026, 11, 2), date(2027, 1, 31), ["noventena"]),                 # art. 195, §6º
    ("pis_cofins", date(2028, 2, 1), date(2028, 5, 1), ["noventena"]),            # 2028 é bissexto
    ("ir", date(2026, 12, 31), date(2027, 1, 1), ["anterioridade_anual"]),        # só anual
    ("iptu_base_calculo", date(2026, 12, 31), date(2027, 1, 1), ["anterioridade_anual"]),
    ("aliquota_referencia_ibs_cbs", date(2026, 11, 20), date(2027, 1, 1), ["anterioridade_anual"]),
    ("iof", date(2026, 10, 1), date(2026, 10, 1), ["publicacao"]),                # nenhuma das duas
])
def test_datas_por_tributo(tributo, publicacao, exigivel, determinante):
    c = _calc(tributo, publicacao)
    assert c["exigivel_a_partir_de"] == exigivel.isoformat()
    assert c["determinante"] == determinante
    assert c["fundamentos"] and all(f.startswith(("CF", "ADCT", "LC 95")) for f in c["fundamentos"])


def test_detalhe_da_regra_geral():
    c = _calc("icms", date(2026, 10, 1))
    assert c["anterioridade_anual"] == {"aplica": True, "data": "2027-01-01", "fundamento": "CF, art. 150, III, b"}
    assert c["noventena"] == {"aplica": True, "data": "2026-12-30", "contada_desde": "2026-10-01",
                              "fundamento": "CF, art. 150, III, c"}
    assert c["pendente"] is None and c["texto_conferido_em"] == "02/11/2026"
    assert any("LC 95/1998" in p for p in c["premissas"])


def test_vigencia_da_lei():
    depois = _calc("icms", date(2026, 10, 1), vigencia_lei=date(2027, 4, 1))
    assert depois["exigivel_a_partir_de"] == "2027-04-01" and depois["determinante"] == ["vigencia_da_lei"]
    antes = _calc("icms", date(2026, 10, 1), vigencia_lei=date(2026, 10, 1))
    assert antes["exigivel_a_partir_de"] == "2027-01-01"
    assert any("antes do que a Constituição permite" in a for a in antes["alertas"])


# ── natureza da mudança ─────────────────────────────────────
def test_reducao_e_prazo_nao_tem_anterioridade():
    r = _calc("icms", date(2026, 10, 1), natureza="reducao_ou_extincao", vigencia_lei=date(2026, 10, 2))
    assert r["exigivel_a_partir_de"] == "2026-10-02" and r["determinante"] == ["vigencia_da_lei"]
    assert not r["anterioridade_anual"]["aplica"] and not r["noventena"]["aplica"]
    p = _calc("icms", date(2026, 10, 1), natureza="alteracao_de_prazo")
    assert p["exigivel_a_partir_de"] == "2026-10-01"
    assert any(j.startswith("Súmula Vinculante 50") for j in p["jurisprudencia"])


def test_revogacao_de_beneficio_e_majoracao_indireta():
    c = _calc("pis_cofins", date(2026, 10, 1), natureza="revogacao_de_beneficio")
    assert c["exigivel_a_partir_de"] == "2026-12-30" and not c["anterioridade_anual"]["aplica"]
    assert any(j.startswith("Tema 1383") for j in c["jurisprudencia"])
    assert any(j.startswith("Tema 1108") for j in c["jurisprudencia"])
    icms = _calc("icms", date(2026, 10, 1), natureza="revogacao_de_beneficio")
    assert icms["exigivel_a_partir_de"] == "2027-01-01"
    assert any("Súmula 615" in a for a in icms["alertas"])


# ── medida provisória ───────────────────────────────────────
def test_mp_de_imposto_so_vale_no_exercicio_seguinte_ao_da_conversao():
    tarde = _calc("ir", date(2026, 11, 10), veiculo="medida_provisoria", data_conversao=date(2027, 2, 15))
    assert tarde["exigivel_a_partir_de"] == "2028-01-01"
    assert "CF, art. 62, §2º" in tarde["fundamentos"]
    no_ano = _calc("ir", date(2026, 11, 10), veiculo="medida_provisoria", data_conversao=date(2026, 12, 20))
    assert no_ano["exigivel_a_partir_de"] == "2027-01-01"
    sem = _calc("ir", date(2026, 11, 10), veiculo="medida_provisoria")
    assert sem["exigivel_a_partir_de"] is None and "conversão" in sem["pendente"]
    iof = _calc("iof", date(2026, 11, 10), veiculo="medida_provisoria")   # exceção do art. 62, §2º
    assert iof["exigivel_a_partir_de"] == "2026-11-10" and iof["pendente"] is None


def test_mp_de_contribuicao_noventena_desde_a_mp_ou_desde_a_conversao():
    mp = _calc("pis_cofins", date(2026, 10, 1), veiculo="medida_provisoria", data_conversao=date(2027, 1, 20))
    assert mp["exigivel_a_partir_de"] == "2026-12-30" and mp["noventena"]["contada_desde"] == "2026-10-01"
    assert any(j.startswith("ARE 1.468.509 AgR") for j in mp["jurisprudencia"])
    so_na_lei = _calc("pis_cofins", date(2026, 10, 1), veiculo="medida_provisoria", data_conversao=date(2027, 1, 20),
                      majoracao_so_na_conversao=True)
    assert so_na_lei["exigivel_a_partir_de"] == "2027-04-20"
    assert any(j.startswith("Tema 278") for j in so_na_lei["jurisprudencia"])


def test_entradas_incoerentes():
    with pytest.raises(ValidationError, match="conversão"):
        ParametrosAnterioridade(tributo="ir", data_publicacao=date(2026, 11, 10), veiculo="medida_provisoria",
                                data_conversao=date(2026, 11, 1))
    with pytest.raises(ValidationError, match="medida provisória"):
        ParametrosAnterioridade(tributo="ir", data_publicacao=date(2026, 11, 10), data_conversao=date(2026, 12, 1))
    with pytest.raises(ValidationError, match="conversão"):
        ParametrosAnterioridade(tributo="cbs", data_publicacao=date(2026, 11, 10), veiculo="medida_provisoria",
                                majoracao_so_na_conversao=True)
    with pytest.raises(ValidationError):
        ParametrosAnterioridade(tributo="icms", data_publicacao=date(1988, 1, 1))     # antes da CF/88


def test_tabela_e_contrato_batem():
    assert set(anterioridade.TRIBUTOS) == set(get_args(TributoAnterioridade))
    for chave, r in anterioridade.TRIBUTOS.items():
        assert r.nome and r.fundamento.startswith(("CF", "ADCT")), chave


# ── agente e cérebro ────────────────────────────────────────
async def test_tarefa_do_agente_sem_claude(montar):  # noqa: F811
    orq, fake = montar(CONSULTA)
    params = ParametrosAnterioridade(tributo="icms", data_publicacao=date(2026, 12, 15))
    r = await orq.comandar("tributario", PedidoTarefa(tarefa="calcular_anterioridade", anterioridade=params),
                           "usuario_api")
    assert r.estado == "concluida" and r.custo_usd == 0 and r.modelo == "regras" and fake.calls == []
    assert r.saida["exigivel_a_partir_de"] == "2027-03-15"
    assert r.resumo == "ICMS: exigível a partir de 15/03/2027 (noventena; CF, art. 150, III, c)."
    assert r.resumo_voz == "A norma sobre ICMS só vale para cobrança a partir de 15 de março de 2027, pela noventena."
    falta = await orq.comandar("tributario", PedidoTarefa(tarefa="calcular_anterioridade"), "usuario_api")
    assert falta.estado == "recusada" and "data de publicação" in falta.erro


@pytest.mark.parametrize(("tributo", "publicacao", "kw", "resumo"), [
    ("icms", date(2026, 10, 1), {}, "ICMS: exigível a partir de 01/01/2027 (anterioridade anual; CF, art. 150, III, b)."),
    ("icms", date(2026, 10, 3), {}, ("ICMS: exigível a partir de 01/01/2027 (anterioridade anual e noventena; "
                                     "CF, art. 150, III, b; CF, art. 150, III, c).")),
    ("cbs", date(2026, 11, 2), {}, "CBS: exigível a partir de 31/01/2027 (noventena; CF, art. 195, §6º)."),
    ("ir", date(2026, 11, 10), {"veiculo": "medida_provisoria", "data_conversao": date(2027, 2, 15)},
     "Imposto de Renda: exigível a partir de 01/01/2028 (anterioridade anual; CF, art. 62, §2º; art. 150, III, b)."),
    ("iof", date(2026, 10, 1), {}, ("IOF: exigível a partir de 01/10/2026 (publicação, sem anterioridade; "
                                    "CF, art. 150, §1º (fora das duas)).")),
    ("icms", date(2026, 10, 1), {"vigencia_lei": date(2027, 4, 1)},
     "ICMS: exigível a partir de 01/04/2027 (vigência fixada na lei; CF, art. 150, III, b e c)."),
])
def test_resumo_cita_o_artigo_da_regra_que_decidiu(tributo, publicacao, kw, resumo):
    assert AgenteTributario._resumo_anterioridade(_calc(tributo, publicacao, **kw)) == resumo


def test_pela_api(settings):
    app, _ = _app(settings)
    corpo = {"tarefa": "calcular_anterioridade",
             "anterioridade": {"tributo": "cbs", "data_publicacao": "2026-11-02", "natureza": "revogacao_de_beneficio"}}
    r = TestClient(app).post("/agentes/tributario/tarefas", headers=AUTH, json=corpo)
    assert r.status_code == 200 and r.json()["saida"]["exigivel_a_partir_de"] == "2027-01-31"
    corpo["anterioridade"]["data_conversao"] = "2026-12-01"                      # lei não tem conversão
    assert TestClient(app).post("/agentes/tributario/tarefas", headers=AUTH, json=corpo).status_code == 422


async def test_pelo_cerebro(settings):
    conv, fake_j, fake_a, _ = _conv(settings, [
        tool_turn("comandar_agente", {"agente": "tributario", "tarefa": "calcular_anterioridade",
                                      "anterioridade": {"tributo": "ir", "data_publicacao": "2026-11-10",
                                                        "veiculo": "medida_provisoria"}}),
        text_turn("Pronto."),
    ])
    await run_turn(conv, "pede ao agente tributário a anterioridade da MP do IR")
    r = json.loads(tool_results(fake_j.calls[1])[0]["content"])
    assert r["estado"] == "concluida" and r["exigivel_a_partir_de"] is None and "conversão" in r["pendente"]
    assert r["fundamentos"] and fake_a.calls == []
