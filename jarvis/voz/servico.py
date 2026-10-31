"""O serviço de voz em execução: microfone → Escuta → Conversa → API local → voz local.

Decisão A (dono do microfone): a cada 1 s o serviço manda o batimento para a API e só abre o microfone quando a
resposta diz dono=servico. Sem resposta da API (caiu ou travou), fecha o microfone: sem API não há para onde
perguntar. A resposta do batimento também traz os comandos do HUD (ouvir, parar, mudo, som).
"""

from __future__ import annotations

import os
import threading

import psutil
from loguru import logger

from jarvis.voz.captura import DetectorDeSilencio, Microfone
from jarvis.voz.cliente import Cliente
from jarvis.voz.conversa import Conversa
from jarvis.voz.escuta import Escuta
from jarvis.voz.fala import VozLocal

BATIMENTO_S = 1.0


class Servico:
    def __init__(self, escuta: Escuta, cliente: Cliente, microfone: Microfone, interromper: bool = False,
                 pai: int | None = None, voz: VozLocal | None = None):
        self.escuta, self.cliente, self.mic = escuta, cliente, microfone
        self.pai = pai
        self.parar = threading.Event()
        self.dono = False
        self.voz = voz or VozLocal(ao_terminar=lambda: self.conversa.fala_terminou(),
                                   na_frase=lambda t: self.conversa.na_frase(t))
        self.conversa = Conversa(cliente, self.voz, interromper=interromper)

    # ---------- batimento e avisos ----------
    def _batimento(self) -> None:
        while not self.parar.is_set():
            try:
                r = self.cliente.batimento(self.conversa.estado())
                self.dono = r.get("dono") == "servico"
                for acao in r.get("comandos", []):
                    self.conversa.comando(acao)
            except Exception as e:  # noqa: BLE001 — qualquer falha = sem API = microfone fechado
                if self.dono:
                    logger.warning("voz: sem resposta da API ({}); microfone fechado", type(e).__name__)
                self.dono = False
            if self.pai and not psutil.pid_exists(self.pai):
                logger.info("voz: a API (pid {}) terminou; encerrando", self.pai)
                self.parar.set()
            self.parar.wait(BATIMENTO_S)

    def _avisos(self) -> None:
        while not self.parar.is_set():
            try:
                for ev in self.cliente.eventos():
                    if self.dono:
                        self.conversa.proativo(ev)
                    if self.parar.is_set():
                        return
            except Exception:  # noqa: BLE001
                self.parar.wait(2.0)

    # ---------- laço do áudio ----------
    def rodar(self) -> None:
        for alvo in (self._batimento, self._avisos):
            threading.Thread(target=alvo, name=alvo.__name__, daemon=True).start()
        mudo = False
        silencio = DetectorDeSilencio()
        while not self.parar.is_set():
            if not self.dono:
                if self.mic.aberto:
                    self.mic.fechar()
                    self.voz.cancelar()
                    self.escuta.descartar()
                    logger.info("voz: microfone fechado (dono: HUD ou API fora)")
                self.parar.wait(0.2)
                continue
            if not self.mic.aberto:
                self.mic.abrir()
                logger.info("voz: microfone aberto ({})", self.mic.nome)
            for q in self.mic.quadros(timeout=0.2):
                if self.parar.is_set() or not self.dono:
                    break
                self.conversa.tick()
                fechar = self.conversa.mic_fechado()
                if fechar != mudo:  # half-duplex: muda o microfone durante a fala e a cauda
                    mudo = self.mic.mudo = fechar
                    if fechar:
                        self.escuta.descartar()
                if q is None or fechar:
                    continue
                if aviso := silencio.alimentar(q):
                    if aviso == "mudo":
                        logger.warning("voz: o microfone só entrega silêncio absoluto há 10 s (desligado, mudo no "
                                       "aparelho ou receptor solto?); troque com JARVIS_VOZ_MICROFONE "
                                       "(python -m jarvis.voz --listar-microfones)")
                    else:
                        logger.info("voz: o microfone voltou a captar som")
                if ev := self.escuta.processar(q):
                    acao = self.conversa.ouvido(ev)
                    logger.info("voz: comando={} ação={} latência={:.2f}s whisper={:.3f}s", ev.comando.tipo,
                                acao, ev.latencia_s, ev.transcricao.segundos)
        self.mic.fechar()
        self.voz.encerrar()


def cliente_padrao() -> Cliente:
    from jarvis.config import get_settings

    s = get_settings()
    return Cliente(f"http://127.0.0.1:{s.port}", s.api_token())


def interromper_por_voz() -> bool:
    return os.getenv("JARVIS_VOZ_INTERROMPER", "0") == "1"
