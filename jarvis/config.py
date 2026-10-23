"""Configuração central, lida do ambiente (.env). Nenhuma credencial fica no código."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


class Settings(BaseModel):
    host: str = Field(default_factory=lambda: _env("JARVIS_HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: int(_env("JARVIS_PORT", "8000")))
    cors_origins: list[str] = Field(
        default_factory=lambda: _env("JARVIS_CORS", "http://localhost:5299").split(",")
    )
    data_dir: Path = Field(default_factory=lambda: Path(_env("JARVIS_DATA_DIR", str(ROOT / "dados"))))

    model_simple: str = Field(default_factory=lambda: _env("JARVIS_MODELO_SIMPLES", "claude-haiku-5-5"))
    model_medium: str = Field(default_factory=lambda: _env("JARVIS_MODELO_MEDIO", "claude-sonnet-5-5"))
    model_complex: str = Field(default_factory=lambda: _env("JARVIS_MODELO_COMPLEXO", "claude-opus-5-5"))
    max_tokens: int = Field(default_factory=lambda: int(_env("JARVIS_MAX_TOKENS", "16000")))
    monthly_budget_usd: float = Field(default_factory=lambda: float(_env("JARVIS_BUDGET_USD", "15")))
    economy_threshold: float = 0.8

    user_name: str = Field(default_factory=lambda: _env("JARVIS_NOME", "Senhor"))
    pii_salt: str = Field(default_factory=lambda: _env("JARVIS_PII_SALT", ""))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    def api_token(self) -> str:
        """Token do HUD: JARVIS_TOKEN do ambiente ou um gerado e guardado em dados/.token."""
        token = _env("JARVIS_TOKEN", "")
        if token:
            return token
        path = self.data_dir / ".token"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
        return token

    def salt(self) -> str:
        """Salt de pseudonimização: do ambiente ou persistido localmente (estável entre sessões)."""
        if self.pii_salt:
            return self.pii_salt
        path = self.data_dir / ".pii_salt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        salt = secrets.token_hex(16)
        path.write_text(salt, encoding="utf-8")
        return salt


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
