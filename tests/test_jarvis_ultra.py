"""JARVIS do Trilhum ULTRA: questionário (chave jarvis) da sincronização, anonimização, coach, modelo por plano de
assinatura com teto por aluno e os avisos pelo WhatsApp 30 minutos antes de cada bloco.

Nada aqui fala com a Anthropic, com o Firestore ou com a Meta: executores e transportes falsos e o FakeAnthropic.
"""

import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from jarvis.api.server import FERRAMENTAS_ALUNO, build_conversation
from jarvis.core.contracts import BudgetState, Route
from jarvis.core.planos import PLANOS, decidir, plano_jarvis
from jarvis.core.privacy import anonimizar_contato, pseudonimizar_nome
from jarvis.core.router import DEFAULT_TIERS
from jarvis.estudos.avisos import (
    FUSO_SP,
    AgendadorAvisos,
    AvisoErro,
    Destinatario,
    EnvioDryRun,
    EnvioMetaCloud,
    RegistroAvisos,
    avisos_do_dia,
    mascarar_numero,
    normalizar_whats,
)
from jarvis.estudos.coach import MARCA, nota_coach, provedor_coach
from jarvis.estudos.sincronizacao import FeedbackJarvis, Progresso, SincronizacaoTrilhum
from jarvis.estudos.trilhum import Agenda, Trilhum
from tests.conftest import FakeAnthropic

SALT = "salt-teste"
NUMERO = "5562999998888"

JARVIS_APP = {   # o que o campo JARVIS do Trilhum grava (trilha.html, jv-f)
    "obj": "Passar na 1ª fase da OAB em janeiro",
    "porque": "Fulano quer dar orgulho à mãe; meu CPF é 123.456.789-09",
    "dif": "Cansaço depois do trabalho. Me chama no (62) 99999-8888 ou fulano@exemplo.com",
    "desiste": "Quando atraso, acho que não dá mais",
    "ans": 4, "hora": "19:30", "tom": "firme", "em": 1793620800000,
}
DADOS_APP = {
    "perfil": {"nome": "Fulano de Tal", "proj": "OAB 48"},
    "cfg": {"start": "2026-10-05", "hora": "06:00"},
    "feito": {"1-1t": 1},
    "perguntas": {"1": "texto pessoal"},
    "jarvis": JARVIS_APP,
}
PLANO = {"id": "rota40-oab-48", "sigla": "OAB 48", "titulo": "Rota 40", "inicio": "2026-10-05",
         "alvo": "2027-01-10", "versao": "1.1", "hora": "05:00"}


def _bloco(id_, inicio, minutos=40, tipo="Lei seca", disc="Ética", assunto="EAOAB"):
    return {"id": id_, "tipo": tipo, "tipo_bloco": id_[-1], "disciplina": disc, "assunto": assunto,
            "minutos": minutos, "inicio": inicio}


AGENDA = {
    "total": 2,
    "semanas": [
        {"n": 1, "segunda": "2026-11-02", "fase": "Fase 1", "titulo": "Primeira volta 1", "dias": [
            {"data": "2026-11-02", "feriado": "Finados", "blocos": [_bloco("1-0t", "05:00"),
                                                                    _bloco("1-0q", "20:00", 90, "Questões")]},
            {"data": "2026-11-03", "blocos": [_bloco("1-1t", "05:00"), _bloco("1-1q", "20:00", 90, "Questões")]},
            {"data": "2026-11-07", "blocos": [_bloco("1-s", None, 300, "Exame", "Simulado", "80 questões")]}]},
        {"n": 2, "segunda": "2027-01-04", "fase": "Fase 3", "titulo": "Reta final", "dias": [
            {"data": "2027-01-10", "blocos": [_bloco("2-6p", None, 0, "Prova", "OAB 48", "13h–18h")]},
            {"data": "2027-01-11", "depois_da_prova": True, "blocos": [_bloco("2-7t", "05:00")]}]},
    ],
}


class SyncFalso:
    """No lugar do Node com o firebase-admin (sync_trilhum.mjs): o plano rota40-oab-48 no envelope do app."""

    def __init__(self, dados=None):
        self.dados = DADOS_APP if dados is None else dados

    def __call__(self, argv, timeout_s, entrada, ambiente):
        if json.loads(entrada)["plano"] != "rota40-oab-48":
            return json.dumps({"existe": False})
        return json.dumps({"existe": True, "json": json.dumps({"app": "trilha", "plano": "rota40-oab-48", "ts": {},
                                                               "data": self.dados, "em": 1762000000000})})

    def sync(self, **kw):
        nm = Path(tempfile.gettempdir()) / "jarvis-testes-trilhum" / "node_modules"
        (nm / "firebase-admin").mkdir(parents=True, exist_ok=True)
        return SincronizacaoTrilhum("AbC123uid", "demo-trilhum", nm, emulador="127.0.0.1:8085", node="node",
                                    executar=self, salt=SALT, **kw)


@pytest.fixture
def pasta(tmp_path):
    (tmp_path / "planos").mkdir()
    (tmp_path / "planos" / "rota40-oab-48.json").write_text(json.dumps(PLANO), encoding="utf-8")
    (tmp_path / "trilha.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "testes" / "node_modules" / "jsdom").mkdir(parents=True)
    return tmp_path


def _trilhum(pasta, dados=None, sync=True):
    return Trilhum(pasta, node="node", executar=lambda argv, t, e=None: json.dumps(AGENDA),
                   sync=SyncFalso(dados).sync() if sync else None)


# ── 1. leitura do questionário (chave jarvis) ────────────────
def test_le_o_questionario_jarvis_da_sincronizacao(pasta):
    prog = _trilhum(pasta).progresso("rota40-oab-48")
    fb = prog.jarvis
    assert fb.obj == "Passar na 1ª fase da OAB em janeiro"
    assert fb.desiste == "Quando atraso, acho que não dá mais"
    assert (fb.ans, fb.hora, fb.tom) == (4, "19:30", "firme")
    assert fb.em == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)   # Date.now() em ms
    assert "perfil" not in prog.model_dump() and "perguntas" not in prog.model_dump()


def test_questionario_tolera_campos_estranhos_ou_ausentes():
    assert Progresso.do_app({"cfg": {}}).jarvis is None
    assert Progresso.do_app({"jarvis": None}).jarvis is None
    fb = FeedbackJarvis.do_app({"obj": "x" * 900, "ans": 9, "hora": "25:00", "tom": "grosso", "em": "ontem",
                                "porque": 42, "extra": "ignorado"})
    assert len(fb.obj) == 300 and fb.porque == ""
    assert (fb.ans, fb.hora, fb.tom, fb.em) == (None, None, "gentil", None)
    assert FeedbackJarvis.do_app({"ans": True}).ans is None   # booleano não é nota de ansiedade
    assert FeedbackJarvis.do_app({}).vazio


# ── 2. anonimização ──────────────────────────────────────────
def test_questionario_sai_anonimizado_da_leitura():
    fb = Progresso.do_app(DADOS_APP, salt=SALT).jarvis
    texto = f"{fb.obj} {fb.porque} {fb.dif} {fb.desiste}"
    for bruto in ("123.456.789-09", "99999-8888", "fulano@exemplo.com", "Fulano"):
        assert bruto not in texto
    assert "***.***.***-**" in fb.porque and "(**) *****-****" in fb.dif and "***@***" in fb.dif
    assert pseudonimizar_nome("Fulano", SALT) in fb.porque   # o primeiro nome, como palavra inteira


def test_primeiro_nome_so_vira_pseudonimo_como_palavra_inteira():
    fb = Progresso.do_app({"perfil": {"nome": "Ana Rosa"}, "jarvis": {"dif": "Banana e Ana Rosa"}}, salt=SALT).jarvis
    assert fb.dif.startswith("Banana e ")   # "Ana" com 3 letras só some como palavra, nunca dentro de "Banana"
    assert "Ana Rosa" not in fb.dif


def test_anonimizar_contato():
    assert anonimizar_contato("zap +55 62 99999-8888, fixo 6233334444") == \
        "zap (**) *****-****, fixo (**) *****-****"
    assert anonimizar_contato("a.b+c@d.com.br") == "***@***"
    assert anonimizar_contato("estudo 2026-11-02 das 05:00 às 06:30, 40 min") == \
        "estudo 2026-11-02 das 05:00 às 06:30, 40 min"


def test_nota_do_coach_usa_o_tom_e_nao_leva_dado_pessoal(pasta):
    nota = provedor_coach(_trilhum(pasta), "Opus", hoje=lambda: date(2026, 11, 3))()
    assert nota.startswith(MARCA)
    assert "Tom escolhido pelo aluno (firme)" in nota and "cobre o combinado" in nota
    assert "Rota 40 (rota40-oab-48), data-alvo 10/01/2027" in nota and "plano Opus" in nota
    assert "Ansiedade com a prova: 4 de 5" in nota and "acolha antes de cobrar" in nota
    assert "CVV" in nota and "não monte outro cronograma" in nota
    for bruto in ("123.456.789-09", "99999-8888", "fulano@exemplo.com", "Fulano"):
        assert bruto not in nota


def test_nota_do_coach_sem_questionario_e_sem_sincronizacao(pasta):
    nota = provedor_coach(_trilhum(pasta, sync=False), hoje=lambda: date(2026, 11, 3))()
    assert "(gentil)" in nota and "ainda não respondeu o questionário" in nota
    assert nota_coach(FeedbackJarvis(tom="direto", obj="passar")).count("Quer conquistar: passar") == 1


# ── 3. modelo por plano de assinatura e teto por aluno ───────
SIMPLES, COMPLEXA = "me lembra de beber água", "faça um planejamento detalhado e compare estratégias passo a passo"


@pytest.mark.parametrize(("plano", "modelo"), [("haiku", "claude-haiku-5-5"), ("sonnet", "claude-sonnet-5-5"),
                                               ("opus", "claude-opus-5-5"), ("fable", "claude-fable-5-1")])
def test_plano_fixo_usa_o_modelo_do_plano(plano, modelo):
    for texto in (SIMPLES, COMPLEXA, "/fable " + COMPLEXA, "/haiku oi tudo bem com o plano?"):
        d = decidir(texto, BudgetState.NORMAL, DEFAULT_TIERS, PLANOS[plano])
        assert d.model == modelo, texto   # prefixo de camada não tira o aluno do plano que comprou


def test_router_escolhe_pela_complexidade():
    p = PLANOS["router"]
    assert decidir(SIMPLES, BudgetState.NORMAL, DEFAULT_TIERS, p).model == "claude-haiku-5-5"
    assert decidir(COMPLEXA, BudgetState.NORMAL, DEFAULT_TIERS, p).model == "claude-fable-5-1"
    assert decidir("/opus " + SIMPLES, BudgetState.NORMAL, DEFAULT_TIERS, p).model == "claude-haiku-5-5"


def test_modo_economia_desce_uma_camada_e_o_teto_pausa():
    eco = {k: decidir(COMPLEXA, BudgetState.ECONOMY, DEFAULT_TIERS, p) for k, p in PLANOS.items()}
    assert {k: d.model for k, d in eco.items()} == {
        "haiku": "claude-haiku-5-5", "sonnet": "claude-haiku-5-5", "opus": "claude-sonnet-5-5",
        "fable": "claude-opus-5-5", "router": "claude-opus-5-5"}
    assert all(d.effort == "low" for d in eco.values())
    assert decidir("pense bem " + SIMPLES, BudgetState.ECONOMY, DEFAULT_TIERS, PLANOS["router"]).route is Route.MEDIUM
    for p in PLANOS.values():
        assert decidir(COMPLEXA, BudgetState.CAP_REACHED, DEFAULT_TIERS, p).route is Route.LOCAL
    assert decidir("bom dia", BudgetState.NORMAL, DEFAULT_TIERS, PLANOS["fable"]).route is Route.LOCAL   # de graça


def test_plano_pelo_nome_ou_preco_e_teto():
    assert plano_jarvis("") is None and plano_jarvis(None) is None
    assert plano_jarvis("Opus").id == "opus" and plano_jarvis("R$ 75").id == "fable" and plano_jarvis("100").id == "router"
    with pytest.raises(ValueError, match="desconhecido"):
        plano_jarvis("premium")
    assert [p.preco_brl for p in PLANOS.values()] == [20, 35, 50, 75, 100]
    assert {k: p.teto_usd() for k, p in PLANOS.items()} == {
        "haiku": 1.82, "sonnet": 3.18, "opus": 4.55, "fable": 6.82, "router": 9.09}
    assert PLANOS["fable"].teto_usd(cambio=5.0, fracao=0.4) == 6.0


def test_instancia_do_aluno_tem_teto_ferramentas_e_coach(settings, monkeypatch, pasta):
    monkeypatch.setenv("JARVIS_TRILHUM_DIR", str(pasta))
    aluno = settings.model_copy(update={"plano_jarvis": "opus"})
    conv = build_conversation(aluno, claude_client=FakeAnthropic())
    assert conv.plano.id == "opus" and conv.ledger.budget == 4.55
    assert set(conv.tools) <= FERRAMENTAS_ALUNO and "ler_arquivo" not in conv.tools and "trilhum_agenda" in conv.tools
    assert conv.coach is not None
    barato = build_conversation(aluno.model_copy(update={"monthly_budget_usd": 2.0}), claude_client=FakeAnthropic())
    assert barato.ledger.budget == 2.0   # JARVIS_BUDGET_USD só baixa o teto do plano
    dono = build_conversation(settings, claude_client=FakeAnthropic())
    assert dono.plano is None and dono.coach is None and "ler_arquivo" in dono.tools


async def test_conversa_do_aluno_usa_o_plano_e_o_coach_uma_vez(settings):
    fake = FakeAnthropic()
    conv = build_conversation(settings.model_copy(update={"plano_jarvis": "sonnet"}), claude_client=fake)
    chamadas = []
    conv.coach = lambda: chamadas.append(1) or f"{MARCA} teste"
    for msg in ("/opus estou ansioso, me liga no (62) 99999-8888", "e agora, como sigo?"):
        [ev async for ev in conv.turn("aluno", msg)]
    assert [c["model"] for c in fake.calls] == ["claude-sonnet-5-5", "claude-sonnet-5-5"]
    assert len(chamadas) == 1   # a nota abre a conversa, não se repete a cada turno
    enviado = json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)
    assert enviado.count(MARCA) == 1 and "99999-8888" not in enviado and "(**) *****-****" in enviado


# ── 4. avisos pelo WhatsApp ──────────────────────────────────
AG = Agenda.model_validate(AGENDA)


def test_aviso_30_minutos_antes_no_fuso_de_sao_paulo():
    avisos = avisos_do_dia(AG, date(2026, 11, 3), set(), "rota40-oab-48")
    assert [a.bloco.id for a in avisos] == ["1-1t", "1-1q"]
    a = avisos[0]
    assert a.inicio == datetime(2026, 11, 3, 5, 0, tzinfo=FUSO_SP)
    assert a.quando == datetime(2026, 11, 3, 4, 30, tzinfo=FUSO_SP)
    assert a.quando.utcoffset() == timedelta(hours=-3)
    assert a.quando.astimezone(UTC) == datetime(2026, 11, 3, 7, 30, tzinfo=UTC)
    assert a.chave == "rota40-oab-48:2026-11-03:1-1t"
    assert a.texto() == "Em 30 minutos, às 05:00: Lei seca · Ética. EAOAB"


def test_aviso_pula_bloco_feito_prova_e_depois_da_data_alvo():
    assert [a.bloco.id for a in avisos_do_dia(AG, date(2026, 11, 3), {"1-1t"}, "p")] == ["1-1q"]
    assert avisos_do_dia(AG, date(2027, 1, 10), set(), "p") == []   # bloco sem duração (a prova), como no .ics
    assert avisos_do_dia(AG, date(2027, 1, 11), set(), "p") == []   # depois da data-alvo
    assert avisos_do_dia(AG, date(2026, 12, 25), set(), "p") == []  # fora do plano
    sab = avisos_do_dia(AG, date(2026, 11, 7), set(), "p", hora_padrao="06:00")
    assert [(a.bloco.id, f"{a.inicio:%H:%M}") for a in sab] == [("1-s", "06:00")]   # sem horário: o do cadastro
    assert avisos_do_dia(AG, date(2026, 11, 7), set(), "p") == []
    assert avisos_do_dia(AG, date(2026, 11, 3), set(), "p", antecedencia=timedelta(minutes=45))[0].texto() \
        .startswith("Em 45 minutos")


def test_aviso_no_feriado():
    avisos = avisos_do_dia(AG, date(2026, 11, 2), set(), "p")
    assert [a.feriado for a in avisos] == ["Finados", "Finados"]
    assert avisos[0].parametros() == ["05:00", "Lei seca · Ética", "EAOAB (feriado: Finados)"]
    assert avisos_do_dia(AG, date(2026, 11, 2), set(), "p", avisar_feriado=False) == []


def _agendador(pasta, tmp_path, agora, envio=None, destino=True, dados=None, **kw):
    dest = Destinatario.da_config("(62) 99999-8888", "2026-11-01T10:00:00-03:00") if destino else None
    return AgendadorAvisos(_trilhum(pasta, dados), envio or EnvioDryRun(), dest,
                           RegistroAvisos(tmp_path / "jarvis.db"), relogio=lambda: agora, **kw)


def test_agendador_manda_uma_vez_no_horario_de_sao_paulo(pasta, tmp_path):
    envio = EnvioDryRun()
    # 22:35 UTC = 19:35 em São Paulo, dentro dos 30 min antes do bloco das 20:00
    ag = _agendador(pasta, tmp_path, datetime(2026, 11, 3, 22, 35, tzinfo=UTC), envio)
    assert [a.bloco.id for a in ag.verificar()] == ["1-1q"]   # o 1-1t (05:00) já passou e está feito
    assert ag.verificar() == []                                # o registro impede o segundo envio
    assert envio.enviados[0][0] == NUMERO
    assert _agendador(pasta, tmp_path, datetime(2026, 11, 3, 22, 35, tzinfo=UTC)).verificar() == []   # reinício


def test_agendador_respeita_bloco_feito_inicio_e_consentimento(pasta, tmp_path):
    cedo = datetime(2026, 11, 3, 7, 35, tzinfo=UTC)   # 04:35 em São Paulo: aviso do bloco das 05:00
    assert _agendador(pasta, tmp_path, cedo).verificar() == []   # 1-1t já marcado como feito no Trilhum
    sem_feito = {**DADOS_APP, "feito": {}}
    assert [a.bloco.id for a in _agendador(pasta, tmp_path, cedo, dados=sem_feito).verificar()] == ["1-1t"]
    comecou = datetime(2026, 11, 3, 23, 5, tzinfo=UTC)   # 20:05: o bloco começou, não avisa mais
    assert _agendador(pasta, tmp_path, comecou, dados=sem_feito).verificar() == []
    assert _agendador(pasta, tmp_path, cedo, destino=False, dados=sem_feito).verificar() == []
    feriado = datetime(2026, 11, 2, 22, 45, tzinfo=UTC)
    assert _agendador(pasta, tmp_path, feriado, avisar_feriado=False).verificar() == []
    assert [a.feriado for a in _agendador(pasta, tmp_path, feriado).verificar()] == ["Finados"]


def test_destinatario_e_numero():
    assert normalizar_whats("(62) 99999-8888") == NUMERO and normalizar_whats("+55 62 3333-4444") == "556233334444"
    assert normalizar_whats("123") is None
    assert Destinatario.da_config("(62) 99999-8888", "") is None          # sem consentimento, nenhum aviso
    assert Destinatario.da_config("999", "2026-11-01") is None
    d = Destinatario.da_config("62999998888", "2026-11-01T10:00:00")
    assert NUMERO not in repr(d)
    assert mascarar_numero(NUMERO) == "5562*****8888"


class MetaFalsa:
    def __init__(self, status=200):
        self.status, self.pedidos = status, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Template name does not exist"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})


def test_envio_pela_meta_cloud_api_com_modelo(pasta, tmp_path):
    meta = MetaFalsa()
    envio = EnvioMetaCloud("token-meta", "123456789012345", cliente=httpx.Client(transport=httpx.MockTransport(meta)))
    ag = _agendador(pasta, tmp_path, datetime(2026, 11, 3, 22, 35, tzinfo=UTC), envio)
    assert len(ag.verificar()) == 1
    req = meta.pedidos[0]
    assert str(req.url) == "https://graph.facebook.com/v23.0/123456789012345/messages"
    assert req.headers["authorization"] == "Bearer token-meta"
    corpo = json.loads(req.content)
    assert corpo["to"] == NUMERO and corpo["type"] == "template"
    assert corpo["template"]["name"] == "aviso_bloco_estudo" and corpo["template"]["language"] == {"code": "pt_BR"}
    assert [p["text"] for p in corpo["template"]["components"][0]["parameters"]] == \
        ["20:00", "Questões · Ética", "EAOAB"]


def test_falha_na_meta_libera_para_tentar_de_novo(pasta, tmp_path):
    meta = MetaFalsa(status=400)
    envio = EnvioMetaCloud("token-meta", "123456789012345", cliente=httpx.Client(transport=httpx.MockTransport(meta)))
    ag = _agendador(pasta, tmp_path, datetime(2026, 11, 3, 22, 35, tzinfo=UTC), envio)
    assert ag.verificar() == [] and ag.verificar() == []
    assert len(meta.pedidos) == 2   # não ficou marcado como enviado
    with pytest.raises(AvisoErro, match="HTTP 400") as e:
        envio.enviar(NUMERO, avisos_do_dia(AG, date(2026, 11, 3), set(), "p")[0])
    assert "token-meta" not in str(e.value) and NUMERO not in str(e.value)
    with pytest.raises(ValueError):
        EnvioMetaCloud("t", "../outro")


# ── 5. número e consentimento do Firestore do Trilhum ────────
class FirestoreFalso:
    """No lugar do Node com o firebase-admin: guarda as chamadas e devolve o registro do assinante."""

    def __init__(self, registro=None, falha=False):
        self.chamadas, self.falha = [], falha
        self.registro = registro if registro is not None else {
            "existe": True, "plano": "ultra", "whatsapp": NUMERO, "whatsappConsentimento": "2026-11-01T13:00:00.000Z"}

    def __call__(self, argv, timeout_s, entrada, ambiente):
        from jarvis.estudos.trilhum import TrilhumErro

        self.chamadas.append((argv, json.loads(entrada), ambiente))
        if self.falha:
            raise TrilhumErro("não li o assinante no Firestore: PERMISSION_DENIED")
        return json.dumps(self.registro)


def _leitor(tmp_path, fs, emulador="127.0.0.1:8085", **kw):
    from jarvis.estudos.assinante import LeitorAssinante

    (tmp_path / "nm" / "firebase-admin").mkdir(parents=True, exist_ok=True)
    return LeitorAssinante("AbC123uid", "demo-trilhum", tmp_path / "nm", emulador=emulador, node="node",
                           executar=fs, **kw)


def test_leitor_do_firestore_le_numero_e_consentimento(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "nao-pode-vazar.json")
    fs = FirestoreFalso()
    agora = [0.0]
    leitor = _leitor(tmp_path, fs, relogio=lambda: agora[0])
    d = leitor.ler()
    assert d.whatsapp == NUMERO and d.whatsappConsentimento == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
    argv, entrada, ambiente = fs.chamadas[0]
    assert argv[1].endswith("assinante_trilhum.mjs") and entrada == {"uid": "AbC123uid", "projeto": "demo-trilhum"}
    assert ambiente["FIRESTORE_EMULATOR_HOST"] == "127.0.0.1:8085" and "GOOGLE_APPLICATION_CREDENTIALS" not in ambiente
    leitor.ler()
    assert len(fs.chamadas) == 1          # cache
    agora[0] = 301.0
    leitor.ler()
    assert len(fs.chamadas) == 2          # relido: "Parar avisos" vale em minutos


@pytest.mark.parametrize("registro", [
    {"existe": False},
    {"existe": True, "plano": "basica", "whatsapp": NUMERO, "whatsappConsentimento": "2026-11-01T13:00:00Z"},
    {"existe": True, "plano": "ultra", "whatsapp": None, "whatsappConsentimento": None},   # parou os avisos
    {"existe": True, "plano": "ultra", "whatsapp": NUMERO, "whatsappConsentimento": None},
])
def test_leitor_fecha_sem_ultra_numero_ou_consentimento(tmp_path, registro):
    assert _leitor(tmp_path, FirestoreFalso(registro)).ler() is None


def test_leitor_fecha_na_falha_e_valida_a_configuracao(tmp_path):
    from jarvis.estudos.assinante import LeitorAssinante
    from jarvis.estudos.trilhum import TrilhumErro

    assert _leitor(tmp_path, FirestoreFalso(falha=True))() is None   # para o agendador: falha = nenhum aviso
    with pytest.raises(TrilhumErro, match="PERMISSION_DENIED"):
        _leitor(tmp_path, FirestoreFalso(falha=True)).ler()
    nm = tmp_path / "nm"
    casos = {"uid/../x": "JARVIS_TRILHUM_UID", "": "JARVIS_TRILHUM_UID"}
    for uid, msg in casos.items():
        assert msg in LeitorAssinante(uid, "demo-trilhum", nm, emulador="127.0.0.1:8085", node="node").problema()
    assert "local" in LeitorAssinante("u1", "demo-trilhum", nm, emulador="10.0.0.5:8085", node="node").problema()
    assert "conta de serviço" in LeitorAssinante("u1", "trilha-estudos-2026", nm, node="node").problema()
    cred = tmp_path / "conta.json"
    cred.write_text("{}", encoding="utf-8")
    fs = FirestoreFalso()
    LeitorAssinante("u1", "trilha-estudos-2026", nm, credenciais=str(cred), node="node", executar=fs).ler()
    amb = fs.chamadas[0][2]
    assert amb["GOOGLE_APPLICATION_CREDENTIALS"] == str(cred) and "FIRESTORE_EMULATOR_HOST" not in amb


def test_agendador_le_o_firestore_so_quando_ha_aviso(pasta, tmp_path):
    fs = FirestoreFalso()
    leitor = _leitor(tmp_path, fs)
    vazio = _agendador(pasta, tmp_path, datetime(2026, 11, 3, 15, 0, tzinfo=UTC))   # 12:00 em São Paulo
    vazio.destino = leitor
    assert vazio.verificar() == [] and fs.chamadas == []   # sem aviso vencido, o Node nem roda
    ag = _agendador(pasta, tmp_path, datetime(2026, 11, 3, 22, 35, tzinfo=UTC))
    ag.destino = leitor
    assert [a.bloco.id for a in ag.verificar()] == ["1-1q"] and len(fs.chamadas) == 1
    parou = _agendador(pasta, tmp_path / "outro", datetime(2026, 11, 3, 22, 35, tzinfo=UTC))
    parou.destino = _leitor(tmp_path, FirestoreFalso({"existe": True, "plano": "ultra", "whatsapp": None}))
    assert parou.verificar() == []


def test_montar_usa_o_firestore_quando_ha_uid(settings, monkeypatch, pasta):
    from jarvis.estudos.assinante import LeitorAssinante
    from jarvis.estudos.avisos import destino

    monkeypatch.setenv("JARVIS_WHATSAPP_NUMERO", "(62) 99999-8888")
    monkeypatch.setenv("JARVIS_WHATSAPP_CONSENTIMENTO", "2026-11-01")
    t = _trilhum(pasta)
    assert isinstance(destino(settings, t), Destinatario)
    monkeypatch.setenv("JARVIS_TRILHUM_UID", "AbC123uid")
    leitor = destino(settings, t)
    assert isinstance(leitor, LeitorAssinante) and leitor.projeto == "trilha-estudos-2026"
    assert leitor.modulos == pasta / "functions" / "node_modules"
