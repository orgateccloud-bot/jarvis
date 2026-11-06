"""Barramento de eventos proativos (pub/sub em asyncio) e a fonte SSE /events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProactiveEvent(BaseModel):
    kind: Literal["saudacao", "alerta_ram", "alerta_disco", "alerta_cpu", "orcamento", "lembrete", "info",
                  "voz", "nova_conversa"]  # os dois últimos só existem com JARVIS_VOZ_LOCAL=1 (Etapa 2)
    nivel: Literal["info", "aviso", "critico"] = "info"
    titulo: str
    texto: str
    falar: bool = True
    at: datetime = Field(default_factory=datetime.now)


class EventBus:
    def __init__(self, queue_size: int = 50):
        self._subs: set[asyncio.Queue[ProactiveEvent]] = set()
        self.queue_size = queue_size

    def publish(self, ev: ProactiveEvent) -> None:
        for q in list(self._subs):
            if q.full():  # assinante lento: descarta o mais antigo, nunca trava o produtor
                q.get_nowait()
            q.put_nowait(ev)

    def abrir(self) -> asyncio.Queue:
        """Fila de um assinante; quem abre fecha com `fechar`."""
        q: asyncio.Queue = asyncio.Queue(self.queue_size)
        self._subs.add(q)
        return q

    def fechar(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    async def subscribe(self) -> AsyncIterator[ProactiveEvent]:
        q = self.abrir()
        try:
            while True:
                yield await q.get()
        finally:
            self.fechar(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)


async def event_source(bus: EventBus, greeting: ProactiveEvent | None, keepalive_s: float = 15.0):
    """Linhas SSE: saudação (opcional), depois cada evento; comentário de keepalive quando ocioso."""
    if greeting:
        yield f"data: {greeting.model_dump_json()}\n\n"
    # Espera na fila, não em subscribe(): cancelar o anext de um gerador o encerra, e o primeiro keepalive derrubaria o
    # stream. Cancelar q.get() no tempo limite não perde evento.
    q = bus.abrir()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=keepalive_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"data: {ev.model_dump_json()}\n\n"
    finally:
        bus.fechar(q)
