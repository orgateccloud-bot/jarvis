"""Grava a voz do usuário para medir a ativação (e, na fase 2b, o acerto do Whisper). Fica FORA do git.

    python -m jarvis.voz.gravar              grava ~60 frases curtas (Enter antes de cada uma, 3 s cada)
    python -m jarvis.voz.gravar --avaliar    roda a escuta completa nas gravações e compara com o esperado

Destino: JARVIS_VOZ_DIR\\gravacoes (padrão D:\\JARVIS-Voz\\gravacoes), com indice.json (arquivo → frase).
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from jarvis.voz import offline
from jarvis.voz.config import TAXA, pastas

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


def esperado(categoria: str, frase: str) -> str | None:
    """O comando que a frase do roteiro deve gerar (None = nenhum: a fala não é para o JARVIS)."""
    if categoria == "negativo":
        return None
    return {"Jarvis.": "so_jarvis", "Ok, Jarvis.": "nova_conversa", "Jarvis, pare.": "parar"}.get(frase, "pergunta")


def avaliar(origem: Path) -> dict:
    """Roda a escuta completa (VAD → Whisper → comando) em cada gravação e compara com o esperado."""
    from jarvis.voz.ativacao import Ativacao
    from jarvis.voz.config import WHISPER
    from jarvis.voz.escuta import Escuta
    from jarvis.voz.transcricao import criar_transcritor

    indice = json.loads((origem / "indice.json").read_text(encoding="utf-8"))
    p = pastas()
    escuta = Escuta(Ativacao(p.ativacao), criar_transcritor(p.whisper(WHISPER)))
    escuta.transcritor.transcrever(np.zeros(TAXA, dtype=np.int16))  # aquecimento
    pad = np.zeros(TAXA, dtype=np.int16)  # 1 s de silêncio antes e depois, como numa escuta contínua
    rel: dict[str, dict] = {}
    latencias = []
    for nome, reg in sorted(indice.items()):
        eventos = escuta.processar_clip(np.concatenate([pad, ler_wav(origem / nome), pad]))
        latencias += [e.latencia_s for e in eventos]
        obtidos = [e.comando.tipo for e in eventos if e.comando.tipo != "nada"]
        alvo = esperado(reg["categoria"], reg["frase"])
        ok = obtidos == ([] if alvo is None else [alvo])
        cat = rel.setdefault(reg["categoria"], {"acertos": 0, "n": 0, "erros": []})
        cat["acertos"] += ok
        cat["n"] += 1
        if not ok:
            cat["erros"].append({"arquivo": nome, "frase": reg["frase"], "obtido": obtidos,
                                 "ouviu": [e.transcricao.texto for e in eventos]})
    latencias.sort()
    rel["latencia_mediana_s"] = round(latencias[len(latencias) // 2], 3) if latencias else None
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
