import json

import anthropic
import httpx
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from tests.conftest import FakeAnthropic

AUTH = {"Authorization": "Bearer token-de-teste"}


def _client(settings, fake):
    conv = build_conversation(settings, claude_client=fake)
    return TestClient(create_app(settings, conversation=conv)), conv


def _events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def test_sem_token_recebe_401(settings, fake_claude):
    client, _ = _client(settings, fake_claude)
    assert client.get("/costs").status_code == 401
    assert client.post("/chat/stream", json={"message": "oi"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_chat_stream_claude_com_pensamento_custo_e_audit(settings, fake_claude):
    client, conv = _client(settings, fake_claude)
    resp = client.post("/chat/stream", headers=AUTH, json={"message": "me fala sobre o CPF 123.456.789-09"})
    evs = _events(resp)
    types = [e["type"] for e in evs]
    assert types[0] == "route" and evs[0]["data"]["rota"] == "simples"
    assert evs[0]["data"]["modelo"] == "claude-haiku-5-5"
    assert "thinking" in types and types[-1] == "done"
    assert "".join(e["data"] for e in evs if e["type"] == "text") == "Às ordens."
    usage = next(e for e in evs if e["type"] == "usage")["data"]
    assert usage["custo_usd"] > 0 and len(usage["audit_hash"]) == 64

    call = fake_claude.calls[0]
    sent_user = call["messages"][0]["content"]
    assert "123.456" not in sent_user  # PII mascarada antes da nuvem
    assert call["messages"][1]["role"] == "system"  # contexto volátil fora do prefixo cacheado
    assert call["output_config"] == {"effort": "low"}
    assert "fallbacks" not in call and call["betas"] == ["compact-2026-01-12"]  # Haiku: sem fallback no servidor
    assert "temperature" not in call

    assert client.get("/costs", headers=AUTH).json()["turnos_claude_mes"] == 1
    assert conv.audit.verify()


def test_historico_append_only_entre_turnos(settings, fake_claude):
    client, _ = _client(settings, fake_claude)
    client.post("/chat/stream", headers=AUTH, json={"message": "me conta uma curiosidade"})
    client.post("/chat/stream", headers=AUTH, json={"message": "e outra sobre o espaço?"})
    first, second = fake_claude.calls
    assert second["messages"][: len(first["messages"])] == first["messages"]  # prefixo intacto = cache válido
    assert second["messages"][2]["role"] == "assistant"
    assert second["messages"][2]["content"][0]["type"] == "thinking"  # thinking devolvido sem alteração


def test_trivial_nao_chama_claude(settings, fake_claude):
    client, _ = _client(settings, fake_claude)
    evs = _events(client.post("/chat/stream", headers=AUTH, json={"message": "que horas são?"}))
    assert evs[0]["data"]["rota"] == "local" and fake_claude.calls == []
    assert "São" in "".join(e["data"] for e in evs if e["type"] == "text")


def test_claude_fora_do_ar_cai_para_local(settings):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake = FakeAnthropic(raise_exc=anthropic.APIConnectionError(request=req))
    client, _ = _client(settings, fake)
    evs = _events(client.post("/chat/stream", headers=AUTH, json={"message": "me conta uma curiosidade"}))
    types = [e["type"] for e in evs]
    assert "error" in types and types[-1] == "done"


def test_sem_credencial_cai_para_local(settings):
    fake = FakeAnthropic(raise_exc=TypeError('"Could not resolve authentication method. Expected one of api_key"'))
    client, _ = _client(settings, fake)
    evs = _events(client.post("/chat/stream", headers=AUTH, json={"message": "me conta uma curiosidade"}))
    err = next(e for e in evs if e["type"] == "error")["data"]
    assert "ANTHROPIC_API_KEY" in err and evs[-1]["type"] == "done"


def test_teto_atingido_usa_somente_local(settings, fake_claude):
    settings.monthly_budget_usd = 0.0002
    client, _ = _client(settings, fake_claude)
    client.post("/chat/stream", headers=AUTH, json={"message": "me conta uma curiosidade"})  # Haiku gasta ~US$ 0,0003
    evs = _events(client.post("/chat/stream", headers=AUTH, json={"message": "me conta outra"}))
    assert evs[0]["data"]["orcamento"] == "local" and len(fake_claude.calls) == 1


def test_opus_e_sonnet_usam_fallback_do_servidor(settings, fake_claude):
    client, _ = _client(settings, fake_claude)
    client.post("/chat/stream", headers=AUTH, json={"message": "resuma este parágrafo"})
    client.post("/chat/stream", headers=AUTH, json={"message": "/opus planeje a estratégia"})
    sonnet, opus = fake_claude.calls
    assert sonnet["model"] == "claude-sonnet-5-5" and sonnet["output_config"] == {"effort": "medium"}
    assert opus["model"] == "claude-opus-5-5" and opus["output_config"] == {"effort": "high"}
    assert opus["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in opus["betas"]
    assert opus["messages"][-2]["content"] == "planeje a estratégia"  # prefixo /opus removido


def test_recusa_do_haiku_escala_para_sonnet(settings):
    fake = FakeAnthropic(stop_reason=["refusal", "end_turn"])
    client, conv = _client(settings, fake)
    evs = _events(client.post("/chat/stream", headers=AUTH, json={"message": "me conta uma curiosidade"}))
    assert [c["model"] for c in fake.calls] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert any(e["type"] == "error" and "escalando" in e["data"] for e in evs)
    assert next(e for e in evs if e["type"] == "usage")["data"]["modelo"] == "claude-sonnet-5-5"
    assert conv.ledger.summary()["turnos_claude_mes"] == 2  # a tentativa recusada também é contabilizada
