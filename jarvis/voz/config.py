"""Constantes do áudio e onde ficam os modelos de voz (fora do repositório, em JARVIS_VOZ_DIR)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.config import Settings, get_settings

TAXA = 16_000          # Hz, mono, PCM 16 bits: o formato que o openWakeWord e o Whisper esperam
QUADRO = 1_280         # amostras = 80 ms; o openWakeWord pede múltiplos de 80 ms
LIMIAR_ATIVACAO = 0.3  # baixo de propósito: o candidato ainda passa pelo VAD (aqui) e pelo Whisper (fase 2b)
LIMIAR_VAD = 0.5       # o disparo só vale com voz no trecho da palavra (ruído puro chega a 0,45 no modelo)

# Release v0.5.1 do openWakeWord: as mesmas URLs de openwakeword/__init__.py, na versão ONNX (a única no Windows).
_OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
MODELOS_ATIVACAO = {
    "melspectrogram.onnx": _OWW + "melspectrogram.onnx",
    "embedding_model.onnx": _OWW + "embedding_model.onnx",
    "hey_jarvis_v0.1.onnx": _OWW + "hey_jarvis_v0.1.onnx",
    "silero_vad.onnx": _OWW + "silero_vad.onnx",  # VAD Silero (MIT) na versão usada pelo openWakeWord
}


@dataclass(frozen=True)
class Pastas:
    raiz: Path

    @property
    def modelos(self) -> Path:
        return self.raiz / "modelos"

    @property
    def ativacao(self) -> Path:
        return self.modelos / "openwakeword"

    @property
    def gravacoes(self) -> Path:
        """Gravações da voz do usuário para medir acerto: nunca entram no git."""
        return self.raiz / "gravacoes"

    @property
    def manifesto(self) -> Path:
        return self.modelos / "manifesto.json"


def pastas(settings: Settings | None = None) -> Pastas:
    return Pastas((settings or get_settings()).voz_dir())
