"""Microfone que some ou só entrega silêncio (31/10, K8 sem fio): o detector avisa e o serviço reabre o stream que
parou sem erro. Sem hardware: quadros sintéticos e um microfone falso."""

import threading
import time

import pytest

np = pytest.importorskip("numpy")

from jarvis.voz import servico as mod
from jarvis.voz.captura import DetectorDeSilencio

ZEROS = np.zeros(1280, dtype=np.int16)
SALA = np.full(1280, 300, dtype=np.int16)


def _estalo(pico=121):
    q = ZEROS.copy()
    q[640] = pico
    return q


def test_detector_avisa_microfone_que_so_entrega_zeros():
    d = DetectorDeSilencio(quadros=5)
    assert [d.alimentar(ZEROS) for _ in range(6)] == [None, None, None, None, "mudo", None]   # avisa uma vez
    assert [d.alimentar(SALA) for _ in range(3)] == [None, None, "voltou"]                    # 240 ms de som
    assert d.alimentar(ZEROS) is None                                                        # recomeça a janela
    assert [d.alimentar(SALA) for _ in range(10)] == [None] * 10                             # som normal: nada


def test_detector_tolera_estalos_soltos_do_receptor_desligado():
    """O K8 desligado entrega zeros com um estalo de vez em quando: o detector antigo (pico <= 2 seguido) nunca
    avisava, e o estalo solto também não pode contar como volta."""
    d = DetectorDeSilencio()
    avisos = [d.alimentar(_estalo() if i % 15 == 0 else ZEROS) for i in range(400)]
    assert avisos.count("mudo") == 1 and "voltou" not in avisos


class MicrofoneQueTrava:
    """Entrega uns quadros, depois o PortAudio para de chamar o callback (parado) e a primeira reabertura falha
    (receptor ainda reiniciando)."""

    nome = "Microfone (K8)"

    def __init__(self):
        self.mudo, self._aberto, self.travado = False, False, False
        self.tentativas, self.reaberto = 0, threading.Event()

    @property
    def aberto(self):
        return self._aberto

    def abrir(self):
        self._aberto = True

    def fechar(self):
        self._aberto = False

    def parado(self):
        return self.travado

    def reabrir(self):
        self.tentativas += 1
        self._aberto = False
        if self.tentativas == 1:
            raise ValueError("microfone não encontrado: 'Microfone (K8)'")
        self._aberto, self.travado = True, False
        self.reaberto.set()

    def quadros(self, timeout=1.0):
        for _ in range(5):
            yield SALA
        self.travado = True
        while self._aberto:
            time.sleep(0.01)
            yield None


class EscutaFalsa:
    def __init__(self):
        self.descartes = 0

    def processar(self, _q):
        return None

    def descartar(self):
        self.descartes += 1


class ClienteSoBatimento:
    def batimento(self, _estado):
        return {"dono": "servico", "comandos": []}

    def eventos(self):
        time.sleep(0.05)
        return iter(())


class VozMuda:
    falando, mudo = False, False

    def cancelar(self):
        pass

    def encerrar(self):
        pass


def test_servico_reabre_o_microfone_que_parou_sem_erro(monkeypatch):
    monkeypatch.setattr(mod, "REABRIR_S", 0.01)
    mic, escuta = MicrofoneQueTrava(), EscutaFalsa()
    srv = mod.Servico(escuta, ClienteSoBatimento(), mic, voz=VozMuda())
    t = threading.Thread(target=srv.rodar, daemon=True)
    t.start()
    try:
        assert mic.reaberto.wait(10), "o serviço não reabriu o microfone"
    finally:
        srv.parar.set()
        t.join(timeout=5)
    assert mic.tentativas == 2           # a primeira falhou (aparelho fora) e ele tentou de novo
    assert escuta.descartes >= 1         # a fala pela metade antes da queda não vira pergunta
