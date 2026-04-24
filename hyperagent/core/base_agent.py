"""
JARVIS HyperAgent - Base Agent
Classe base que todos os sub-agentes herdam.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from loguru import logger


class BaseAgent(ABC):
    """Interface base para todos os sub-agentes do JARVIS."""

    name: str = "base"
    description: str = "Agente base"
    capabilities: list[str] = []

    def __init__(self):
        logger.info(f"Sub-agente [{self.name}] inicializado")

    @abstractmethod
    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        """Executa uma acao. Cada agente implementa sua logica."""
        pass

    def can_handle(self, action: str) -> float:
        """Retorna score 0-1 de confianca em lidar com esta acao."""
        action_lower = action.lower()
        matches = sum(1 for cap in self.capabilities if cap in action_lower)
        return min(1.0, matches * 0.3)

    def __repr__(self):
        return f"<{self.__class__.__name__} name='{self.name}'>"
