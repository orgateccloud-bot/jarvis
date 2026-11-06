"""Voz local do serviço: a mesma do HUD (OneCore "Microsoft Daniel", rate 1.05, pitch 0.92 de webspeech.js),
sintetizada pelo WinRT (Windows.Media.SpeechSynthesis) e tocada pelo sounddevice, frase a frase, numa thread.

Medido nesta máquina: a síntese de uma frase leva 55 a 64 ms e já sai em WAV 16 kHz mono 16 bits.
cancelar() para no bloco seguinte (~64 ms): é o "Jarvis, pare" e o Esc do HUD.
"""

from __future__ import annotations

import asyncio
import io
import queue
import threading
import time
import wave
from collections.abc import Callable

import numpy as np
from loguru import logger

VOZ = "Daniel"          # webspeech.js escolhe a 1ª voz pt-BR local: no Chrome desta máquina, "Microsoft Daniel"
RATE, PITCH = 1.05, 0.92  # webspeech.js:145-146
BLOCO = 1024            # amostras por escrita no alto-falante: o cancelamento é checado entre blocos


def sintetizador_winrt(voz: str = VOZ, rate: float = RATE, pitch: float = PITCH) -> Callable[[str], tuple]:
    """Devolve sintetizar(texto) → (amostras int16, taxa). Cria o SpeechSynthesizer uma vez, na thread que chama."""
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    escolhida = next((v for v in SpeechSynthesizer.all_voices if voz.lower() in v.display_name.lower()
                      and v.language.lower() == "pt-br"), None)
    if escolhida is None:
        raise RuntimeError(f"voz {voz!r} pt-BR não instalada no Windows")
    s = SpeechSynthesizer()
    s.voice = escolhida
    s.options.speaking_rate = rate
    s.options.audio_pitch = pitch
    laco = asyncio.new_event_loop()

    async def _sintetizar(texto: str) -> bytes:
        st = await s.synthesize_text_to_stream_async(texto)
        buf = Buffer(st.size)
        await st.read_async(buf, st.size, InputStreamOptions.NONE)
        return bytes(buf)

    def sintetizar(texto: str) -> tuple[np.ndarray, int]:
        with wave.open(io.BytesIO(laco.run_until_complete(_sintetizar(texto)))) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()

    return sintetizar


def tocador_sounddevice(pedido: str = "") -> Callable[[np.ndarray, int, Callable[[], bool]], None]:
    """`pedido` é parte do nome do alto-falante (JARVIS_VOZ_ALTO_FALANTE); vazio = o padrão do Windows.

    Um viva-voz só cancela o eco do que sai por ele. O aparelho é procurado a cada frase, porque o índice muda quando
    o PortAudio relê a lista. Sem ele, ou se ele falhar (desconectado, o PortAudio ainda lista até reiniciar), a frase
    toca no padrão do Windows: melhor falar em outro lugar que ficar mudo.
    """
    import sounddevice as sd

    from jarvis.voz.captura import TRAVA_PORTAUDIO, alto_falantes

    ausente = False

    def procurar() -> int | None:
        nonlocal ausente
        if not pedido:
            return None
        achado = next((i for i, nome in alto_falantes() if pedido.lower() in nome.lower()), None)
        if (achado is None) != ausente:  # só registra quando muda
            ausente = achado is None
            if ausente:
                logger.warning("voz: alto-falante {!r} não está conectado; falando no padrão do Windows", pedido)
            else:
                logger.info("voz: alto-falante {!r} voltou", pedido)
        return achado

    def reproduzir(audio: np.ndarray, taxa: int, cancelado: Callable[[], bool], dispositivo: int | None) -> None:
        with sd.OutputStream(samplerate=taxa, channels=1, dtype="int16", device=dispositivo) as out:
            for i in range(0, len(audio), BLOCO):
                if cancelado():
                    return
                out.write(audio[i:i + BLOCO].reshape(-1, 1))

    def tocar(audio: np.ndarray, taxa: int, cancelado: Callable[[], bool]) -> None:
        # a trava impede que a reabertura do microfone reinicie o PortAudio com este stream aberto
        with TRAVA_PORTAUDIO:
            dispositivo = procurar()
            if dispositivo is not None:
                try:
                    reproduzir(audio, taxa, cancelado, dispositivo)
                    return
                except sd.PortAudioError as e:
                    logger.warning("voz: alto-falante {!r} falhou ({}); falando no padrão do Windows", pedido, e)
            reproduzir(audio, taxa, cancelado, None)

    return tocar


class VozLocal:
    """Fila de frases faladas numa thread. Avisa o começo e o fim de cada sequência (para o half-duplex) e cada
    frase que começa (para o filtro de eco)."""

    def __init__(self, sintetizar_fabrica: Callable[[], Callable] = sintetizador_winrt,
                 tocar: Callable | None = None, ao_comecar: Callable[[], None] = lambda: None,
                 ao_terminar: Callable[[], None] = lambda: None, na_frase: Callable[[str], None] = lambda _t: None):
        self._fabrica = sintetizar_fabrica
        self._tocar = tocar
        self.ao_comecar, self.ao_terminar, self.na_frase = ao_comecar, ao_terminar, na_frase
        self.mudo = False
        self._fila: queue.Queue[str | None] = queue.Queue()
        self._cancelar = threading.Event()
        self._falando = threading.Event()
        self.inicio_audio: float | None = None  # monotonic do 1º bloco da última sequência (medir latência)
        self._thread = threading.Thread(target=self._laco, name="voz-local", daemon=True)
        self._thread.start()

    @property
    def falando(self) -> bool:
        return self._falando.is_set() or not self._fila.empty()

    def falar(self, texto: str) -> None:
        if texto and not self.mudo:
            self._fila.put(texto)

    def cancelar(self) -> None:
        while True:
            try:
                self._fila.get_nowait()
            except queue.Empty:
                break
        self._cancelar.set()

    def encerrar(self) -> None:
        self.cancelar()
        self._fila.put(None)

    def _laco(self) -> None:
        sintetizar = self._fabrica()  # o WinRT fica nesta thread do começo ao fim
        tocar = self._tocar or tocador_sounddevice()
        while (texto := self._fila.get()) is not None:
            if not self._falando.is_set():
                self._cancelar.clear()
                self._falando.set()
                self.inicio_audio = None
                self.ao_comecar()
            try:
                if not self._cancelar.is_set():
                    audio, taxa = sintetizar(texto)
                    self.na_frase(texto)
                    if self.inicio_audio is None:
                        self.inicio_audio = time.monotonic()
                    tocar(audio, taxa, self._cancelar.is_set)
            finally:
                if self._fila.empty() or self._cancelar.is_set():
                    self._falando.clear()
                    self.ao_terminar()
