"""Ferramentas do JARVIS: registro tipado (Pydantic V2) exposto ao Claude via tool use."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..core.costs import CostLedger
from ..proactive.reminders import ReminderStore


@dataclass
class ToolContext:
    roots: list[Path]          # pastas que as ferramentas de arquivo podem ler
    ledger: CostLedger
    reminders: ReminderStore
    salt: str = ""
    archive: Path = field(default_factory=lambda: Path("D:/JARVIS-Arquivo"))  # destino dos movimentos
    move_roots: list[Path] = field(default_factory=list)                      # de onde se pode mover
    journal: Any = None                                                      # MoveJournal
    memory: Any = None                                                       # JarvisMemory


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    run: Callable[[Any, ToolContext], str]
    summary: Callable[[Any], str]     # frase curta em pt-BR para o HUD e o pedido de aprovação
    needs_approval: bool = False
    details: Callable[[Any, Any], dict] | None = None  # extra para o card de aprovação (ex.: itens e GB do lote)
    builtin: dict | None = None       # ferramenta definida pela Anthropic (sem schema próprio), ex.: memória

    def definition(self) -> dict:
        if self.builtin:
            return dict(self.builtin)
        schema = self.params.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            "eager_input_streaming": True,  # padrão para requisições em streaming; a entrada é validada aqui
        }

    def parse(self, raw: Any) -> BaseModel:
        """Valida a entrada do modelo; levanta ValueError com mensagem legível se não servir."""
        try:
            return self.params.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError as e:
            raise ValueError(f"entrada inválida para {self.name}: {e.errors(include_url=False)}") from e


class ToolError(Exception):
    """Erro esperado de ferramenta (vira tool_result com is_error, sem stack trace)."""


def registry() -> dict[str, Tool]:
    from .disk import DISK_TOOLS
    from .files import FILE_TOOLS
    from .memory import MEMORY_TOOLS
    from .settings import SETTINGS_TOOLS
    from .system import SYSTEM_TOOLS
    from .tasks import TASK_TOOLS

    tools = [*SYSTEM_TOOLS, *FILE_TOOLS, *TASK_TOOLS, *DISK_TOOLS, *SETTINGS_TOOLS, *MEMORY_TOOLS]
    return {t.name: t for t in tools}


# Ferramentas de servidor da Anthropic (só nos modelos que suportam a versão com filtragem dinâmica)
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3},
]
WEB_CAPABLE = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-opus-4-8"}


def definitions_for(model: str, tools: dict[str, Tool]) -> list[dict]:
    """Lista em ordem fixa (nome) — mudar a ordem invalidaria o cache de prompt."""
    defs = [tools[name].definition() for name in sorted(tools)]
    if model in WEB_CAPABLE:
        defs += WEB_TOOLS
    return defs


def manifesto(tools: dict[str, Tool]) -> str:
    """Lista curta do que o JARVIS consegue fazer, gerada das ferramentas reais (nunca desatualiza)."""
    linhas = []
    for name in sorted(tools):
        t = tools[name]
        frase = t.description.split(". ")[0].rstrip(".")
        linhas.append(f"- {name}: {frase}" + (" (pede confirmação)" if t.needs_approval else ""))
    linhas.append("- web_search / web_fetch: buscar e ler páginas da web (só nos modelos Sonnet e Opus)")
    return "\n".join(linhas)
