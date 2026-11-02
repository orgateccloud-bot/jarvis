"""Perfil só Trilhum (padrão do JARVIS-TRILHUM): só o Trilhum e o Direito, com a base jurídica do
JARVIS-IurisNotitia, e nada que leia ou mexa no Windows."""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.conhecimento.restrita import BaseRestrita
from jarvis.core.llm import RuleResponder
from jarvis.proactive.monitors import Monitor
from jarvis.proactive.reminders import ReminderStore
from tests.conftest import FakeAnthropic

PERMITIDAS = {"trilhum_agenda", "trilhum_plano", "trilhum_planos", "trilhum_progresso", "buscar_conhecimento",
              "memory", "criar_lembrete", "lembretes_listar", "cancelar_lembrete", "custos"}
DO_WINDOWS = {"ler_arquivo", "buscar_arquivos", "listar_pasta", "mover_itens", "enviar_para_lixeira", "abrir_app",
              "apps_abertos", "status_sistema", "processos_pesados", "encerrar_processo", "comando_seguro",
              "analisar_espaco", "abrir_configuracao", "hardware_info"}


def _trilhum(settings):
    return settings.model_copy(update={"so_trilhum": True})


def test_so_ferramentas_do_trilhum_e_juridicas(settings):
    conv = build_conversation(_trilhum(settings), claude_client=FakeAnthropic())
    assert set(conv.tools) == PERMITIDAS and not set(conv.tools) & DO_WINDOWS
    assert conv.web is False
    assert "só jurídico e do Trilhum" in conv.claude.system and "JARVIS-IurisNotitia" in conv.claude.system
    assert "web_search" not in conv.claude.system and "$OUTPUT_DIR" not in conv.claude.system
    assert "RAM" not in conv.contexto() and "CPU" not in conv.contexto()
    completo = build_conversation(settings, claude_client=FakeAnthropic())
    assert DO_WINDOWS <= set(completo.tools) and completo.web is True


async def test_turno_sem_web_sem_sandbox_e_sem_telemetria(settings):
    fake = FakeAnthropic()
    conv = build_conversation(_trilhum(settings), claude_client=fake)
    [ev async for ev in conv.turn("s", "/sonnet explique a prescrição intercorrente na execução fiscal")]
    chamada = fake.calls[0]
    assert chamada["model"] == "claude-sonnet-5-5"   # o Sonnet teria web e sandbox no perfil completo
    nomes = {t["name"] for t in chamada["tools"]}
    assert "web_search" not in nomes and "web_fetch" not in nomes and not nomes & DO_WINDOWS
    enviado = json.dumps(chamada["messages"], ensure_ascii=False)
    assert "RAM" not in enviado and "GB livres" not in enviado


def test_regras_nao_leem_o_windows():
    r = RuleResponder("Senhor", ler_sistema=False).answer("qual o uso da cpu e da ram?")
    assert "Não leio o Windows" in r
    assert "CPU em" in RuleResponder("Senhor").answer("qual o uso da cpu?")


def test_monitor_nao_le_cpu_ram_nem_disco(settings):
    def proibido():
        raise AssertionError("o perfil só Trilhum não pode ler o sistema")

    ledger = build_conversation(_trilhum(settings), claude_client=FakeAnthropic()).ledger
    m = Monitor(ledger, ReminderStore(settings.db_path), sampler=proibido, ler_sistema=False,
                assistente="JARVIS-TRILHUM")
    assert m.check() == []
    assert m.greeting().texto.endswith("JARVIS-TRILHUM online. Pronto para os estudos.")


def test_api_nao_expoe_o_status_do_sistema(settings, tmp_path):
    s = _trilhum(settings)
    app = create_app(s, conversation=build_conversation(s, claude_client=FakeAnthropic()), proactive=False,
                     hud_dir=tmp_path / "sem_hud")
    with TestClient(app) as c:
        r = c.get("/system/status", headers={"Authorization": "Bearer token-de-teste"})
    assert r.status_code == 404


class BaseFalsa:
    """Base de conhecimento com áreas jurídicas e não jurídicas; súmula transversal aparece em todas."""

    def __init__(self):
        self.pedidos = []

    def areas(self):
        return ["contabil", "geral", "juridico", "oab", "rural", "tributario"]

    def areas_em_uso(self):
        return ["contabil", "juridico", "oab", "tributario"]

    def buscar(self, consulta, area=None, k=5, **filtros):
        self.pedidos.append(area)
        sumula = SimpleNamespace(arquivo="juridico/sumulas.txt", rotulo="Súmula 314", area="juridico")
        proprio = SimpleNamespace(arquivo=f"{area}/lei.txt", rotulo="Art. 1", area=area)
        return [(3.0 if area == "tributario" else 1.0, sumula), (2.0, proprio)]


def test_base_restrita_as_areas_juridicas():
    base = BaseFalsa()
    r = BaseRestrita(base)
    assert r.areas() == ["juridico", "oab", "tributario"] and "contabil" not in r.areas_em_uso()
    achados = r.buscar("prescrição", k=5)
    assert base.pedidos == ["juridico", "oab", "tributario"]   # nunca contábil nem rural
    assert [t.arquivo for _, t in achados].count("juridico/sumulas.txt") == 1   # transversal sem repetir
    assert achados[0] == (3.0, achados[0][1]) and len(achados) == 4
    assert r.buscar("balanço", area="contabil") == []
    assert r.buscar("ética", area="oab")[1][1].area == "oab"
