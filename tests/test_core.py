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
    assert d.route is Route.MEDIUM and d.model == "claude-sonnet-5-5" and d.effort == "medium"


def test_tarefa_complexa_vai_para_opus():
    pedido = "analise os prós e contras de migrar meu banco para Postgres e planeje a estratégia"
    d = decide(pedido, BudgetState.NORMAL)
    assert d.route is Route.COMPLEX and d.model == "claude-opus-5-5" and d.effort == "high"


def test_texto_longo_com_codigo_vai_para_opus():
    texto = "revise:\n```python\nx = 1\n```\n" + "a" * 500
    assert decide(texto, BudgetState.NORMAL).route is Route.COMPLEX


def test_prefixo_forca_camada_e_e_removido():
    assert decide("/opus oi", BudgetState.NORMAL).route is Route.COMPLEX
    assert decide("/haiku planeje a estratégia fiscal", BudgetState.NORMAL).route is Route.SIMPLE
    assert decide("pense bem: qual o melhor caminho?", BudgetState.NORMAL).route is Route.COMPLEX
    assert strip_force("/opus  qual o melhor caminho?") == "qual o melhor caminho?"


def test_modelos_configuraveis():
    d = decide("me conta uma piada", BudgetState.NORMAL, Tiers(simple="claude-sonnet-5-5"))
    assert d.model == "claude-sonnet-5-5"


def test_economia_desce_uma_camada_e_teto_forca_local():
    d = decide("analise e planeje a estratégia", BudgetState.ECONOMY)
    assert d.route is Route.MEDIUM and d.effort == "low"
    assert decide("/opus analise", BudgetState.ECONOMY).route is Route.COMPLEX  # forçado não desce
    assert decide("analise isso", BudgetState.LOCAL_ONLY).route is Route.LOCAL


# ── custos ───────────────────────────────────────────────────
def test_preco_por_camada_turno_tipico():
    # 800 entrada + 300 saída + 6000 cache read
    assert abs(price_usage("claude-opus-5-5", 800, 300, 6000, 0) - 0.0104) < 1e-6
    assert abs(price_usage("claude-sonnet-5-5", 800, 300, 6000, 0) - 0.0058) < 1e-6
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
    assert ledger.state() is BudgetState.LOCAL_ONLY
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
