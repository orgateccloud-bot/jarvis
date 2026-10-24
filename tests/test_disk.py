import json

import pytest

from jarvis.api.server import build_conversation
from jarvis.tools import ToolError, disk, registry
from tests.conftest import FakeAnthropic, text_turn, tool_turn


@pytest.fixture
def ctx(settings):
    return build_conversation(settings).tool_ctx


@pytest.fixture
def origem(ctx):
    return ctx.move_roots[0]


def run(name, raw, ctx):
    tool = registry()[name]
    return tool.run(tool.parse(raw), ctx)


def test_analisar_espaco_lista_os_maiores(ctx, origem):
    (origem / "grande.bin").write_bytes(b"x" * 300_000)
    (origem / "pasta").mkdir()
    (origem / "pasta" / "medio.bin").write_bytes(b"x" * 100_000)
    out = json.loads(run("analisar_espaco", {"pasta": str(origem)}, ctx))
    assert [m["nome"] for m in out["maiores"]][:2] == ["grande.bin", "pasta"]
    assert "C:\\" in out["drives"] and "parcial" not in out


def test_analisar_espaco_estoura_prazo_e_avisa(ctx, origem, monkeypatch):
    (origem / "a").mkdir()
    monkeypatch.setattr(disk, "ANALISE_PRAZO_S", -1)
    out = json.loads(run("analisar_espaco", {"pasta": str(origem)}, ctx))
    assert out["parcial"] and "dica" in out


def test_mover_mantem_estrutura_registra_lote_e_nao_sobrescreve(ctx, origem):
    (origem / "relatorio.pdf").write_bytes(b"1")
    out = json.loads(run("mover_itens", {"itens": [str(origem / "relatorio.pdf")]}, ctx))
    destino = ctx.archive / origem.name / "relatorio.pdf"
    assert destino.exists() and not (origem / "relatorio.pdf").exists()
    assert out["lote"] == 1 and out["movidos"] == 1
    (origem / "relatorio.pdf").write_bytes(b"2")                      # outro arquivo com o mesmo nome
    run("mover_itens", {"itens": [str(origem / "relatorio.pdf")]}, ctx)
    assert destino.read_bytes() == b"1"                                # o primeiro continua intacto
    assert (ctx.archive / origem.name / "relatorio (1).pdf").read_bytes() == b"2"


def test_mover_recusa_raiz_e_fora_das_pastas(ctx, origem, tmp_path):
    with pytest.raises(ToolError):
        run("mover_itens", {"itens": [str(origem)]}, ctx)              # a pasta inteira (ex.: Downloads)
    (tmp_path / "dados" / "x.txt").write_text("segredo")
    with pytest.raises(ToolError):
        run("mover_itens", {"itens": [str(tmp_path / "dados" / "x.txt")]}, ctx)
    with pytest.raises(ValueError):
        registry()["mover_itens"].parse({"itens": []})


def test_subpasta_nao_escapa_do_arquivo(ctx, origem):
    (origem / "a.txt").write_text("a")
    run("mover_itens", {"itens": [str(origem / "a.txt")], "subpasta": "..\\..\\Windows"}, ctx)
    assert any(p.name == "a.txt" for p in ctx.archive.rglob("a.txt"))
    assert all(p.resolve().is_relative_to(ctx.archive.resolve()) for p in ctx.archive.rglob("*"))


def test_desfazer_devolve_e_nao_sobrescreve(ctx, origem):
    (origem / "foto.jpg").write_bytes(b"f")
    (origem / "doc.txt").write_bytes(b"d")
    run("mover_itens", {"itens": [str(origem / "foto.jpg"), str(origem / "doc.txt")]}, ctx)
    (origem / "doc.txt").write_bytes(b"novo")                         # algo novo ocupou o lugar
    out = json.loads(run("desfazer_movimento", {}, ctx))
    assert out["devolvidos"] == 1 and len(out["falhas"]) == 1
    assert (origem / "foto.jpg").read_bytes() == b"f" and (origem / "doc.txt").read_bytes() == b"novo"
    assert json.loads(run("movimentos_recentes", {}, ctx))[0]["estado"] == "parcialmente desfeito"


def test_mover_entre_drives_copia_confere_e_so_depois_remove(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.bin").write_bytes(b"x" * 1000)
    dst = tmp_path / "dst" / "src"
    assert disk.mover(src, dst, same_drive=False) == 1000
    assert (dst / "sub" / "a.bin").stat().st_size == 1000 and not src.exists()


def test_mover_entre_drives_mantem_origem_se_copia_incompleta(tmp_path, monkeypatch):
    src = tmp_path / "f.bin"
    src.write_bytes(b"x" * 10)
    real = disk.tamanho
    monkeypatch.setattr(disk, "tamanho", lambda p, d=None: (0, True) if p.name == "f.bin" and "dst" in str(p) else real(p, d))
    with pytest.raises(ToolError):
        disk.mover(src, tmp_path / "dst" / "f.bin", same_drive=False)
    assert src.exists()                                               # nunca perde a origem


def test_lixeira_usa_send2trash_e_respeita_pastas(ctx, origem, tmp_path, monkeypatch):
    enviados = []
    monkeypatch.setattr(disk, "_para_lixeira", enviados.append)
    (origem / "velho.zip").write_bytes(b"z")
    out = json.loads(run("enviar_para_lixeira", {"itens": [str(origem / "velho.zip")]}, ctx))
    assert out["enviados"] == 1 and enviados == [str((origem / "velho.zip").resolve())]
    with pytest.raises(ToolError):
        run("enviar_para_lixeira", {"itens": [str(origem)]}, ctx)       # a raiz nunca
    assert registry()["enviar_para_lixeira"].needs_approval


def test_configuracao_so_da_lista():
    tool = registry()["abrir_configuracao"]
    assert not tool.needs_approval
    assert tool.parse({"tela": "armazenamento"}).tela == "armazenamento"
    with pytest.raises(ValueError):
        tool.parse({"tela": "editor de registro"})


async def test_card_de_aprovacao_traz_itens_e_tamanho_do_lote(settings):
    conv0 = build_conversation(settings)
    origem = conv0.tool_ctx.move_roots[0]
    for i in range(10):
        (origem / f"f{i}.bin").write_bytes(b"x" * 1024)
    itens = [str(origem / f"f{i}.bin") for i in range(10)]
    fake = FakeAnthropic(script=[tool_turn("mover_itens", {"itens": itens}), text_turn("Movidos.")])
    conv = build_conversation(settings, claude_client=fake)
    approval = None
    async for ev in conv.turn("t", "libera espaço movendo esses arquivos para o D"):
        if ev.type == "approval":
            approval = ev.data
            conv.approvals.resolve(ev.data["id"], True)
    det = approval["detalhes"]
    assert len(det["itens"]) == 8 and det["outros"] == 2 and det["total_gb"] >= 0
    assert approval["resumo"] == "mover 10 item(ns) para o arquivo no D:"
    assert len(list(conv.tool_ctx.archive.rglob("*.bin"))) == 10
