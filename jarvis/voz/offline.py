"""Trava de rede do processo de voz: só conexões locais (127.0.0.1, ::1, localhost).

O áudio e o texto transcrito só podem ir para a API local; a chamada ao Claude é feita pela API, em outro processo.
Cada tentativa bloqueada é contada e registrada (critério de aceite: zero tentativas com a internet desligada).
"""

from __future__ import annotations

import ipaddress
import socket
import threading

from loguru import logger

_LOCAIS = {"localhost", "localhost.localdomain"}
_trava = threading.Lock()
_estado = {"ativa": False, "bloqueadas": 0}
_orig: dict = {}


class RedeBloqueada(ConnectionError):
    """Conexão para fora do PC dentro do processo de voz."""


def _local(host) -> bool:
    if host is None:
        return True  # bind/listen sem destino
    h = str(host).strip("[]").lower()
    if h in _LOCAIS:
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False  # nome que exigiria DNS


def _barrar(destino) -> None:
    with _trava:
        _estado["bloqueadas"] += 1
    logger.warning("rede bloqueada no processo de voz: {}", destino)
    raise RedeBloqueada(f"processo de voz só fala com 127.0.0.1; bloqueado: {destino}")


def _host(endereco):
    return endereco[0] if isinstance(endereco, tuple) and endereco else None


def ativar() -> None:
    """Instala a trava (idempotente). Vale para todo socket criado pelo Python neste processo."""
    with _trava:
        if _estado["ativa"]:
            return
        _estado["ativa"] = True
        _orig.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                     sendto=socket.socket.sendto, getaddrinfo=socket.getaddrinfo)

    def connect(self, endereco):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(_host(endereco)):
            _barrar(endereco)
        return _orig["connect"](self, endereco)

    def connect_ex(self, endereco):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(_host(endereco)):
            _barrar(endereco)
        return _orig["connect_ex"](self, endereco)

    def sendto(self, dados, *args):
        endereco = args[-1]
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(_host(endereco)):
            _barrar(endereco)
        return _orig["sendto"](self, dados, *args)

    def getaddrinfo(host, *args, **kwargs):
        if not _local(host):
            _barrar(host)  # nem a consulta de DNS sai
        return _orig["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo


def desativar() -> None:
    """Remove a trava (só para testes)."""
    with _trava:
        if not _estado["ativa"]:
            return
        socket.socket.connect = _orig["connect"]
        socket.socket.connect_ex = _orig["connect_ex"]
        socket.socket.sendto = _orig["sendto"]
        socket.getaddrinfo = _orig["getaddrinfo"]
        _estado["ativa"] = False


def bloqueadas() -> int:
    return _estado["bloqueadas"]
