"""Etapa 2 na API: supervisão do processo de voz local e dono do microfone (Decisão A, aprovada em 30/10).

Tudo aqui só existe com JARVIS_VOZ_LOCAL=1; com a flag em 0, a API não registra rotas nem sobe processo.

Dono do microfone: o serviço local, sempre que estiver vivo. O HUD só pega o microfone se o usuário pedir
(botão "usar o microfone do navegador" quando o serviço para), por uma concessão de 15 s que ele renova a cada 5 s;
fechou ou travou, a concessão vence e o microfone volta ao serviço. Um lado só captura por vez: o serviço abre o
microfone apenas quando o batimento responde dono=servico.
"""

from __future__ import annotations

import asyncio
import os
import subprocess  # nosec B404 — só o próprio Python, com argumentos fixos e sem shell
import sys
import time
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi import Path as Caminho
from loguru import logger
from pydantic import BaseModel

from ..config import ROOT

BATIMENTO_VIVO_S = 6.0     # sem batimento por mais que isso = parado
TRAVADO_S = 10.0           # processo vivo mas sem batimento = travado: o supervisor reinicia
CARGA_S = 60.0             # tolerância na subida (carregar o Whisper na GPU leva alguns segundos)
CONCESSAO_HUD_S = 15.0
ESPERAS_S = (1, 2, 5, 10, 30)
FALHAS_MAX, JANELA_FALHAS_S = 5, 300

EstadoServico = Literal["repouso", "ouvindo", "processando", "falando"]
Acao = Literal["ouvir", "parar", "mudo", "som"]


class Batimento(BaseModel):
    estado: EstadoServico


class Dono(BaseModel):
    dono: Literal["hud", "servico"]


class Comando(BaseModel):
    acao: Acao


class EstadoVoz:
    """Fonte única de quem é o dono do microfone e de como está o serviço."""

    def __init__(self, relogio: Callable[[], float] = time.monotonic,
                 ao_mudar: Callable[[str], None] = lambda _estado: None):
        self.relogio = relogio
        self.ao_mudar = ao_mudar  # avisa o HUD (evento "voz") quando o estado do serviço muda
        self.estado = "iniciando"
        self.ultimo: float | None = None
        self.hud_ate = 0.0
        self.comandos: list[str] = []
        self.situacao = "iniciando"  # do supervisor: iniciando | rodando | reiniciando | falhou | desligado

    def dono(self) -> str:
        return "hud" if self.relogio() < self.hud_ate else "servico"

    def vivo(self) -> bool:
        return self.ultimo is not None and self.relogio() - self.ultimo <= BATIMENTO_VIVO_S

    def batimento(self, estado: str) -> dict:
        if estado != self.estado or not self.vivo():
            self.ao_mudar(estado)
        self.estado, self.ultimo = estado, self.relogio()
        comandos, self.comandos = self.comandos, []
        return {"dono": self.dono(), "comandos": comandos}

    def resumo(self) -> dict:
        return {"ativo": True, "estado": self.estado if self.vivo() else "parado", "dono": self.dono(),
                "situacao": self.situacao}


class Supervisor:
    """Sobe python -m jarvis.voz, reinicia com espera crescente e desiste depois de 5 falhas em 5 min."""

    def __init__(self, estado: EstadoVoz, comando: list[str] | None = None, popen=subprocess.Popen,
                 dormir=asyncio.sleep, relogio: Callable[[], float] = time.monotonic):
        self.estado = estado
        self.comando = comando or [sys.executable, "-m", "jarvis.voz", "--pai", str(os.getpid())]
        self._popen, self._dormir, self.relogio = popen, dormir, relogio
        self.proc = None
        self.falhas: list[float] = []
        self._parar = False

    def _iniciar(self):
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # o serviço escreve em logs/voz.log
        return self._popen(self.comando, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=sem_janela)

    async def rodar(self) -> None:
        while not self._parar:
            self.estado.situacao = "rodando"
            self.estado.ultimo = None
            self.proc, inicio = self._iniciar(), self.relogio()
            logger.info("voz: serviço local iniciado (pid {})", self.proc.pid)
            motivo = await self._vigiar(inicio)
            if self._parar:
                break
            agora = self.relogio()
            self.falhas = [t for t in self.falhas if agora - t <= JANELA_FALHAS_S] + [agora]
            logger.warning("voz: serviço local {}; falhas em 5 min: {}", motivo, len(self.falhas))
            if len(self.falhas) >= FALHAS_MAX:
                self.estado.situacao = "falhou"
                logger.error("voz: desisti depois de {} falhas em 5 min", FALHAS_MAX)
                return
            self.estado.situacao = "reiniciando"
            await self._dormir(ESPERAS_S[min(len(self.falhas), len(ESPERAS_S)) - 1])
        self.estado.situacao = "desligado"

    async def _vigiar(self, inicio: float) -> str:
        while not self._parar:
            await self._dormir(1.0)
            if (codigo := self.proc.poll()) is not None:
                return f"terminou (código {codigo})"
            ultimo = self.estado.ultimo
            desde = ultimo if ultimo is not None else inicio + CARGA_S - TRAVADO_S
            if self.relogio() - desde > TRAVADO_S:
                self.proc.kill()
                return "travado (sem batimento)"
        return "parado"

    def parar(self) -> None:
        self._parar = True
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def rotas(estado: EstadoVoz, conv, exigir_token, publicar: Callable[[str, str], None] = lambda _k, _t: None
          ) -> APIRouter:
    r = APIRouter(dependencies=[Depends(exigir_token)])

    @r.get("/voz")
    async def voz():
        return estado.resumo()

    @r.post("/voz/estado")
    async def batimento(b: Batimento):
        return estado.batimento(b.estado)

    @r.post("/voz/dono")
    async def dono(d: Dono):
        estado.hud_ate = estado.relogio() + CONCESSAO_HUD_S if d.dono == "hud" else 0.0
        return {"dono": estado.dono()}

    @r.post("/voz/comando")
    async def comando(c: Comando):
        estado.comandos.append(c.acao)
        return {"ok": True}

    @r.post("/sessions/{session_id}/nova")
    async def nova(session_id: str = Caminho(pattern=r"^[A-Za-z0-9_-]{1,64}$")):  # mesmo formato do ChatRequest
        arquivada = await conv.nova_conversa(session_id)
        publicar("nova_conversa", session_id)  # o HUD aberto limpa a transcrição
        return {"ok": True, "arquivada": arquivada}

    return r
