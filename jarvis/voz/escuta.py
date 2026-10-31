"""Laço da escuta: quadro a quadro, ativação → recorte da fala → Whisper → comando (Decisão B).

Fase 2b: devolve o Evento e o chamador só registra no log. Na 2c o Evento vira pergunta à API e resposta falada.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from jarvis.voz.ativacao import Ativacao
from jarvis.voz.comando import Comando, classificar
from jarvis.voz.config import QUADRO
from jarvis.voz.fala_fim import SEG_QUADRO, SILENCIO_MS, FimDeFala
from jarvis.voz.transcricao import Transcricao, Transcritor

PREROLL = 25  # quadros guardados antes do disparo (2 s): a transcrição precisa incluir o "Ok" de "Ok Jarvis"


@dataclass(frozen=True)
class Evento:
    comando: Comando
    transcricao: Transcricao
    duracao_fala_s: float
    espera_fim_s: float   # silêncio esperado para decidir que a fala acabou
    latencia_s: float     # do último quadro com voz até a transcrição pronta (espera_fim_s + Whisper)


class Escuta:
    def __init__(self, ativacao: Ativacao, transcritor: Transcritor, silencio_ms: int = SILENCIO_MS,
                 relogio: Callable[[], float] = time.monotonic):
        self.ativacao = ativacao
        self.transcritor = transcritor
        self.relogio = relogio
        self.fim = FimDeFala(ativacao.vad, silencio_ms=silencio_ms)
        self._preroll: deque[np.ndarray] = deque(maxlen=PREROLL)
        self.gravando = False
        self.disparos = 0

    def processar(self, quadro: np.ndarray) -> Evento | None:
        if not self.gravando:
            self._preroll.append(quadro)
            d = self.ativacao.processar(quadro)  # zera os buffers da ativação (e o VAD) quando dispara
            if d:
                self.disparos += 1
                self.fim.iniciar(list(self._preroll), list(d.voz_recente))
                self.gravando = True
            return None
        if not self.fim.adicionar(quadro):
            return None
        return self._encerrar()

    def encerrar(self) -> Evento | None:
        """Fecha uma fala em andamento (fim do áudio de teste ou desligamento)."""
        return self._encerrar() if self.gravando else None

    def _encerrar(self) -> Evento:
        espera = self.fim.quadros_desde_a_voz * SEG_QUADRO
        tr = self.transcritor.transcrever(self.fim.audio)
        cmd = classificar(tr.texto, self.fim.duracao_fala_s, tr.no_speech_prob)
        ev = Evento(cmd, tr, self.fim.duracao_fala_s, espera, espera + tr.segundos)
        self.gravando = False
        self._preroll.clear()
        self.ativacao.reset()
        return ev

    def processar_clip(self, audio: np.ndarray) -> list[Evento]:
        """Simula a escuta contínua num áudio inteiro (testes e medição)."""
        self.ativacao.reset()
        self.gravando = False
        self._preroll.clear()
        eventos = []
        for i in range(len(audio) // QUADRO):
            if ev := self.processar(audio[i * QUADRO:(i + 1) * QUADRO]):
                eventos.append(ev)
        if ev := self.encerrar():
            eventos.append(ev)
        return eventos
