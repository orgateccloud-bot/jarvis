import json
import sqlite3
from datetime import datetime

import pytest

from jarvis.api.server import build_conversation
from jarvis.proactive.reminders import ReminderStore, proxima
from jarvis.tools import ToolContext, ToolError
from jarvis.tools import system as sistema
from jarvis.tools.system import ComandoParams, comando_seguro, hardware_info
from jarvis.tools.tasks import LembreteParams, criar_lembrete
from tests.conftest import FakeAnthropic, text_turn, tool_turn
from tests.test_tools import run_turn

SEX_9H = datetime(2026, 10, 30, 9, 0)  # sexta-feira


def test_proxima_ocorrencia_pula_fim_de_semana_e_atrasos():
    assert proxima(SEX_9H, "dias_uteis", SEX_9H) == datetime(2026, 11, 2, 9, 0)        # segunda
    assert proxima(SEX_9H, "diario", SEX_9H) == datetime(2026, 10, 31, 9, 0)
    assert proxima(SEX_9H, "semanal", SEX_9H) == datetime(2026, 11, 6, 9, 0)
    # PC desligado por dias: dispara uma vez e vai para a próxima no futuro
    assert proxima(SEX_9H, "diario", datetime(2026, 11, 4, 12, 0)) == datetime(2026, 11, 5, 9, 0)


def test_lembrete_recorrente_reagenda_em_vez_de_encerrar(tmp_path):
    store = ReminderStore(tmp_path / "j.db")
    r = store.add("ponto do almoço", SEX_9H, "dias_uteis")
    unico = store.add("ligar para o banco", SEX_9H)
    disparados = store.take_due(SEX_9H)
    assert {x.id for x in disparados} == {r.id, unico.id}
    pend = {x.id: x for x in store.pending()}
    assert unico.id not in pend and pend[r.id].quando == datetime(2026, 11, 2, 9, 0)
    assert not store.take_due(datetime(2026, 11, 1, 23, 0))                              # domingo: nada


def test_migracao_da_tabela_antiga_de_lembretes(tmp_path):
    db = tmp_path / "j.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT NOT NULL,
                     quando TEXT NOT NULL, criado TEXT NOT NULL, disparado INTEGER DEFAULT 0)""")
        c.execute("INSERT INTO reminders (texto, quando, criado) VALUES ('antigo', '2026-10-30T09:00:00', 'x')")
    store = ReminderStore(db)
    ReminderStore(db)                                                                    # idempotente
    assert store.pending()[0].texto == "antigo" and store.pending()[0].repetir is None


def test_criar_lembrete_dias_uteis_comeca_num_dia_util(tmp_path):
    ctx = ToolContext(roots=[], ledger=None, reminders=ReminderStore(tmp_path / "j.db"))
    sabado = LembreteParams(texto="revisar e-mails", quando="2099-10-31T08:30", repetir="dias_uteis")
    assert sabado.horario().weekday() == 0
    assert "repete todo dia útil" in criar_lembrete(sabado, ctx)


def test_hardware_info_sem_gpu_nvidia(monkeypatch):
    monkeypatch.setattr(sistema.shutil, "which", lambda _: None)
    info = json.loads(hardware_info(sistema._Vazio(), None))
    assert "nvidia-smi ausente" in info["gpu"] and "não disponível" in info["cpu"]["temperatura"]


def test_hardware_info_le_a_gpu_com_argumentos_fixos(monkeypatch):
    chamadas = []

    def run(argv, **kw):
        chamadas.append(argv)
        return type("R", (), {"stdout": "NVIDIA GeForce RTX 4060, 12, 1024, 8188, 45\n"})()

    monkeypatch.setattr(sistema.shutil, "which", lambda _: "nvidia-smi.exe")
    monkeypatch.setattr(sistema.subprocess, "run", run)
    gpu = json.loads(hardware_info(sistema._Vazio(), None))["gpu"][0]
    assert gpu == {"nome": "NVIDIA GeForce RTX 4060", "uso_percent": 12, "vram_usada_mb": 1024,
                   "vram_total_mb": 8188, "temperatura_c": 45}
    assert chamadas == [["nvidia-smi.exe", *sistema.NVIDIA_SMI_ARGS]]


def test_comando_seguro_so_aceita_a_lista_e_decodifica_utf16(monkeypatch):
    with pytest.raises(ValueError):
        ComandoParams(nome="format_c")
    chamadas = []

    def run(argv, **kw):
        chamadas.append(argv)
        assert "shell" not in kw
        return type("R", (), {"returncode": 0, "stdout": "A operação foi concluída.".encode("utf-16-le"),
                              "stderr": b""})()

    monkeypatch.setattr(sistema.shutil, "which", lambda n: f"C:/Windows/System32/{n}.exe")
    monkeypatch.setattr(sistema.subprocess, "run", run)
    out = comando_seguro(ComandoParams(nome="desligar_wsl"), None)
    assert chamadas == [["C:/Windows/System32/wsl.exe", "--shutdown"]] and "concluída" in out
    monkeypatch.setattr(sistema.subprocess, "run",
                        lambda argv, **kw: type("R", (), {"returncode": 1, "stdout": b"erro", "stderr": b""})())
    with pytest.raises(ToolError):
        comando_seguro(ComandoParams(nome="limpar_cache_dns"), None)


async def test_comando_seguro_pede_aprovacao_mostrando_o_comando_e_negado_nao_executa(settings, monkeypatch):
    executou = []
    monkeypatch.setattr(sistema.subprocess, "run", lambda *a, **k: executou.append(a))
    fake = FakeAnthropic(script=[tool_turn("comando_seguro", {"nome": "desligar_wsl"}), text_turn("Entendido.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "desliga o wsl", on_approval=lambda c, d: c.approvals.resolve(d["id"], False))
    card = next(e.data for e in evs if e.type == "approval")
    assert card["detalhes"]["comando"] == "wsl --shutdown" and "Vmmem" in card["detalhes"]["efeito"]
    assert not executou
