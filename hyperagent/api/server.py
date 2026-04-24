"""
JARVIS HyperAgent - API Server
Ponto de entrada FastAPI com todos os endpoints.
"""

import os
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from ..core.orchestrator import Orchestrator
from ..agents.system_agent import SystemAgent
from ..agents.web_agent import WebAgent
from ..agents.file_agent import FileAgent
from ..agents.code_agent import CodeAgent
from ..agents.memory_agent import MemoryAgent
from ..agents.data_agent import DataAgent
from ..agents.plugin_agent import PluginAgent

# ── App Setup ─────────────────────────────────────────────
app = FastAPI(
    title="JARVIS HyperAgent",
    description="Orquestrador Central de Sub-Agentes IA",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logger.add(os.path.join(LOG_DIR, "hyperagent.log"), rotation="10 MB", retention="30 days")

# ── Orchestrator Init ─────────────────────────────────────
orchestrator = Orchestrator()

# Registra todos os sub-agentes
orchestrator.register_agent("system", SystemAgent())
orchestrator.register_agent("web", WebAgent())
orchestrator.register_agent("files", FileAgent())
orchestrator.register_agent("code", CodeAgent())
orchestrator.register_agent("memory", MemoryAgent())
orchestrator.register_agent("data", DataAgent())
orchestrator.register_agent("plugin", PluginAgent())

logger.info(f"HyperAgent inicializado com {len(orchestrator.agents)} agentes: {orchestrator.agent_names}")


# ── Models ────────────────────────────────────────────────
class TaskRequest(BaseModel):
    tarefa: str
    contexto: Optional[str] = None
    source: Optional[str] = "api"

class AgentRequest(BaseModel):
    agente: str
    acao: str

class ChatMessage(BaseModel):
    mensagem: str


# ── Endpoints ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve o dashboard principal."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>JARVIS HyperAgent</h1><p>Dashboard em construcao</p>")


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "online",
        "servico": "JARVIS HyperAgent",
        "versao": "2.0.0",
        "brain": orchestrator.brain.provider,
        "model": orchestrator.brain.model,
        "agentes": len(orchestrator.agents),
        "hora": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    """Status completo do HyperAgent."""
    sys_agent: SystemAgent = orchestrator.agents.get("system")
    sys_status = sys_agent._system_status() if sys_agent else {}
    return {
        **orchestrator.get_status(),
        "sistema": sys_status,
    }


@app.post("/jarvis")
async def jarvis_execute(req: TaskRequest):
    """Endpoint principal - envia tarefa ao HyperAgent."""
    logger.info(f"[API] Tarefa: {req.tarefa[:100]}")

    # Injeta contexto da memoria
    memory_agent: MemoryAgent = orchestrator.agents.get("memory")
    context = ""
    if memory_agent:
        context = memory_agent.get_context()
    if req.contexto:
        context += f"\n{req.contexto}"

    # Se tiver contexto, prepend na tarefa
    full_task = f"[Contexto: {context}]\n{req.tarefa}" if context else req.tarefa

    result = await orchestrator.execute(full_task, source=req.source or "api")

    # Salva conversa na memoria
    if memory_agent:
        memory_agent._log_conversation(req.tarefa)

    return result


@app.post("/chat")
async def chat(msg: ChatMessage):
    """Interface de chat simples."""
    result = await orchestrator.execute(msg.mensagem, source="chat")
    return {
        "resposta": result.get("final_response", "Sem resposta"),
        "task_id": result.get("id"),
        "status": result.get("status"),
        "agentes_usados": [s.get("agente", "") for s in result.get("plan", [])],
    }


@app.post("/agent/{agent_name}")
async def direct_agent(agent_name: str, req: AgentRequest):
    """Chama um sub-agente diretamente (bypass do orquestrador)."""
    agent = orchestrator.agents.get(agent_name)
    if not agent:
        raise HTTPException(404, f"Agente '{agent_name}' nao encontrado. Disponiveis: {orchestrator.agent_names}")

    try:
        result = agent.execute(req.acao, brain=orchestrator.brain)
        return {"agente": agent_name, "resultado": result}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/agents")
async def list_agents():
    """Lista todos os sub-agentes e suas capacidades."""
    return {
        "total": len(orchestrator.agents),
        "agentes": {
            name: {
                "classe": agent.__class__.__name__,
                "descricao": agent.description,
                "capacidades": agent.capabilities,
            }
            for name, agent in orchestrator.agents.items()
        }
    }


@app.get("/tasks")
async def list_tasks():
    """Lista tarefas recentes."""
    return {
        "ativas": {tid: t.to_dict() for tid, t in orchestrator.tasks.items()},
        "historico": orchestrator.task_history[-20:],
    }


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Detalhes de uma tarefa."""
    task = orchestrator.tasks.get(task_id)
    if not task:
        # Busca no historico
        for t in orchestrator.task_history:
            if t.get("id") == task_id:
                return t
        raise HTTPException(404, "Tarefa nao encontrada")
    return task.to_dict()


# ── Atalhos para sub-agentes ────────────────────────────

@app.get("/sistema")
async def sistema():
    """Status do sistema (atalho)."""
    agent: SystemAgent = orchestrator.agents["system"]
    return agent._system_status()


@app.get("/processos")
async def processos(top: int = 10):
    """Top processos."""
    agent: SystemAgent = orchestrator.agents["system"]
    return agent._top_processes(top)


@app.post("/pesquisar")
async def pesquisar(payload: dict):
    """Pesquisa web (atalho)."""
    query = payload.get("query", "")
    agent: WebAgent = orchestrator.agents["web"]
    return agent._search(query)


@app.get("/cotacoes")
async def cotacoes():
    """Cotacoes de moedas."""
    agent: WebAgent = orchestrator.agents["web"]
    return agent._exchange_rates()


@app.get("/memoria")
async def memoria():
    """Estado da memoria."""
    agent: MemoryAgent = orchestrator.agents["memory"]
    return {
        "preferencias": agent.preferences,
        "notas": len(agent.notes),
        "aprendizados": len(agent.learned),
        "conversas": len(agent.conversations),
    }


@app.get("/plugins")
async def plugins():
    """Status dos plugins."""
    agent: PluginAgent = orchestrator.agents["plugin"]
    n8n = agent._n8n_health()
    wpp = agent._whatsapp_status()
    return {"n8n": n8n, "whatsapp": wpp}
