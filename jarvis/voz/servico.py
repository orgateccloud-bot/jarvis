"""O serviço de voz em execução: microfone → Escuta → Conversa → API local → voz local.

Decisão A (dono do microfone): a cada 1 s o serviço manda o batimento para a API e só abre o microfone quando a
resposta diz dono=servico. Sem resposta da API (caiu ou travou), fecha o microfone: sem API não há para onde
perguntar. A resposta do batimento também traz os comandos do HUD (ouvir, parar, mudo, som).
"""

from __future__ import annotations

import os
import threading
import time

import psutil
from loguru import logger

from jarvis.voz.captura import DetectorDeSilencio, Microfone
from jarvis.voz.cliente import Cliente
from jarvis.voz.conversa import Conversa
from jarvis.voz.escuta import Escuta
from jarvis.voz.fala import VozLocal

BATIMENTO_S = 1.0
# Esperas entre as tentativas de abrir o microfone que sumiu (depois da última, ela se repete). Cada tentativa
# reinicia o PortAudio para enxergar o aparelho que voltou: de 2 em 2 s por meia hora, foram mais de 800 (31/10).
ESPERAS_REABRIR_S = (2.0, 4.0, 8.0, 15.0, 30.0)
LEMBRETE_S = 300.0  # com o microfone fora há muito tempo, o log lembra a cada 5 min (o serviço segue vivo)


def texto_para_log(texto: str) -> str:
    """O texto transcrito só vai para o log com JARVIS_VOZ_LOG_TEXTO=1, com CPF/CNPJ mascarados."""
    if os.getenv("JARVIS_VOZ_LOG_TEXTO", "0") != "1":
        return f"<{len(texto)} caracteres>"
    from jarvis.core.privacy import sanitizar

    return repr(sanitizar(texto)[:200])


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
                try:
                    self.mic.abrir()
                except Exception as e:  # noqa: BLE001 — aparelho fora ao subir (ex.: receptor do K8 desligado)
                    logger.warning("voz: microfone {} indisponível ao abrir ({}); esperando ele voltar",
                                   self.mic.nome, e)
                    self._esperar_microfone()
                    continue
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
                if q is None and self.mic.parado() and not self.voz.falando:
                    logger.warning("voz: o microfone ({}) parou de entregar áudio; reabrindo", self.mic.nome)
                    self.escuta.descartar()
                    self._esperar_microfone()
                    break
                if q is None or fechar:
                    continue
                if aviso := silencio.alimentar(q):
                    if aviso == "mudo":
                        logger.warning("voz: o microfone só entrega silêncio digital há 10 s (desligado, mudo no "
                                       "aparelho ou receptor solto?); troque com JARVIS_VOZ_MICROFONE "
                                       "(python -m jarvis.voz --listar-microfones)")
                    else:
                        logger.info("voz: o microfone voltou a captar som")
                if ev := self.escuta.processar(q):
                    acao = self.conversa.ouvido(ev)
                    logger.info("voz: comando={} ação={} texto={} latência={:.2f}s whisper={:.3f}s", ev.comando.tipo,
                                acao, texto_para_log(ev.transcricao.texto), ev.latencia_s, ev.transcricao.segundos)
        self.mic.fechar()
        self.voz.encerrar()

    def _esperar_microfone(self) -> None:
        """O aparelho sumiu (receptor sem fio que reiniciou, cabo solto) ou não estava lá ao subir: reabre o mesmo
        aparelho até ele voltar, com esperas crescentes (2 s até 30 s). Nunca reinicia o PortAudio com a fala
        tocando, e o processo não cai: sem isso o serviço ficava "ouvindo" um stream morto, ou saía com código 1."""
        n, inicio = 0, time.monotonic()
        lembrete = inicio + LEMBRETE_S
        while not self.parar.is_set() and self.dono:
            if self.voz.falando:  # a fala usa o PortAudio: espera ela acabar
                self.parar.wait(0.5)
                continue
            try:
                self.mic.reabrir()
                logger.info("voz: microfone reaberto ({})", self.mic.nome)
                return
            except Exception as e:  # noqa: BLE001 — aparelho ainda fora: tenta de novo
                if n == 0:
                    logger.warning("voz: microfone ainda indisponível ({}); tentando de novo com espera crescente "
                                   "(até {:.0f} s)", e, ESPERAS_REABRIR_S[-1])
                elif time.monotonic() >= lembrete:
                    logger.warning("voz: ainda esperando o microfone {} ({:.0f} min)", self.mic.nome,
                                   (time.monotonic() - inicio) / 60)
                    lembrete = time.monotonic() + LEMBRETE_S
                self.parar.wait(ESPERAS_REABRIR_S[min(n, len(ESPERAS_REABRIR_S) - 1)])
                n += 1

def cliente_padrao() -> Cliente:
    from jarvis.config import get_settings

    s = get_settings()
    return Cliente(f"http://127.0.0.1:{s.port}", s.api_token())


def interromper_por_voz() -> bool:
    return os.getenv("JARVIS_VOZ_INTERROMPER", "0") == "1"
