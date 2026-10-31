"""Trava de rede do processo de voz: só 127.0.0.1. Nada aqui sai do PC: o bloqueio acontece antes da conexão."""

import socket
import threading

import pytest

from jarvis.voz import offline


@pytest.fixture
def trava():
    offline.ativar()
    yield
    offline.desativar()


def test_local_passa_e_externo_e_barrado(trava):
    srv = socket.create_server(("127.0.0.1", 0))
    porta = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True).start()
    with socket.create_connection(("127.0.0.1", porta), timeout=5):
        pass
    srv.close()

    antes = offline.bloqueadas()
    with pytest.raises(offline.RedeBloqueada):
        socket.create_connection(("203.0.113.10", 443), timeout=5)   # TEST-NET-3: nem chega a tentar
    with pytest.raises(offline.RedeBloqueada):
        socket.getaddrinfo("api.anthropic.com", 443)                  # nem a consulta de DNS sai
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(offline.RedeBloqueada):
        udp.sendto(b"x", ("8.8.8.8", 53))
    udp.close()
    assert offline.bloqueadas() == antes + 3


def test_detector_de_silencio_avisa_microfone_que_so_entrega_zeros():
    np = pytest.importorskip("numpy")
    from jarvis.voz.captura import DetectorDeSilencio

    d = DetectorDeSilencio(quadros=5)
    zeros, sala = np.zeros(1280, dtype=np.int16), np.full(1280, 300, dtype=np.int16)
    assert [d.alimentar(zeros) for _ in range(6)] == [None, None, None, None, "mudo", None]   # avisa uma vez
    assert d.alimentar(sala) == "voltou" and d.alimentar(zeros) is None
    assert [d.alimentar(sala) for _ in range(10)] == [None] * 10                             # som normal: nada
