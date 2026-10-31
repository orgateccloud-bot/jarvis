"""Painel fiscal na API: token em todas as rotas, formato das respostas, cliente no card e atualização a pedido."""

from datetime import datetime

from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.painel.clientes.banco import BancoClientes
from jarvis.painel.clientes.servico import ServicoClientes
from jarvis.painel.coleta import ArmazemPainel, ServicoColeta
from jarvis.painel.fontes import FonteConfig
from tests.conftest import FakeAnthropic
from tests.test_painel_fontes import fetch_de, ler

AUTH = {"Authorization": "Bearer token-de-teste"}
TO = "https://www.to.gov.br/sefaz/noticias"
CLIENTE = {"documento": "11.222.333/0001-81", "razao_social": "Alfa Comércio Ltda", "regime_tributario": "simples",
           "obrigacoes": ["DAS"], "certidoes": [{"tipo": "CND federal", "situacao": "negativa", "validade": "2026-12-01"}],
           "contratos": [{"descricao": "Assessoria", "honorario_mensal": 900, "vencimento_dia": 10}],
           "pendencias": [{"descricao": "Enviar notas de outubro", "prazo": "2026-11-05"}]}


def _rotas(rotas):
    """Rotas da app, abrindo os roteadores incluídos (o FastAPI 0.161 os embrulha em _IncludedRouter)."""
    for r in rotas:
        if hasattr(r, "original_router"):
            yield from _rotas(r.original_router.routes)
        else:
            yield r


def _app(settings, tmp_path, fetch=None):
    def agora():
        return datetime(2026, 10, 31, 9, 0)

    coleta = ServicoColeta(ArmazemPainel(tmp_path / "p.db"),
                           [FonteConfig(id="sefaz_to", tipo="sefaz_to", nome="SEFAZ-TO", url=TO)],
                           fetch=fetch or fetch_de({TO: ler("sefaz_to_noticias.html")}), relogio=agora)
    clientes = ServicoClientes(BancoClientes(tmp_path / "p.db"), [], relogio=agora)
    conv = build_conversation(settings, claude_client=FakeAnthropic())
    app = create_app(settings, conversation=conv, proactive=False, iniciar_voz=False,
                     painel_servicos=(coleta, clientes), iniciar_painel=False)
    return TestClient(app), coleta


def test_todas_as_rotas_do_painel_exigem_token(settings, tmp_path):
    client, _ = _app(settings, tmp_path)
    rotas = [(m, r.path) for r in _rotas(client.app.routes) if getattr(r, "path", "").startswith("/painel")
             for m in r.methods]
    assert len(rotas) == 5
    for metodo, caminho in rotas:
        resp = client.request(metodo, caminho.replace("{cliente_id}", "1"), json={})
        assert resp.status_code == 401, (metodo, caminho)


def test_card_tributario_com_e_sem_cliente(settings, tmp_path):
    client, coleta = _app(settings, tmp_path)
    coleta.coletar()
    sem = client.get("/painel/tributario", headers=AUTH).json()
    assert set(sem["grupos"]) == {"prazos", "legislacao", "situacao", "interno"}
    assert sem["grupos"]["legislacao"][0]["fonte_url"].startswith("https://www.to.gov.br/")
    assert sem["atualizado_em"] == "2026-10-31T09:00:00" and sem["fontes"][0]["ok"] is True

    cid = client.post("/painel/clientes", headers=AUTH, json=CLIENTE).json()["id"]
    assert [c["nome"] for c in client.get("/painel/clientes", headers=AUTH).json()] == ["Alfa Comércio Ltda"]
    com = client.get(f"/painel/tributario?cliente={cid}", headers=AUTH).json()
    assert com["cliente_id"] == cid
    assert {i["titulo"] for i in com["grupos"]["situacao"]} == {"Regime tributário: simples", "CND federal: negativa"}
    interno = com["grupos"]["interno"]
    assert all(i["origem"] == "interna" and i["fonte_nome"] == "banco do JARVIS" for i in interno)
    assert client.get("/painel/tributario?cliente=999", headers=AUTH).status_code == 404


def test_detalhe_do_cliente_traz_a_fonte_de_cada_campo(settings, tmp_path):
    client, _ = _app(settings, tmp_path)
    cid = client.post("/painel/clientes", headers=AUTH, json=CLIENTE).json()["id"]
    d = client.get(f"/painel/clientes/{cid}", headers=AUTH).json()
    assert d["campos"]["razao_social"] == {"valor": "Alfa Comércio Ltda", "fonte": "banco",
                                           "fonte_nome": "banco do JARVIS", "atualizado_em": d["campos"]["razao_social"]["atualizado_em"],
                                           "antigo": False}
    assert d["campos"]["documento"]["valor"] == "11222333000181"
    assert client.post("/painel/clientes", headers=AUTH, json={**CLIENTE, "documento": "123"}).status_code == 422


def test_atualizar_a_pedido_e_fonte_fora_do_ar_nao_quebra_o_card(settings, tmp_path):
    rede = {TO: ler("sefaz_to_noticias.html")}
    client, _ = _app(settings, tmp_path, fetch=lambda u: fetch_de(rede)(u))
    status = client.post("/painel/atualizar", headers=AUTH).json()
    assert status[0]["ok"] is True
    rede.clear()                                          # a fonte cai
    status = client.post("/painel/atualizar", headers=AUTH).json()
    assert status[0]["ok"] is False and status[0]["erro"]
    card = client.get("/painel/tributario", headers=AUTH).json()
    assert card["grupos"]["legislacao"]                   # os últimos dados válidos continuam
    assert card["fontes"][0]["ok"] is False


def test_painel_desligado_nao_tem_rotas(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PAINEL", "0")
    from jarvis.config import Settings

    s = Settings(data_dir=settings.data_dir, pii_salt="x")
    app = create_app(s, conversation=build_conversation(s, claude_client=FakeAnthropic()), proactive=False,
                     iniciar_voz=False)
    assert not [r for r in _rotas(app.routes) if getattr(r, "path", "").startswith("/painel")]
