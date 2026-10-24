"""Ferramentas de tarefas: custos e lembretes (que o laço proativo dispara na hora certa)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import Tool, ToolContext, ToolError


class _Vazio(BaseModel):
    model_config = ConfigDict(extra="forbid")


def custos(_: _Vazio, ctx: ToolContext) -> str:
    return json.dumps(ctx.ledger.summary(), ensure_ascii=False)


class LembreteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = Field(min_length=2, max_length=300, description="O que lembrar, em poucas palavras")
    em_minutos: int | None = Field(default=None, ge=1, le=60 * 24 * 30, description="Daqui a quantos minutos")
    quando: datetime | None = Field(default=None, description="Data/hora local ISO 8601, ex.: 2026-10-25T09:00")

    @model_validator(mode="after")
    def _um_horario(self):
        if (self.em_minutos is None) == (self.quando is None):
            raise ValueError("informe exatamente um entre em_minutos e quando")
        return self

    def horario(self) -> datetime:
        return datetime.now() + timedelta(minutes=self.em_minutos) if self.em_minutos else self.quando.replace(tzinfo=None)


def criar_lembrete(p: LembreteParams, ctx: ToolContext) -> str:
    quando = p.horario()
    if quando < datetime.now() - timedelta(minutes=1):
        raise ToolError("o horário do lembrete já passou")
    r = ctx.reminders.add(p.texto, quando)
    return f"Lembrete #{r.id} criado para {quando:%d/%m %H:%M}: {p.texto}"


def _resumo_lembrete(p: LembreteParams) -> str:
    try:
        return f"lembrete \"{p.texto}\" para {p.horario():%d/%m %H:%M}"
    except (TypeError, AttributeError):
        return f"lembrete \"{p.texto}\""


def lembretes_listar(_: _Vazio, ctx: ToolContext) -> str:
    pend = ctx.reminders.pending()
    return json.dumps(
        [{"id": r.id, "texto": r.texto, "quando": r.quando.strftime("%d/%m/%Y %H:%M")} for r in pend],
        ensure_ascii=False,
    ) if pend else "Nenhum lembrete pendente."


class CancelarParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1, description="Número do lembrete")


def cancelar_lembrete(p: CancelarParams, ctx: ToolContext) -> str:
    if not ctx.reminders.cancel(p.id):
        raise ToolError(f"lembrete #{p.id} não existe ou já disparou")
    return f"Lembrete #{p.id} cancelado."


TASK_TOOLS = [
    Tool(
        name="custos",
        description="Gasto com o Claude hoje e no mês, teto, modo de economia e taxa de cache.",
        params=_Vazio, run=custos, summary=lambda p: "consultou os custos",
    ),
    Tool(
        name="criar_lembrete",
        description="Agenda um lembrete; na hora o JARVIS avisa por voz, no HUD e com notificação do Windows. "
                    "Chame direto quando o usuário pedir para lembrar algo; a confirmação é automática.",
        params=LembreteParams, run=criar_lembrete, summary=_resumo_lembrete, needs_approval=True,
    ),
    Tool(
        name="lembretes_listar",
        description="Lista os lembretes pendentes com seus números.",
        params=_Vazio, run=lembretes_listar, summary=lambda p: "listou os lembretes",
    ),
    Tool(
        name="cancelar_lembrete",
        description="Cancela um lembrete pendente pelo número (use lembretes_listar para achar o número).",
        params=CancelarParams, run=cancelar_lembrete, summary=lambda p: f"cancelar o lembrete #{p.id}",
        needs_approval=True,
    ),
]
