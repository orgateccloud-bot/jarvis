"""Grava a voz do usuário para medir a ativação (e, na fase 2b, o acerto do Whisper). Fica FORA do git.

    python -m jarvis.voz.gravar              grava ~60 frases curtas (Enter antes de cada uma, 3 s cada)
    python -m jarvis.voz.gravar --avaliar    mede a ativação nas gravações, por categoria e por limiar

Destino: JARVIS_VOZ_DIR\\gravacoes (padrão D:\\JARVIS-Voz\\gravacoes), com indice.json (arquivo → frase).
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from jarvis.voz import offline
from jarvis.voz.config import QUADRO, TAXA, pastas

SEGUNDOS = 3.0
# categoria → (frases, repetições). "negativo" inclui as palavras que o reconhecimento confunde com "Jarvis".
ROTEIRO = {
    "ativacao": ([
        "Jarvis.",
        "Jarvis, que horas são?",
        "Jarvis, como está o disco?",
        "Jarvis, me lembra de beber água.",
        "Ok, Jarvis.",
        "Ok Jarvis, que horas são?",
        "Jarvis, pare.",
    ], 4),
    "negativo": ([
        "Que horas são?",
        "O disco está quase cheio.",
        "Vou sair para almoçar agora.",
        "Graves problemas no servidor.",
        "O Jarbas já chegou?",
        "Ok, pode ser.",
        "Abre o navegador para mim.",
        "Travis mandou a planilha.",
        "Amanhã tem reunião às nove.",
        "O jardim está bonito hoje.",
    ], 3),
}
LIMIARES = (0.2, 0.3, 0.4, 0.5)


def salvar_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(audio.astype(np.int16).tobytes())


def ler_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (TAXA, 1, 2):
            raise ValueError(f"{path.name}: precisa ser 16 kHz, mono, 16 bits")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def gravar(destino: Path, microfone: str | None) -> None:
    import sounddevice as sd

    from jarvis.voz.captura import escolher

    destino.mkdir(parents=True, exist_ok=True)
    indice_path = destino / "indice.json"
    indice = json.loads(indice_path.read_text(encoding="utf-8")) if indice_path.exists() else {}
    dispositivo = escolher(microfone)
    total = sum(len(f) * r for f, r in ROTEIRO.values())
    n = 0
    for cat, (frases, reps) in ROTEIRO.items():
        for rep in range(reps):
            for i, frase in enumerate(frases):
                n += 1
                nome = f"{cat}_{i:02d}_{rep}.wav"
                input(f"[{n}/{total}] Enter, espere o \u201cfale\u201d e diga: \u201c{frase}\u201d ")
                # a grava\u00e7\u00e3o come\u00e7a ANTES do aviso: na 1\u00aa rodada, falas ditas logo ap\u00f3s o Enter sa\u00edram cortadas
                audio = sd.rec(int((SEGUNDOS + 0.5) * TAXA), samplerate=TAXA, channels=1, dtype="int16",
                               device=dispositivo)
                sd.sleep(500)
                print("   fale")
                sd.wait()
                salvar_wav(destino / nome, audio[:, 0])
                indice[nome] = {"categoria": cat, "frase": frase}
                indice_path.write_text(json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{n} gravações em {destino} (fora do git).")


def avaliar(origem: Path) -> dict:
    from jarvis.voz.ativacao import Ativacao

    indice = json.loads((origem / "indice.json").read_text(encoding="utf-8"))
    atv = Ativacao(pastas().ativacao)
    pad = np.zeros(TAXA, dtype=np.int16)  # 1 s de silêncio antes e depois, como numa escuta contínua
    maximos: dict[str, list[tuple[str, float]]] = {}
    for nome, reg in sorted(indice.items()):
        a = np.concatenate([pad, ler_wav(origem / nome), pad])
        a = a[: len(a) // QUADRO * QUADRO]
        maximos.setdefault(reg["categoria"], []).append((reg["frase"], max(atv.scores_do_clip(a))))
    rel = {}
    for cat, itens in maximos.items():
        rel[cat] = {f"limiar_{lim}": round(sum(s >= lim for _, s in itens) / len(itens), 3) for lim in LIMIARES}
        rel[cat]["n"] = len(itens)
        por_frase: dict[str, list[float]] = {}
        for frase, s in itens:
            por_frase.setdefault(frase, []).append(round(s, 3))
        rel[cat]["scores_por_frase"] = por_frase
    return rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.voz.gravar", description=__doc__.splitlines()[0])
    ap.add_argument("--avaliar", action="store_true")
    ap.add_argument("--microfone", default="")
    args = ap.parse_args(argv)
    offline.ativar()
    p = pastas()
    if args.avaliar:
        print(json.dumps(avaliar(p.gravacoes), indent=2, ensure_ascii=False))
    else:
        gravar(p.gravacoes, args.microfone or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
