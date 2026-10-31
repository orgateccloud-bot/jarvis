"""python -m jarvis.voz: serviço de escuta local.

Microfone → recorte da fala (VAD) → Whisper local, que também é a ativação ("Jarvis" no começo da fala) →
comando (Decisão B) → a mesma pergunta do HUD à API local → resposta falada com a voz local (Daniel).
Com JARVIS_VOZ_LOCAL=1 a API sobe e supervisiona este processo; ele também roda sozinho para diagnóstico:

    python -m jarvis.voz --listar-microfones
    python -m jarvis.voz [--microfone "K8"] [--cpu]       serviço completo (precisa da API no ar)
    python -m jarvis.voz --sem-api                        só escuta e registra no log (fase 2b)
    python -m jarvis.voz --medir 600                      sem API: 10 min e imprime CPU, RAM, falas e latências

O texto transcrito só vai para o log com JARVIS_VOZ_LOG_TEXTO=1, e passa por sanitizar() (CPF/CNPJ mascarados).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

import psutil
from loguru import logger

from jarvis.config import ROOT
from jarvis.voz import offline
from jarvis.voz.config import LIMIAR_ATIVACAO, MODELOS_ATIVACAO, TAXA, WHISPER, pastas


def _logs() -> None:
    logger.remove()
    if sys.stderr is not None:  # sem console (pythonw) não há stderr
        logger.add(sys.stderr, level="INFO")
    (ROOT / "logs").mkdir(exist_ok=True)
    logger.add(ROOT / "logs" / "voz.log", level="INFO", rotation="10 MB", retention="30 days", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.voz", description="Escuta por voz local do JARVIS.")
    ap.add_argument("--listar-microfones", action="store_true")
    ap.add_argument("--microfone", default=os.getenv("JARVIS_VOZ_MICROFONE", ""),
                    help="parte do nome do microfone (padrão: o do Windows)")
    ap.add_argument("--limiar", type=float, default=LIMIAR_ATIVACAO)
    ap.add_argument("--cpu", action="store_true", help="Whisper na CPU mesmo com GPU")
    ap.add_argument("--medir", type=float, default=0, metavar="SEGUNDOS")
    ap.add_argument("--sem-api", action="store_true", help="só escuta e registra no log")
    ap.add_argument("--pai", type=int, default=None, help="pid da API: o serviço termina junto com ela")
    args = ap.parse_args(argv)
    _logs()
    offline.ativar()  # antes de qualquer import pesado: nada neste processo sai do PC

    from jarvis.voz.captura import Microfone, escolher, microfones

    if args.listar_microfones:
        for i, nome in microfones():
            print(f"{i:3d}  {nome}")
        return 0

    import numpy as np

    from jarvis.voz.ativacao import Ativacao
    from jarvis.voz.baixar import verificar, verificar_whisper
    from jarvis.voz.escuta import Escuta
    from jarvis.voz.servico import texto_para_log
    from jarvis.voz.transcricao import criar_transcritor

    p = pastas()
    if erros := verificar(p, list(MODELOS_ATIVACAO)) + verificar_whisper(p, WHISPER):
        for e in erros:
            logger.error("modelo de voz: {}", e)
        return 2

    proc = psutil.Process()
    transcritor = criar_transcritor(p.whisper(WHISPER), "cpu" if args.cpu else None)
    transcritor.transcrever(np.zeros(TAXA, dtype=np.int16))  # aquecimento: a 1ª transcrição aloca na GPU (+0,3 s)
    escuta = Escuta(Ativacao(p.ativacao, limiar=args.limiar), transcritor)
    if not args.sem_api and not args.medir:
        from jarvis.voz.servico import Servico, cliente_padrao, interromper_por_voz

        srv = Servico(escuta, cliente_padrao(), Microfone(escolher(args.microfone)), interromper_por_voz(), args.pai)
        logger.info("voz: serviço local no ar (Whisper {}; interromper por voz: {})", transcritor.config,
                    srv.conversa.interromper)
        try:
            srv.rodar()
        except KeyboardInterrupt:
            srv.parar.set()
        return 0
    proc.cpu_percent(None)
    t0, quadros, eventos = time.monotonic(), 0, []
    mic = Microfone(escolher(args.microfone))
    try:
        with mic:
            logger.info("ouvindo (ativação pelo Whisper {}; atalho hey_jarvis {:.2f})", transcritor.config, args.limiar)
            for q in mic.quadros():
                if args.medir and time.monotonic() - t0 >= args.medir:
                    break
                if q is None:
                    continue
                quadros += 1
                if ev := escuta.processar(q):
                    eventos.append(ev)
                    logger.info("fala: comando={} texto={} fala={:.2f}s espera_fim={:.2f}s whisper={:.3f}s "
                                "latencia={:.2f}s sem_fala={:.2f} atalho={}", ev.comando.tipo,
                                texto_para_log(ev.transcricao.texto), ev.duracao_fala_s, ev.espera_fim_s,
                                ev.transcricao.segundos, ev.latencia_s, ev.transcricao.no_speech_prob, ev.atalho)
    except KeyboardInterrupt:
        pass

    if args.medir:
        cpu_nucleo = proc.cpu_percent(None)  # média desde o início, em % de UM núcleo
        mem = proc.memory_full_info()
        lat = [e.latencia_s for e in eventos]
        print(json.dumps({
            "segundos": round(time.monotonic() - t0, 1),
            "whisper": transcritor.config,
            "quadros": quadros,
            "quadros_perdidos": mic.perdidos,
            "falas": escuta.contagem.falas,
            "falas_curtas_demais": escuta.contagem.curtas_demais,
            "falas_longas_sem_atalho": escuta.contagem.longas_sem_atalho,
            "transcritas": escuta.contagem.transcritas,
            "comandos": escuta.contagem.comandos,
            "latencia_mediana_s": round(statistics.median(lat), 3) if lat else None,
            "cpu_pct_de_um_nucleo": round(cpu_nucleo, 2),
            "cpu_pct_do_total": round(cpu_nucleo / psutil.cpu_count(), 2),
            "ram_rss_mb": round(mem.rss / 2**20),
            "ram_privada_mb": round(mem.uss / 2**20),
            "rede_bloqueada": offline.bloqueadas(),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
