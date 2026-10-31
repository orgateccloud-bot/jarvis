"""Etapa 3 na API: toda rota exige o token (teste estrutural), /agentes vem antes do mount do HUD, a configuração
versiona, tarefa demorada responde 202 e a verificação do selo confere."""

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from jarvis.api.server import build_conversation, create_app
from jarvis.config import Settings
from tests.conftest import FakeAnthropic, FakeStream, text_turn

AUTH = {"Authorization": "Bearer token-de-teste"}
FIXTURE = Path(__file__).parent / "fixtures" / "agentes" / "extrato.csv"
# Rota pública de propósito (a página do HUD e a documentação não entram no OpenAPI)
PUBLICAS = {"/health"}
EXEMPLOS = {"agente_id": "tributario", "tarefa_id": "0123456789abcdef", "session_id": "hud",
            "approval_id": "x"}
CONSULTA = {"resposta": "Cinco anos.", "resumo_voz": "Cinco anos.", "fontes_usadas": [], "dualidade": None,
            "nao_verificado": []}


class _FakeDemorado(FakeAnthropic):
    def _stream(self, **kwargs):
        stream = super()._stream(**kwargs)

        class Demorado(FakeStream):
            async def __aenter__(self):
                import asyncio

                await asyncio.sleep(0.3)
                return self

        return Demorado(stream.owner, stream.kwargs, stream.turn)


def _app(settings, hud_dir=None, agente=None, **kw):
    conv = build_conversation(settings, claude_client=FakeAnthropic(script=[text_turn("Às ordens.")]),
                              agent_client=agente or FakeAnthropic(script=[text_turn(json.dumps(CONSULTA))]))
    extra = {"hud_dir": hud_dir} if hud_dir else {}
    return create_app(settings, conversation=conv, proactive=False, **extra, **kw), conv


def test_todas_rotas_exigem_token(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_VOZ_LOCAL", "1")           # inclui as rotas da voz na varredura
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    com_voz = Settings(data_dir=settings.data_dir, monthly_budget_usd=15.0, pii_salt="salt-teste")
    app, _ = _app(com_voz, hud_dir=dist, iniciar_voz=False)
    caminhos = app.openapi()["paths"]
    assert any(c.startswith("/agentes") for c in caminhos) and any(c.startswith("/voz") for c in caminhos)
    client = TestClient(app)
    sem_token = []
    for caminho, metodos in caminhos.items():
        if caminho in PUBLICAS:
            continue
        url = caminho.format(**EXEMPLOS)
        for metodo in metodos:
            if client.request(metodo.upper(), url, json={}).status_code != 401:
                sem_token.append(f"{metodo.upper()} {caminho}")
    assert sem_token == [], f"rotas sem o token da API: {sem_token}"
    assert len(caminhos) > 15


def test_agentes_antes_do_mount(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    app, _ = _app(settings, hud_dir=dist)
    assert isinstance(app.routes[-1], Mount)                  # o HUD pega só o que sobrar
    client = TestClient(app)
    r = client.get("/agentes", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.json()[0]["id"] == "tributario" and r.json()[0]["estado"] == "ocioso"
    assert client.get("/agentes/tributario", headers=AUTH).json()["estado"]["versao_config"] == 1


def test_post_config_versiona(settings):
    app, _ = _app(settings)
    client = TestClient(app)
    r = client.post("/agentes/tributario/config", headers=AUTH, json={"teto_mensal_usd": 10, "motivo": "teste"})
    assert r.json() == {"agente": "tributario", "versao": 2, "mudou": {"teto_mensal_usd": {"de": 30.0, "para": 10.0}}}
    assert client.post("/agentes/tributario/config", headers=AUTH, json={"teto_mensal_usd": 10}).status_code == 422
    assert client.post("/agentes/tributario/config/reverter", headers=AUTH,
                       json={"versao": 1, "motivo": "voltar"}).json()["versao"] == 3
    assert client.post("/agentes/tributario/config/reverter", headers=AUTH,
                       json={"versao": 9, "motivo": "não existe"}).status_code == 404
    detalhe = client.get("/agentes/tributario", headers=AUTH).json()
    assert [v["versao"] for v in detalhe["versoes"]] == [1, 2, 3] and detalhe["estado"]["config"]["teto_mensal_usd"] == 30
    assert client.post("/agentes/tributario/pausar", headers=AUTH).json()["pausado"] is True
    assert client.get("/agentes/tributario", headers=AUTH).json()["estado"]["estado"] == "pausado"
    assert client.post("/agentes/tributario/retomar", headers=AUTH).json()["pausado"] is False
    assert client.get("/agentes/inexistente", headers=AUTH).status_code == 404
    assert client.get("/agentes/Nao-Vale!", headers=AUTH).status_code == 422


def test_tarefa_com_csv_e_verificar(settings):
    destino = settings.tool_roots()[0] / "extrato.csv"
    shutil.copy(FIXTURE, destino)
    app, _ = _app(settings)
    client = TestClient(app)
    r = client.post("/agentes/tributario/tarefas", headers=AUTH,
                    json={"tarefa": "analisar_lancamentos", "arquivo": str(destino)})
    assert r.status_code == 200 and r.json()["estado"] == "concluida" and r.json()["saida"]["risco"]["indice"] == 66.0
    tarefa_id = r.json()["tarefa_id"]
    assert client.get(f"/agentes/tarefas/{tarefa_id}", headers=AUTH).json()["audit_hash"] == r.json()["audit_hash"]
    assert client.get(f"/agentes/tarefas/{tarefa_id}/verificar", headers=AUTH).json() == {
        "tarefa_id": tarefa_id, "conteudo_ok": True, "na_cadeia": True, "cadeia_integra": True}
    assert client.get("/audit/verify", headers=AUTH).json() == {"integra": True}
    fora = client.post("/agentes/tributario/tarefas", headers=AUTH,
                       json={"tarefa": "analisar_lancamentos", "arquivo": str(FIXTURE)})
    assert fora.status_code == 400 and "fora das pastas permitidas" in fora.json()["detail"]
    assert client.get("/agentes/tarefas/fedcba9876543210", headers=AUTH).status_code == 404


def test_tarefa_202_e_consulta(settings):
    app, conv = _app(settings, agente=_FakeDemorado(script=[text_turn(json.dumps(CONSULTA))]))
    conv.tool_ctx.agentes.espera_s = 0.05
    with TestClient(app) as client:          # o loop do app segue vivo entre as requisições
        r = client.post("/agentes/tributario/tarefas", headers=AUTH, json={"tarefa": "consultar", "pedido": "prazo?"})
        assert r.status_code == 202 and r.json()["estado"] == "em_andamento"
        url = f"/agentes/tarefas/{r.json()['tarefa_id']}"
        for _ in range(50):
            final = client.get(url, headers=AUTH).json()
            if final["estado"] != "em_andamento":
                break
            time.sleep(0.05)
        assert final["estado"] == "concluida" and final["saida"]["resposta"] == "Cinco anos."
        custos = client.get("/costs", headers=AUTH).json()
        assert custos["por_origem"]["agentes"] > 0


def test_flag_desligada_sem_rotas(settings, monkeypatch):
    monkeypatch.setenv("JARVIS_AGENTES", "")
    desligado = Settings(data_dir=settings.data_dir, monthly_budget_usd=15.0, pii_salt="salt-teste")
    app, _ = _app(desligado)
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/agentes")]
    assert TestClient(app).get("/agentes", headers=AUTH).status_code == 404


@pytest.mark.parametrize("corpo", [{"tarefa": "consultar", "pedido": "x", "executar_como": "root"},
                                   {"tarefa": "Consultar!"}])
def test_pedido_invalido(settings, corpo):
    app, _ = _app(settings)
    assert TestClient(app).post("/agentes/tributario/tarefas", headers=AUTH, json=corpo).status_code == 422
