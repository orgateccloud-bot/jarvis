"""Contratos de dados (Pydantic V2) compartilhados entre núcleo, API e HUD."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Route(StrEnum):
    LOCAL = "local"  # resposta por regra (sem IA), custo zero
    SIMPLE = "simples"  # Haiku 5.5, effort low
    MEDIUM = "media"  # Sonnet 5.5, effort medium
    COMPLEX = "complexa"  # Opus 5.5, effort high


class BudgetState(StrEnum):
    NORMAL = "normal"
    ECONOMY = "economia"  # >= 80% do teto: desce uma camada, effort low
    CAP_REACHED = "teto"  # >= 100%: Claude pausado, só respostas por regra


class Decision(BaseModel):
    route: Route
    model: str | None = None
    effort: Literal["low", "medium", "high"] | None = None
    reason: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,64}$")


class StreamEvent(BaseModel):
    """Evento enviado ao HUD por SSE."""

    type: Literal["route", "thinking", "text", "usage", "error", "done"]
    data: Any = None


class UsageRecord(BaseModel):
    at: datetime = Field(default_factory=datetime.now)
    session_id: str
    model: str
    route: Route
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


class AgentResult(BaseModel):
    """Resultado de um turno, com audit_hash encadeado (cadeia de custódia)."""

    session_id: str
    route: Route
    model: str
    text: str
    cost_usd: float = 0.0
    stop_reason: str | None = None
    at: datetime = Field(default_factory=datetime.now)
    audit_hash: str = ""
