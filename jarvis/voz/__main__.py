"""python -m jarvis.voz: serviço de escuta local.

Fase 2a: escuta o microfone e só registra no log cada ativação ("Jarvis"); ainda não transcreve nem responde.

    python -m jarvis.voz --listar-microfones
    python -m jarvis.voz [--microfone "K8"] [--limiar 0.3]
    python -m jarvis.voz --medir 600          roda 10 min e imprime CPU, RAM, quadros e disparos (JSON)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import psutil
from loguru import logger

from jarvis.config import ROOT
from jarvis.voz import offline
from jarvis.voz.config import LIMIAR_ATIVACAO, MODELOS_ATIVACAO, pastas


def _logs() -> None:
    logger.remove()
    if sys.stderr is not None:  # sem console (pythonw) não há stderr
        logger.add(sys.stderr, level="INFO")
    (ROOT / "logs").mkdir(exist_ok=True)
    logger.add(ROOT / "logs" / "voz.log", level="INFO", rotation="10 MB", retention="30 days", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.voz", description="Escuta local do JARVIS (fase 2a).")
    ap.add_argument("--listar-microfones", action="store_true")
    ap.add_argument("--microfone", default=os.getenv("JARVIS_VOZ_MICROFONE", ""),
                    help="parte do nome do microfone (padrão: o do Windows)")
    ap.add_argument("--limiar", type=float, default=LIMIAR_ATIVACAO)
    ap.add_argument("--medir", type=float, default=0, metavar="SEGUNDOS")
    args = ap.parse_args(argv)
    _logs()
    offline.ativar()  # antes de qualquer import pesado: nada neste processo sai do PC

    from jarvis.voz.captura import Microfone, escolher, microfones

    if args.listar_microfones:
        for i, nome in microfones():
            print(f"{i:3d}  {nome}")
        return 0

    from jarvis.voz.ativacao import Ativacao
    from jarvis.voz.baixar import verificar

    p = pastas()
    if erros := verificar(p, list(MODELOS_ATIVACAO)):
        for e in erros:
            logger.error("modelo de voz: {}", e)
        return 2

    atv = Ativacao(p.ativacao, limiar=args.limiar)
    proc = psutil.Process()
    proc.cpu_percent(None)
    t0, quadros, disparos = time.monotonic(), 0, 0
    mic = Microfone(escolher(args.microfone))
    try:
        with mic:
            logger.info("ouvindo só a palavra de ativação (limiar {:.2f})", args.limiar)
            for q in mic.quadros():
                if args.medir and time.monotonic() - t0 >= args.medir:
                    break
                if q is None:
                    continue
                quadros += 1
                if d := atv.processar(q):
                    disparos += 1
                    logger.info("ativação: score={:.3f}", d.score)  # nenhum áudio é gravado
    except KeyboardInterrupt:
        pass

    if args.medir:
        cpu_nucleo = proc.cpu_percent(None)  # média desde o início, em % de UM núcleo
        mem = proc.memory_full_info()
        print(json.dumps({
            "segundos": round(time.monotonic() - t0, 1),
            "quadros": quadros,
            "quadros_perdidos": mic.perdidos,
            "disparos": disparos,
            "cpu_pct_de_um_nucleo": round(cpu_nucleo, 2),
            "cpu_pct_do_total": round(cpu_nucleo / psutil.cpu_count(), 2),
            "ram_rss_mb": round(mem.rss / 2**20),
            "ram_privada_mb": round(mem.uss / 2**20),
            "rede_bloqueada": offline.bloqueadas(),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
