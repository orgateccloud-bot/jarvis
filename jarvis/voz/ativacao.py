"""Palavra de ativação: os 3 modelos ONNX do openWakeWord (melspectrograma → embedding → "hey jarvis"), rodados
direto no onnxruntime.

O pacote openwakeword faz a mesma conta, mas importa scipy e scikit-learn ao ser carregado: medido nesta máquina,
136 MB de memória privada contra 37 MB das 3 sessões ONNX. A sequência abaixo segue openwakeword/utils.py
(AudioFeatures._streaming_features) e model.py (predict) da versão 0.6.0, para quadros de exatamente 80 ms.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

from jarvis.voz.config import LIMIAR_ATIVACAO, LIMIAR_VAD, QUADRO, TAXA
from jarvis.voz.vad import Vad

_MEL_CONTEXTO = 160 * 3   # amostras anteriores que o melspectrograma precisa para emendar os quadros
_MEL_MAX = 10 * 97        # ~10 s de quadros de melspectrograma
_JANELA_MEL = 76          # quadros de mel por embedding
_PASSO_MEL = 8            # quadros de mel novos a cada 80 ms
_FEAT_MAX = 120           # ~10 s de embeddings
_AQUECIMENTO = 5          # o openWakeWord zera as 5 primeiras previsões (buffers ainda frios)


def _sessao(path: Path) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1  # 1 thread: a meta é < 5% de CPU em repouso
    so.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


@dataclass(frozen=True)
class Disparo:
    score: float
    voz: float   # probabilidade de voz no trecho da palavra (VAD)
    quadro: int  # índice do quadro de 80 ms em que o score passou do limiar
    voz_recente: tuple[float, ...] = ()  # VAD dos últimos quadros (o mais novo por último): acha o começo da fala


class Ativacao:
    """Recebe quadros de 1.280 amostras int16 e devolve o score de "hey jarvis" (0 a 1) de cada um.

    O disparo exige as duas coisas: score >= limiar e voz detectada pelo VAD no trecho da palavra.
    """

    def __init__(self, pasta: Path, modelo: str = "hey_jarvis_v0.1.onnx", limiar: float = LIMIAR_ATIVACAO,
                 limiar_vad: float = LIMIAR_VAD):
        self.limiar = limiar
        self.limiar_vad = limiar_vad
        self.vad = Vad(pasta / "silero_vad.onnx")
        self._mel = _sessao(pasta / "melspectrogram.onnx")
        self._emb = _sessao(pasta / "embedding_model.onnx")
        self._ww = _sessao(pasta / modelo)
        self._ww_in = self._ww.get_inputs()[0].name
        self._n_feat = self._ww.get_inputs()[0].shape[1]  # 16 embeddings (~1,3 s) por previsão
        self.reset()

    def reset(self) -> None:
        """Esvazia os buffers: usado depois de cada disparo e ao reabrir o microfone após a fala do JARVIS."""
        self._bruto: deque[int] = deque(maxlen=TAXA * 10)
        self._mels = np.ones((_JANELA_MEL, 32), dtype=np.float32)
        # o original aquece com 4 s de ruído aleatório; aqui a semente é fixa para o resultado ser reproduzível
        ruido = np.random.default_rng(0).integers(-1000, 1000, TAXA * 4).astype(np.int16)
        self._feats = self._embeddings_do_clip(ruido)
        self._n = 0
        self.vad.reset()

    def _melspec(self, x: np.ndarray) -> np.ndarray:
        spec = self._mel.run(None, {"input": x.astype(np.float32)[None, :]})[0]
        return np.squeeze(spec) / 10 + 2  # mesma transformação do openWakeWord (aproxima do TensorFlow original)

    def _embedding(self, mels: np.ndarray) -> np.ndarray:
        return self._emb.run(None, {"input_1": mels.astype(np.float32)[None, :, :, None]})[0].squeeze()

    def _embeddings_do_clip(self, x: np.ndarray) -> np.ndarray:
        mels = self._melspec(x)
        n = (mels.shape[0] - _JANELA_MEL) // _PASSO_MEL + 1
        return np.vstack([self._embedding(mels[i * _PASSO_MEL:i * _PASSO_MEL + _JANELA_MEL]) for i in range(n)])

    def score(self, quadro: np.ndarray) -> float:
        if quadro.shape != (QUADRO,) or quadro.dtype != np.int16:
            raise ValueError(f"quadro precisa ter {QUADRO} amostras int16, veio {quadro.shape} {quadro.dtype}")
        self._bruto.extend(quadro.tolist())
        recentes = np.fromiter(self._bruto, dtype=np.int16)[-(QUADRO + _MEL_CONTEXTO):]
        self._mels = np.vstack((self._mels, self._melspec(recentes)))[-_MEL_MAX:]
        self._feats = np.vstack((self._feats, self._embedding(self._mels[-_JANELA_MEL:])))[-_FEAT_MAX:]
        entrada = self._feats[-self._n_feat:][None, :].astype(np.float32)
        s = float(self._ww.run(None, {self._ww_in: entrada})[0].squeeze())
        self._n += 1
        return 0.0 if self._n <= _AQUECIMENTO else s

    def confirma(self, score: float) -> bool:
        """O score do quadro passou do limiar E o VAD ouviu voz no trecho da palavra (ruído não tem voz)."""
        return score >= self.limiar and self.vad.voz_na_palavra() >= self.limiar_vad

    def processar(self, quadro: np.ndarray) -> Disparo | None:
        """Um Disparo quando o score passa do limiar com voz no trecho; aí os buffers são zerados (debounce)."""
        s = self.score(quadro)
        self.vad(quadro)  # roda sempre: o histórico do VAD precisa estar em dia quando o score subir
        if not self.confirma(s):
            return None
        voz = self.vad.voz_na_palavra()
        d = Disparo(s, voz, self._n, tuple(self.vad.historico))
        self.reset()
        return d

    def disparos_do_clip(self, audio: np.ndarray) -> list[Disparo]:
        """Simula a escuta contínua num áudio inteiro (testes e medição)."""
        self.reset()
        n = len(audio) // QUADRO
        return [d for i in range(n) if (d := self.processar(audio[i * QUADRO:(i + 1) * QUADRO]))]

    def scores_do_clip(self, audio: np.ndarray) -> list[float]:
        """Simula o streaming num áudio inteiro (testes e medição): um score por quadro de 80 ms."""
        self.reset()
        n = len(audio) // QUADRO
        return [self.score(audio[i * QUADRO:(i + 1) * QUADRO]) for i in range(n)]
