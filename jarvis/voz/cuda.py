"""Bibliotecas CUDA do Whisper no Windows: cuBLAS 12 e cuDNN 9 vêm dos wheels oficiais da NVIDIA no .venv.

O README do faster-whisper chama esse caminho de "Linux only" porque lá basta o LD_LIBRARY_PATH; no Windows as
DLLs ficam em site-packages/nvidia/*/bin e precisam entrar na busca de DLLs antes de importar o ctranslate2.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_feito = False


def pastas_nvidia() -> list[Path]:
    bases = [Path(p) / "nvidia" for p in sys.path if p and Path(p, "nvidia").is_dir()]
    return [b for base in bases for b in sorted(base.glob("*/bin")) if b.is_dir()]


def preparar() -> list[Path]:
    """Põe as DLLs da NVIDIA na busca (idempotente). Devolve as pastas adicionadas."""
    global _feito
    pastas = pastas_nvidia()
    if _feito or os.name != "nt":
        return pastas
    for p in pastas:
        os.add_dll_directory(str(p))
    # o ctranslate2 carrega o cuBLAS sob demanda com LoadLibrary, que olha o PATH e não o add_dll_directory
    os.environ["PATH"] = os.pathsep.join([*map(str, pastas), os.environ.get("PATH", "")])
    _feito = True
    return pastas


def gpu_disponivel() -> bool:
    preparar()
    import ctranslate2

    return ctranslate2.get_cuda_device_count() > 0
