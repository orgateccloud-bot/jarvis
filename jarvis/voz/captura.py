"""Microfone em quadros de 80 ms (1.280 amostras int16, 16 kHz mono) via sounddevice (PortAudio)."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Iterator
from typing import Self

import numpy as np
import sounddevice as sd

from jarvis.voz.config import QUADRO, TAXA

# O PortAudio é global no processo: reiniciá-lo (_terminate/_initialize, para enxergar um aparelho que voltou) com
# um stream de saída aberto em outra thread corrompe a memória (31/10, 12:37: código 0xC0000374, com o K8 fora havia
# 28 min). A fala segura esta trava enquanto toca; a reabertura do microfone, enquanto reinicia.
TRAVA_PORTAUDIO = threading.Lock()


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


class DetectorDeSilencio:
    """Microfone que só entrega silêncio digital (desligado, mudo no aparelho, transmissor sem fio dormindo): sem
    isso o serviço fica "ouvindo" sem ouvir nada e ninguém sabe por quê (31/10: o K8 entregava pico 1 enquanto a C920
    captava a sala). Conta os quadros "mortos" (RMS abaixo de `limite`; um microfone ligado tem ruído de fundo bem
    acima) numa janela de 10 s, tolerando estalos soltos: o K8 desligado também solta picos de até ~120.
    alimentar() devolve "mudo" ao entrar nesse estado e "voltou" ao sair (VOLTA_QUADROS vivos seguidos); senão None."""

    VOLTA_QUADROS = 3  # 240 ms de som de verdade, para um estalo solto não contar como volta

    def __init__(self, quadros: int = 125, limite: float = 2.0, tolerancia: float = 0.1):  # 125 quadros = 10 s
        self.quadros, self.limite = quadros, limite
        self.max_vivos = int(quadros * tolerancia)
        self._janela: deque[bool] = deque(maxlen=quadros)
        self._vivos_seguidos = 0
        self.mudo = False

    def alimentar(self, quadro: np.ndarray) -> str | None:
        q = quadro.astype(np.float32)
        vivo = bool(len(q)) and float(np.sqrt(np.mean(q * q))) >= self.limite
        self._janela.append(vivo)
        self._vivos_seguidos = self._vivos_seguidos + 1 if vivo else 0
        if self.mudo:
            if self._vivos_seguidos >= self.VOLTA_QUADROS:
                self.mudo = False
                self._janela.clear()
                return "voltou"
            return None
        if len(self._janela) == self.quadros and sum(self._janela) <= self.max_vivos:
            self.mudo = True
            return "mudo"
        return None


class Microfone:
    """Captura contínua. O callback do PortAudio só enfileira; quem consome é `quadros()`.

    `mudo` descarta os quadros sem fechar o stream (half-duplex da fase 2c: reabrir custaria latência).
    """

    def __init__(self, dispositivo: int | None = None, fila_max: int = 50, alvo: str | None = None):
        self.dispositivo = dispositivo
        self.mudo = False
        self.perdidos = 0  # quadros descartados porque o consumidor atrasou
        self._fila: queue.Queue[np.ndarray] = queue.Queue(maxsize=fila_max)
        self._stream: sd.InputStream | None = None
        # nome (ou parte dele) do aparelho, para reachar depois que o índice mudar. Com alvo e sem dispositivo, o
        # aparelho só é procurado ao abrir: o serviço sobe mesmo com ele fora (receptor sem fio desligado)
        self._alvo: str | None = alvo
        self.ultimo = 0.0              # time.monotonic() do último callback, mesmo com `mudo`

    def _callback(self, dados, _frames, _tempo, _status) -> None:
        self.ultimo = time.monotonic()
        if self.mudo:
            return
        try:
            self._fila.put_nowait(dados[:, 0].copy())
        except queue.Full:
            self.perdidos += 1

    @property
    def nome(self) -> str:
        if self.dispositivo is None and self._alvo:
            return self._alvo
        return str(sd.query_devices(self.dispositivo, kind="input")["name"])

    @property
    def aberto(self) -> bool:
        return self._stream is not None

    def abrir(self) -> None:
        """ValueError se o aparelho escolhido pelo nome não está na lista do PortAudio."""
        if self.dispositivo is None and self._alvo is not None:
            self.dispositivo = escolher(self._alvo)
        if self.dispositivo is not None and self._alvo is None:
            self._alvo = self.nome
        self._stream = sd.InputStream(samplerate=TAXA, channels=1, dtype="int16", blocksize=QUADRO,
                                      device=self.dispositivo, callback=self._callback)
        self._stream.start()
        self.ultimo = time.monotonic()

    def fechar(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.abort()
                stream.close()
            except sd.PortAudioError:
                pass  # aparelho que sumiu: o stream já está morto

    def parado(self, segundos: float = 3.0) -> bool:
        """Aberto, mas o PortAudio não chama o callback há `segundos`. Acontece quando o aparelho some e volta
        (31/10: o receptor do K8 reiniciou e o stream ficou mudo para sempre, sem erro nenhum)."""
        return self.aberto and time.monotonic() - self.ultimo > segundos

    def reabrir(self) -> None:
        """Fecha, recarrega a lista de aparelhos do PortAudio (ele só a lê ao iniciar, e o aparelho que volta pode
        ganhar outro índice) e abre o mesmo aparelho pelo nome. ValueError se ele ainda não voltou."""
        self.fechar()
        with TRAVA_PORTAUDIO:   # nunca com a fala tocando em outra thread
            sd._terminate()
            sd._initialize()
        if self._alvo is not None:
            self.dispositivo = escolher(self._alvo)
        self.abrir()

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
