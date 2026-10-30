from datetime import datetime

from jarvis.core.audit import AuditChain
from jarvis.core.contracts import AgentResult, BudgetState, Route, UsageRecord
from jarvis.core.costs import CostLedger, price_usage
from jarvis.core.privacy import anonimizar_cpf, pseudonimizar_nome, sanitizar
from jarvis.core.router import Tiers, decide, strip_force


# ── privacidade ──────────────────────────────────────────────
def test_cpf_mascarado_com_e_sem_pontuacao():
    assert anonimizar_cpf("cpf 123.456.789-09 e 12345678909") == "cpf ***.***.***-** e ***.***.***-**"


def test_cnpj_mascarado_antes_do_cpf():
    out = sanitizar("Banco 60.746.948/0001-12")
    assert "60.746" not in out and "**.***.***/****-**" in out


def test_nome_pseudonimizado_deterministico():
    a = pseudonimizar_nome("Fulano de Tal", "s")
    assert a == pseudonimizar_nome("Fulano de Tal", "s") and a.startswith("PESSOA_")
    assert "Fulano" not in sanitizar("falei com fulano de tal", nomes=["Fulano de Tal"], salt="s")


# ── roteador ─────────────────────────────────────────────────
def test_trivial_vai_para_local():
    assert decide("Bom dia!", BudgetState.NORMAL).route is Route.LOCAL
    assert decide("quanto de RAM estou usando?", BudgetState.NORMAL).route is Route.LOCAL


def test_conversa_simples_vai_para_haiku():
    d = decide("me conta uma curiosidade sobre buracos negros", BudgetState.NORMAL)
    assert d.route is Route.SIMPLE and d.model == "claude-haiku-5-5" and d.effort == "low"


def test_tarefa_intermediaria_vai_para_sonnet():
    d = decide("resuma este parágrafo em duas linhas", BudgetState.NORMAL)
    assert d.route is Route.MEDIUM and d.model == "claude-sonnet-5-5" and d.effort == "high"


def test_tarefa_complexa_vai_para_opus_com_esforco_xhigh():
    d = decide("explique de forma detalhada como funciona o DNS", BudgetState.NORMAL)   # pontuação 3
    assert d.route is Route.COMPLEX and d.model == "claude-opus-5-5" and d.effort == "xhigh"


def test_topo_da_complexidade_vai_para_o_fable():
    pedido = "analise os prós e contras de migrar meu banco para Postgres e planeje a estratégia"
    d = decide(pedido, BudgetState.NORMAL)
    assert d.route is Route.FABLE and d.model == "claude-fable-5-1" and d.effort == "high"
    texto = "revise:\n```python\nx = 1\n```\n" + "a" * 500
    assert decide(texto, BudgetState.NORMAL).route is Route.FABLE
    # limiar configurável (JARVIS_FABLE_PONTOS): mais alto, o mesmo pedido fica no Opus
    assert decide(pedido, BudgetState.NORMAL, Tiers(fable_pontos=99)).route is Route.COMPLEX


def test_prefixo_fable_forca_a_camada_e_e_removido():
    d = decide("/fable oi", BudgetState.NORMAL)
    assert d.route is Route.FABLE and d.model == "claude-fable-5-1"
    assert decide("/fable revise isto", BudgetState.ECONOMY).route is Route.FABLE   # forçado não desce
    assert strip_force("/fable  qual o melhor caminho?") == "qual o melhor caminho?"


def test_prefixo_forca_camada_e_e_removido():
    assert decide("/opus oi", BudgetState.NORMAL).route is Route.COMPLEX
    assert decide("/haiku planeje a estratégia fiscal", BudgetState.NORMAL).route is Route.SIMPLE
    assert decide("pense bem: qual o melhor caminho?", BudgetState.NORMAL).route is Route.COMPLEX
    assert strip_force("/opus  qual o melhor caminho?") == "qual o melhor caminho?"


def test_modelos_configuraveis():
    d = decide("me conta uma piada", BudgetState.NORMAL, Tiers(simple="claude-sonnet-5-5"))
    assert d.model == "claude-sonnet-5-5"


def test_economia_desce_uma_camada_e_teto_forca_local():
    d = decide("analise e planeje a estratégia", BudgetState.ECONOMY)   # iria ao Fable: desce para o Opus
    assert d.route is Route.COMPLEX and d.effort == "low"
    d = decide("explique de forma detalhada o DNS", BudgetState.ECONOMY)   # iria ao Opus: desce para o Sonnet
    assert d.route is Route.MEDIUM and d.effort == "low"
    assert decide("/opus analise", BudgetState.ECONOMY).route is Route.COMPLEX  # forçado não desce
    assert decide("analise isso", BudgetState.CAP_REACHED).route is Route.LOCAL


# ── custos ───────────────────────────────────────────────────
def test_preco_por_camada_turno_tipico():
    # 800 entrada + 300 saída + 6000 cache read
    assert abs(price_usage("claude-opus-5-5", 800, 300, 6000, 0) - 0.0104) < 1e-6
    assert abs(price_usage("claude-sonnet-5-5", 800, 300, 6000, 0) - 0.0052) < 1e-6  # leitura de cache US$ 0,10
    assert abs(price_usage("claude-haiku-5-5", 800, 300, 6000, 0) - 0.00029) < 1e-6


def test_haiku_prompt_longo_usa_segunda_tabela():
    assert price_usage("claude-haiku-5-5", 120_000, 0, 0, 0) == 0.06


def test_estados_do_orcamento(tmp_path):
    ledger = CostLedger(tmp_path / "j.db", monthly_budget_usd=1.0)

    def rec(c):
        return UsageRecord(session_id="s", model="claude-opus-5-5", route=Route.SIMPLE, cost_usd=c)

    assert ledger.state() is BudgetState.NORMAL
    ledger.record(rec(0.85))
    assert ledger.state() is BudgetState.ECONOMY
    ledger.record(rec(0.20))
    assert ledger.state() is BudgetState.CAP_REACHED
    assert ledger.state(datetime(1999, 1, 1)) is BudgetState.NORMAL  # mês diferente zera


# ── audit ────────────────────────────────────────────────────
def test_cadeia_de_audit_detecta_adulteracao(tmp_path):
    path = tmp_path / "audit.jsonl"
    chain = AuditChain(path)
    r1 = chain.seal(AgentResult(session_id="s", route=Route.SIMPLE, model="m", text="a"))
    r2 = chain.seal(AgentResult(session_id="s", route=Route.SIMPLE, model="m", text="b"))
    assert r1.audit_hash != r2.audit_hash and chain.verify()
    assert AuditChain(path)._last == r2.audit_hash  # retoma a cadeia após reinício
    path.write_text(path.read_text(encoding="utf-8").replace('"text": "a"', '"text": "x"'), encoding="utf-8")
    assert not AuditChain(path).verify()


def test_preco_do_fable():
    # oficial: US$ 10 entrada, 50 saída, 0,25 leitura de cache, 12,50 escrita (5 min)
    # 800×10 + 300×50 + 6000×0,25 + 1000×12,50 = 37.000 / 1e6
    assert abs(price_usage("claude-fable-5-1", 800, 300, 6000, 1000) - 0.037) < 1e-6


def test_telemetria_por_modelo_projecao_e_fatia_do_fable(tmp_path):
    ledger = CostLedger(tmp_path / "j.db", monthly_budget_usd=15.0)
    dia10 = datetime(2026, 10, 10, 12, 0)
    for model, route, custo, n in (("claude-haiku-5-5", Route.SIMPLE, 0.002, 10), ("claude-opus-5-5", Route.COMPLEX, 0.07, 9),
                                   ("claude-fable-5-1", Route.FABLE, 0.17, 1)):
        for _ in range(n):
            ledger.record(UsageRecord(at=dia10, session_id="s", model=model, route=route, cost_usd=custo))
    t = ledger.telemetry(now=dia10)
    assert [m["modelo"] for m in t["por_modelo"]] == ["claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5"]
    opus = t["por_modelo"][0]
    assert opus["requisicoes"] == 9 and opus["custo_usd"] == 0.63 and opus["media_usd"] == 0.07
    assert opus["fatia_req_pct"] == 45.0 and opus["fatia_custo_pct"] == round(100 * 0.63 / 0.82, 1)
    assert t["fable"] == {"fatia_req_pct": 5.0, "meta_pct": 5.0, "custo_usd": 0.17}
    assert t["projecao_mes_usd"] == round(0.82 / 10 * 31, 2)                  # ritmo de 10 dias levado a 31
    assert CostLedger(tmp_path / "vazio.db", 15.0).telemetry(now=dia10)["por_modelo"] == []
