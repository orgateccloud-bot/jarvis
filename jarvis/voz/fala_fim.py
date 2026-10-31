"""Recorte da fala depois do disparo: começo (pré-gravação aparada pelo VAD) e fim (silêncio de `silencio_ms`)."""

from __future__ import annotations

import math

import numpy as np

from jarvis.voz.config import LIMIAR_VAD, QUADRO, TAXA
from jarvis.voz.vad import Vad

SEG_QUADRO = QUADRO / TAXA   # 0,08 s
SILENCIO_MS = 700            # fim de fala (SUPOSIÇÃO do plano; medido na fase 2b)
MAX_S = 15.0                 # teto de uma fala
FOLGA_INICIO = 2             # quadros mantidos antes da primeira voz (160 ms)
LACUNA_MAX = 4               # pausa tolerada dentro da mesma fala ao procurar o começo ("Ok, ... Jarvis")


def inicio_da_fala(probs: list[float], limiar: float = LIMIAR_VAD) -> int | None:
    """Índice do primeiro quadro com voz na ÚLTIMA fala contínua de `probs` (o mais novo por último).
    Pausas de até LACUNA_MAX quadros contam como a mesma fala; antes disso é outra conversa ou silêncio."""
    inicio, lacuna = None, 0
    for i in range(len(probs) - 1, -1, -1):
        if probs[i] >= limiar:
            inicio, lacuna = i, 0
        elif inicio is not None:
            lacuna += 1
            if lacuna > LACUNA_MAX:
                break
    return inicio


class FimDeFala:
    """Junta os quadros de uma fala. `adicionar` devolve True quando a fala acabou."""

    def __init__(self, vad: Vad, limiar: float = LIMIAR_VAD, silencio_ms: int = SILENCIO_MS, max_s: float = MAX_S):
        self.vad = vad
        self.limiar = limiar
        self.n_silencio = math.ceil(silencio_ms / 1000 / SEG_QUADRO)
        self.max_quadros = int(max_s / SEG_QUADRO)
        self.iniciar([], [])

    def iniciar(self, preroll: list[np.ndarray], probs: list[float]) -> None:
        """preroll: quadros antes do disparo; probs: VAD desses quadros (alinhados pelo fim)."""
        probs = list(probs)[-len(preroll):] if preroll else []
        probs = [0.0] * (len(preroll) - len(probs)) + probs
        i = inicio_da_fala(probs, self.limiar)
        corte = max(0, (i if i is not None else len(preroll)) - FOLGA_INICIO)
        self.quadros: list[np.ndarray] = list(preroll[corte:])
        self.primeira_voz = (i - corte) if i is not None else None
        self.ultima_voz = len(self.quadros) - 1 if i is not None else None
        self.silencio = 0

    def adicionar(self, quadro: np.ndarray, prob: float | None = None) -> bool:
        """prob: VAD do quadro, se o chamador já calculou (rodar o VAD duas vezes no mesmo quadro corromperia o
        estado interno dele)."""
        self.quadros.append(quadro)
        if (self.vad(quadro) if prob is None else prob) >= self.limiar:
            self.silencio = 0
            self.ultima_voz = len(self.quadros) - 1
            if self.primeira_voz is None:
                self.primeira_voz = self.ultima_voz
        else:
            self.silencio += 1
        return self.silencio >= self.n_silencio or len(self.quadros) >= self.max_quadros

    @property
    def audio(self) -> np.ndarray:
        return np.concatenate(self.quadros) if self.quadros else np.zeros(0, dtype=np.int16)

    @property
    def duracao_fala_s(self) -> float:
        if self.primeira_voz is None or self.ultima_voz is None:
            return 0.0
        return (self.ultima_voz - self.primeira_voz + 1) * SEG_QUADRO

    @property
    def quadros_desde_a_voz(self) -> int:
        """Quadros depois do último com voz: (quadros_desde_a_voz × 80 ms) = quanto o fim de fala esperou."""
        return len(self.quadros) - 1 - (self.ultima_voz if self.ultima_voz is not None else -1)
