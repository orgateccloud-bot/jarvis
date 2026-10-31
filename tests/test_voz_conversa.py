"""Fase 2c: a conversa por voz do serviço local, com API, voz e relógio falsos (nenhuma chamada ao Claude).

Pergunta → frases faladas; "Pois não?" e a janela de 12 s; half-duplex com cauda de 1,5 s; confirmação por voz;
"Ok Jarvis" com confirmação pendente; eco; "Jarvis, pare" no modo fone; API fora; comandos do HUD.
"""

import threading

import pytest

from jarvis.voz.cliente import ApiIndisponivel
from jarvis.voz.comando import classificar
from jarvis.voz.conversa import CAUDA_S, JANELA_S, Conversa
from jarvis.voz.eco import FiltroDeEco
from jarvis.voz.escuta import Evento
from jarvis.voz.fala import VozLocal
from jarvis.voz.transcricao import Transcricao


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class VozFalsa:
    def __init__(self):
        self.falados, self.cancelamentos, self.falando, self.mudo = [], 0, False, False

    def falar(self, texto):
        self.falados.append(texto)

    def cancelar(self):
        self.cancelamentos += 1
        self.falando = False


class ClienteFalso:
    def __init__(self, roteiro=None, falha=False):
        self.roteiro = roteiro or [{"type": "text", "data": "São dez horas, Senhor. "}, {"type": "done"}]
        self.falha = falha
        self.perguntas, self.aprovacoes, self.novas = [], [], 0

    def perguntar(self, texto):
        self.perguntas.append(texto)
        if self.falha:
            raise ApiIndisponivel("conexão recusada")
        yield from self.roteiro

    def aprovar(self, aid, ok):
        self.aprovacoes.append((aid, ok))

    def nova_conversa(self):
        self.novas += 1


def _ev(texto, duracao=1.5, sem_fala=0.05):
    return Evento(classificar(texto, duracao, sem_fala), Transcricao(texto, sem_fala, -0.3, 0.34), duracao, 0.72,
                  1.06, False)


@pytest.fixture
def ambiente():
    rel, voz = Relogio(), VozFalsa()
    eco = FiltroDeEco(agora_ms=lambda: rel.t * 1000)
    cli = ClienteFalso()
    conv = Conversa(cli, voz, eco, relogio=rel, executar=lambda f: f())
    return conv, cli, voz, rel


def test_pergunta_vira_frases_faladas(ambiente):
    conv, cli, voz, _ = ambiente
    assert conv.ouvido(_ev("Jarvis, que horas são?")) == "pergunta"
    assert cli.perguntas == ["que horas são?"]
    assert voz.falados == ["São dez horas, Senhor."]
    assert not conv.ocupado and conv.modo == "ativa"


def test_pois_nao_e_janela_de_12_segundos_sem_precisar_do_jarvis(ambiente):
    conv, cli, voz, rel = ambiente
    assert conv.ouvido(_ev("Jarvis.", 0.6)) == "pois_nao"
    assert voz.falados == ["Pois não?"]
    conv.fala_terminou()
    rel.t += CAUDA_S + JANELA_S - 1
    assert conv.ouvido(_ev("que horas são?")) == "pergunta"       # conversa aberta: sem "Jarvis"
    conv.fala_terminou()
    rel.t += CAUDA_S + JANELA_S + 1
    conv.tick()
    assert conv.modo == "repouso"
    assert conv.ouvido(_ev("e amanhã, vai chover?")) == "ignorado"  # fechou: precisa do "Jarvis" de novo
    assert cli.perguntas == ["que horas são?"]


def test_half_duplex_mudo_durante_a_fala_e_na_cauda(ambiente):
    conv, _, voz, rel = ambiente
    assert not conv.mic_fechado()
    voz.falando = True
    assert conv.mic_fechado()
    voz.falando = False
    conv.fala_terminou()
    assert conv.mic_fechado()                    # cauda: o eco ainda pode chegar
    rel.t += CAUDA_S + 0.01
    assert not conv.mic_fechado()


def test_modo_fone_microfone_aberto_e_jarvis_pare_interrompe(ambiente):
    _, cli, voz, rel = ambiente
    conv = Conversa(cli, voz, FiltroDeEco(agora_ms=lambda: rel.t * 1000), interromper=True, relogio=rel,
                    executar=lambda f: f())
    voz.falando = True
    assert not conv.mic_fechado()
    assert conv.ouvido(_ev("Jarvis, que horas são?")) == "ignorado"   # falando: só "pare" vale
    assert conv.ouvido(_ev("Jarvis, parê!", 0.8)) == "parou"
    assert voz.cancelamentos == 1


def test_eco_da_propria_voz_nao_vira_pergunta(ambiente):
    conv, cli, _, rel = ambiente
    conv.ouvido(_ev("Jarvis, que horas são?"))
    conv.na_frase("São dez horas, Senhor.")
    conv.fala_terminou()
    rel.t += CAUDA_S + 0.5
    assert conv.ouvido(_ev("São dez horas, Senhor.")) == "eco"
    assert len(cli.perguntas) == 1


def test_confirmacao_por_voz_sim_nao_e_ok_jarvis(ambiente):
    conv, cli, voz, rel = ambiente
    aprovacao = {"type": "approval", "data": {"id": "a1", "nome": "abrir_app", "resumo": "abrir o Chrome"}}
    cli.roteiro = [aprovacao, {"type": "done"}]
    for falas, esperado, acao in [
        ("sim, pode abrir", ("a1", True), "aprovou"),
        ("não", ("a1", False), "negou"),
        ("Ok, Jarvis.", ("a1", False), "negou_e_nova_conversa"),   # nunca aprova, mesmo com "ok" em SIM
    ]:
        cli.aprovacoes.clear()
        # o turno fica parado na confirmação: simula o stream ainda aberto
        conv.aprovacao = aprovacao["data"]
        conv.na_frase("Confirma: abrir o Chrome? Diga sim ou não.")
        conv.fala_terminou()
        rel.t += CAUDA_S + 0.3
        assert conv.ouvido(_ev(falas, 1.0)) == acao
        assert cli.aprovacoes == [esperado]
    assert cli.novas == 1 and voz.falados[-1] == "Nova conversa."


def test_aprovacao_chega_pelo_stream_e_o_eco_da_pergunta_nao_aprova(ambiente):
    conv, cli, voz, rel = ambiente
    cli.roteiro = [{"type": "approval", "data": {"id": "a2", "resumo": "abrir o Chrome"}}]
    conv.ouvido(_ev("Jarvis, abre o Chrome."))
    assert voz.falados[-1] == "Confirma: abrir o Chrome? Diga sim ou não."
    conv.aprovacao = {"id": "a2"}  # o stream real fica aberto esperando a decisão
    conv.na_frase(voz.falados[-1])
    conv.fala_terminou()
    rel.t += CAUDA_S + 0.2
    assert conv.ouvido(_ev("sim ou não", 0.8)) == "eco"
    assert cli.aprovacoes == []


def test_api_fora_fala_um_aviso_e_libera(ambiente):
    conv, cli, voz, _ = ambiente
    cli.falha = True
    assert conv.ouvido(_ev("Jarvis, que horas são?")) == "pergunta"
    assert voz.falados == ["Não consegui falar com o núcleo do JARVIS."]
    assert not conv.ocupado


def test_jarvis_pare_sem_nada_falando_e_falas_sem_vocativo_no_repouso(ambiente):
    conv, cli, _, _ = ambiente
    assert conv.ouvido(_ev("Jarvis, pare.", 0.8)) == "ignorado"
    assert conv.ouvido(_ev("O disco está quase cheio.")) == "ignorado"
    assert cli.perguntas == []


def test_comandos_do_hud(ambiente):
    conv, _, voz, _ = ambiente
    conv.comando("ouvir")
    assert conv.modo == "ativa" and conv.estado() == "ouvindo"
    conv.comando("mudo")
    assert voz.mudo and voz.cancelamentos == 1
    conv.comando("som")
    assert not voz.mudo
    conv.comando("parar")
    assert conv.modo == "repouso" and conv.estado() == "repouso"


def test_voz_local_fila_callbacks_e_cancelamento():
    eventos, liberar = [], threading.Event()

    def tocar(audio, taxa, cancelado):
        eventos.append(("tocou", int(audio[0])))
        liberar.wait(2)

    voz = VozLocal(sintetizar_fabrica=lambda: (lambda t: (__import__("numpy").full(10, len(t), "int16"), 16000)),
                   tocar=tocar, ao_comecar=lambda: eventos.append("comecou"),
                   ao_terminar=lambda: eventos.append("terminou"), na_frase=lambda t: eventos.append(("frase", t)))
    voz.falar("Bom dia.")
    voz.falar("Tudo certo.")
    liberar.set()
    for _ in range(100):
        if "terminou" in eventos:
            break
        threading.Event().wait(0.02)
    assert eventos == ["comecou", ("frase", "Bom dia."), ("tocou", 8), ("frase", "Tudo certo."), ("tocou", 11),
                       "terminou"]
    assert not voz.falando
    voz.encerrar()
