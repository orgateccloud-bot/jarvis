"""Fase 2b: texto da voz local. Paridade com o HUD (mesmos casos de tests/fixtures/voz/casos.json, conferidos pelo
npm test) e classificação de "Ok Jarvis" × "Jarvis, ..." (Decisão B). Sem áudio, sem modelos, sem rede."""

import json
from pathlib import Path

import pytest

from jarvis.voz.comando import classificar
from jarvis.voz.texto import corrigir_termos, depois_do_vocativo, e_comando_de_parar

CASOS = json.loads((Path(__file__).parent / "fixtures" / "voz" / "casos.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("entrada", "saida"), CASOS["corrigirTermos"])
def test_paridade_corrigir_termos(entrada, saida):
    assert corrigir_termos(entrada) == saida


@pytest.mark.parametrize(("entrada", "saida"), CASOS["afterWakeWord"])
def test_paridade_depois_do_vocativo(entrada, saida):
    assert depois_do_vocativo(entrada) == saida


@pytest.mark.parametrize(("entrada", "saida"), CASOS["isStopCommand"])
def test_paridade_comando_de_parar(entrada, saida):
    assert e_comando_de_parar(entrada) is saida


@pytest.mark.parametrize("fala", ["Ok, Jarvis.", "OK Jarvis!", "Okay, Jarvis", "oquei jarvis", "Ok, Javis."])
def test_ok_jarvis_isolado_e_curto_abre_nova_conversa(fala):
    assert classificar(fala, duracao_fala_s=1.2).tipo == "nova_conversa"


@pytest.mark.parametrize(("fala", "pedido"), [
    ("Jarvis, que horas são?", "que horas são?"),
    ("Ok Jarvis, que horas são?", "que horas são?"),        # "Ok" na frente de um pedido não zera
    ("Graves, me lembra de beber água.", "me lembra de beber água."),
    ("E aí, Jarvis, como está o disco?", "como está o disco?"),
])
def test_jarvis_com_pedido_e_pergunta_normal(fala, pedido):
    c = classificar(fala, duracao_fala_s=2.5)
    assert (c.tipo, c.texto) == ("pergunta", pedido)


def test_ok_jarvis_longo_ou_sem_fala_nao_zera():
    assert classificar("Ok, Jarvis.", duracao_fala_s=2.6).tipo == "so_jarvis"          # devagar demais
    assert classificar("Ok, Jarvis.", duracao_fala_s=1.0, no_speech_prob=0.8).tipo == "nada"


def test_jarvis_sozinho_parar_e_falso_disparo():
    assert classificar("Jarvis.", 0.6).tipo == "so_jarvis"
    assert classificar("Jarvis, pare.", 0.9).tipo == "parar"
    assert classificar("Travis, pare.", 0.9).tipo == "parar"
    # o modelo disparou, mas o Whisper não ouviu o vocativo no começo: descarta
    for fala in ["Os problemas são graves.", "Que horas são?", "o filme do homem de ferro com o jarvis", ""]:
        assert classificar(fala, 1.5).tipo == "nada"


def test_ok_jarvis_com_aprovacao_pendente_nega_e_nunca_aprova():
    c = classificar("Ok, Jarvis.", 1.0, aprovacao_pendente=True)
    assert c.tipo == "nova_conversa" and c.negar_aprovacao
    assert not classificar("Ok, Jarvis.", 1.0).negar_aprovacao
