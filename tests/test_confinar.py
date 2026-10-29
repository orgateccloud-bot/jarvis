"""confinar(): caminho relativo prefere a pasta do usuário; ambíguo exige absoluto; nada sai das raízes."""

import os
import sys

import pytest

from jarvis.tools import ToolContext, ToolError
from jarvis.tools.files import confinar


@pytest.fixture
def ctx(tmp_path):
    """Usuário falso em tmp: Downloads e Documentos são raízes; a pasta do usuário em si não é."""
    home, arquivo = tmp_path / "Usuario", tmp_path / "JARVIS-Arquivo"
    for p in (home / "Downloads", home / "Documents" / "Relatorios", arquivo / "Downloads", arquivo / "Relatorios"):
        p.mkdir(parents=True)
    (arquivo / "so-no-arquivo.txt").write_text("x", encoding="utf-8")
    (home / "segredo.txt").write_text("fora das raízes", encoding="utf-8")
    roots = [(home / "Downloads").resolve(), (home / "Documents").resolve(), arquivo.resolve()]
    return ToolContext(roots=roots, ledger=None, reminders=None, home=home)


def test_downloads_relativo_vai_para_a_pasta_do_usuario(ctx):
    # regressão: antes casava com JARVIS-Arquivo\Downloads, a única raiz que tinha uma subpasta "Downloads"
    assert confinar("Downloads", ctx) == (ctx.home / "Downloads").resolve()


def test_nome_em_mais_de_uma_raiz_exige_caminho_absoluto(ctx):
    with pytest.raises(ToolError, match="caminho absoluto") as e:
        confinar("Relatorios", ctx)
    assert "Documents" in str(e.value) and "JARVIS-Arquivo" in str(e.value)


def test_relativo_numa_raiz_so_continua_resolvendo(ctx):
    assert confinar("so-no-arquivo.txt", ctx).name == "so-no-arquivo.txt"


def test_caminho_absoluto_continua_funcionando(ctx):
    arquivo_downloads = ctx.roots[2] / "Downloads"
    assert confinar(str(arquivo_downloads), ctx) == arquivo_downloads
    assert confinar(f'"{ctx.home / "Documents" / "Relatorios"}"', ctx).name == "Relatorios"


def test_nada_sai_das_raizes(ctx):
    for caminho in ("segredo.txt",                      # na pasta do usuário, mas ela não é raiz
                    str(ctx.home / "segredo.txt"),      # idem, absoluto
                    "Downloads/../segredo.txt",         # sobe com ..
                    "../Usuario/segredo.txt",
                    "inexistente"):
        with pytest.raises(ToolError):
            confinar(caminho, ctx)


def _link(origem, destino) -> bool:
    try:
        os.symlink(destino, origem, target_is_directory=True)
        return True
    except OSError:
        if sys.platform != "win32":
            return False
    try:  # sem modo desenvolvedor o Windows nega symlink; junction não exige admin
        import _winapi

        _winapi.CreateJunction(str(destino), str(origem))
        return True
    except OSError:
        return False


def test_link_simbolico_para_fora_e_bloqueado(ctx, tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "dados.txt").write_text("x", encoding="utf-8")
    if not _link(ctx.home / "Downloads" / "atalho", fora):
        pytest.skip("este sistema não permite criar link simbólico nem junction")
    with pytest.raises(ToolError):
        confinar("Downloads/atalho/dados.txt", ctx)
    with pytest.raises(ToolError):
        confinar(str(ctx.home / "Downloads" / "atalho"), ctx)
