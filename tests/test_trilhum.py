"""Trilhum (planos de estudo): escolha do plano, agenda montada pelo app, cache e as três ferramentas, só leitura.

Os unitários usam um executor falso no lugar do Node. O de integração roda o app de verdade (D:\\01_Projetos_Ativos\\
Trilha) e é pulado se o Node, a pasta ou o jsdom dos testes do Trilhum não estiverem na máquina.
"""

import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from jarvis.estudos.trilhum import Trilhum, TrilhumErro
from jarvis.tools import ToolContext, ToolError, registry
from jarvis.tools.trilhum import (
    AgendaParams,
    PlanoParams,
    PlanosParams,
    trilhum_agenda,
    trilhum_plano,
    trilhum_planos,
)

PLANOS = {
    "rota40-oab-48": {"id": "rota40-oab-48", "sigla": "OAB 48", "titulo": "Rota 40", "inicio": "2026-10-05",
                      "alvo": "2027-01-10", "versao": "1.1", "lead": "Lei seca às 05h.",
                      "metas": {"meta": 57.5, "base": 50},
                      "disciplinas": {"Ética": {"nome": "Ética profissional", "pri": "A", "obj": "8 questões",
                                                "retorno": "infrações e honorários"}}},
    "oab-60-dias": {"id": "oab-60-dias", "sigla": "OAB 60", "titulo": "OAB em 60 dias", "inicio": "2026-11-09",
                    "alvo": "2027-01-10", "versao": "1.1"},
    "plano-teste-dados": {"id": "plano-teste-dados", "sigla": "DADOS", "titulo": "Preparação DADOS",
                          "inicio": "2026-10-19", "versao": "teste 1.0"},   # sem alvo: "em andamento" para sempre
}

AGENDA = {
    "total": 2,
    "semanas": [
        {"n": 1, "segunda": "2026-11-02", "fase": "Fase 1 · Primeira volta", "titulo": "Primeira volta 1", "dias": [
            {"data": "2026-11-02", "feriado": "Finados", "blocos": [
                {"tipo": "Lei seca", "disciplina": "Const. e Adm.", "assunto": "CF arts. 76–91", "minutos": 40,
                 "inicio": "05:00", "questoes": 0},
                {"tipo": "Questões", "disciplina": "Const. e Adm.", "assunto": "10 questões", "minutos": 90,
                 "inicio": "20:00", "questoes": 10}]},
            {"data": "2026-11-07", "blocos": [
                {"tipo": "Exame", "disciplina": "Exame de 80 questões", "assunto": "13h–18h", "minutos": 300}]},
            {"data": "2026-11-08", "blocos": []}]},
        {"n": 2, "segunda": "2027-01-04", "fase": "Fase 3 · Afiação e prova", "titulo": "Reta final 2", "dias": [
            {"data": "2027-01-10", "blocos": [{"tipo": "Prova", "disciplina": "OAB 48", "assunto": "13h–18h"}]},
            {"data": "2027-01-11", "depois_da_prova": True, "blocos": []}]},
    ],
    "fases": [{"nome": "Fase 1 · Primeira volta", "inicio": "2026-10-05", "fim": "2026-11-15", "saida": "CP1"},
              {"nome": "Fase 3 · Afiação e prova", "inicio": "2026-12-28", "fim": "2027-01-10"}],
}


@pytest.fixture
def pasta(tmp_path):
    (tmp_path / "planos").mkdir()
    for pid, d in PLANOS.items():
        (tmp_path / "planos" / f"{pid}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "trilha.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "testes" / "node_modules" / "jsdom").mkdir(parents=True)
    return tmp_path


class ExecutorFalso:
    def __init__(self, saida=None):
        self.chamadas, self.saida = [], json.dumps(saida or AGENDA)

    def __call__(self, argv, timeout_s):
        self.chamadas.append(argv)
        return self.saida


def _ctx(trilhum):
    return ToolContext(roots=[], ledger=None, reminders=None, trilhum=trilhum)


def test_escolha_do_plano(pasta):
    t = Trilhum(pasta, node="node", executar=ExecutorFalso())
    assert [p.id for p in t.planos()] == ["rota40-oab-48", "plano-teste-dados", "oab-60-dias"]   # por início
    assert t.escolher(None, date(2026, 11, 2)).id == "rota40-oab-48"   # o de teste nunca é escolhido sozinho
    assert t.escolher(None, date(2026, 11, 12)).id == "oab-60-dias"    # dois em andamento: o que começou depois
    assert t.escolher(None, date(2026, 9, 1)).id == "rota40-oab-48"    # nenhum em andamento: o próximo
    assert t.escolher("plano-teste-dados", date(2026, 11, 2)).id == "plano-teste-dados"   # pedido pelo nome vale
    assert t.escolher("oab 48", date(2026, 11, 12)).id == "rota40-oab-48"                  # e pela sigla
    assert Trilhum(pasta, plano_padrao="oab-60-dias").escolher(None, date(2026, 11, 2)).id == "oab-60-dias"
    with pytest.raises(TrilhumErro, match="não encontrado; os planos são: rota40"):
        t.escolher("tjgo", date(2026, 11, 2))


def test_agenda_vem_do_app_e_fica_em_cache_ate_o_plano_mudar(pasta):
    ex = ExecutorFalso()
    t = Trilhum(pasta, node="node", executar=ex)
    a = t.agenda("rota40-oab-48")
    assert a.total == 2 and t.agenda("rota40-oab-48") is a and len(ex.chamadas) == 1
    argv = ex.chamadas[0]
    assert argv[0] == "node" and argv[1].endswith("agenda_trilhum.mjs") and argv[3].endswith("rota40-oab-48.json")
    f = pasta / "planos" / "rota40-oab-48.json"
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 10**9))   # o plano mudou: monta de novo
    t.agenda("rota40-oab-48")
    assert len(ex.chamadas) == 2


def test_erros_claros(pasta):
    with pytest.raises(TrilhumErro, match="nome de plano inválido"):
        Trilhum(pasta, node="node", executar=ExecutorFalso()).agenda("../segredo")
    sem_node = Trilhum(pasta, executar=ExecutorFalso())
    sem_node.node = None                       # como se shutil.which("node") não achasse nada
    with pytest.raises(TrilhumErro, match="Node não está instalado"):
        sem_node.agenda("rota40-oab-48")
    shutil.rmtree(pasta / "testes")
    with pytest.raises(TrilhumErro, match="jsdom não está"):
        Trilhum(pasta, node="node", executar=ExecutorFalso()).agenda("rota40-oab-48")
    (pasta / "testes" / "node_modules" / "jsdom").mkdir(parents=True)
    with pytest.raises(TrilhumErro, match="não entendi"):
        Trilhum(pasta, node="node", executar=ExecutorFalso({"total": "x"})).agenda("rota40-oab-48")
    with pytest.raises(TrilhumErro, match="pasta de planos do Trilhum não existe"):
        Trilhum(pasta / "nada").planos()


def test_ferramenta_agenda(pasta):
    ctx = _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso()))
    r = trilhum_agenda(AgendaParams(data=date(2026, 11, 2)), ctx)
    assert r.startswith("Rota 40 (rota40-oab-48), 05/10/2026 a 10/01/2027.")
    assert "segunda, 02/11/2026 · semana 1 de 2, Primeira volta 1 (Fase 1 · Primeira volta) · feriado: Finados" in r
    assert "- 05:00 · Lei seca, 40 min · Const. e Adm.: CF arts. 76–91" in r
    assert "o progresso fica no navegador" in r
    semana = trilhum_agenda(AgendaParams(data=date(2026, 11, 6), dias=3), ctx)
    assert "sexta, 06/11/2026: fora do plano." in semana
    assert "- Exame, 300 min · Exame de 80 questões: 13h–18h" in semana
    assert "domingo, 08/11/2026 · semana 1 de 2" in semana and "sem estudo marcado" in semana
    fim = trilhum_agenda(AgendaParams(plano="rota40-oab-48", data=date(2027, 1, 10), dias=2), ctx)
    assert "- Prova · OAB 48: 13h–18h" in fim and "depois da data-alvo, sem estudo." in fim
    dois = trilhum_agenda(AgendaParams(data=date(2026, 11, 12)), ctx)
    assert dois.startswith("OAB em 60 dias") and "Também em andamento: rota40-oab-48" in dois


def test_ferramentas_planos_e_resumo(pasta):
    ctx = _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso()))
    lista = trilhum_planos(PlanosParams(), ctx)
    assert "- plano-teste-dados: Preparação DADOS (desde 19/10/2026; versão teste 1.0) · plano de teste" in lista
    resumo = trilhum_plano(PlanoParams(plano="rota40-oab-48"), ctx)
    assert "Rota 40 (rota40-oab-48), versão 1.1: 05/10/2026 a 10/01/2027." in resumo
    assert "- Fase 1 · Primeira volta: 05/10/2026 a 15/11/2026. CP1" in resumo
    assert "- Ética profissional [A]: 8 questões; infrações e honorários" in resumo
    assert "Meta: 57.5 (base 50)" in resumo
    sem_node = _ctx(Trilhum(pasta, node="node", modulos=pasta / "sem-jsdom", executar=ExecutorFalso()))
    assert "Fases" not in trilhum_plano(PlanoParams(plano="rota40-oab-48"), sem_node)   # resumo sem as datas


def test_registro_validacao_e_sem_trilhum(pasta):
    tools = registry()
    assert {"trilhum_agenda", "trilhum_planos", "trilhum_plano"} <= set(tools)
    assert not any(tools[n].needs_approval for n in ("trilhum_agenda", "trilhum_planos", "trilhum_plano"))
    with pytest.raises(ValueError, match="entrada inválida"):
        tools["trilhum_agenda"].parse({"plano": "../../segredo"})
    with pytest.raises(ValueError, match="entrada inválida"):
        tools["trilhum_agenda"].parse({"dias": 30})
    with pytest.raises(ToolError, match="não está configurado"):
        trilhum_agenda(AgendaParams(), _ctx(None))


REAL = Path(r"D:\01_Projetos_Ativos\Trilha")


@pytest.mark.skipif(not (shutil.which("node") and (REAL / "planos" / "rota40-oab-48.json").is_file()
                         and (REAL / "testes" / "node_modules" / "jsdom").is_dir()),
                    reason="sem o Node, o Trilhum ou o jsdom dos testes do Trilhum nesta máquina")
def test_integracao_com_o_app_de_verdade():
    t = Trilhum(REAL)
    info = t.escolher("rota40-oab-48", date.today())
    agenda = t.agenda(info.id)
    assert agenda.total > 0 and agenda.semanas[0].segunda <= info.inicio
    achado = agenda.dia(info.alvo)
    assert achado is not None and achado[1].blocos, "a data-alvo do plano precisa aparecer na agenda"
