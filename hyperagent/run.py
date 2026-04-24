"""Entrypoint para rodar o JARVIS HyperAgent."""
import sys
import os
import uvicorn

# Garante que o diretorio pai esteja no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    port = int(os.getenv("JARVIS_PORTA", "8000"))
    uvicorn.run(
        "hyperagent.api.server:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("JARVIS_DEV", "false").lower() == "true",
        log_level="info",
    )
