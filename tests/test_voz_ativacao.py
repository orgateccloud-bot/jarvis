"""Fase 2a: palavra de ativação com WAVs sintéticos (vozes Daniel e Maria do Windows, scripts/gerar_wavs_teste.py)
e silêncio/ruído gerados com semente fixa. Nenhuma gravação de pessoa e nenhuma chamada de rede.

Precisam do extra [voz] e dos modelos baixados (python -m jarvis.voz.baixar); sem eles, são pulados (ex.: no CI).
"""

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")

from jarvis.voz.baixar import verificar
from jarvis.voz.config import MODELOS_ATIVACAO, TAXA, pastas

FIXTURES = Path(__file__).parent / "fixtures" / "voz"
pytestmark = [
    pytest.mark.voz_modelos,
    pytest.mark.skipif(bool(verificar(pastas(), list(MODELOS_ATIVACAO))), reason="modelos de voz não baixados"),
]


@pytest.fixture(scope="module")
def ativacao():
    from jarvis.voz.ativacao import Ativacao

    return Ativacao(pastas().ativacao)


def _clip(nome: str):
    """WAV com 1 s de silêncio antes e depois, como numa escuta contínua."""
    with wave.open(str(FIXTURES / f"{nome}.wav"), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (TAXA, 1, 2)
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(TAXA, dtype=np.int16)
    return np.concatenate([pad, audio, pad])


def _ruido(tipo: str, sigma: float, semente: int, segundos: int = 10):
    rng = np.random.default_rng(semente)
    n = TAXA * segundos
    if tipo == "branco":
        x = rng.normal(0, sigma, n)
    else:  # rosa: espectro 1/f
        esp = np.fft.rfft(rng.normal(0, 1, n))
        f = np.fft.rfftfreq(n, 1 / TAXA)
        esp[1:] /= np.sqrt(f[1:])
        esp[0] = 0
        x = np.fft.irfft(esp, n)
        x = x / x.std() * sigma
    return x.clip(-32768, 32767).astype(np.int16)


@pytest.mark.parametrize("nome", ["ok_jarvis_daniel", "ok_jarvis_maria", "hey_jarvis_maria", "jarvis_daniel",
                                  "jarvis_que_horas_daniel", "ok_jarvis_que_horas_daniel"])
def test_ativacao_dispara_uma_vez(ativacao, nome):
    disparos = ativacao.disparos_do_clip(_clip(nome))
    assert len(disparos) == 1                       # um disparo por fala (os buffers zeram depois dele)
    assert disparos[0].score >= ativacao.limiar and disparos[0].voz >= ativacao.limiar_vad


@pytest.mark.xfail(strict=True, reason="falso negativo medido: 'Jarvis, que horas são?' na voz Maria chega a 0,108")
def test_falso_negativo_conhecido_voz_maria(ativacao):
    assert ativacao.disparos_do_clip(_clip("jarvis_que_horas_maria"))


def test_silencio_nao_dispara(ativacao):
    assert ativacao.disparos_do_clip(np.zeros(TAXA * 10, dtype=np.int16)) == []


@pytest.mark.parametrize("tipo", ["branco", "rosa"])
@pytest.mark.parametrize("sigma", [300, 3000, 8000])
def test_ruido_nao_dispara(ativacao, tipo, sigma):
    # sem o VAD, o ruído rosa chega a 0,45 no modelo (acima do limiar 0,3): quem barra é a falta de voz
    assert ativacao.disparos_do_clip(_ruido(tipo, sigma, semente=1)) == []


@pytest.mark.parametrize("nome", ["eco_disco_daniel", "eco_lembrete_daniel", "eco_custo_maria"])
def test_eco_da_propria_voz_nao_dispara(ativacao, nome):
    assert ativacao.disparos_do_clip(_clip(nome)) == []
