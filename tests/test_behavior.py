import sqlite3
from datetime import datetime, timedelta

from jarvis.api.server import build_conversation
from jarvis.core.costs import CostLedger
from jarvis.core.session import SessionStore
from jarvis.tools import manifesto, registry
from tests.conftest import FakeAnthropic


async def run(conv, msg, session="t"):
    return [ev async for ev in conv.turn(session, msg)]


def test_manifesto_lista_cada_ferramenta_e_as_que_pedem_confirmacao():
    reg = registry()
    m = manifesto(reg)
    for name in reg:
        assert f"- {name}:" in m
    assert "mover_itens" in m and "(pede confirmação)" in m


async def test_prompt_traz_manifesto_e_limites_e_compaction_em_60k(settings, fake_claude):
    conv = build_conversation(settings, claude_client=fake_claude)
    await run(conv, "me conta uma curiosidade")
    call = fake_claude.calls[0]
    assert "analisar_espaco" in call["system"]                 # manifesto gerado do registro real
    assert "NÃO consegue" in call["system"] and "sandbox" in call["system"]
    edit = call["context_management"]["edits"][0]
    assert edit == {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": 60_000}}
    assert "pano de fundo" in call["messages"][1]["content"]   # telemetria marcada como não-comentável


async def test_conversa_parada_e_arquivada_e_a_nova_comeca_vazia(settings):
    agora = [datetime(2026, 10, 26, 9, 0)]
    fake = FakeAnthropic()
    conv = build_conversation(settings, claude_client=fake)
    conv.store = SessionStore(settings.data_dir / "sessions", idle=timedelta(minutes=30), clock=lambda: agora[0])
    evs = await run(conv, "me conta uma curiosidade")
    assert evs[0].data["nova_conversa"] is False
    agora[0] += timedelta(minutes=10)
    await run(conv, "e outra?")
    assert len(fake.calls[1]["messages"]) > 2                  # mesma conversa: histórico continua
    agora[0] += timedelta(minutes=45)
    evs = await run(conv, "e mais uma?")
    assert evs[0].data["nova_conversa"] is True
    assert len(fake.calls[2]["messages"]) == 2                  # só o pedido novo + contexto atual
    arquivados = list((settings.data_dir / "sessions" / "arquivo").glob("t-*.json"))
    assert len(arquivados) == 1 and arquivados[0].stat().st_size > 100


def test_migracao_do_preco_do_sonnet_roda_uma_vez(tmp_path):
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE usage (at TEXT, session_id TEXT, model TEXT, route TEXT, input_tokens INTEGER,
                     output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL)""")
        c.execute("INSERT INTO usage VALUES ('2026-10-24T10:00','s','claude-sonnet-5-5','media',0,0,1000000,0,0.30)")
        c.execute("INSERT INTO usage VALUES ('2026-10-24T10:00','s','claude-haiku-5-5','simples',0,0,1000000,0,0.01)")
    CostLedger(db, 15)
    CostLedger(db, 15)                                          # segunda abertura não desconta de novo
    with sqlite3.connect(db) as c:
        custos = dict(c.execute("SELECT model, cost_usd FROM usage").fetchall())
        versao = c.execute("PRAGMA user_version").fetchone()[0]
    assert abs(custos["claude-sonnet-5-5"] - 0.20) < 1e-9 and custos["claude-haiku-5-5"] == 0.01 and versao == 1
