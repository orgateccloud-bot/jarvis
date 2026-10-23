from datetime import datetime

from jarvis.core.audit import AuditChain
from jarvis.core.contracts import AgentResult, BudgetState, Route, UsageRecord
from jarvis.core.costs import CostLedger, price_usage
from jarvis.core.privacy import anonimizar_cpf, pseudonimizar_nome, sanitizar
from jarvis.core.router import decide


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


def test_conversa_vai_para_chat_low():
    d = decide("me conta uma curiosidade sobre buracos negros", BudgetState.NORMAL)
    assert d.route is Route.CHAT and d.effort == "low"


def test_tarefa_vai_para_high():
    d = decide("analise os prós e contras de migrar meu banco para Postgres", BudgetState.NORMAL)
    assert d.route is Route.TASK and d.effort == "high"


def test_economia_rebaixa_effort_e_teto_forca_local():
    assert decide("analise isso", BudgetState.ECONOMY).effort == "low"
    assert decide("analise isso", BudgetState.LOCAL_ONLY).route is Route.LOCAL


# ── custos ───────────────────────────────────────────────────
def test_preco_opus_turno_tipico():
    # 800 entrada + 300 saída + 6000 cache read ≈ US$ 0,0104
    assert abs(price_usage("claude-opus-5-5", 800, 300, 6000, 0) - 0.0104) < 1e-6


def test_estados_do_orcamento(tmp_path):
    ledger = CostLedger(tmp_path / "j.db", monthly_budget_usd=1.0)
    def rec(c):
        return UsageRecord(session_id="s", model="claude-opus-5-5", route=Route.CHAT, cost_usd=c)

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
    r1 = chain.seal(AgentResult(session_id="s", route=Route.CHAT, model="m", text="a"))
    r2 = chain.seal(AgentResult(session_id="s", route=Route.CHAT, model="m", text="b"))
    assert r1.audit_hash != r2.audit_hash and chain.verify()
    assert AuditChain(path)._last == r2.audit_hash  # retoma a cadeia após reinício
    path.write_text(path.read_text(encoding="utf-8").replace('"text": "a"', '"text": "x"'), encoding="utf-8")
    assert not AuditChain(path).verify()
