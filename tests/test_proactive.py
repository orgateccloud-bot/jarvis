import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.core.contracts import Route, UsageRecord
from jarvis.proactive.bus import EventBus, ProactiveEvent, event_source
from jarvis.proactive.monitors import COOLDOWN, Monitor

CALMO = {"cpu": 10, "ram": 50, "ram_used_gb": 8, "ram_total_gb": 16, "disk": 60, "disk_free_gb": 200}


class Relogio:
    def __init__(self):
        self.t = datetime(2026, 10, 24, 9, 0)

    def __call__(self):
        return self.t

    def avanca(self, **kw):
        self.t += timedelta(**kw)


def make(settings, leituras):
    conv = build_conversation(settings)
    clock = Relogio()
    state = {"s": dict(CALMO)}

    def sampler():
        return state["s"]

    mon = Monitor(conv.ledger, conv.tool_ctx.reminders, "Senhor", sampler=sampler, clock=clock)
    state["s"].update(leituras)
    return mon, clock, state, conv


def kinds(evs):
    return [e.kind for e in evs]


def test_ram_exige_duas_leituras_e_respeita_intervalo(settings):
    mon, clock, _, _ = make(settings, {"ram": 93})
    assert kinds(mon.check()) == []                 # 1ª leitura alta: pode ser um pico
    clock.avanca(seconds=15)
    evs = mon.check()
    assert kinds(evs) == ["alerta_ram"] and "93%" in evs[0].texto
    clock.avanca(minutes=5)
    assert kinds(mon.check()) == []                 # intervalo mínimo entre avisos iguais
    clock.avanca(seconds=COOLDOWN.total_seconds())
    assert kinds(mon.check()) == ["alerta_ram"]


def test_disco_cheio_avisa_na_hora_e_e_critico(settings):
    mon, _, _, _ = make(settings, {"disk": 99, "disk_free_gb": 1.2})
    evs = mon.check()
    assert kinds(evs) == ["alerta_disco"] and evs[0].nivel == "critico" and "1,2 GB" in evs[0].texto


def test_cpu_so_avisa_se_sustentada(settings):
    mon, clock, state, _ = make(settings, {"cpu": 95})
    assert mon.check() == []
    clock.avanca(seconds=30)
    assert mon.check() == []
    clock.avanca(seconds=31)
    assert kinds(mon.check()) == ["alerta_cpu"]
    state["s"]["cpu"] = 20
    clock.avanca(seconds=15)
    assert mon.check() == []                        # voltou ao normal: zera a contagem


def test_mudanca_de_orcamento_avisa_uma_vez(settings):
    settings.monthly_budget_usd = 1.0
    mon, _, _, conv = make(settings, {})
    conv.ledger.record(UsageRecord(session_id="s", model="m", route=Route.SIMPLE, cost_usd=0.85))
    assert kinds(mon.check()) == ["orcamento"]
    assert mon.check() == []


def test_lembrete_vencido_vira_evento_falado(settings):
    mon, clock, _, conv = make(settings, {})
    conv.tool_ctx.reminders.add("beber água", clock() + timedelta(minutes=1))
    assert mon.check() == []
    clock.avanca(minutes=2)
    evs = mon.check()
    assert kinds(evs) == ["lembrete"] and evs[0].falar and "beber água" in evs[0].texto
    assert mon.check() == []                        # não repete


def test_saudacao_por_horario_e_alertas(settings):
    mon, clock, state, _ = make(settings, {"disk": 100})
    g = mon.greeting()
    assert g.kind == "saudacao" and g.texto.startswith("Bom dia, Senhor") and "disco C:" in g.texto
    clock.t = clock.t.replace(hour=20)
    state["s"]["disk"] = 50
    assert mon.greeting().texto.startswith("Boa noite") and "estáveis" in mon.greeting().texto


async def test_event_source_entrega_saudacao_e_eventos():
    bus = EventBus()
    src = event_source(bus, ProactiveEvent(kind="saudacao", titulo="Oi", texto="Olá"), keepalive_s=0.05)
    first = await anext(src)
    assert '"saudacao"' in first
    await asyncio.sleep(0)
    task = asyncio.ensure_future(anext(src))
    await asyncio.sleep(0.01)
    bus.publish(ProactiveEvent(kind="lembrete", titulo="L", texto="beber água"))
    line = await asyncio.wait_for(task, 1)
    assert "beber água" in line
    assert await asyncio.wait_for(anext(src), 1) == ": ping\n\n"   # keepalive quando ocioso
    await src.aclose()
    assert bus.subscribers == 0


def test_events_exige_token(settings, fake_claude):
    conv = build_conversation(settings, claude_client=fake_claude)
    client = TestClient(create_app(settings, conversation=conv, proactive=False))
    assert client.get("/events").status_code == 401
