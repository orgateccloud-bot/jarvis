"""Espelho do turno de voz no HUD (B2): o turno pedido pela voz aparece na tela, o digitado não se repete, e nada disso
existe com a voz local desligada. Sem Claude e sem processo de voz."""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.core.contracts import StreamEvent
from jarvis.proactive.bus import EventBus, event_source
from jarvis.voz.cliente import Cliente
from tests.conftest import FakeAnthropic, text_turn, tool_turn

AUTH = {"Authorization": "Bearer token-de-teste"}


def _app(settings, voz_local=True, fake=None):
    s = settings.model_copy(update={"voz_local": voz_local})
    conv = build_conversation(s, claude_client=fake or FakeAnthropic())
    return TestClient(create_app(s, conversation=conv, proactive=False, iniciar_voz=False)), conv


def _assinar(client) -> asyncio.Queue:
    fila: asyncio.Queue = asyncio.Queue(500)
    client.app.state.espelho._subs.add(fila)
    return fila


def _drenar(fila) -> list[StreamEvent]:
    return [fila.get_nowait() for _ in range(fila.qsize())]


def _perguntar(client, mensagem, origem):
    corpo = {"message": mensagem, "session_id": "hud", "origem": origem}
    return client.post("/chat/stream", headers=AUTH, json=corpo)


def test_turno_de_voz_chega_ao_espelho_com_a_pergunta_mascarada(settings):
    client, _ = _app(settings)
    fila = _assinar(client)
    assert _perguntar(client, "meu cpf é 123.456.789-09, tudo certo?", "voz").status_code == 200
    eventos = _drenar(fila)
    assert eventos[0].type == "pergunta" and eventos[0].data == "meu cpf é ***.***.***-**, tudo certo?"
    tipos = [e.type for e in eventos]
    assert {"route", "text", "usage"} <= set(tipos) and tipos[-1] == "done"


def test_pergunta_digitada_nao_vai_ao_espelho(settings):
    client, _ = _app(settings)
    fila = _assinar(client)
    assert _perguntar(client, "me conta algo", "hud").status_code == 200
    assert _drenar(fila) == []


def test_ferramenta_passa_pelo_espelho(settings):
    client, _ = _app(settings, fake=FakeAnthropic(script=[tool_turn("custos", {}), text_turn("Pronto.")]))
    fila = _assinar(client)
    _perguntar(client, "me conta algo", "voz")
    assert "tool" in [e.type for e in _drenar(fila)]


def test_aviso_de_escalada_passa_pelo_espelho(settings):
    client, _ = _app(settings, fake=FakeAnthropic(stop_reason=["refusal", "end_turn"]))
    fila = _assinar(client)
    _perguntar(client, "me conta algo", "voz")
    assert "aviso" in [e.type for e in _drenar(fila)]


def test_decisao_de_aprovacao_avisa_o_hud(settings):
    client, conv = _app(settings)
    fila = _assinar(client)
    laco = asyncio.new_event_loop()
    conv.approvals._pending["a1"] = laco.create_future()
    assert client.post("/approvals/a1", headers=AUTH, json={"aprovar": True}).status_code == 200
    evento = _drenar(fila)[0]
    assert evento.type == "aprovacao" and evento.data == {"id": "a1", "aprovado": True}
    laco.close()


def test_sem_voz_local_nao_ha_espelho(settings):
    client, _ = _app(settings, voz_local=False)
    assert client.get("/turnos/eventos", headers=AUTH).status_code == 404
    assert not hasattr(client.app.state, "espelho")
    assert _perguntar(client, "me conta algo", "voz").status_code == 200   # a origem é ignorada


def test_espelho_pede_token(settings):
    client, _ = _app(settings)
    assert client.get("/turnos/eventos").status_code == 401


async def test_event_source_serve_os_eventos_do_turno():
    bus = EventBus(queue_size=10)
    fonte = event_source(bus, None)
    leitura = asyncio.create_task(anext(fonte))
    while not bus.subscribers:
        await asyncio.sleep(0)
    bus.publish(StreamEvent(type="text", data="oi"))
    assert json.loads((await leitura)[6:]) == {"type": "text", "data": "oi"}
    await fonte.aclose()


def test_cliente_da_voz_se_identifica_como_voz():
    corpos = []

    def responder(pedido):
        corpos.append(json.loads(pedido.content))
        return httpx.Response(200, text='data: {"type":"done"}\n\n')

    cliente = Cliente("http://127.0.0.1:8000", "t")
    cliente._http = httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(responder))
    assert list(cliente.perguntar("oi")) == [{"type": "done"}]
    assert corpos == [{"message": "oi", "session_id": "hud", "origem": "voz"}]
