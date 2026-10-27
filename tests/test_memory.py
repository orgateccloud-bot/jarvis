import pytest

from jarvis.api.server import build_conversation
from jarvis.tools import ToolContext, ToolError, definitions_for, manifesto, registry
from jarvis.tools.memory import LIMITE_ARQUIVO, JarvisMemory, MemoriaParams, memoria
from tests.conftest import FakeAnthropic, text_turn, tool_turn
from tests.test_tools import run_turn, tool_results


@pytest.fixture
def mem(tmp_path):
    m = JarvisMemory(tmp_path / "dados", salt="s")
    return m, ToolContext(roots=[], ledger=None, reminders=None, memory=m)


def call(ctx, **kw):
    return memoria(MemoriaParams(**kw), ctx)


def test_caminhos_fora_de_memories_sao_recusados(mem):
    _, ctx = mem
    for path in ("/memories/../segredo.txt", "/memories/../../.env", "/etc/passwd", "C:/Windows/win.ini"):
        with pytest.raises(ToolError):
            call(ctx, command="view", path=path)
    with pytest.raises(ToolError):
        call(ctx, command="create", path="/memories/../fora.md", file_text="x")


def test_grava_mascarando_cpf_e_sobrescrever_guarda_a_versao_anterior(mem):
    m, ctx = mem
    call(ctx, command="create", path="/memories/notas.md", file_text="cliente 123.456.789-09 prefere e-mail\n")
    texto = (m.memory_root / "notas.md").read_text(encoding="utf-8")
    assert "123.456.789-09" not in texto and "***.***.***-**" in texto
    call(ctx, command="create", path="/memories/notas.md", file_text="versão 2\n")
    assert (m.memory_root / "notas.md").read_text(encoding="utf-8") == "versão 2\n"
    assert len(list(m.lixeira.glob("*-notas.md"))) == 1
    listagem = call(ctx, command="view", path="/memories")
    assert "notas.md" in listagem and ".lixeira" not in listagem


def test_apagar_vai_para_a_lixeira_e_a_raiz_e_intocavel(mem):
    m, ctx = mem
    call(ctx, command="create", path="/memories/velho.md", file_text="x\n")
    assert "Successfully deleted" in call(ctx, command="delete", path="/memories/velho.md")
    assert not (m.memory_root / "velho.md").exists() and list(m.lixeira.glob("*-velho.md"))
    for path in ("/memories", "/memories/"):
        with pytest.raises(ToolError):
            call(ctx, command="delete", path=path)
    with pytest.raises(ToolError):
        call(ctx, command="rename", old_path="/memories/", new_path="/memories/outro")
    assert m.memory_root.is_dir()


def test_teto_de_tamanho_e_campos_obrigatorios(mem):
    _, ctx = mem
    with pytest.raises(ToolError):
        call(ctx, command="create", path="/memories/grande.md", file_text="a" * (LIMITE_ARQUIVO + 1))
    with pytest.raises(ValueError):
        MemoriaParams(command="create", path="/memories/x.md")          # sem file_text
    call(ctx, command="create", path="/memories/p.md", file_text="linha 1\n")
    assert "edited" in call(ctx, command="str_replace", path="/memories/p.md", old_str="linha 1", new_str="linha um")
    assert "edited" in call(ctx, command="insert", path="/memories/p.md", insert_line=1, insert_text="linha 2")


def test_perfil_inicial_so_na_primeira_vez(tmp_path):
    m = JarvisMemory(tmp_path / "dados")
    m.semear("Senhor")
    perfil = m.memory_root / "perfil.md"
    assert "OAB" in perfil.read_text(encoding="utf-8") and "ORGATEC" in perfil.read_text(encoding="utf-8")
    perfil.write_text("editado pelo JARVIS", encoding="utf-8")
    m.semear("Senhor")
    assert perfil.read_text(encoding="utf-8") == "editado pelo JARVIS"


def test_definicao_e_a_da_anthropic_e_entra_no_manifesto():
    reg = registry()
    defs = definitions_for("claude-haiku-5-5", reg)
    assert {"type": "memory_20250818", "name": "memory"} in defs
    assert "- memory: Memória de longo prazo" in manifesto(reg)


async def test_conversa_consulta_a_memoria_sem_pedir_aprovacao(settings):
    fake = FakeAnthropic(script=[tool_turn("memory", {"command": "view", "path": "/memories"}),
                                 text_turn("Às ordens.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "bom dia, o que você lembra de mim")
    assert not [e for e in evs if e.type == "approval"]
    res = tool_results(fake.calls[1])
    assert res and "perfil.md" in res[0]["content"] and not res[0].get("is_error")
    assert "memória do JARVIS" not in fake.calls[0]["system"]          # o perfil não vai no prompt fixo (cache)
