from fastapi import FastAPI
from pydantic import BaseModel
from api.brain import brain
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import psutil
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class JarvisRequest(BaseModel):
    message: str

def generate_jarvis_response(user_message):
    try:
        # 1. Resposta Automática de Curto Circuito
        if not user_message.strip() or user_message.lower() == "jarvis":
            yield "data: Às suas ordens, Senhor. Sistemas operacionais. \n\n"
            yield "data: [DONE]\n\n"
            return

        # 2. Feedback de Processamento (Aparece no HUD na hora)
        yield "data: Processando dados, Senhor. Por favor, aguarde... \n\n"
        
        # 3. Acionando o Llama 3 (Onde ocorre a latência da GPU)
        full_response = brain(user_message)
        
        # Limpa o "Processando..." e entrega a resposta real
        # O HUD v3.0 concatena, então enviamos um separador visual
        yield f"data: \n\n --- \n\n {full_response} \n\n"
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        yield f"data: Erro no núcleo neural, Senhor: {str(e)} \n\n"
        yield "data: [DONE]\n\n"

@app.post("/jarvis/stream")
async def chat_endpoint(data: JarvisRequest):
    return StreamingResponse(
        generate_jarvis_response(data.message), 
        media_type="text/event-stream"
    )

# --- SENSORES DE TELEMETRIA MANTIDOS ---
@app.get("/system/status")
async def get_system_status():
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('C:\\').percent,
        "process_count": len(psutil.pids()),
        "uptime_hours": 1.5
    }

@app.get("/consciousness")
async def get_consciousness():
    return {"state": "online", "emotion": "alerta"}

@app.get("/memory/stats")
async def get_memory_stats():
    return {"available": True}