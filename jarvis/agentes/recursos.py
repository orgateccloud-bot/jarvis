"""Recursos de um agente: a única coisa que ele recebe do JARVIS (objeto-capacidade).

Não há aqui orquestrador, outros agentes, ferramentas do JARVIS nem cliente de rede: o agente não tem como dar ordem a
ninguém. O Claude só é alcançado pelo gateway, que mascara PII e confere custo e teto antes de cada chamada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConsultaConhecimento:
    """A base de conhecimento só para leitura: o agente busca trechos, não reindexa nem baixa nada."""

    def __init__(self, base: Any):
        self._base = base

    def buscar(self, consulta: str, area: str | None = "tributario", k: int = 5) -> list[dict]:
        if self._base is None:
            return []
        return [{"fonte": t.fonte, "trecho": t.rotulo, "arquivo": t.arquivo, "texto": t.texto}
                for _, t in self._base.buscar(consulta, area, k)]


@dataclass(frozen=True)
class Recursos:
    claude: Any                          # GatewayClaude (ou None: o agente só roda tarefas locais)
    conhecimento: ConsultaConhecimento
    pasta: Path                          # onde o agente grava o que entrega (laudos)
    salt: str                            # pseudonimização determinística de nomes
