"""Etapa 1b: abrir_app pela lista em JSON, listar_apps e apps_abertos. Tudo com mocks: nada abre, nada lê o
registro, os atalhos ou as janelas reais."""

import json

import pytest
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.tools import ToolContext, ToolError, registry
from jarvis.tools import apps as mod
from tests.conftest import FakeAnthropic, text_turn, tool_turn


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """apps.json de teste, executáveis falsos, uma raiz permitida e o registro das chamadas de abertura."""
    exe = tmp_path / "bin" / "Editor.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    raiz, home = tmp_path / "raiz", tmp_path / "home"
    (raiz / "projeto").mkdir(parents=True)
    (tmp_path / "fora").mkdir()
    catalogo = tmp_path / "apps.json"
    catalogo.write_text(json.dumps({"apps": {
        "bloco de notas": {"tipo": "app", "abrir": "notepad.exe"},
        "editor": {"tipo": "editor", "exe": str(exe)},
        "sumido": {"tipo": "app", "exe": str(tmp_path / "nao-existe.exe")},
    }}), encoding="utf-8")
    chamadas = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: chamadas.append(("popen", a)))
    monkeypatch.setattr(mod.os, "startfile", lambda alvo: chamadas.append(("startfile", alvo)), raising=False)
    ctx = ToolContext(roots=[raiz.resolve()], ledger=None, reminders=None, home=home)
    return {"reg": registry(catalogo), "ctx": ctx, "chamadas": chamadas, "tmp": tmp_path, "catalogo": catalogo}


def _abrir(amb, **entrada):
    tool = amb["reg"]["abrir_app"]
    return tool.run(tool.parse(entrada), amb["ctx"])


def test_json_invalido_ou_app_ausente_da_erro_claro_sem_derrubar_a_api(ambiente, settings, tmp_path, monkeypatch):
    quebrado = tmp_path / "quebrado.json"
    quebrado.write_text('{"apps": {"chrome": {"tipo": "app",}}}', encoding="utf-8")
    cat = mod.carregar_catalogo(quebrado)
    assert "quebrado.json inválido (linha 1" in cat.erro
    assert "não encontrada" in mod.carregar_catalogo(tmp_path / "nao-existe.json").erro

    # a API sobe e o modelo recebe o erro como resultado da ferramenta, sem quebrar o turno
    monkeypatch.setattr(mod, "CATALOGO_PADRAO", quebrado)
    fake = FakeAnthropic(script=[tool_turn("abrir_app", {"nome": "chrome"}), text_turn("Não consegui.")])
    conv = build_conversation(settings, claude_client=fake, approval_timeout_s=5)
    client = TestClient(create_app(settings, conversation=conv, proactive=False))
    assert client.get("/health").status_code == 200
    with pytest.raises(ToolError, match="quebrado.json inválido"):
        conv.tools["abrir_app"].run(conv.tools["abrir_app"].parse({"nome": "chrome"}), conv.tool_ctx)

    # app fora da lista ou com executável ausente não entra no enum
    with pytest.raises(ValueError):
        ambiente["reg"]["abrir_app"].parse({"nome": "chrome"})
    with pytest.raises(ValueError):
        ambiente["reg"]["abrir_app"].parse({"nome": "sumido"})
    assert ambiente["chamadas"] == []


def test_pasta_fora_das_raizes_e_recusada(ambiente):
    with pytest.raises(ToolError):
        _abrir(ambiente, nome="editor", pasta=str(ambiente["tmp"] / "fora"))
    assert ambiente["chamadas"] == []


def test_pasta_para_app_que_nao_e_editor_e_recusada(ambiente):
    with pytest.raises(ToolError, match="só programas do tipo editor"):
        _abrir(ambiente, nome="bloco de notas", pasta=str(ambiente["ctx"].roots[0] / "projeto"))
    assert ambiente["chamadas"] == []


@pytest.mark.parametrize("nome", ["& calc", "editor & calc", "editor\" & calc.exe", "bloco de notas; calc"])
def test_injecao_no_nome_e_recusada(ambiente, nome):
    with pytest.raises(ValueError):
        ambiente["reg"]["abrir_app"].parse({"nome": nome})
    assert ambiente["chamadas"] == []


@pytest.mark.parametrize("pasta", ["..\\", "..\\..\\Windows", "projeto & calc", "projeto\" & calc.exe \""])
def test_injecao_na_pasta_e_recusada(ambiente, pasta):
    with pytest.raises(ToolError):
        _abrir(ambiente, nome="editor", pasta=pasta)
    assert ambiente["chamadas"] == []


def test_listar_apps_e_apps_abertos_nao_alteram_nada(ambiente, monkeypatch):
    antes = ambiente["catalogo"].read_bytes()
    exe = str(ambiente["tmp"] / "bin" / "Editor.exe")
    monkeypatch.setattr(mod, "_atalhos_menu_iniciar", lambda: [("Editor", exe), ("Bloco de Notas", "C:/Windows/notepad.exe")])
    monkeypatch.setattr(mod, "_registro_uninstall", lambda: [("Editor 1.2.3", exe), ("Outro App", "C:/Outro/outro.exe")])

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return "editor.exe"

        def memory_info(self):
            return type("M", (), {"rss": 50 * 2**20})()

        def cmdline(self):
            raise AssertionError("a linha de comando não pode ser lida")

    monkeypatch.setattr(mod, "_janelas", lambda: [("Contrato CPF 123.456.789-09", 42)])
    monkeypatch.setattr(mod.psutil, "Process", Proc)

    lista = json.loads(ambiente["reg"]["listar_apps"].run(mod.ListarAppsParams(), ambiente["ctx"]))
    nomes = {a["nome"]: a for a in lista["apps"]}
    assert set(nomes) == {"Editor", "Bloco de Notas", "Outro App"}            # "Editor 1.2.3" é duplicata
    assert nomes["Editor"]["na_lista"] and nomes["Bloco de Notas"]["na_lista"] and not nomes["Outro App"]["na_lista"]

    janelas = json.loads(ambiente["reg"]["apps_abertos"].run(mod._Vazio(), ambiente["ctx"]))
    assert janelas == [{"titulo": "Contrato CPF ***.***.***-**", "processo": "editor.exe", "pid": 42, "memoria_mb": 50}]

    assert ambiente["catalogo"].read_bytes() == antes                       # a lista permitida não mudou
    assert ambiente["chamadas"] == []                                         # nada foi aberto
    assert not ambiente["reg"]["listar_apps"].needs_approval and not ambiente["reg"]["apps_abertos"].needs_approval
