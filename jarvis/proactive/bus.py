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

    async def subscribe(self) -> AsyncIterator[ProactiveEvent]:
        q: asyncio.Queue[ProactiveEvent] = asyncio.Queue(self.queue_size)
        self._subs.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subs)


async def event_source(bus: EventBus, greeting: ProactiveEvent | None, keepalive_s: float = 15.0):
    """Linhas SSE: saudação (opcional), depois cada evento; comentário de keepalive quando ocioso."""
    if greeting:
        yield f"data: {greeting.model_dump_json()}\n\n"
    sub = bus.subscribe()
    try:
        while True:
            try:
                ev = await asyncio.wait_for(anext(sub), timeout=keepalive_s)
                yield f"data: {ev.model_dump_json()}\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        await sub.aclose()
