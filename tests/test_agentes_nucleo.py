"""Etapa 3, fundamentos: contratos, registro versionado e a fronteira do agente (objeto-capacidade)."""

import ast
import dataclasses
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.agentes.contratos import (
    AtualizacaoAgente,
    ConfigAgente,
    Ordem,
    PedidoTarefa,
    Regra,
    ResultadoTarefa,
)
from jarvis.agentes.recursos import Recursos
from jarvis.agentes.registro import OrdemRepetida, Registro
from jarvis.core.costs import CostLedger

AGENTES = Path(__file__).resolve().parent.parent / "jarvis" / "agentes"

# O código de um agente só pode importar isto. Nada de rede (anthropic, httpx, urllib, socket), processos, API,
# ferramentas do JARVIS nem o orquestrador: o Claude só chega pelo gateway em Recursos.
PERMITIDOS = {
    "__future__", "abc", "collections", "csv", "dataclasses", "datetime", "decimal", "enum", "functools",
    "hashlib", "io", "itertools", "json", "math", "pathlib", "re", "secrets", "statistics", "textwrap", "typing",
    "unicodedata", "pydantic", "loguru",
    "jarvis.agentes.contratos", "jarvis.agentes.base", "jarvis.agentes.recursos", "jarvis.core.privacy",
}


def _ordem(tarefa="eco", agente="teste", **kw) -> Ordem:
    return Ordem(agente_id=agente, pedido=PedidoTarefa(tarefa=tarefa, pedido="oi"), origem="usuario_api", **kw)


def test_contratos_extra_forbid():
    with pytest.raises(ValidationError):
        PedidoTarefa(tarefa="consultar", pedido="x", executar_como="admin")
    with pytest.raises(ValidationError):
        Ordem(agente_id="Tributário!", pedido=PedidoTarefa(tarefa="consultar"), origem="usuario_api")
    with pytest.raises(ValidationError):
        Ordem(agente_id="tributario", pedido=PedidoTarefa(tarefa="consultar"), origem="outro_agente")
    with pytest.raises(ValidationError):
        AtualizacaoAgente(teto_mensal_usd=5)          # sem motivo, não muda nada


def test_atualizacao_aplica_e_mostra_diff():
    atual = ConfigAgente()
    mudanca = AtualizacaoAgente(teto_mensal_usd=10, regras_extras=[Regra(palavra="DAS", categoria="Simples")],
                                motivo="limitar gasto")
    nova = mudanca.aplicar(atual)
    assert nova.teto_mensal_usd == 10 and nova.modelo == atual.modelo
    assert mudanca.diff(atual) == {
        "teto_mensal_usd": {"de": 30.0, "para": 10.0},
        "regras_extras": {"de": [], "para": [{"palavra": "DAS", "categoria": "Simples"}]},
    }
    assert AtualizacaoAgente(teto_mensal_usd=30, motivo="igual").diff(atual) == {}


def test_reverter_cria_versao(tmp_path):
    reg = Registro(tmp_path / "j.db")
    assert reg.criar("tributario", "tributario", ConfigAgente()) is True
    assert reg.criar("tributario", "tributario", ConfigAgente(teto_mensal_usd=1)) is False   # já existe: nada muda
    v2 = reg.nova_versao("tributario", ConfigAgente(teto_mensal_usd=5), "usuario_api", "teste")
    v3 = reg.reverter("tributario", 1, "usuario_api", "voltar")
    assert (v2, v3) == (2, 3)
    versao, cfg = reg.config("tributario")
    assert versao == 3 and cfg.teto_mensal_usd == 30
    historico = reg.versoes("tributario")
    assert [v.versao for v in historico] == [1, 2, 3]                    # nada apagado
    assert historico[2].motivo.startswith("reverte para v1")
    with pytest.raises(KeyError):
        reg.reverter("tributario", 9, "usuario_api", "não existe")


def test_ordem_repetida_recusada(tmp_path):
    reg = Registro(tmp_path / "j.db")
    reg.criar("teste", "teste", ConfigAgente())
    ordem = _ordem()
    reg.iniciar(ordem, 1)
    with pytest.raises(OrdemRepetida):
        reg.iniciar(ordem, 1)
    em_andamento = reg.execucao(ordem.id)
    assert em_andamento.estado == "em_andamento" and em_andamento.tarefa == "eco"


def test_execucao_concluida_e_resumo_do_mes(tmp_path):
    reg = Registro(tmp_path / "j.db")
    reg.criar("teste", "teste", ConfigAgente())
    ok, ruim = _ordem(), _ordem()
    for o, estado, custo in ((ok, "concluida", 0.02), (ruim, "falhou", 0.01)):
        reg.iniciar(o, 1)
        base = reg.execucao(o.id)
        reg.concluir(ResultadoTarefa(**{**base.model_dump(), "estado": estado, "versao_codigo": "1.0.0",
                                        "custo_usd": custo, "resumo": f"tarefa {estado}"}))
    assert reg.mes("teste") == (2, 1, pytest.approx(0.03))
    assert reg.execucao(ok.id).resumo == "tarefa concluida"
    assert {e.estado for e in reg.ultimas("teste")} == {"concluida", "falhou"}
    assert reg.ultima("teste") in {ok.id, ruim.id}


def test_boot_marca_interrompida(tmp_path):
    reg = Registro(tmp_path / "j.db")
    reg.criar("teste", "teste", ConfigAgente())
    ordem = _ordem()
    reg.iniciar(ordem, 1)
    assert Registro(tmp_path / "j.db").marcar_interrompidas() == 1     # o processo anterior morreu no meio
    assert reg.execucao(ordem.id).estado == "interrompida"


def test_registro_nao_mexe_user_version(tmp_path):
    db = tmp_path / "j.db"
    Registro(db)
    CostLedger(db, 30)                       # a migração do ledger ainda roda depois do registro
    Registro(db)
    with sqlite3.connect(db) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert c.execute("SELECT versao FROM agentes_schema WHERE modulo = 'agentes'").fetchone()[0] == 1


def test_pausar(tmp_path):
    reg = Registro(tmp_path / "j.db")
    reg.criar("teste", "teste", ConfigAgente())
    reg.pausar("teste", True)
    assert reg.pausado("teste") and reg.agentes() == [{"id": "teste", "tipo": "teste", "pausado": True}]


def test_recursos_sem_orquestrador():
    """O agente recebe só isto: nenhum caminho até o orquestrador, outros agentes ou ferramentas do JARVIS."""
    assert {f.name for f in dataclasses.fields(Recursos)} == {"claude", "conhecimento", "pasta", "salt"}
    assert Recursos.__dataclass_params__.frozen


def _modulos_de_agente() -> list[Path]:
    return [AGENTES / "base.py", AGENTES / "contratos.py",
            *(p for p in AGENTES.glob("*/**/*.py") if "__pycache__" not in p.parts)]


def _importados(path: Path) -> set[str]:
    pacote = ".".join(path.relative_to(AGENTES.parent.parent).with_suffix("").parts[:-1])
    nomes = set()
    for no in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            if no.level:
                base = pacote.rsplit(".", no.level - 1)[0] if no.level > 1 else pacote
                nomes.add(f"{base}.{no.module}" if no.module else base)
            else:
                nomes.add(no.module)
    return nomes


def test_imports_lista_branca():
    for path in _modulos_de_agente():
        pacote_do_agente = ".".join(path.relative_to(AGENTES.parent.parent).parts[:3])  # jarvis.agentes.<tipo>
        for nome in _importados(path):
            raiz = nome.split(".")[0]
            proprio = nome.startswith(pacote_do_agente + ".") or nome == pacote_do_agente
            assert proprio or nome in PERMITIDOS or (raiz != "jarvis" and raiz in PERMITIDOS), \
                f"{path.name} importa {nome}, fora da lista branca dos agentes"
