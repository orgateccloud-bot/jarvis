"""Fase 2c na API: a flag desligada não muda nada; ligada, o dono do microfone (Decisão A), os comandos do HUD,
a nova conversa e a supervisão do processo de voz. Sem Claude e sem processo de verdade."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from jarvis.api.server import build_conversation, create_app
from jarvis.api.voz import CARGA_S, CONCESSAO_HUD_S, ESPERAS_S, FALHAS_MAX, RETOMAR_S, EstadoVoz, Supervisor
from tests.conftest import FakeAnthropic

AUTH = {"Authorization": "Bearer token-de-teste"}


def _app(settings, voz_local):
    s = settings.model_copy(update={"voz_local": voz_local})
    conv = build_conversation(s, claude_client=FakeAnthropic())
    return TestClient(create_app(s, conversation=conv, proactive=False, iniciar_voz=False)), conv


def test_flag_desligada_nao_cria_rotas_nem_processo(settings):
    client, _ = _app(settings, voz_local=False)
    for metodo, url in [("get", "/voz"), ("post", "/voz/estado"), ("post", "/voz/dono"), ("post", "/voz/comando"),
                        ("post", "/sessions/hud/nova")]:
        assert getattr(client, metodo)(url, headers=AUTH).status_code in (404, 405), url
    assert not hasattr(client.app.state, "voz")
    assert client.get("/health").status_code == 200


def test_dono_do_microfone_batimento_e_comandos(settings):
    client, _ = _app(settings, voz_local=True)
    estado: EstadoVoz = client.app.state.voz
    agora = [100.0]
    estado.relogio = lambda: agora[0]

    assert client.post("/voz/estado", json={"estado": "ouvindo"}).status_code == 401   # exige o token
    assert client.get("/voz", headers=AUTH).json()["estado"] == "parado"                 # sem batimento ainda
    assert client.post("/voz/estado", json={"estado": "ouvindo"}, headers=AUTH).json() == {
        "dono": "servico", "comandos": []}
    assert client.get("/voz", headers=AUTH).json()["estado"] == "ouvindo"

    client.post("/voz/comando", json={"acao": "ouvir"}, headers=AUTH)
    client.post("/voz/comando", json={"acao": "mudo"}, headers=AUTH)
    assert client.post("/voz/comando", json={"acao": "apagar_tudo"}, headers=AUTH).status_code == 422
    r = client.post("/voz/estado", json={"estado": "ouvindo"}, headers=AUTH).json()
    assert r["comandos"] == ["ouvir", "mudo"]                      # entregues uma vez só
    assert client.post("/voz/estado", json={"estado": "ouvindo"}, headers=AUTH).json()["comandos"] == []

    # o HUD pede o microfone (serviço parado e o usuário clicou): concessão de 15 s, renovável
    assert client.post("/voz/dono", json={"dono": "hud"}, headers=AUTH).json() == {"dono": "hud"}
    assert client.post("/voz/estado", json={"estado": "repouso"}, headers=AUTH).json()["dono"] == "hud"
    agora[0] += CONCESSAO_HUD_S + 0.1                                # o HUD fechou ou travou: venceu
    assert client.post("/voz/estado", json={"estado": "repouso"}, headers=AUTH).json()["dono"] == "servico"
    client.post("/voz/dono", json={"dono": "hud"}, headers=AUTH)
    assert client.post("/voz/dono", json={"dono": "servico"}, headers=AUTH).json() == {"dono": "servico"}
    agora[0] += 7                                                    # sem batimento por mais de 6 s
    assert client.get("/voz", headers=AUTH).json()["estado"] == "parado"


def test_nova_conversa_arquiva_o_historico(settings):
    client, conv = _app(settings, voz_local=True)
    conv.store.history("hud").append({"role": "user", "content": "que horas são?"})
    conv.store.save("hud")
    assert client.post("/sessions/hud/nova", headers=AUTH).json() == {"ok": True, "arquivada": True}
    assert conv.store.history("hud") == []
    arquivos = list((conv.store.root / "arquivo").glob("hud-*.json"))
    assert len(arquivos) == 1 and json.loads(arquivos[0].read_text(encoding="utf-8"))[0]["content"] == "que horas são?"
    assert client.post("/sessions/hud/nova", headers=AUTH).json()["arquivada"] is False     # já estava vazia
    assert client.post("/sessions/..%5C..%5Cdados/nova", headers=AUTH).status_code in (404, 422)


class ProcFalso:
    def __init__(self, vive=False):
        self.pid, self.vive, self.mortes, self.terminado = 4242, vive, 0, False

    def poll(self):
        return None if self.vive else 1

    def kill(self):
        self.mortes += 1
        self.vive = False

    def terminate(self):
        self.terminado = True
        self.vive = False

    def wait(self, timeout=None):
        return 0


def _supervisor(estado, procs, agora):
    esperas = []

    async def dormir(s):
        esperas.append(s)
        agora[0] += s
        await asyncio.sleep(0)  # devolve a vez ao laço, como um sleep de verdade

    sup = Supervisor(estado, comando=["python", "-m", "jarvis.voz"], popen=lambda *a, **k: procs.pop(0),
                     dormir=dormir, relogio=lambda: agora[0])
    return sup, esperas


def test_supervisor_reinicia_com_espera_crescente_e_retoma_depois_de_falhar():
    """5 falhas em 5 min: fica em "falhou" (o HUD oferece o microfone do navegador), espera RETOMAR_S e tenta de
    novo. Antes desistia de vez, e a voz só voltava reiniciando a API (31/10, 12:38)."""
    agora = [0.0]
    estado = EstadoVoz(relogio=lambda: agora[0])
    procs = [ProcFalso() for _ in range(FALHAS_MAX)] + [ProcFalso(vive=True)]
    situacao_na_pausa = []
    sup, esperas = _supervisor(estado, procs, agora)

    async def cenario():
        tarefa = asyncio.create_task(sup.rodar())
        while procs:                        # o sexto processo só sobe depois da pausa longa
            if RETOMAR_S in esperas and not situacao_na_pausa:
                situacao_na_pausa.append(estado.situacao)
            await asyncio.sleep(0)
        sup.parar()
        await tarefa

    asyncio.run(cenario())
    curtas = [e for e in esperas if e not in (1.0, RETOMAR_S)]
    assert curtas == list(ESPERAS_S[1:FALHAS_MAX - 1])             # 1 s de vigia entre elas
    assert esperas.count(RETOMAR_S) == 1 and situacao_na_pausa == ["falhou"]
    assert sup.falhas == [] and estado.situacao == "desligado"     # recomeçou do zero e parou a pedido


def test_supervisor_mata_processo_travado_sem_batimento():
    agora = [0.0]
    estado = EstadoVoz(relogio=lambda: agora[0])
    travado, seguinte = ProcFalso(vive=True), ProcFalso(vive=True)
    sup, _ = _supervisor(estado, [travado, seguinte], agora)

    async def cenario():
        tarefa = asyncio.create_task(sup.rodar())
        while not travado.mortes:          # sem nenhum batimento: tolera a carga e depois mata
            await asyncio.sleep(0)
        assert agora[0] > CARGA_S
        while sup.proc is not seguinte:
            await asyncio.sleep(0)
        sup.parar()
        await tarefa

    asyncio.run(cenario())
    assert travado.mortes == 1 and seguinte.terminado and estado.situacao == "desligado"


@pytest.mark.parametrize("estado", ["ouvindo", "falando"])
def test_resumo_mostra_o_estado_vivo(estado):
    e = EstadoVoz(relogio=lambda: 10.0)
    e.batimento(estado)
    assert e.resumo() == {"ativo": True, "estado": estado, "dono": "servico", "situacao": "iniciando"}


def test_mudanca_de_estado_e_nova_conversa_viram_eventos_para_o_hud(settings):
    client, _ = _app(settings, voz_local=True)
    eventos = []
    client.app.state.bus.publish = eventos.append  # registra o que iria para o HUD
    client.post("/voz/estado", json={"estado": "ouvindo"}, headers=AUTH)
    client.post("/voz/estado", json={"estado": "ouvindo"}, headers=AUTH)     # igual: não repete
    client.post("/voz/estado", json={"estado": "falando"}, headers=AUTH)
    client.post("/sessions/hud/nova", headers=AUTH)
    assert [(e.kind, e.texto, e.falar) for e in eventos] == [
        ("voz", "ouvindo", False), ("voz", "falando", False), ("nova_conversa", "hud", False)]


def test_processo_de_voz_usa_o_mesmo_python_da_api_sem_janela(monkeypatch):
    """Na tarefa de logon a API roda em pythonw.exe: o serviço de voz herda o mesmo executável (sem console) e
    morre junto com ela (--pai)."""
    import os
    import subprocess
    import sys

    chamadas = []
    sup = Supervisor(EstadoVoz(), popen=lambda *a, **k: chamadas.append((a, k)) or ProcFalso(vive=True))
    assert sup.comando == [sys.executable, "-m", "jarvis.voz", "--pai", str(os.getpid())]
    sup._iniciar()
    (argv,), kw = chamadas[0]
    assert argv == sup.comando and kw["stdout"] == subprocess.DEVNULL and "shell" not in kw
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
