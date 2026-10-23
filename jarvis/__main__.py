"""python -m jarvis — sobe a API local."""

import uvicorn

from .api.server import create_app
from .config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    print(f"JARVIS em http://{settings.host}:{settings.port}  (token em {settings.data_dir / '.token'})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
