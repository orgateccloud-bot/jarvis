"""Trilhum (planos de estudo): escolha do plano, agenda montada pelo app, cache, sincronização do progresso (só
leitura) e as quatro ferramentas.

Os unitários usam executores falsos no lugar do Node (agenda e Firestore do Trilhum); um deles roda o
sync_trilhum.mjs de verdade com um firebase-admin falso. O de integração
roda o app de verdade (D:\\01_Projetos_Ativos\\Trilha) e é pulado se o Node, a pasta ou o jsdom dos testes do
Trilhum não estiverem na máquina.
"""

import json
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import pytest

from jarvis.estudos.andamento import calcular
from jarvis.estudos.sincronizacao import Progresso, SincronizacaoTrilhum, plano_sync
from jarvis.estudos.trilhum import Agenda, Trilhum, TrilhumErro
from jarvis.tools import ToolContext, ToolError, registry
from jarvis.tools.trilhum import (
    AgendaParams,
    PlanoParams,
    PlanosParams,
    ProgressoParams,
    trilhum_agenda,
    trilhum_plano,
    trilhum_planos,
    trilhum_progresso,
)

UID = "AbC123uidDoAluno"   # falso, só para o formato (o código de "Copiar código para o JARVIS")

PLANOS = {
    "rota40-oab-48": {"id": "rota40-oab-48", "sigla": "OAB 48", "titulo": "Rota 40", "inicio": "2026-10-05",
                      "alvo": "2027-01-10", "versao": "1.1", "lead": "Lei seca às 05h.", "notaMax": 80,
                      "unidadeNota": "acertos", "metas": {"meta": 57.5, "base": 50},
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
                {"id": "1-0t", "tipo": "Lei seca", "tipo_bloco": "t", "disciplina": "Const. e Adm.",
                 "assunto": "CF arts. 76–91", "minutos": 40, "inicio": "05:00"},
                {"id": "1-0q", "tipo": "Questões", "tipo_bloco": "q", "disciplina": "Const. e Adm.",
                 "assunto": "10 questões", "minutos": 90, "inicio": "20:00", "questoes": 10}]},
            {"data": "2026-11-03", "blocos": [
                {"id": "1-1t", "tipo": "Lei seca", "tipo_bloco": "t", "disciplina": "Ética", "assunto": "EAOAB",
                 "minutos": 40, "inicio": "05:00"}]},
            {"data": "2026-11-07", "blocos": [
                {"id": "1-s", "tipo": "Exame", "tipo_bloco": "e", "disciplina": "Exame de 80 questões",
                 "assunto": "13h–18h", "minutos": 300}]},
            {"data": "2026-11-08", "blocos": []}]},
        {"n": 2, "segunda": "2027-01-04", "fase": "Fase 3 · Afiação e prova", "titulo": "Reta final 2", "dias": [
            {"data": "2027-01-10", "blocos": [{"id": "2-6p", "tipo": "Prova", "disciplina": "OAB 48",
                                               "assunto": "13h–18h"}]},
            {"data": "2027-01-11", "depois_da_prova": True, "blocos": []}]},
    ],
    "fases": [{"nome": "Fase 1 · Primeira volta", "inicio": "2026-10-05", "fim": "2026-11-15", "saida": "CP1"},
              {"nome": "Fase 3 · Afiação e prova", "inicio": "2026-12-28", "fim": "2027-01-10"}],
}

# o JSON que o app grava na sincronização (dadosLocais): perfil e perguntas precisam ser descartados
DADOS_APP = {
    "perfil": {"nome": "Fulano de Tal", "proj": "OAB 48"},
    "cfg": {"start": "2026-10-05", "hDia": 4.5, "blocos": {"t": {"s": "05:30", "m": 40}}, "outra": "ignorada"},
    "feito": {"1-0t": 1, "1-0q": 1, "1-9t": 0},
    "acertos": {"1-0q": {"ok": 7, "tot": 10}},
    "notas": [{"id": "a", "d": "2026-10-31", "t": "obj", "n": 52}, {"d": "lixo", "n": 1}],
    "check": {"1": [True, True, False, False, False, False]},
    "perguntas": {"1": "texto pessoal que não pode ir ao Claude"},
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
        self.chamadas, self.entradas, self.saida = [], [], json.dumps(saida or AGENDA)

    def __call__(self, argv, timeout_s, entrada=None):
        self.chamadas.append(argv)
        self.entradas.append(entrada)
        return self.saida


def _envelope(dados, plano="rota40-oab-48"):
    """O registro como o app grava em sync/{uid}/planos/{plano}.json: {app, plano, ts, data, em}."""
    return {"app": "trilha", "plano": plano, "ts": {"cfg": 1}, "data": dados, "em": 1762000000000}


class FirestoreFalso:
    """No lugar do Node com o firebase-admin (sync_trilhum.mjs): guarda as chamadas e responde o plano pedido como a
    leitura de sync/{uid}/planos/{plano}; plano que não existe vira {"existe": false}."""

    def __init__(self, registros=None, falha=False):
        self.chamadas, self.falha = [], falha
        self.registros = {"rota40-oab-48": _envelope(DADOS_APP)} if registros is None else registros

    def __call__(self, argv, timeout_s, entrada, ambiente):
        self.chamadas.append((argv, json.loads(entrada), ambiente))
        if self.falha:
            raise TrilhumErro("não li o Firestore do Trilhum: o Firestore recusou a leitura: PERMISSION_DENIED")
        reg = self.registros.get(json.loads(entrada)["plano"])
        if reg is None:
            return json.dumps({"existe": False, "json": None, "em": None})
        return json.dumps({"existe": True, "json": reg if isinstance(reg, str) else json.dumps(reg),
                           "em": "2026-11-02T10:00:00.000Z"})

    def sync(self, **kw):
        return SincronizacaoTrilhum(UID, "demo-trilhum", _modulos(), emulador="127.0.0.1:8085", node="node",
                                    executar=self, **kw)


def _modulos() -> Path:
    """Uma pasta node_modules com um firebase-admin vazio, só para a checagem de configuração passar."""
    nm = Path(tempfile.gettempdir()) / "jarvis-testes-trilhum" / "node_modules"
    (nm / "firebase-admin").mkdir(parents=True, exist_ok=True)
    return nm


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


def test_agenda_vem_do_app_com_o_cadastro_e_fica_em_cache(pasta):
    ex = ExecutorFalso()
    t = Trilhum(pasta, node="node", executar=ex)
    a = t.agenda("rota40-oab-48")
    assert a.total == 2 and t.agenda("rota40-oab-48") is a and len(ex.chamadas) == 1
    argv = ex.chamadas[0]
    assert argv[0] == "node" and argv[1].endswith("agenda_trilhum.mjs") and argv[3].endswith("node_modules")
    entrada = json.loads(ex.entradas[0])      # o plano e o cadastro vão pela entrada, não pela linha de comando
    assert entrada["plano"]["id"] == "rota40-oab-48" and entrada["cfg"] is None
    cfg = {"start": "2026-10-12"}
    t.agenda("rota40-oab-48", cfg)                     # cadastro diferente: monta de novo
    assert json.loads(ex.entradas[1])["cfg"] == cfg
    t.agenda("rota40-oab-48", dict(cfg))
    assert len(ex.chamadas) == 2                        # mesmo cadastro: cache
    f = pasta / "planos" / "rota40-oab-48.json"
    f.write_text(json.dumps({**PLANOS["rota40-oab-48"], "versao": "1.2"}), encoding="utf-8")   # o plano mudou
    t.agenda("rota40-oab-48")
    assert len(ex.chamadas) == 3


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


def test_sincronizacao_so_le_e_descarta_o_que_e_pessoal(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "nao-pode-vazar.json")
    fs = FirestoreFalso()
    s = fs.sync()
    p = s.ler("rota40-oab-48")
    argv, entrada, ambiente = fs.chamadas[0]
    assert argv[0] == "node" and argv[1].endswith("sync_trilhum.mjs") and argv[2] == str(_modulos())
    assert entrada == {"uid": UID, "projeto": "demo-trilhum", "plano": "rota40-oab-48"}   # pela entrada, não no argv
    assert ambiente["FIRESTORE_EMULATOR_HOST"] == "127.0.0.1:8085" and "GOOGLE_APPLICATION_CREDENTIALS" not in ambiente
    assert p.feito == {"1-0t", "1-0q"} and p.acertos["1-0q"].ok == 7
    assert p.cfg == {"start": "2026-10-05", "hDia": 4.5, "blocos": {"t": {"s": "05:30", "m": 40}}}
    assert [n.n for n in p.notas] == [52] and p.revisoes == {"1": 2}
    tudo = p.model_dump_json()
    assert "Fulano" not in tudo and "pessoal" not in tudo        # perfil e perguntas nunca chegam ao Claude
    s.ler("rota40-oab-48")
    assert len(fs.chamadas) == 1                                 # guardado por 60 s
    assert FirestoreFalso({"x": DADOS_APP}).sync().ler("x").feito == {"1-0t", "1-0q"}   # sem envelope também vale
    assert plano_sync({"id": "rota 40/oab"}, "x") == "rota_40_oab"
    script = (Path(__file__).parents[1] / "jarvis" / "estudos" / "sync_trilhum.mjs").read_text(encoding="utf-8")
    assert ".get()" in script and not any(f".{m}(" in script for m in ("set", "update", "create", "add", "batch"))
    assert script.count(".delete(") == 1 and "await app.delete()" in script   # só fecha o app, não apaga nada


def test_sincronizacao_erros_sem_vazar_o_uid():
    assert "não está configurada" in SincronizacaoTrilhum().problema()
    assert "JARVIS_TRILHUM_UID" in SincronizacaoTrilhum("uid/../outro", "demo-trilhum", _modulos(),
                                                        emulador="127.0.0.1:8085", node="node").problema()
    assert "conta de serviço" in SincronizacaoTrilhum(UID, "trilha-estudos-2026", _modulos(), node="node").problema()
    with pytest.raises(TrilhumErro, match="PERMISSION_DENIED") as e:
        FirestoreFalso(falha=True).sync().ler("rota40-oab-48")
    assert UID not in str(e.value)
    assert FirestoreFalso(registros={}).sync().ler("rota40-oab-48") is None   # plano ainda não sincronizado
    with pytest.raises(TrilhumErro, match="não é JSON"):
        FirestoreFalso({"rota40-oab-48": "{quebrado"}).sync().ler("rota40-oab-48")


def test_sincronizacao_da_config(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_TRILHUM_UID", UID)
    monkeypatch.setenv("JARVIS_TRILHUM_DIR", str(tmp_path))
    s = SincronizacaoTrilhum.da_config(settings, "sal")
    assert s.configurada and s.uid == UID and s.projeto == "trilha-estudos-2026" and s.salt == "sal"
    assert s.modulos == tmp_path / "functions" / "node_modules"


FIREBASE_ADMIN_FALSO = {
    "package.json": json.dumps({"name": "firebase-admin", "exports": {"./app": "./app.js",
                                                                      "./firestore": "./firestore.js"}}),
    "app.js": "exports.initializeApp = (o) => ({o, delete: async () => {}});\n"
              "exports.applicationDefault = () => { throw new Error('sem credencial no teste'); };\n",
    "firestore.js": (
        "const dados = require('./dados.json');\n"
        "const doc = (p) => ({collection: (c) => col(p + '/' + c),\n"
        "  get: async () => (p in dados ? {exists: true, data: () => dados[p]} : {exists: false})});\n"
        "const col = (p) => ({doc: (d) => doc(p + '/' + d)});\n"
        "exports.getFirestore = () => ({collection: (c) => col(c)});\n"),
}


@pytest.mark.skipif(not shutil.which("node"), reason="sem o Node nesta máquina")
def test_sync_trilhum_mjs_le_o_caminho_do_app(tmp_path):
    """O sync_trilhum.mjs de verdade, com um firebase-admin falso que responde sync/{uid}/planos/{plano}."""
    fa = tmp_path / "node_modules" / "firebase-admin"
    fa.mkdir(parents=True)
    for nome, texto in FIREBASE_ADMIN_FALSO.items():
        (fa / nome).write_text(texto, encoding="utf-8")
    (fa / "dados.json").write_text(json.dumps({f"sync/{UID}/planos/rota40-oab-48": {
        "json": json.dumps(_envelope(DADOS_APP)), "em": "2026-11-02T10:00:00.000Z"}}), encoding="utf-8")
    s = SincronizacaoTrilhum(UID, "demo-trilhum", tmp_path / "node_modules", emulador="127.0.0.1:8085")
    assert s.ler("rota40-oab-48").feito == {"1-0t", "1-0q"}
    assert s.ler("oab-60-dias") is None
    script = Path(__file__).parents[1] / "jarvis" / "estudos" / "sync_trilhum.mjs"
    r = subprocess.run([shutil.which("node"), str(script), str(tmp_path / "node_modules")], check=False,
                       input=json.dumps({"uid": "../x", "projeto": "demo-trilhum", "plano": "p"}),
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 2 and "inválido" in r.stderr


def test_andamento():
    agenda = Agenda.model_validate(AGENDA)
    prog = Progresso.do_app(DADOS_APP)
    a = calcular(agenda, prog, date(2026, 11, 4))
    assert (a.passados_feitos, a.passados_previstos) == (2, 3) and a.semana.n == 1
    assert (a.semana_feitos, a.semana_previstos) == (2, 4)
    assert [x.bloco.id for x in a.pendentes_semana] == ["1-1t"] and a.pendentes_antes == 0
    const = next(x for x in a.disciplinas if x.disciplina == "Const. e Adm.")
    assert (const.feitos, const.previstos, const.acertos_ok, const.acertos_tot) == (2, 2, 7, 10)


def test_ferramenta_agenda(pasta):
    ctx = _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso()))
    r = trilhum_agenda(AgendaParams(data=date(2026, 11, 2)), ctx)
    assert r.startswith("Rota 40 (rota40-oab-48), 05/10/2026 a 10/01/2027.")
    assert "segunda, 02/11/2026 · semana 1 de 2, Primeira volta 1 (Fase 1 · Primeira volta) · feriado: Finados" in r
    assert "- 05:00 · Lei seca, 40 min · Const. e Adm.: CF arts. 76–91" in r
    assert "sem a sincronização configurada" in r
    semana = trilhum_agenda(AgendaParams(data=date(2026, 11, 6), dias=3), ctx)
    assert "sexta, 06/11/2026: fora do plano." in semana
    assert "- Exame, 300 min · Exame de 80 questões: 13h–18h" in semana
    assert "domingo, 08/11/2026 · semana 1 de 2" in semana and "sem estudo marcado" in semana
    fim = trilhum_agenda(AgendaParams(plano="rota40-oab-48", data=date(2027, 1, 10), dias=2), ctx)
    assert "- Prova · OAB 48: 13h–18h" in fim and "depois da data-alvo, sem estudo." in fim
    dois = trilhum_agenda(AgendaParams(data=date(2026, 11, 12)), ctx)
    assert dois.startswith("OAB em 60 dias") and "Também em andamento: rota40-oab-48" in dois


def test_ferramenta_agenda_com_progresso(pasta):
    ex = ExecutorFalso()
    ctx = _ctx(Trilhum(pasta, node="node", executar=ex, sync=FirestoreFalso().sync()))
    r = trilhum_agenda(AgendaParams(data=date(2026, 11, 2), dias=2), ctx)
    assert json.loads(ex.entradas[0])["cfg"]["blocos"] == {"t": {"s": "05:30", "m": 40}}   # agenda com o cadastro
    assert "- ✓ 05:00 · Lei seca, 40 min · Const. e Adm." in r
    assert "- ✓ 20:00 · Questões, 90 min · Const. e Adm.: 10 questões (7 de 10 acertos)" in r
    assert "- · 05:00 · Lei seca, 40 min · Ética" in r and "Horários do seu cadastro no Trilhum" in r
    falha = _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso(), sync=FirestoreFalso(falha=True).sync()))
    r = trilhum_agenda(AgendaParams(data=date(2026, 11, 2)), falha)
    assert "Não li o progresso" in r and "- 05:00 · Lei seca" in r   # a agenda sai mesmo sem o progresso


def test_ferramenta_progresso(pasta, monkeypatch):
    from jarvis.tools import trilhum as mod

    class Hoje(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 4)

    monkeypatch.setattr(mod, "date", Hoje)
    ctx = _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso(), sync=FirestoreFalso().sync()))
    r = trilhum_progresso(ProgressoParams(plano="rota40-oab-48"), ctx)
    assert "Até ontem: 2 de 3 blocos feitos (67%). Hoje: 0 de 0." in r
    assert "Semana 1 de 2 (Primeira volta 1): 2 de 4 blocos feitos." in r
    assert "- terça 03/11: Lei seca · Ética (EAOAB)" in r
    assert "- Const. e Adm.: 2 de 2 blocos; questões 7 de 10 (70%)" in r
    assert "Últimas notas: 31/10 objetiva 52 de 80 acertos." in r and "Revisões de sábado: semana 1 (2/6)." in r
    assert "Fulano" not in r
    with pytest.raises(ToolError, match="não está configurada"):
        trilhum_progresso(ProgressoParams(), _ctx(Trilhum(pasta, node="node", executar=ExecutorFalso(),
                                                          sync=SincronizacaoTrilhum())))


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
    nomes = ("trilhum_agenda", "trilhum_progresso", "trilhum_planos", "trilhum_plano")
    assert set(nomes) <= set(tools) and not any(tools[n].needs_approval for n in nomes)
    with pytest.raises(ValueError, match="entrada inválida"):
        tools["trilhum_agenda"].parse({"plano": "../../segredo"})
    with pytest.raises(ValueError, match="entrada inválida"):
        tools["trilhum_agenda"].parse({"dias": 30})
    with pytest.raises(ToolError, match="não está configurado"):
        trilhum_agenda(AgendaParams(), _ctx(None))


def test_planos_salvos_no_app_entram_e_sao_preferidos(pasta):
    """31/10: no app, o usuário tinha "rota40" (gerado no app, sem arquivo na pasta) e "oab-60-dias"; o JARVIS só
    conhecia a pasta e não achava o plano em uso. Os planos do catálogo sincronizado (_planos) entram na lista,
    valem sobre a pasta quando o id é o mesmo e são preferidos na escolha automática."""
    app = {**PLANOS["rota40-oab-48"], "id": "rota40", "titulo": "Exame da Ordem (no app)"}
    sb = FirestoreFalso({"_planos": {"app": "trilha", "itens": {"rota40": {"em": 1, "plano": app},
                                                                "removido": {"em": 2, "plano": None}}},
                         "rota40": _envelope(DADOS_APP, "rota40")})
    ex = ExecutorFalso()
    t = Trilhum(pasta, node="node", executar=ex, sync=sb.sync())
    planos = {p.id: p for p in t.planos()}
    assert planos["rota40"].origem == "app" and planos["rota40-oab-48"].origem == "pasta" and "removido" not in planos
    assert t.escolher(None, date(2026, 11, 2)).id == "rota40"     # os dois em andamento: o do app vem antes
    t.agenda("rota40")
    assert json.loads(ex.entradas[0])["plano"]["titulo"] == "Exame da Ordem (no app)"
    assert t.progresso("rota40").feito == {"1-0t", "1-0q"}          # progresso lido com o id do app
    lista = trilhum_planos(PlanosParams(), _ctx(t))
    assert "- rota40: Exame da Ordem (no app) (05/10/2026 a 10/01/2027; versão 1.1) · em andamento · salvo no app" in lista
    sem_catalogo = Trilhum(pasta, node="node", executar=ExecutorFalso(), sync=FirestoreFalso(falha=True).sync())
    assert "rota40-oab-48" in {p.id for p in sem_catalogo.planos()}   # catálogo fora do ar: a pasta continua valendo


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
    assert all(b.id for s in agenda.semanas for d in s.dias for b in d.blocos)   # todo bloco tem o id do app
    outra = t.agenda(info.id, {"start": "2026-10-12", "blocos": {"t": {"s": "05:30", "m": 40}}})
    primeiro = outra.semanas[0].dias[0].blocos[0]
    assert outra.semanas[0].segunda == date(2026, 10, 12) and primeiro.inicio == "05:30"   # o cadastro vale
