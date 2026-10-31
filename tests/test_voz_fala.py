"""Fase 2c: a voz local de verdade (WinRT, "Microsoft Daniel", rate 1.05 e pitch 0.92 como no HUD). Nada toca no
alto-falante: o tocador é trocado por um gravador. Pulado se o WinRT ou a voz não existirem (ex.: no CI)."""

import threading
import time

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("winrt.windows.media.speechsynthesis")

from jarvis.voz.fala import VOZ, VozLocal, sintetizador_winrt


@pytest.fixture(scope="module")
def sintetizar():
    try:
        return sintetizador_winrt()
    except RuntimeError as e:
        pytest.skip(str(e))


def test_daniel_sintetiza_em_16_khz_rapido(sintetizar):
    sintetizar("aquecimento")
    t0 = time.perf_counter()
    audio, taxa = sintetizar("Bom dia, Senhor. O disco C está com 82 por cento de uso.")
    gasto = time.perf_counter() - t0
    assert taxa == 16000 and audio.dtype == np.int16 and len(audio) > taxa       # mais de 1 s de fala
    assert np.abs(audio).max() > 1000                                             # não é silêncio
    assert gasto < 0.5, gasto                                                     # medido: 55 a 64 ms


def test_voz_local_comeca_a_tocar_logo_e_cancela():
    tocados, inicio, liberar = [], [], threading.Event()

    def tocar(audio, taxa, cancelado):
        tocados.append(len(audio) / taxa)
        inicio.append(time.monotonic())
        liberar.wait(5)

    voz = VozLocal(sintetizar_fabrica=lambda: sintetizador_winrt(VOZ), tocar=tocar)
    voz.falar("Aquecendo.")
    for _ in range(200):
        if tocados:
            break
        time.sleep(0.01)
    liberar.set()
    time.sleep(0.2)
    liberar.clear()
    t0 = time.monotonic()
    voz.falar("Pois não?")
    for _ in range(200):
        if len(tocados) == 2:
            break
        time.sleep(0.01)
    assert len(tocados) == 2 and inicio[1] - t0 < 0.3, inicio[1] - t0             # da frase ao áudio
    voz.falar("Esta frase vai ser cancelada.")
    voz.cancelar()
    liberar.set()
    time.sleep(0.3)
    assert not voz.falando
    voz.encerrar()
