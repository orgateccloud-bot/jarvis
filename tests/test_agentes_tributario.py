"""Etapa 3, núcleo tributário determinístico: cópia do MiniSaaS, CSV brasileiro, análise com PII mascarada,
cronograma da Reforma e a calculadora atual × pós-Reforma. Nada aqui chama o Claude."""

import ast
import hashlib
import importlib.util
import json
import random
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.agentes.contratos import Lancamento, ParametrosCenario, Regra
from jarvis.agentes.tributario import fiscal_base, reforma
from jarvis.agentes.tributario.fiscal_base import (
    REGRAS_PADRAO,
    calcular_risco_autuacao,
    classificar,
    fatores_risco,
)
from jarvis.agentes.tributario.lancamentos import analisar, categoria, ler_csv, regras_com_extras

FIXTURE = Path(__file__).parent / "fixtures" / "agentes" / "extrato.csv"
MINI = Path(r"d:\01_Projetos_Ativos\Mini\saas\core\financeiro.py")
SIMBOLOS = ("REGRAS_PADRAO", "classificar", "calcular_risco_autuacao")


def _linha(d, valor, contraparte="X", categoria="Outros"):
    return {"Data": d, "Valor": valor, "Contraparte": contraparte, "Categoria": categoria}


# ── cópia do MiniSaaS ────────────────────────────────────────
def test_ultima_regra_vence():
    regras = [("PIX", "PIX"), ("PIX EMITIDO", "Pagamentos PIX"), ("TARIFA", "Tarifas")]
    assert classificar("pix emitido para fulano", regras) == "Pagamentos PIX"
    assert classificar("TARIFA PIX", regras) == "Tarifas"
    assert classificar("nada a ver", regras) == "Outros"
    assert ("POSTO", "Combustível") in REGRAS_PADRAO and len(REGRAS_PADRAO) == 16


def test_risco_valores_fixos():
    lancs = ler_csv(FIXTURE.read_bytes())
    regras = regras_com_extras()
    linhas = [_linha(x.data, x.valor, x.contraparte, categoria(x, regras)) for x in lancs]
    f = fatores_risco(linhas)
    # 6 de 10 sem contraparte → (60 - 20) × 0,4 = 16; 3 PIX iguais no mesmo dia → 30% × 1,5 = 45; "Outros" em 20%
    assert f["sem_contraparte"]["pontos"] == pytest.approx(16.0)
    assert f["fracionamento"]["pontos"] == pytest.approx(45.0)
    assert f["fracionamento"]["grupos"] == [{"data": date(2026, 1, 3), "valor": -1200.0, "qtd": 3}]
    assert f["nao_classificados"] == {"pct": pytest.approx(20.0), "pontos": 0.0}
    assert calcular_risco_autuacao(linhas) == pytest.approx(66.0)


def test_risco_bordas():
    d = date(2026, 1, 1)
    assert calcular_risco_autuacao([]) == 0.0
    # um espaço conta como contraparte preenchida, como no original
    assert fatores_risco([_linha(d, i, " ") for i in range(5)])["sem_contraparte"]["pct"] == 0.0
    # grupo de 2 não é fracionamento; o de 3 é
    assert fatores_risco([_linha(d, 10.0), _linha(d, 10.0)])["fracionamento"]["pct"] == 0.0
    assert fatores_risco([_linha(d, 10.0)] * 3)["fracionamento"]["pct"] == 100.0
    # 100% "Outros", valores distintos e contraparte preenchida: 5 + (100 - 30) × 0,2 = 19
    assert calcular_risco_autuacao([_linha(d, float(i)) for i in range(10)]) == pytest.approx(19.0)
    # tudo ruim estoura o teto de 99
    assert calcular_risco_autuacao([_linha(d, 1.0, "")] * 10) == 99.0


def _original():
    if not MINI.exists():
        pytest.skip("o MiniSaaS não está nesta máquina")
    pytest.importorskip("pandas")
    spec = importlib.util.spec_from_file_location("financeiro_mini", MINI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.mini
def test_paridade_pandas():
    """O porte em Python puro dá o mesmo índice que o original com pandas, em dados aleatórios."""
    mini = _original()
    rnd = random.Random(42)
    for rodada in range(40):
        rows = [SimpleNamespace(id=i, data=date(2026, 1, rnd.randint(1, 5)), tipo="DEBIT",
                                valor=rnd.choice([-100.0, -250.5, 300.0, 15.0]),
                                memo=rnd.choice(["PIX EMITIDO", "TARIFA", "COMPRA", "POSTO 1", ""]),
                                nome=rnd.choice(["", "FULANO"]), contraparte=rnd.choice(["", " ", "C1", "C2"]))
                for i in range(rnd.randint(1, 60))]
        rows.sort(key=lambda t: (t.data, t.id))
        esperado = mini.calcular_risco_autuacao(mini.montar_dataframe(rows, 0.0, mini.REGRAS_PADRAO))
        linhas = [_linha(t.data, t.valor, t.contraparte, classificar(f"{t.memo} {t.nome}", REGRAS_PADRAO))
                  for t in rows]
        assert calcular_risco_autuacao(linhas) == pytest.approx(esperado), f"rodada {rodada}"


def _sha_simbolos(fonte: str) -> str:
    fonte = fonte.replace("\r\n", "\n")
    partes = {}
    for no in ast.parse(fonte).body:
        nome = getattr(no, "name", None) or getattr(getattr(no, "target", None), "id", None)
        if nome in SIMBOLOS:
            partes[nome] = ast.get_source_segment(fonte, no)
    return hashlib.sha256("\n\n".join(partes[n] for n in SIMBOLOS).encode()).hexdigest()


@pytest.mark.mini
def test_deriva_ast():
    """Se REGRAS_PADRAO, classificar ou calcular_risco_autuacao mudarem no Mini, a cópia precisa ser revista."""
    if not MINI.exists():
        pytest.skip("o MiniSaaS não está nesta máquina")
    assert _sha_simbolos(MINI.read_text(encoding="utf-8")) == fiscal_base.ORIGEM_SHA256


# ── CSV e análise ────────────────────────────────────────────
def test_csv_ptbr():
    lancs = ler_csv(FIXTURE.read_bytes())                    # UTF-8 com BOM, ";" e vírgula decimal
    assert len(lancs) == 10 and lancs[0].valor == 15000.0 and lancs[5].valor == -890.45
    assert lancs[0].data == date(2026, 1, 2) and lancs[0].nome == "CLIENTE ALFA LTDA"
    cp1252 = "Data;Valor;Histórico;Favorecido\n31/12/2025;-1.234,56;CONTRIBUIÇÃO;Açougue\n".encode("cp1252")
    unico = ler_csv(cp1252)[0]
    assert (unico.valor, unico.memo, unico.contraparte) == (-1234.56, "CONTRIBUIÇÃO", "Açougue")
    virgula = ler_csv(b"date,value,description\n2026-02-01,1234.5,TARIFA\n")[0]
    assert (virgula.data, virgula.valor, virgula.memo) == (date(2026, 2, 1), 1234.5, "TARIFA")
    with pytest.raises(ValueError, match="colunas data e valor"):
        ler_csv(b"quando;quanto\n01/01/2026;1\n")
    with pytest.raises(ValueError, match="linha 3"):
        ler_csv(b"data;valor\n01/01/2026;1\n32/13/2026;2\n")


def test_regras_fiscais_palavra_inteira():
    regras = regras_com_extras([Regra(palavra="ALFA", categoria="Cliente Alfa")])
    def cat(memo, nome=""):
        return categoria(Lancamento(data=date(2026, 1, 1), valor=1, memo=memo, nome=nome), regras)
    assert cat("PAGTO DAS 12/2025") == "Simples Nacional (DAS)"
    assert cat("VENDAS DIVERSAS") == "Outros"                  # "DAS" dentro de VENDAS não conta
    assert cat("COMISSAO DE VENDA") == "Outros"                # nem "ISS" dentro de COMISSAO
    assert cat("DARF IRPJ") == "Tributos federais (DARF)"
    assert cat("CRD.TED", "ALFA LTDA") == "Cliente Alfa"       # regra do usuário vem por último e vence


def test_analise_mascara_pii():
    saida = analisar(ler_csv(FIXTURE.read_bytes()), salt="s")
    texto = json.dumps(saida, ensure_ascii=False)
    for pii in ("123.456.789-09", "987.654.321-00", "12.345.678/0001-90", "JOAO", "CARLOS", "MARIA", "ALFA"):
        assert pii not in texto, pii
    assert saida["risco"]["indice"] == 66.0 and "heurístico" in saida["risco"]["natureza"]
    assert saida["grupos_fracionamento"][0]["qtd"] == 3
    assert saida["periodo"] == {"inicio": "2026-01-02", "fim": "2026-01-25"}
    assert saida["maiores_contrapartes"][0]["contraparte"].startswith("PESSOA_")
    assert {"categoria": "Simples Nacional (DAS)", "qtd": 1, "total": -890.45} in saida["categorias"]


# ── Reforma ──────────────────────────────────────────────────
def test_cronograma_marcos():
    assert (reforma.fase(2026)["cbs_teste"], reforma.fase(2026)["ibs_teste"]) == (0.009, 0.001)
    f27 = reforma.fase(2027)
    assert (f27["pis_cofins"], f27["ipi"], f27["icms_iss"]) == (0.0, 0.0, 1.0)
    assert [reforma.fase(a)["icms_iss"] for a in range(2029, 2033)] == [0.9, 0.8, 0.7, 0.6]
    assert reforma.fase(2033)["icms_iss"] == 0.0
    assert reforma.fase(2040)["fase"] == "plena" and reforma.fase(2040)["ano"] == 2040
    assert "EC 132/2023" in reforma.resumo_cronograma()


def test_calculadora_premissas():
    p = ParametrosCenario(faturamento_anual=1_000_000, regime="lucro_presumido", atividade="servicos", ano=2033)
    r = reforma.calcular(p)
    assert r["atual"]["pis_cofins"] == 36_500 and r["atual"]["iss"] == 50_000 and r["atual"]["total"] == 86_500
    assert (r["pos_reforma"]["cbs"], r["pos_reforma"]["ibs"]) == (92_400, 187_600)
    assert r["pos_reforma"]["iss"] == 0 and r["diferenca"]["valor"] == 193_500
    assert any("ESTIMATIVA" in x for x in r["premissas"]) and "ISS: 5,00% (padrão do JARVIS" in " ".join(r["premissas"])
    assert "R$ 1.000.000,00" in r["premissas"][0]
    assert r["limitacoes"]

    real = reforma.calcular(ParametrosCenario(faturamento_anual=1_000_000, regime="lucro_real", atividade="comercio",
                                              ano=2029, compras_creditaveis_pct=0.6, aliquota_referencia=0.28))
    assert real["atual"]["pis_cofins"] == 37_000 and real["atual"]["icms"] == 76_000
    assert real["pos_reforma"]["icms"] == 68_400 and real["pos_reforma"]["cbs"] == pytest.approx(36_960)
    assert real["pos_reforma"]["ibs"] == pytest.approx(7_504, abs=0.01)
    assert any("(informada)" in x for x in real["premissas"])

    teste = reforma.calcular(p.model_copy(update={"ano": 2026}))
    assert teste["pos_reforma"]["total"] == teste["atual"]["total"]       # ano de teste sem efeito líquido
    simples = reforma.calcular(p.model_copy(update={"regime": "simples"}))
    assert simples["suportado"] is False and "Simples" in simples["motivo"]
