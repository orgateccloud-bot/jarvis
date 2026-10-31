"""Etapa 3, ligação ao cérebro: o JARVIS delega pela conversa (a mesma da voz), com dois Claudes falsos — um do
JARVIS e um do agente —, espera limitada que libera a trava da sessão, aprovação com diff e a flag que desliga tudo."""

import asyncio
import inspect
import json

from jarvis.api.server import build_conversation
from jarvis.config import Settings
from jarvis.core.contracts import BudgetState, Route
from jarvis.core.router import decide
from tests.conftest import FakeAnthropic, FakeStream, text_turn, tool_turn
from tests.test_tools import run_turn, tool_results

CONSULTA = {"resposta": "Cinco anos, pelo CTN.", "resumo_voz": "Cinco anos.", "fontes_usadas": [],
            "dualidade": None, "nao_verificado": ["base local vazia"]}
PEDIDO = "Jarvis, pede ao agente tributário o prazo de decadência do crédito tributário"


def _conv(settings, jarvis_script, agente_script=(CONSULTA,), agente=None):
    fake_j = FakeAnthropic(script=jarvis_script)
    fake_a = agente or FakeAnthropic(script=[text_turn(json.dumps(r, ensure_ascii=False)) for r in agente_script])
    conv = build_conversation(settings, claude_client=fake_j, agent_client=fake_a)
    eventos = []
    conv.tool_ctx.agentes.publicar = eventos.append
    return conv, fake_j, fake_a, eventos


async def test_ponta_a_ponta_dois_fakes(settings):
    conv, fake_j, fake_a, eventos = _conv(settings, [
        tool_turn("comandar_agente", {"agente": "tributario", "tarefa": "consultar", "pedido": "prazo de decadência"}),
        text_turn("O agente tributário diz: cinco anos."),
    ])
    evs = await run_turn(conv, PEDIDO, session="hud")
    rota = evs[0].data
    assert (rota["rota"], rota["modelo"], rota["effort"]) == ("complexa", "claude-opus-5-5", "low")
    assert "delegação" in rota["motivo"]
    primeira = fake_j.calls[0]
    assert "comandar_agente" in primeira["system"] and "agentes_status" in primeira["system"]
    assert "[delegação ao agente tributario]" in primeira["messages"][-1]["content"]
    resultado = json.loads(tool_results(fake_j.calls[1])[0]["content"])
    assert resultado["estado"] == "concluida" and resultado["resposta"] == "Cinco anos, pelo CTN."
    assert resultado["aviso"].startswith("Conteúdo produzido pelo agente")
    assert len(fake_a.calls) == 1 and "agente tributário do JARVIS" in fake_a.calls[0]["system"]
    assert [e.data["nome"] for e in evs if e.type == "tool"] == ["comandar_agente", "comandar_agente"]
    assert conv.audit.verify() and conv.ledger.summary()["por_origem"]["agentes"] > 0
    assert eventos == []                                  # terminou dentro do turno: o JARVIS conta


class _FakeLento(FakeAnthropic):
    """O Claude do agente só responde quando o portão abre."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.portao = asyncio.Event()

    def _stream(self, **kwargs):
        stream = super()._stream(**kwargs)
        portao = self.portao

        class Lento(FakeStream):
            async def __aenter__(self):
                await portao.wait()
                return self

        return Lento(stream.owner, stream.kwargs, stream.turn)


async def test_espera_limitada_libera_trava(settings):
    lento = _FakeLento(script=[text_turn(json.dumps(CONSULTA))])
    conv, fake_j, _, eventos = _conv(settings, [
        tool_turn("comandar_agente", {"agente": "tributario", "tarefa": "consultar", "pedido": "prazo?"}),
        text_turn("O agente começou; aviso quando terminar."),
        tool_turn("resultado_agente", {}, tool_id="toolu_2"),
        text_turn("Cinco anos."),
    ], agente=lento)
    orq = conv.tool_ctx.agentes
    orq.espera_s = 0.05
    await run_turn(conv, PEDIDO, session="hud")
    em_andamento = json.loads(tool_results(fake_j.calls[1])[0]["content"])
    assert em_andamento["estado"] == "em_andamento" and "Não consulte" in em_andamento["proximo_passo"]
    assert not conv._locks["hud"].locked()                       # a sessão (e o "Ok Jarvis") ficou livre
    assert await asyncio.wait_for(conv.nova_conversa("outra"), 1) is False
    lento.portao.set()
    await asyncio.gather(*orq._tarefas)
    assert eventos[-1].kind == "agente" and eventos[-1].falar is True
    assert eventos[-1].texto.startswith("O agente tributário concluiu: consultar.")
    await run_turn(conv, "e o resultado?", session="hud")
    final = json.loads(tool_results(fake_j.calls[3])[-1]["content"])
    assert final["estado"] == "concluida" and final["tarefa_id"] == em_andamento["tarefa_id"]


async def test_gerenciar_aprovacao_com_diff(settings):
    turno = tool_turn("gerenciar_agente", {"agente": "tributario", "acao": "atualizar", "teto_mensal_usd": 5,
                                           "motivo": "limitar o gasto"})
    conv, fake_j, _, eventos = _conv(settings, [turno, text_turn("Feito.")])
    vistos = []

    def negar(c, d):
        vistos.append(d)
        c.approvals.resolve(d["id"], False)

    await run_turn(conv, "baixa o teto do agente tributário para 5 dólares", on_approval=negar)
    assert vistos[0]["detalhes"]["mudancas"] == {"teto_mensal_usd": {"de": 30.0, "para": 5.0}}
    assert vistos[0]["detalhes"]["versao_atual"] == 1
    assert conv.tool_ctx.agentes.observar("tributario").versao_config == 1    # negado: nada muda
    fake_j.script = [turno, text_turn("Feito.")]
    fake_j.calls.clear()
    await run_turn(conv, "baixa o teto", on_approval=lambda c, d: c.approvals.resolve(d["id"], True))
    estado = conv.tool_ctx.agentes.observar("tributario")
    assert estado.versao_config == 2 and estado.config.teto_mensal_usd == 5
    assert eventos[-1].texto.startswith("Configuração do agente tributário atualizada para a v2")


async def test_csv_confinado_e_analise_sem_claude(settings, tmp_path):
    permitido = settings.tool_roots()[0] / "extrato.csv"
    permitido.write_text("data;valor;memo;contraparte\n01/01/2026;-10,00;TARIFA;BANCO\n", encoding="utf-8")
    fora = tmp_path / "fora.csv"
    fora.write_text("data;valor\n01/01/2026;1\n", encoding="utf-8")
    conv, fake_j, fake_a, _ = _conv(settings, [
        tool_turn("comandar_agente", {"agente": "tributario", "tarefa": "analisar_lancamentos", "arquivo": str(fora)}),
        tool_turn("comandar_agente", {"agente": "tributario", "tarefa": "analisar_lancamentos",
                                      "arquivo": str(permitido)}, tool_id="toolu_2"),
        text_turn("Pronto."),
    ])
    await run_turn(conv, "pede ao agente tributário para analisar o extrato")
    recusa = tool_results(fake_j.calls[1])[0]
    assert recusa["is_error"] and "fora das pastas permitidas" in recusa["content"]
    ok = json.loads(tool_results(fake_j.calls[2])[-1]["content"])
    assert ok["estado"] == "concluida" and ok["indice_risco_pct"] == 5.0 and fake_a.calls == []


def test_delegacao_opus_low():
    ativos = {"tributario"}
    d = decide("Jarvis, pede ao agente tributário um laudo da empresa", BudgetState.NORMAL, agentes=ativos)
    assert (d.route, d.model, d.effort, d.delegar) == (Route.COMPLEX, "claude-opus-5-5", "low", "tributario")
    sem = decide("Jarvis, pede ao agente tributário um laudo da empresa", BudgetState.NORMAL)
    assert sem.delegar is None and sem.route is Route.FABLE       # sem agente ativo: segue o roteamento normal
    economia = decide("pede ao agente tributário a análise", BudgetState.ECONOMY, agentes=ativos)
    assert (economia.route, economia.effort) == (Route.COMPLEX, "low")   # o usuário quer Opus mesmo na economia
    assert decide("pede ao agente tributário", BudgetState.CAP_REACHED, agentes=ativos).route is Route.LOCAL
    forcado = decide("/opus pede ao agente tributário um parecer", BudgetState.NORMAL, agentes=ativos)
    assert forcado.route is Route.COMPLEX and forcado.delegar == "tributario"


def test_delegacao_a_gente():
    ativos = {"tributario"}
    assert decide("pede pra a gente tributária comparar 2027", BudgetState.NORMAL, agentes=ativos).delegar == \
        "tributario"
    assert decide("a gente vai ao cinema hoje?", BudgetState.NORMAL, agentes=ativos).delegar is None


def test_tool_async_e_sync(settings):
    conv = build_conversation(settings, claude_client=FakeAnthropic())
    for nome, tool in conv.tools.items():
        assert tool.builtin or inspect.iscoroutinefunction(tool.run) == tool.assincrona, nome
    assert conv.tools["comandar_agente"].assincrona and conv.tools["gerenciar_agente"].needs_approval
    assert not conv.tools["agentes_status"].needs_approval


async def test_flag_desligada_sem_ferramentas(settings, monkeypatch):
    monkeypatch.setenv("JARVIS_AGENTES", "0")
    desligado = Settings(data_dir=settings.data_dir, monthly_budget_usd=15.0, pii_salt="salt-teste")
    assert desligado.agentes == []
    fake = FakeAnthropic()
    conv = build_conversation(desligado, claude_client=fake)
    assert conv.tool_ctx.agentes is None and not any("agente" in n for n in conv.tools)
    evs = await run_turn(conv, PEDIDO)
    assert "delegação" not in evs[0].data["motivo"]
    assert "[delegação" not in json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
