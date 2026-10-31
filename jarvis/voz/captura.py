"""Microfone em quadros de 80 ms (1.280 amostras int16, 16 kHz mono) via sounddevice (PortAudio)."""

from __future__ import annotations

import queue
from collections.abc import Iterator
from typing import Self

import numpy as np
import sounddevice as sd

from jarvis.voz.config import QUADRO, TAXA


def microfones() -> list[tuple[int, str]]:
    """Dispositivos de entrada: (índice, nome). Só leitura."""
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def escolher(nome: str | None) -> int | None:
    """Índice do primeiro microfone cujo nome contém `nome` (sem diferenciar maiúsculas); None = padrão do Windows."""
    if not nome:
        return None
    for i, n in microfones():
        if nome.lower() in n.lower():
            return i
    raise ValueError(f"microfone não encontrado: {nome!r}. Disponíveis: {[n for _, n in microfones()]}")


class Microfone:
    """Captura contínua. O callback do PortAudio só enfileira; quem consome é `quadros()`.

    `mudo` descarta os quadros sem fechar o stream (half-duplex da fase 2c: reabrir custaria latência).
    """

    def __init__(self, dispositivo: int | None = None, fila_max: int = 50):
        self.dispositivo = dispositivo
        self.mudo = False
        self.perdidos = 0  # quadros descartados porque o consumidor atrasou
        self._fila: queue.Queue[np.ndarray] = queue.Queue(maxsize=fila_max)
        self._stream: sd.InputStream | None = None

    def _callback(self, dados, _frames, _tempo, _status) -> None:
        if self.mudo:
            return
        try:
            self._fila.put_nowait(dados[:, 0].copy())
        except queue.Full:
            self.perdidos += 1

    @property
    def aberto(self) -> bool:
        return self._stream is not None

    def abrir(self) -> None:
        self._stream = sd.InputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=QUADRO,
                                      device=self.dispositivo, callback=self._callback)
        self._stream.start()

    def fechar(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def quadros(self, timeout: float = 1.0) -> Iterator[np.ndarray | None]:
        """Quadros na ordem; None quando nada chega em `timeout` (o laço pode checar se deve parar)."""
        while self._stream is not None:
            try:
                yield self._fila.get(timeout=timeout)
            except queue.Empty:
                yield None

    def __enter__(self) -> Self:
        self.abrir()
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()
