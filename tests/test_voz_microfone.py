"""Microfone que some ou só entrega silêncio (31/10, K8 sem fio): o detector avisa e o serviço reabre o stream que
parou sem erro. Sem hardware: quadros sintéticos e um microfone falso."""

import threading
import time

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sounddevice")

from jarvis.voz import captura
from jarvis.voz import servico as mod
from jarvis.voz.captura import TRAVA_PORTAUDIO, DetectorDeSilencio, Microfone

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

    nome, pedido, reserva = "Microfone (K8)", None, False

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
    gravando = False

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
    monkeypatch.setattr(mod, "ESPERAS_REABRIR_S", (0.01,))
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


def test_microfone_pedido_ausente_abre_o_padrao_e_volta_quando_ele_aparece(monkeypatch):
    """31/10: o receptor do K8 sumiu por horas; o serviço nem iniciava (ValueError) e o supervisor desistiu."""
    from jarvis.voz import captura

    conectados, abertos = [], []

    def escolher(nome):
        if nome in conectados:
            return 7
        raise ValueError(f"microfone não encontrado: {nome!r}")

    class StreamFalso:
        def __init__(self, device=None, **_kw):
            abertos.append(device)

        def start(self):
            pass

        abort = close = start

    monkeypatch.setattr(captura, "escolher", escolher)
    monkeypatch.setattr(captura.sd, "InputStream", StreamFalso)
    monkeypatch.setattr(captura.sd, "_terminate", lambda: None)
    monkeypatch.setattr(captura.sd, "_initialize", lambda: None)
    mic = captura.Microfone(pedido="K8")
    mic.abrir()
    assert mic.reserva and abertos == [None]          # None = padrão do Windows
    mic.reabrir()
    assert mic.reserva and abertos == [None, None]    # ainda fora: continua no padrão, sem erro
    conectados.append("K8")
    mic.reabrir()
    assert not mic.reserva and abertos == [None, None, 7]


class MicrofoneReserva(MicrofoneQueTrava):
    """Aberto no padrão do Windows; o pedido volta na primeira conferência."""

    pedido, reserva = "K8", True

    def reabrir(self):
        self.tentativas += 1
        self.reserva = False
        self.reaberto.set()

    def quadros(self, timeout=1.0):
        while self._aberto:
            time.sleep(0.01)
            yield SALA


def test_servico_confere_em_repouso_se_o_microfone_pedido_voltou(monkeypatch):
    monkeypatch.setattr(mod, "CONFERIR_PEDIDO_S", 0.05)
    mic = MicrofoneReserva()
    srv = mod.Servico(EscutaFalsa(), ClienteSoBatimento(), mic, voz=VozMuda())
    t = threading.Thread(target=srv.rodar, daemon=True)
    t.start()
    try:
        assert mic.reaberto.wait(10), "o serviço não conferiu o microfone pedido"
        time.sleep(0.2)                    # de volta ao pedido: não confere mais
    finally:
        srv.parar.set()
        t.join(timeout=5)
    assert mic.tentativas == 1 and not mic.reserva


# ── PR #18: trava do PortAudio, nada de reabrir com a fala tocando, sem microfone nenhum ao subir ──────
class SemMicrofone(MicrofoneQueTrava):
    """Nenhum aparelho de entrada: abrir e as primeiras reaberturas falham."""

    def __init__(self, falhas=3):
        super().__init__()
        self.falhas = falhas

    def abrir(self):
        raise OSError("nenhum aparelho de entrada")

    def reabrir(self):
        self.tentativas += 1
        if self.tentativas <= self.falhas:
            raise OSError("nenhum aparelho de entrada")
        self._aberto = True
        self.reaberto.set()

    def quadros(self, timeout=1.0):
        while self._aberto:
            time.sleep(0.01)
            yield None


def test_servico_sem_microfone_nenhum_ao_subir_espera_em_vez_de_cair(monkeypatch):
    monkeypatch.setattr(mod, "ESPERAS_REABRIR_S", (0.01,))
    mic = SemMicrofone(falhas=3)
    srv = mod.Servico(EscutaFalsa(), ClienteSoBatimento(), mic, voz=VozMuda())
    t = threading.Thread(target=srv.rodar, daemon=True)
    t.start()
    try:
        assert mic.reaberto.wait(10), "o serviço não esperou um microfone aparecer"
        assert t.is_alive()                       # o processo não caiu
    finally:
        srv.parar.set()
        t.join(timeout=5)
    assert mic.tentativas == 4


class ParadaFalsa:
    """Event que só registra as esperas (sem dormir de verdade)."""

    def __init__(self):
        self.esperas = []

    def is_set(self):
        return False

    def wait(self, s):
        self.esperas.append(s)
        return False


def test_espera_crescente_entre_as_tentativas(monkeypatch):
    """De 2 em 2 s para sempre, foram mais de 800 reinícios do PortAudio em meia hora; agora a espera cresce."""
    monkeypatch.setattr(mod, "ESPERAS_REABRIR_S", (1.0, 2.0, 3.0))
    mic = SemMicrofone(falhas=6)
    srv = mod.Servico(EscutaFalsa(), ClienteSoBatimento(), mic, voz=VozMuda())
    srv.dono, srv.parar = True, ParadaFalsa()
    srv._reabrir_microfone()
    assert srv.parar.esperas == [1.0, 2.0, 3.0, 3.0, 3.0, 3.0] and mic.tentativas == 7


class VozQueFala(VozMuda):
    def __init__(self, frases):
        self.frases = frases

    @property
    def falando(self):
        return self.frases > 0


def test_nao_reinicia_o_portaudio_com_a_fala_tocando():
    voz = VozQueFala(frases=3)
    mic = SemMicrofone(falhas=0)
    srv = mod.Servico(EscutaFalsa(), ClienteSoBatimento(), mic, voz=voz)
    srv.dono = True

    class Parada(ParadaFalsa):
        def wait(self, s):
            super().wait(s)
            voz.frases -= 1                      # cada espera de 0,5 s, uma frase a menos
            return False

    srv.parar = Parada()
    srv._reabrir_microfone()
    assert srv.parar.esperas == [0.5, 0.5, 0.5] and mic.tentativas == 1   # só reabriu depois da fala


def test_reabrir_reinicia_o_portaudio_so_com_a_trava(monkeypatch):
    vistos = []
    monkeypatch.setattr(captura.sd, "_terminate", lambda: vistos.append(("terminate", TRAVA_PORTAUDIO.locked())))
    monkeypatch.setattr(captura.sd, "_initialize", lambda: vistos.append(("initialize", TRAVA_PORTAUDIO.locked())))
    monkeypatch.setattr(captura, "escolher", lambda _n: (_ for _ in ()).throw(ValueError("fora")))
    mic = Microfone()
    mic._alvo = "Microfone (K8)"                  # aberto antes pelo índice; agora sumiu
    with pytest.raises(ValueError):
        mic.reabrir()
    assert vistos == [("terminate", True), ("initialize", True)] and not TRAVA_PORTAUDIO.locked()


def test_a_fala_toca_segurando_a_trava(monkeypatch):
    from jarvis.voz import fala

    vistos = []

    class SaidaFalsa:
        def __init__(self, **_kw):
            vistos.append(TRAVA_PORTAUDIO.locked())

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def write(self, _bloco):
            vistos.append(TRAVA_PORTAUDIO.locked())

    monkeypatch.setattr(captura.sd, "OutputStream", SaidaFalsa)
    fala.tocador_sounddevice()(np.zeros(4000, dtype=np.int16), 16000, lambda: False)
    assert vistos and all(vistos) and not TRAVA_PORTAUDIO.locked()
