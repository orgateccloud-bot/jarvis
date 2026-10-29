"""python -m jarvis — sobe a API local (que também serve o HUD buildado)."""

import sys

import uvicorn

from .api.server import create_app
from .config import ROOT, get_settings

if __name__ == "__main__":
    settings = get_settings()
    # Sem console (pythonw.exe, ex.: tarefa do Agendador no logon) não há stdout/stderr e o uvicorn não sobe.
    # A saída vai para um arquivo, sem o log de acesso por requisição, para não crescer sem parar.
    sem_console = sys.stdout is None or sys.stderr is None
    if sem_console:
        (ROOT / "logs").mkdir(exist_ok=True)
        sys.stdout = sys.stderr = open(ROOT / "logs" / "api-console.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    print(f"JARVIS em http://{settings.host}:{settings.port}  (token em {settings.data_dir / '.token'})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info",
                access_log=not sem_console)
