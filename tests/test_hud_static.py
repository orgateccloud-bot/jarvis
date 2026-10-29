"""HUD buildado servido pela API: token só para Host local, rotas da API intactas, dist/ ausente não quebra."""

import json

import pytest
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from tests.conftest import FakeAnthropic, text_turn

AUTH = {"Authorization": "Bearer token-de-teste"}
INDEX = ('<!doctype html><html><head><title>JARVIS</title></head>'
         '<body><script type="module" src="/assets/app.js"></script></body></html>')


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX, encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log('hud')", encoding="utf-8")
    (d / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return d


def _client(settings, hud_dir, base_url="http://127.0.0.1:8000"):
    fake = FakeAnthropic(script=[text_turn("Às ordens.")])
    conv = build_conversation(settings, claude_client=fake)
    app = create_app(settings, conversation=conv, proactive=False, hud_dir=hud_dir)
    return TestClient(app, base_url=base_url)


@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"])
def test_hud_aberto_por_endereco_local_recebe_o_token(settings, dist, base):
    r = _client(settings, dist, base).get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert f"window.__JARVIS_TOKEN__={json.dumps('token-de-teste')}" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "token-de-teste" not in (dist / "index.html").read_text(encoding="utf-8")   # o build em disco não muda


def test_outro_host_recebe_a_pagina_sem_token(settings, dist):
    # site que aponta o próprio domínio para 127.0.0.1 (DNS rebinding) chega com outro Host
    r = _client(settings, dist, "http://ataque.exemplo:8000").get("/")
    assert r.status_code == 200 and "token-de-teste" not in r.text and "__JARVIS_TOKEN__" not in r.text


def test_arquivos_do_build_e_rotas_da_api_convivem(settings, dist):
    c = _client(settings, dist)
    assert c.get("/assets/app.js").text == "console.log('hud')"
    assert c.get("/favicon.svg").status_code == 200
    assert c.get("/health").json()["status"] == "online"           # rota da API vence o mount em "/"
    assert c.get("/costs").status_code == 401                      # e continua exigindo token
    r = c.post("/chat/stream", json={"message": "me conta uma curiosidade"}, headers=AUTH)
    assert r.status_code == 200 and "Às ordens." in r.text
    assert c.get("/nao-existe.js").status_code == 404


def test_sem_build_a_api_sobe_normalmente(settings, tmp_path):
    c = _client(settings, tmp_path / "sem-dist")
    assert c.get("/health").status_code == 200
    assert c.get("/").status_code == 404
