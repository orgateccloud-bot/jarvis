"""Detector de voz (VAD Silero em ONNX, sem PyTorch), na mesma forma que o openWakeWord usa (openwakeword/vad.py).

Na fase 2a confirma a ativação (ruído não tem voz); na 2b também marca o fim da fala.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
import onnxruntime as ort

from jarvis.voz.config import TAXA

SUBQUADRO = 640  # 40 ms: o openWakeWord chama o VAD com 160*4 amostras e tira a média por quadro de 80 ms


class Vad:
    def __init__(self, path: Path, historico: int = 125):
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self._s = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self._sr = np.array(TAXA, dtype=np.int64)
        self.historico: deque[float] = deque(maxlen=historico)  # uma probabilidade por quadro de 80 ms (~10 s)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self.historico.clear()

    def __call__(self, quadro: np.ndarray) -> float:
        """Probabilidade de voz no quadro (0 a 1); fica guardada no histórico."""
        probs = []
        for i in range(0, len(quadro), SUBQUADRO):
            x = (quadro[i:i + SUBQUADRO] / 32767).astype(np.float32)[None, :]
            out, self._h, self._c = self._s.run(None, {"input": x, "h": self._h, "c": self._c, "sr": self._sr})
            probs.append(float(out[0][0]))
        p = float(np.mean(probs))
        self.historico.append(p)
        return p

    def voz_na_palavra(self) -> float:
        """Maior probabilidade de voz entre 560 e 320 ms atrás: o score da ativação sobe depois que a palavra
        termina, então a voz que importa ficou alguns quadros para trás (mesma janela [-7:-4] do openWakeWord)."""
        janela = list(self.historico)[-7:-4]
        return max(janela) if janela else 0.0
