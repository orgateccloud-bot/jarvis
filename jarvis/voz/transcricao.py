"""Transcrição local com faster-whisper (CTranslate2), carregado só de pasta local: nada é baixado em execução."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Transcricao:
    texto: str
    no_speech_prob: float  # o maior entre os segmentos: alto = provavelmente não havia fala
    avg_logprob: float     # o menor entre os segmentos: baixo = o modelo estava inseguro
    segundos: float        # tempo gasto na transcrição


DICA = "Jarvis"  # hotwords: medido na 2b, o small sem a dica ouvia "Javes" e "já avise" na voz Daniel
# Teto de tokens pela duração do áudio. Com ruído o Whisper às vezes entra em laço ("dois, três, dois, três..." levou
# 2,5 s em 31/10, e a fila do Whisper é uma só); fala rápida em português dá uns 6 tokens/s, então 10/s é folga.
TOKENS_POR_S, TOKENS_FOLGA, TOKENS_MAX = 10, 16, 300


class Transcritor:
    def __init__(self, pasta: Path, device: str = "cuda", compute_type: str = "float16", threads: int = 4,
                 janela: int = 30, dica: str | None = DICA):
        os.environ["HF_HUB_OFFLINE"] = "1"  # garantia extra: com pasta local a biblioteca não consulta o Hub
        if device == "cuda":
            from jarvis.voz.cuda import preparar

            preparar()
        from faster_whisper import WhisperModel

        self.config = f"{pasta.name}:{device}:{compute_type}:{janela}"
        self.janela = janela  # o Whisper completa todo áudio até a janela (30 s); menor = encoder mais rápido
        self.dica = dica
        self.modelo = WhisperModel(str(pasta), device=device, compute_type=compute_type, cpu_threads=threads,
                                   local_files_only=True)

    def transcrever(self, audio: np.ndarray) -> Transcricao:
        """audio: int16 a 16 kHz, mono."""
        x = audio.astype(np.float32) / 32768.0
        tokens = min(TOKENS_MAX, TOKENS_FOLGA + int(TOKENS_POR_S * len(x) / 16000))
        t0 = time.perf_counter()
        # beam 1 e temperatura fixa: sem as novas tentativas do Whisper, a latência fica previsível
        segmentos, _ = self.modelo.transcribe(x, language="pt", beam_size=1, temperature=0.0, vad_filter=False,
                                              condition_on_previous_text=False, without_timestamps=True,
                                              hotwords=self.dica, chunk_length=self.janela, max_new_tokens=tokens)
        segmentos = list(segmentos)  # o gerador só decodifica quando é percorrido
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        return Transcricao(
            texto=texto,
            no_speech_prob=max((s.no_speech_prob for s in segmentos), default=1.0),
            avg_logprob=min((s.avg_logprob for s in segmentos), default=-10.0),
            segundos=time.perf_counter() - t0,
        )


def criar_transcritor(pasta: Path, forcar: str | None = None) -> Transcritor:
    """O Whisper escolhido na fase 2b: na GPU se houver (JARVIS_VOZ_DEVICE=cpu força a CPU)."""
    from jarvis.voz.config import WHISPER_CPU, WHISPER_GPU
    from jarvis.voz.cuda import gpu_disponivel

    forcar = forcar or os.getenv("JARVIS_VOZ_DEVICE", "")
    device, compute = WHISPER_GPU if forcar != "cpu" and gpu_disponivel() else WHISPER_CPU
    return Transcritor(pasta, device, compute)
