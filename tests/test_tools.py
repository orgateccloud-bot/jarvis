import json

import pytest
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.tools import ToolContext, ToolError, definitions_for, registry
from jarvis.tools.files import confinar
from tests.conftest import FakeAnthropic, text_turn, tool_turn

AUTH = {"Authorization": "Bearer token-de-teste"}


async def run_turn(conv, message, on_approval=None, session="t"):
    events = []
    async for ev in conv.turn(session, message):
        events.append(ev)
        if ev.type == "approval" and on_approval:
            on_approval(conv, ev.data)
    return events


def tool_results(call):
    """tool_result enviados ao modelo na chamada dada."""
    out = []
    for m in call["messages"]:
        if m["role"] == "user" and isinstance(m["content"], list):
            out += [b for b in m["content"] if b.get("type") == "tool_result"]
    return out


# ── unidades das ferramentas ─────────────────────────────────
def test_confinar_recusa_fora_da_raiz(settings, tmp_path):
    reg = registry()
    ctx = build_conversation(settings).tool_ctx
    (settings.tool_roots()[0] / "nota.txt").write_text("cpf 123.456.789-09", encoding="utf-8")
    assert confinar("nota.txt", ctx).name == "nota.txt"
    with pytest.raises(ToolError):
        confinar(str(tmp_path / "dados"), ctx)          # existe, mas fora das pastas permitidas
    with pytest.raises(ToolError):
        confinar("../dados", ctx)                        # escapar com ..
    out = reg["ler_arquivo"].run(reg["ler_arquivo"].parse({"caminho": "nota.txt"}), ctx)
    assert "123.456" not in out and "***.***.***-**" in out   # PII mascarada antes de ir ao modelo


def test_abrir_app_so_aceita_lista_permitida():
    tool = registry()["abrir_app"]
    assert tool.needs_approval
    with pytest.raises(ValueError):
        tool.parse({"nome": "cmd"})
    assert tool.parse({"nome": "bloco de notas"}).nome == "bloco de notas"


def test_encerrar_processo_protege_sistema(settings):
    tool = registry()["encerrar_processo"]
    ctx = build_conversation(settings).tool_ctx
    for nome in ("explorer", "lsass.exe", "python.exe"):
        with pytest.raises(ToolError):
            tool.run(tool.parse({"nome": nome}), ctx)


def test_lembrete_exige_um_horario_e_dispara_uma_vez(settings):
    tool = registry()["criar_lembrete"]
    with pytest.raises(ValueError):
        tool.parse({"texto": "água"})
    ctx: ToolContext = build_conversation(settings).tool_ctx
    tool.run(tool.parse({"texto": "beber água", "em_minutos": 1}), ctx)
    from datetime import datetime, timedelta

    later = datetime.now() + timedelta(minutes=2)
    assert [r.texto for r in ctx.reminders.take_due(later)] == ["beber água"]
    assert ctx.reminders.take_due(later) == []


def test_web_so_nos_modelos_capazes():
    reg = registry()
    names = lambda m: [d.get("name") for d in definitions_for(m, reg)]
    assert "web_search" not in names("claude-haiku-5-5")
    assert "web_search" in names("claude-sonnet-5-5")
    assert names("claude-haiku-5-5") == sorted(names("claude-haiku-5-5"))  # ordem fixa: cache estável
    # as nossas ferramentas fazem streaming da entrada; as definidas pela Anthropic (memória) não têm schema próprio
    assert all(d.get("eager_input_streaming") for d in definitions_for("claude-haiku-5-5", reg) if "type" not in d)


# ── loop agêntico ────────────────────────────────────────────
async def test_ferramenta_de_leitura_executa_sem_aprovacao(settings):
    fake = FakeAnthropic(script=[tool_turn("status_sistema", {}), text_turn("Tudo em ordem.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "como está o desempenho do computador hoje")
    assert not [e for e in evs if e.type == "approval"]
    assert any(e.type == "tool" and e.data.get("ok") for e in evs)
    res = tool_results(fake.calls[1])
    assert res and "cpu_percent" in res[0]["content"] and not res[0].get("is_error")
    assert "Tudo em ordem." in "".join(e.data for e in evs if e.type == "text")


async def test_acao_aprovada_executa(settings):
    fake = FakeAnthropic(script=[tool_turn("criar_lembrete", {"texto": "beber água", "em_minutos": 5}),
                                 text_turn("Lembrete criado.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "me lembra de beber água daqui a 5 minutos",
                         on_approval=lambda c, d: c.approvals.resolve(d["id"], True))
    appr = next(e for e in evs if e.type == "approval")
    assert appr.data["nome"] == "criar_lembrete" and "beber água" in appr.data["resumo"]
    assert [r.texto for r in conv.tool_ctx.reminders.pending()] == ["beber água"]
    assert not tool_results(fake.calls[1])[0].get("is_error")


async def test_acao_negada_nao_executa(settings):
    fake = FakeAnthropic(script=[tool_turn("criar_lembrete", {"texto": "regar plantas", "em_minutos": 5}),
                                 text_turn("Tudo bem, não criei.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "me lembra de algo em 5 minutos",
                         on_approval=lambda c, d: c.approvals.resolve(d["id"], False))
    assert conv.tool_ctx.reminders.pending() == []
    res = tool_results(fake.calls[1])[0]
    assert res["is_error"] and "NÃO autorizou" in res["content"]
    assert any(e.type == "tool" and e.data.get("negado") for e in evs)


async def test_aprovacao_expira_e_nega(settings):
    fake = FakeAnthropic(script=[tool_turn("criar_lembrete", {"texto": "regar plantas", "em_minutos": 5}), text_turn("Ok.")])
    conv = build_conversation(settings, claude_client=fake, approval_timeout_s=0.05)
    await run_turn(conv, "me lembra em 5 minutos")       # ninguém responde
    assert conv.tool_ctx.reminders.pending() == []
    assert tool_results(fake.calls[1])[0]["is_error"]


async def test_entrada_invalida_e_ferramenta_desconhecida_voltam_como_erro(settings):
    fake = FakeAnthropic(script=[
        {"content": [
            {"type": "tool_use", "id": "a", "name": "abrir_app", "input": {"nome": "cmd"}},
            {"type": "tool_use", "id": "b", "name": "formatar_disco", "input": {}},
        ], "stop_reason": "tool_use"},
        text_turn("Não consegui."),
    ])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "abra o prompt de comando e formate o disco agora")
    assert not [e for e in evs if e.type == "approval"]      # nada inválido chega a pedir aprovação
    res = {r["tool_use_id"]: r for r in tool_results(fake.calls[1])}
    assert res["a"]["is_error"] and "INVALID_INPUT" in res["a"]["content"]
    assert res["b"]["is_error"] and "desconhecida" in res["b"]["content"]
    assert len(fake.calls[1]["messages"][-1]["content"]) == 2  # resultados juntos numa única mensagem


async def test_max_tokens_com_tool_use_nao_executa_e_mantem_historico_valido(settings):
    fake = FakeAnthropic(script=[{"content": [{"type": "tool_use", "id": "t", "name": "criar_lembrete",
                                               "input": {"texto": "x"}}], "stop_reason": "max_tokens"}])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "me lembra de algo")
    assert not [e for e in evs if e.type == "approval"] and len(fake.calls) == 1
    hist = conv.store.history("t")
    assert hist[-1]["role"] == "user" and hist[-1]["content"][0]["tool_use_id"] == "t"


async def test_turno_interrompido_na_aprovacao_fecha_o_historico(settings):
    fake = FakeAnthropic(script=[tool_turn("criar_lembrete", {"texto": "regar plantas", "em_minutos": 5}), text_turn("ok")])
    conv = build_conversation(settings, claude_client=fake)
    gen = conv.turn("t", "me lembra em 5 minutos")
    async for ev in gen:
        if ev.type == "approval":
            break                                       # cliente "desconecta" esperando a aprovação
    await gen.aclose()
    hist = conv.store.history("t")
    tool_use_ids = {b["id"] for m in hist if m["role"] == "assistant" for b in m["content"]
                    if isinstance(b, dict) and b.get("type") == "tool_use"}
    answered = {b["tool_use_id"] for m in hist if m["role"] == "user" and isinstance(m["content"], list)
                for b in m["content"] if b.get("type") == "tool_result"}
    assert tool_use_ids == answered == {"toolu_1"}
    assert hist[-1]["role"] == "assistant"               # próximo turno começa com histórico válido


async def test_ultimo_passo_proibe_ferramentas(settings):
    fake = FakeAnthropic(script=[tool_turn("status_sistema", {})])   # o modelo insiste em ferramentas
    conv = build_conversation(settings, claude_client=fake)
    await run_turn(conv, "como está o desempenho do computador hoje")
    assert len(fake.calls) == 6 and fake.calls[-1]["tool_choice"] == {"type": "none"}


# ── endpoint de aprovação ────────────────────────────────────
def test_endpoint_de_aprovacao_exige_token_e_id_valido(settings, fake_claude):
    conv = build_conversation(settings, claude_client=fake_claude)
    client = TestClient(create_app(settings, conversation=conv))
    assert client.post("/approvals/x", json={"aprovar": True}).status_code == 401
    assert client.post("/approvals/x", headers=AUTH, json={"aprovar": True}).status_code == 404
    assert json.loads(client.get("/health").text)["status"] == "online"


async def test_interrupcao_nao_deixa_aprovacao_pendente(settings):
    fake = FakeAnthropic(script=[tool_turn("criar_lembrete", {"texto": "regar plantas", "em_minutos": 5})])
    conv = build_conversation(settings, claude_client=fake)
    gen = conv.turn("t", "me lembra em 5 minutos")
    async for ev in gen:
        if ev.type == "approval":
            break
    await gen.aclose()
    assert conv.approvals.pending == []
