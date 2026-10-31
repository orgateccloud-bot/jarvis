"""Laço da escuta: quadro a quadro, VAD → recorte da fala → Whisper → comando (Decisão B).

Ativação pelo Whisper (decisão de 31/10, depois das gravações do usuário): o modelo pronto "hey jarvis" só pegou
8 de 28 falas com "Jarvis" na voz dele; o Whisper, com a dica "Jarvis", ouviu o vocativo em 23 de 28. Então toda
fala curta (até MAX_CURTA_S) é transcrita e só vale se começar pelo vocativo (comando.classificar). O modelo pronto
fica como atalho: uma fala mais longa só é transcrita se ele disparou nela.

Fase 2b: devolve o Evento e o chamador só registra no log. Na 2c o Evento vira pergunta à API e resposta falada.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from jarvis.voz.ativacao import Ativacao
from jarvis.voz.comando import Comando, classificar
from jarvis.voz.config import QUADRO
from jarvis.voz.fala_fim import SEG_QUADRO, SILENCIO_MS, FimDeFala
from jarvis.voz.transcricao import Transcricao, Transcritor

PREROLL = 6           # quadros antes da 1ª voz (480 ms): o VAD demora um pouco a subir no começo da fala
MIN_FALA_S = 0.3      # mais curto que isso é estalo, tosse ou batida: nem vai ao Whisper
MAX_CURTA_S = 8.0     # falas mais longas (conversa, TV) só vão ao Whisper se o modelo pronto disparou nelas


@dataclass(frozen=True)
class Evento:
    comando: Comando
    transcricao: Transcricao
    duracao_fala_s: float
    espera_fim_s: float   # silêncio esperado para decidir que a fala acabou
    latencia_s: float     # do último quadro com voz até a transcrição pronta (espera_fim_s + Whisper)
    atalho: bool          # o modelo pronto "hey jarvis" também disparou nesta fala


@dataclass
class Contagem:
    falas: int = 0          # trechos de voz recortados pelo VAD
    curtas_demais: int = 0
    longas_sem_atalho: int = 0
    transcritas: int = 0
    comandos: dict = field(default_factory=dict)  # tipo do comando → quantas


class Escuta:
    def __init__(self, ativacao: Ativacao, transcritor: Transcritor, silencio_ms: int = SILENCIO_MS):
        self.ativacao = ativacao
        self.transcritor = transcritor
        self.fim = FimDeFala(ativacao.vad, silencio_ms=silencio_ms)
        self._preroll: deque[tuple[np.ndarray, float]] = deque(maxlen=PREROLL)
        self.gravando = False
        self._atalho = False
        self.contagem = Contagem()

    def processar(self, quadro: np.ndarray) -> Evento | None:
        s = self.ativacao.score(quadro)   # modelo pronto: só o atalho para falas longas
        p = self.ativacao.vad(quadro)     # um VAD por quadro, compartilhado com o recorte da fala
        if not self.gravando:
            self._preroll.append((quadro, p))
            if p >= self.fim.limiar:      # começou uma fala
                quadros, probs = zip(*self._preroll, strict=True)
                self.fim.iniciar(list(quadros), list(probs))
                self.gravando, self._atalho = True, self.ativacao.confirma(s)
            return None
        self._atalho = self._atalho or self.ativacao.confirma(s)
        if not self.fim.adicionar(quadro, p):
            return None
        return self._encerrar()

    def encerrar(self) -> Evento | None:
        """Fecha uma fala em andamento (fim do áudio de teste ou desligamento)."""
        return self._encerrar() if self.gravando else None

    def _encerrar(self) -> Evento | None:
        c = self.contagem
        c.falas += 1
        duracao, atalho = self.fim.duracao_fala_s, self._atalho
        espera = self.fim.quadros_desde_a_voz * SEG_QUADRO
        audio = self.fim.audio
        self.gravando, self._atalho = False, False
        self._preroll.clear()
        self.ativacao.reset()  # zera também o VAD: a próxima fala começa do zero
        if duracao < MIN_FALA_S:
            c.curtas_demais += 1
            return None
        if duracao > MAX_CURTA_S and not atalho:
            c.longas_sem_atalho += 1
            return None
        tr = self.transcritor.transcrever(audio)
        cmd = classificar(tr.texto, duracao, tr.no_speech_prob)
        c.transcritas += 1
        c.comandos[cmd.tipo] = c.comandos.get(cmd.tipo, 0) + 1
        return Evento(cmd, tr, duracao, espera, espera + tr.segundos, atalho)

    def processar_clip(self, audio: np.ndarray) -> list[Evento]:
        """Simula a escuta contínua num áudio inteiro (testes e medição). Inclui os eventos "nada"."""
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
