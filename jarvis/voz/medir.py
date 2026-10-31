"""Mede o Whisper em várias configurações, cada uma num processo próprio (RAM e VRAM isoladas).

    python -m jarvis.voz.medir                      roda a matriz e imprime a tabela
    python -m jarvis.voz.medir --uma small:cuda:float16:30   (interno) mede uma configuração e imprime JSON

Áudios: os WAVs sintéticos de tests/fixtures/voz (textos em textos.json) e, se existirem, as gravações do usuário
(JARVIS_VOZ_DIR/gravacoes/indice.json). Taxa de erro de palavras (WER) depois de corrigir_termos, como no serviço.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess  # nosec B404
import sys
import time
import wave
from pathlib import Path

from jarvis.config import ROOT
from jarvis.voz.config import TAXA, pastas

FIXTURES = ROOT / "tests" / "fixtures" / "voz"
MATRIZ = [  # modelo:device:compute:janela (s)
    "base:cuda:float16:30", "small:cuda:float16:30", "small:cuda:int8_float16:30", "small:cuda:int8:30",
    "small:cuda:float16:10", "small:cuda:int8_float16:10", "small:cpu:int8:30", "base:cpu:int8:30",
]


def _wav(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def amostras() -> list[tuple[str, Path, str]]:
    """(origem, arquivo, texto de referência)."""
    itens = [("sintetico", FIXTURES / f"{n}.wav", t)
             for n, t in json.loads((FIXTURES / "textos.json").read_text(encoding="utf-8")).items()]
    g = pastas().gravacoes / "indice.json"
    if g.exists():
        itens += [("usuario", g.parent / n, r["frase"]) for n, r in json.loads(g.read_text(encoding="utf-8")).items()]
    return itens


def wer(ref: str, hip: str) -> tuple[int, int]:
    """(erros, palavras da referência): distância de edição por palavra."""
    from jarvis.voz.texto import corrigir_termos, palavras

    r, h = palavras(corrigir_termos(ref)), palavras(corrigir_termos(hip))
    ant = list(range(len(h) + 1))
    for i, pr in enumerate(r, 1):
        cur = [i]
        for j, ph in enumerate(h, 1):
            cur.append(min(ant[j] + 1, cur[j - 1] + 1, ant[j - 1] + (pr != ph)))
        ant = cur
    return ant[-1], len(r)


def _gpu_mb() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],  # nosec
                             capture_output=True, text=True, check=True, timeout=10).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def medir_uma(spec: str) -> dict:
    import numpy as np
    import psutil

    from jarvis.voz.transcricao import Transcritor

    nome, device, compute, janela = spec.split(":")
    proc = psutil.Process()
    gpu0, ram0 = _gpu_mb(), proc.memory_full_info()
    t0 = time.perf_counter()
    tr = Transcritor(pastas().whisper(nome), device, compute, janela=int(janela))
    carga = time.perf_counter() - t0
    tr.transcrever(np.zeros(TAXA, dtype=np.int16))  # aquecimento (primeira chamada aloca na GPU)
    gpu1 = _gpu_mb()
    silencio = tr.transcrever(np.zeros(TAXA * 3, dtype=np.int16))
    res = {}
    for origem, arq, ref in amostras():
        r = tr.transcrever(_wav(arq))
        e, n = wer(ref, r.texto)
        d = res.setdefault(origem, {"erros": 0, "palavras": 0, "lat": [], "exemplos": []})
        d["erros"] += e
        d["palavras"] += n
        d["lat"].append(r.segundos)
        if e:
            d["exemplos"].append(f"{ref!r} -> {r.texto!r}")
    ram = proc.memory_full_info()
    saida = {"config": spec, "carga_s": round(carga, 2), "ram_rss_mb": round(ram.rss / 2**20),
             "ram_privada_mb": round(ram.uss / 2**20), "ram_privada_antes_mb": round(ram0.uss / 2**20),
             "vram_mb": (gpu1 - gpu0) if device == "cuda" and gpu0 is not None and gpu1 is not None else 0,
             "silencio": {"texto": silencio.texto, "no_speech_prob": round(silencio.no_speech_prob, 2)}}
    for origem, d in res.items():
        lat = sorted(d["lat"])
        saida[origem] = {"wer_pct": round(100 * d["erros"] / max(d["palavras"], 1), 1), "n": len(lat),
                         "lat_mediana_s": round(statistics.median(lat), 3), "lat_max_s": round(lat[-1], 3),
                         "erros": d["exemplos"][:6]}
    return saida


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.voz.medir")
    ap.add_argument("--uma", help="mede uma configuração modelo:device:compute:janela (uso interno)")
    ap.add_argument("--matriz", nargs="*", default=MATRIZ)
    args = ap.parse_args(argv)
    if args.uma:
        from jarvis.voz import offline

        offline.ativar()
        print(json.dumps(medir_uma(args.uma), ensure_ascii=False))
        return 0
    resultados = []
    for spec in args.matriz:
        r = subprocess.run([sys.executable, "-m", "jarvis.voz.medir", "--uma", spec],  # nosec B603
                           capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                           cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        linha = (r.stdout.strip().splitlines() or [""])[-1]
        try:
            resultados.append(json.loads(linha))
        except json.JSONDecodeError:
            resultados.append({"config": spec, "erro": (r.stderr or r.stdout).strip()[-400:]})
        print(json.dumps(resultados[-1], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
