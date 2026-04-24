"""
JARVIS HyperAgent - Orchestrator
Coordena sub-agentes, executa planos, gerencia estado e historico.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Optional
from enum import Enum
from loguru import logger

from .brain import Brain


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    """Representa uma tarefa no HyperAgent."""

    def __init__(self, description: str, source: str = "user"):
        self.id = str(uuid.uuid4())[:8]
        self.description = description
        self.source = source
        self.status = TaskStatus.PENDING
        self.plan: list[dict] = []
        self.results: dict[int, Any] = {}
        self.created_at = datetime.now()
        self.completed_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.final_response: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "source": self.source,
            "status": self.status.value,
            "plan": self.plan,
            "results": {str(k): str(v)[:500] for k, v in self.results.items()},
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "final_response": self.final_response,
        }


class Orchestrator:
    """Orquestrador central do JARVIS HyperAgent."""

    def __init__(self):
        self.brain = Brain()
        self.agents: dict[str, Any] = {}
        self.tasks: dict[str, Task] = {}
        self.task_history: list[dict] = []
        self.max_history = 100
        logger.info("Orchestrator inicializado")

    def register_agent(self, name: str, agent: Any):
        """Registra um sub-agente."""
        self.agents[name] = agent
        logger.info(f"Agente registrado: {name} -> {agent.__class__.__name__}")

    @property
    def agent_names(self) -> list[str]:
        return list(self.agents.keys())

    async def execute(self, user_input: str, source: str = "user") -> dict:
        """Ponto de entrada principal — recebe input e orquestra tudo."""
        task = Task(user_input, source)
        self.tasks[task.id] = task
        logger.info(f"[{task.id}] Nova tarefa: {user_input[:80]}...")

        try:
            # 1. Classifica: tarefa simples ou complexa?
            is_complex = self._is_complex(user_input)

            if is_complex:
                # Tarefa complexa: planeja e executa em etapas
                return await self._execute_complex(task)
            else:
                # Tarefa simples: roteia para um agente
                return await self._execute_simple(task)

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"[{task.id}] Falha: {e}")
            return task.to_dict()

        finally:
            self._archive_task(task)

    def _is_complex(self, text: str) -> bool:
        """Heuristica rapida para decidir se a tarefa precisa de planejamento."""
        complex_indicators = [
            " e ", " depois ", " em seguida", " alem disso",
            " primeiro ", " segundo ", " todos ", " cada ",
            " analise ", " compare ", " crie um relatorio",
            " organize e ", " pesquise e ",
        ]
        text_lower = text.lower()
        matches = sum(1 for ind in complex_indicators if ind in text_lower)
        return matches >= 2 or len(text) > 200

    async def _execute_simple(self, task: Task) -> dict:
        """Executa tarefa simples: roteia para 1 agente."""
        task.status = TaskStatus.RUNNING

        # Brain decide qual agente usar
        agent_name = self.brain.route(task.description, self.agent_names)
        logger.info(f"[{task.id}] Roteado para: {agent_name}")

        agent = self.agents.get(agent_name)
        if not agent:
            task.status = TaskStatus.FAILED
            task.error = f"Agente '{agent_name}' nao encontrado"
            return task.to_dict()

        # Executa
        result = await self._run_agent(agent_name, agent, task.description)
        task.results[1] = result

        # Brain sintetiza resposta final
        context = f"Tarefa: {task.description}\nAgente: {agent_name}\nResultado: {json.dumps(result, ensure_ascii=False, default=str)[:2000]}"
        task.final_response = self.brain.think(
            "Sintetize o resultado da tarefa em uma resposta clara e util para o usuario.",
            context=context
        )
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        return task.to_dict()

    async def _execute_complex(self, task: Task) -> dict:
        """Executa tarefa complexa: planeja, decompoe e coordena."""
        task.status = TaskStatus.PLANNING

        # 1. Brain cria plano
        plan_data = self.brain.plan(task.description, self.agent_names)
        task.plan = plan_data.get("plano", [])
        logger.info(f"[{task.id}] Plano com {len(task.plan)} passos")

        task.status = TaskStatus.RUNNING

        # 2. Executa cada passo (respeitando dependencias)
        completed_steps: set[int] = set()

        for step in task.plan:
            step_num = step["passo"]
            agent_name = step["agente"]
            action = step["acao"]
            depends = step.get("depende_de", [])

            # Aguarda dependencias
            for dep in depends:
                if dep not in completed_steps:
                    logger.warning(f"[{task.id}] Passo {step_num} aguarda passo {dep}")

            agent = self.agents.get(agent_name)
            if not agent:
                task.results[step_num] = {"erro": f"Agente '{agent_name}' nao encontrado"}
                continue

            # Contexto dos passos anteriores
            dep_context = ""
            for dep in depends:
                if dep in task.results:
                    dep_context += f"\nResultado do passo {dep}: {json.dumps(task.results[dep], ensure_ascii=False, default=str)[:500]}"

            full_action = f"{action}\n{dep_context}" if dep_context else action

            result = await self._run_agent(agent_name, agent, full_action)
            task.results[step_num] = result
            completed_steps.add(step_num)
            logger.info(f"[{task.id}] Passo {step_num}/{len(task.plan)} concluido ({agent_name})")

        # 3. Brain sintetiza resultado final
        all_results = json.dumps(task.results, ensure_ascii=False, default=str)[:3000]
        context = f"Tarefa original: {task.description}\nPlano executado: {json.dumps(task.plan, ensure_ascii=False)}\nResultados: {all_results}"

        task.final_response = self.brain.think(
            "Sintetize TODOS os resultados em uma resposta final completa, clara e organizada para o usuario.",
            context=context
        )
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        return task.to_dict()

    async def _run_agent(self, name: str, agent: Any, action: str) -> Any:
        """Executa um sub-agente (sync ou async)."""
        try:
            if asyncio.iscoroutinefunction(getattr(agent, 'execute', None)):
                return await agent.execute(action, brain=self.brain)
            else:
                return await asyncio.to_thread(agent.execute, action, brain=self.brain)
        except Exception as e:
            logger.error(f"Agente {name} falhou: {e}")
            return {"erro": str(e), "agente": name}

    def _archive_task(self, task: Task):
        """Salva tarefa no historico."""
        self.task_history.append(task.to_dict())
        if len(self.task_history) > self.max_history:
            self.task_history = self.task_history[-self.max_history:]

    def get_status(self) -> dict:
        """Status geral do HyperAgent."""
        return {
            "brain": {"provider": self.brain.provider, "model": self.brain.model},
            "agents": {name: agent.__class__.__name__ for name, agent in self.agents.items()},
            "active_tasks": len([t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]),
            "total_tasks": len(self.task_history),
            "uptime": datetime.now().isoformat(),
        }
