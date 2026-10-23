"""
╔══════════════════════════════════════════════════════╗
║           JARVIS - ASSISTENTE PESSOAL IA             ║
║  Voz + PC + Internet + Agenda + Smart Home           ║
╚══════════════════════════════════════════════════════╝
"""

import os
import json
import time
import subprocess
import webbrowser
import psutil
import schedule
import threading
import requests
from datetime import datetime
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ai import chatgpt
import re

load_dotenv()



NOME = os.getenv("JARVIS_NOME", "Senhor")

app = FastAPI(title="JARVIS - Assistente Pessoal IA", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

logger.add("logs/jarvis.log", rotation="10 MB", retention="30 days")

os.makedirs("/dados", exist_ok=True)
os.makedirs("/agenda", exist_ok=True)

# ── Gemini ────────────────────────────────────────────
SYSTEM = f"""Voce e JARVIS, assistente pessoal avancado de {NOME}.
Responda sempre em portugues do Brasil de forma clara, inteligente e direta.
Voce pode: pesquisar na internet, controlar o computador, gerenciar agenda,
monitorar o sistema, gerar relatorios e muito mais.
Seja proativo e sugira acoes quando relevante."""

def gemini(prompt: str, contexto: str = "") -> str:
    for tentativa in range(3):
        try:
            msg = f"{contexto}\n\n{prompt}" if contexto else prompt
            resp = modelo.generate_content(f"{SYSTEM}\n\n{msg}")
            return resp.text.strip()
        except Exception as e:
            if "429" in str(e):
                time.sleep(30)
            else:
                raise
    raise Exception("Limite Gemini atingido.")

# ── Ferramentas do JARVIS ─────────────────────────────

def status_sistema() -> dict:
    disco = psutil.disk_usage("/")
    return {
        "cpu":        psutil.cpu_percent(interval=1),
        "ram":        psutil.virtual_memory().percent,
        "disco_livre": round(disco.free / 1024**3, 2),
        "hora":       datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "processos":  len(psutil.pids()),
    }

def pesquisar_web(query: str) -> str:
    try:
        url = f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        import re
        textos = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text)
        resultados = [re.sub(r'<[^>]+>', '', t).strip() for t in textos[:5]]
        return "\n".join(resultados) if resultados else "Sem resultados."
    except Exception as e:
        return f"Erro na pesquisa: {e}"

def abrir_programa(nome: str) -> str:
    programas = {
        "chrome":    "chrome",
        "edge":      "msedge",
        "notepad":   "notepad",
        "calculadora": "calc",
        "explorer":  "explorer",
        "word":      "winword",
        "excel":     "excel",
    }
    cmd = programas.get(nome.lower(), nome)
    try:
        subprocess.Popen(cmd, shell=True)
        return f"{nome} aberto com sucesso."
    except Exception as e:
        return f"Erro ao abrir {nome}: {e}"

def executar_comando(cmd: str) -> str:
    BLOQUEADOS = ["rm -rf", "format", "del /f /s /q C:\\"]
    if any(b in cmd for b in BLOQUEADOS):
        return "Comando bloqueado por segurança."
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or r.stderr.strip() or "Comando executado."
    except Exception as e:
        return f"Erro: {e}"

def carregar_agenda() -> list:
    path = "/agenda/eventos.json"
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def salvar_evento(titulo: str, data: str, hora: str, descricao: str = "") -> dict:
    eventos = carregar_agenda()
    evento = {
        "id":        len(eventos) + 1,
        "titulo":    titulo,
        "data":      data,
        "hora":      hora,
        "descricao": descricao,
        "criado_em": datetime.now().isoformat()
    }
    eventos.append(evento)
    with open("/agenda/eventos.json", "w", encoding="utf-8") as f:
        json.dump(eventos, f, ensure_ascii=False, indent=2)
    return evento

def relatorio_diario() -> str:
    st  = status_sistema()
    ev  = carregar_agenda()
    hoje = datetime.now().strftime("%d/%m/%Y")
    ev_hoje = [e for e in ev if e.get("data") == hoje]

    return f"""RELATÓRIO JARVIS — {hoje}
━━━━━━━━━━━━━━━━━━━━━━━━
Sistema: CPU {st['cpu']}% | RAM {st['ram']}% | Disco {st['disco_livre']}GB livre
Eventos hoje: {len(ev_hoje)}
{chr(10).join([f"  • {e['hora']} — {e['titulo']}" for e in ev_hoje]) or '  Nenhum evento.'}
━━━━━━━━━━━━━━━━━━━━━━━━
Gerado por JARVIS em {datetime.now().strftime('%H:%M')}"""

def carregar_lembretes() -> list:
    path = "/dados/lembretes.json"
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def salvar_lembrete(mensagem: str, hora: str) -> dict:
    lembretes = carregar_lembretes()
    l = {"id": len(lembretes)+1, "mensagem": mensagem, "hora": hora, "ativo": True}
    lembretes.append(l)
    with open("/dados/lembretes.json", "w", encoding="utf-8") as f:
        json.dump(lembretes, f, ensure_ascii=False, indent=2)
    return l

# ── Endpoints ─────────────────────────────────────────

class TarefaReq(BaseModel):
    tarefa: str
    contexto: Optional[str] = None

class EventoReq(BaseModel):
    titulo: str
    data: str
    hora: str
    descricao: Optional[str] = ""

class LembreteReq(BaseModel):
    mensagem: str
    hora: str

class ComandoReq(BaseModel):
    comando: str

class ProgramaReq(BaseModel):
    nome: str

@app.get("/")
def home():
    return FileResponse("/app/dashboard.html")

@app.get("/health")
def health():
    return {"status": "ok", "ia": "Gemini 2.0 Flash", "nome": NOME,
            "hora": datetime.now().isoformat()}

@app.get("/sistema/status")
def sistema():
    return status_sistema()

@app.post("/jarvis")
def jarvis(req: TarefaReq):
    """Endpoint principal — conversa com o JARVIS."""
    logger.info(f"Tarefa: {req.tarefa}")
    st = status_sistema()
    ctx = f"Status do sistema: CPU {st['cpu']}%, RAM {st['ram']}%"
    if req.contexto:
        ctx += f"\n{req.contexto}"
    try:
        resp = gemini(req.tarefa, ctx)
        return {"resposta": resp, "ia": "Gemini 2.0 Flash"}
    except Exception as e:
        raise HTTPException(503, str(e))

@app.post("/web/pesquisar")
def pesquisar(payload: dict):
    query = payload.get("query", "")
    resultados = pesquisar_web(query)
    analise    = gemini(f"Com base nesses resultados de busca por '{query}': {resultados}\n\nResuma de forma clara.")
    return {"query": query, "resultados": resultados, "analise": analise}

@app.post("/pc/abrir")
def abrir(req: ProgramaReq):
    return {"resultado": abrir_programa(req.nome)}

@app.post("/pc/executar")
def executar(req: ComandoReq):
    return {"resultado": executar_comando(req.comando)}

@app.get("/pc/processos")
def processos(top: int = 10):
    procs = sorted(
        [p.info for p in psutil.process_iter(["pid","name","cpu_percent","memory_percent"])],
        key=lambda x: x.get("cpu_percent") or 0, reverse=True
    )[:top]
    return {"processos": procs}

@app.get("/agenda")
def listar_agenda():
    return {"eventos": carregar_agenda()}

@app.post("/agenda/criar")
def criar_evento(req: EventoReq):
    ev = salvar_evento(req.titulo, req.data, req.hora, req.descricao)
    return {"criado": True, "evento": ev}

@app.get("/agenda/hoje")
def agenda_hoje():
    hoje   = datetime.now().strftime("%d/%m/%Y")
    eventos = [e for e in carregar_agenda() if e.get("data") == hoje]
    return {"data": hoje, "total": len(eventos), "eventos": eventos}

@app.get("/lembretes")
def listar_lembretes():
    return {"lembretes": carregar_lembretes()}

@app.post("/lembretes/criar")
def criar_lembrete(req: LembreteReq):
    l = salvar_lembrete(req.mensagem, req.hora)
    return {"criado": True, "lembrete": l}

@app.get("/relatorio/diario")
def relatorio():
    return {"relatorio": relatorio_diario()}

@app.get("/relatorio/sistema")
def relatorio_sistema():
    st  = status_sistema()
    ctx = json.dumps(st, ensure_ascii=False)
    analise = gemini(f"Analise o status do sistema e recomende acoes: {ctx}")
    return {"status": st, "analise": analise}

@app.post("/jarvis")
def jarvis(req: TarefaReq):

    st = status_sistema()
    ctx = f"Status do sistema: CPU {st['cpu']}%, RAM {st['ram']}%"

    if req.contexto:
        ctx += f"\n{req.contexto}"

    try:
        resp = chatgpt(req.tarefa, ctx)  # ← AQUI ESTÁ A CHAMADA
        return {"resposta": resp, "ia": "ChatGPT"}
    except Exception as e:
        raise HTTPException(503, str(e))