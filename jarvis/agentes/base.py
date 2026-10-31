"""Base de todo agente: catálogo de tarefas e despacho. Quem chama executar() é só o orquestrador."""

from __future__ import annotations

from abc import ABC
from typing import ClassVar

from .contratos import ConfigAgente, PedidoTarefa, SaidaTarefa, TarefaRecusada
from .recursos import Recursos

__all__ = ["Agente", "TarefaRecusada"]


class Agente(ABC):
    tipo: ClassVar[str]
    nome: ClassVar[str]
    descricao: ClassVar[str]
    versao_codigo: ClassVar[str]
    tarefas: ClassVar[dict[str, str]]                  # nome → descrição (manifesto do JARVIS e /agentes)
    com_claude: ClassVar[frozenset[str]] = frozenset()  # as que chamam o Claude (param no teto)

    def __init__(self, agente_id: str, recursos: Recursos):
        self.id = agente_id
        self.recursos = recursos

    @classmethod
    def config_padrao(cls) -> ConfigAgente:
        return ConfigAgente()

    async def executar(self, pedido: PedidoTarefa, config: ConfigAgente) -> SaidaTarefa:
        """Despacha para tarefa_<nome>; tarefa fora do catálogo é recusada."""
        handler = getattr(self, f"tarefa_{pedido.tarefa}", None)
        if pedido.tarefa not in self.tarefas or handler is None:
            raise TarefaRecusada(f"o {self.nome} não tem a tarefa {pedido.tarefa}")
        return await handler(pedido, config)
