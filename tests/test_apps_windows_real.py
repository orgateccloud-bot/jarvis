"""Teste de fumaça REAL (Windows): lê o Menu Iniciar, o registro e as janelas abertas desta máquina.

Fica fora da execução padrão. Rode manualmente:  .venv\\Scripts\\python -m pytest -m windows_real -v
Não abre nenhum programa e não altera nada."""

import json
import sys

import pytest

from jarvis.tools import ToolContext, registry
from jarvis.tools.apps import ListarAppsParams, _Vazio

pytestmark = [pytest.mark.windows_real,
              pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")]


def test_listar_apps_real():
    reg = registry()
    lista = json.loads(reg["listar_apps"].run(ListarAppsParams(), ToolContext(roots=[], ledger=None, reminders=None)))
    print(f"\n{lista['total']} programas; primeiros: {[a['nome'] for a in lista['apps'][:8]]}")
    assert lista["total"] > 0
    assert all({"nome", "caminho", "origem", "na_lista"} <= set(a) for a in lista["apps"])
    assert any(a["na_lista"] for a in lista["apps"]), "nenhum programa instalado reconhecido como da lista"


def test_apps_abertos_real():
    reg = registry()
    janelas = json.loads(reg["apps_abertos"].run(_Vazio(), ToolContext(roots=[], ledger=None, reminders=None)))
    print(f"\n{len(janelas)} janelas; maiores: {[(j['processo'], j['memoria_mb']) for j in janelas[:5]]}")
    assert janelas, "nenhuma janela visível encontrada"
    assert all(set(j) == {"titulo", "processo", "pid", "memoria_mb"} for j in janelas)
