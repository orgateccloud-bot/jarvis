"""Fase 2b: texto da voz local. Paridade com o HUD (mesmos casos de tests/fixtures/voz/casos.json, conferidos pelo
npm test) e classificação de "Ok Jarvis" × "Jarvis, ..." (Decisão B). Sem áudio, sem modelos, sem rede."""

import json
from pathlib import Path

import pytest

from jarvis.voz.comando import classificar
from jarvis.voz.eco import FiltroDeEco
from jarvis.voz.texto import (
    NAO,
    SIM,
    DivisorDeFrases,
    corrigir_termos,
    depois_do_vocativo,
    e_comando_de_parar,
    para_fala,
)

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
    assert classificar("Jarvis, parê!", 0.9).tipo == "parar"           # grafia do Whisper na voz do usuário
    # o modelo disparou, mas o Whisper não ouviu o vocativo no começo: descarta
    for fala in ["Os problemas são graves.", "Que horas são?", "o filme do homem de ferro com o jarvis", "",
                 "O Jarvis já chegou?", "Então o Jarvis falou"]:   # o vocativo precisa abrir a fala
        assert classificar(fala, 1.5).tipo == "nada"


@pytest.mark.parametrize(("fala", "duracao", "esperado"), [
    ("Tá bom. Jarvis, que horas são?", 3.0, ("pergunta", "que horas são?")),             # emendou sem pausa
    ("Ele vem na segunda, né? Jarvis, que horas são? Mas ele vem cedo.", 9.5, ("pergunta", "que horas são?")),
    ("Jarvis, que horas são? Tá, mas ele vem na segunda.", 9.5, ("pergunta", "que horas são?")),  # longa: só a frase
    ("Jarvis, abra o Chrome. Depois pesquise o clima.", 4.0,
     ("pergunta", "abra o Chrome. Depois pesquise o clima.")),                           # curta: o pedido inteiro
    ("Ele falou isso. O Jarvis já chegou? Não sei.", 9.5, ("nada", "")),                 # no meio da frase: não
    ("Vou ali. Jarvis, pare.", 3.0, ("parar", "")),
])
def test_vocativo_pode_abrir_qualquer_frase_e_so_ela_segue(fala, duracao, esperado):
    c = classificar(fala, duracao)
    assert (c.tipo, c.texto) == esperado


def test_ok_jarvis_com_aprovacao_pendente_nega_e_nunca_aprova():
    c = classificar("Ok, Jarvis.", 1.0, aprovacao_pendente=True)
    assert c.tipo == "nova_conversa" and c.negar_aprovacao
    assert not classificar("Ok, Jarvis.", 1.0).negar_aprovacao


@pytest.mark.parametrize(("entrada", "saida"), CASOS["paraFala"])
def test_paridade_para_fala(entrada, saida):
    assert para_fala(entrada) == saida


@pytest.mark.parametrize(("trechos", "frases"), CASOS["divisor"])
def test_paridade_divisor_de_frases(trechos, frases):
    saida = []
    d = DivisorDeFrases(saida.append)
    for t in trechos:
        for pedaco in (t[1:] if t.startswith("*") else [t]):  # "*" = chega caractere a caractere
            d.push(pedaco)
    d.flush()
    assert saida == frases


@pytest.mark.parametrize(("texto", "sim", "nao"), CASOS["simNao"])
def test_paridade_sim_nao(texto, sim, nao):
    assert (bool(SIM.match(texto)), bool(NAO.match(texto))) == (sim, nao)


@pytest.mark.parametrize("caso", CASOS["eco"], ids=lambda c: c["ouvido"][:30])
def test_paridade_filtro_de_eco(caso):
    agora = [1_000_000.0]
    f = FiltroDeEco(agora_ms=lambda: agora[0])
    for linha in caso["lembrar"]:
        f.lembrar(linha)
    if caso["terminou"]:
        f.terminou()
    agora[0] += caso["passa_ms"]
    assert f.e_eco(caso["ouvido"], resposta=caso.get("resposta", False)) is caso["eco"]
