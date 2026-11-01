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


def var_chave_agente(agente_id: str) -> str:
    """Variável da chave da Anthropic só de um agente: JARVIS_AGENTE_<ID>_API_KEY."""
    return f"JARVIS_AGENTE_{agente_id.upper()}_API_KEY"


class Settings(BaseModel):
    host: str = Field(default_factory=lambda: _env("JARVIS_HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: int(_env("JARVIS_PORT", "8000")))
    cors_origins: list[str] = Field(
        default_factory=lambda: _env("JARVIS_CORS", "http://localhost:5299,http://127.0.0.1:5299").split(",")
    )
    data_dir: Path = Field(default_factory=lambda: Path(_env("JARVIS_DATA_DIR", str(ROOT / "dados"))))

    model_simple: str = Field(default_factory=lambda: _env("JARVIS_MODELO_SIMPLES", "claude-haiku-5-5"))
    model_medium: str = Field(default_factory=lambda: _env("JARVIS_MODELO_MEDIO", "claude-sonnet-5-5"))
    model_complex: str = Field(default_factory=lambda: _env("JARVIS_MODELO_COMPLEXO", "claude-opus-5-5"))
    model_fable: str = Field(default_factory=lambda: _env("JARVIS_MODELO_FABLE", "claude-fable-5-1"))
    fable_pontos: int = Field(default_factory=lambda: int(_env("JARVIS_FABLE_PONTOS", "4")))
    max_tokens: int = Field(default_factory=lambda: int(_env("JARVIS_MAX_TOKENS", "16000")))
    monthly_budget_usd: float = Field(default_factory=lambda: float(_env("JARVIS_BUDGET_USD", "30")))
    economy_threshold: float = 0.8

    user_name: str = Field(default_factory=lambda: _env("JARVIS_NOME", "Senhor"))
    # nome deste JARVIS (prompt e saudação falada); o HUD usa o mesmo em jarvis-hud/src/lib/marca.js
    assistente: str = Field(default_factory=lambda: _env("JARVIS_ASSISTENTE", "JARVIS Tributário"))
    proactive: bool = Field(default_factory=lambda: _env("JARVIS_PROATIVO", "1") != "0")
    session_idle_min: int = Field(default_factory=lambda: int(_env("JARVIS_SESSAO_OCIOSA_MIN", "30")))
    pii_salt: str = Field(default_factory=lambda: _env("JARVIS_PII_SALT", ""))
    # Etapa 2: escuta por voz local (microfone → "Jarvis" → Whisper → fala), sem o HUD. Desligada por padrão.
    voz_local: bool = Field(default_factory=lambda: _env("JARVIS_VOZ_LOCAL", "0") == "1")
    # Painel fiscal do HUD (card tributário e card do cliente). Ligado por padrão; 0 desliga rotas e coleta.
    painel: bool = Field(default_factory=lambda: _env("JARVIS_PAINEL", "1") != "0")
    fiscal_intervalo_min: int = Field(default_factory=lambda: int(_env("JARVIS_FISCAL_INTERVALO_MIN", "360")))
    clientes_intervalo_min: int = Field(default_factory=lambda: int(_env("JARVIS_CLIENTES_INTERVALO_MIN", "1440")))
    # Etapa 3: agentes subordinados ativos (separados por vírgula); vazio ou 0 desliga a camada inteira
    agentes: list[str] = Field(default_factory=lambda: [
        a.strip() for a in _env("JARVIS_AGENTES", "tributario").split(",") if a.strip() and a.strip() != "0"])
    agentes_espera_s: float = Field(default_factory=lambda: float(_env("JARVIS_AGENTES_ESPERA_S", "20")))

    def chave_agente(self, agente_id: str) -> str:
        """Chave da Anthropic só do agente ("" = usa a do JARVIS). Lida do ambiente na hora: não é campo, então não
        aparece no repr nem no model_dump."""
        return _env(var_chave_agente(agente_id), "")

    def tool_roots(self) -> list[Path]:
        """Pastas que as ferramentas podem ler: JARVIS_PASTAS (separadas por ;) ou as pastas pessoais."""
        custom = _env("JARVIS_PASTAS", "")
        if custom:
            cands = [Path(c) for c in custom.split(";") if c.strip()]
        else:
            h = Path.home()
            cands = [h / "Documents", h / "Documentos", h / "OneDrive" / "Documentos", h / "Downloads",
                     h / "Desktop", h / "OneDrive" / "Desktop", h / "OneDrive" / "Área de Trabalho", ROOT]
        archive = self.archive_dir()
        if archive.exists():
            cands.append(archive)
        return [c.resolve() for c in cands if c.exists()]

    def archive_dir(self) -> Path:
        """Destino dos movimentos (reversíveis) do JARVIS: JARVIS_ARQUIVO ou D:\\JARVIS-Arquivo."""
        return Path(_env("JARVIS_ARQUIVO", "D:\\JARVIS-Arquivo"))

    def knowledge_dir(self) -> Path:
        """Base de conhecimento do especialista (leis e documentos): JARVIS_CONHECIMENTO ou D:\\JARVIS-Conhecimento."""
        return Path(_env("JARVIS_CONHECIMENTO", "D:\\JARVIS-Conhecimento"))

    def agentes_dir(self) -> Path:
        """Entregas dos agentes (laudos), uma subpasta por agente: <JARVIS_ARQUIVO>\\Agentes."""
        return self.archive_dir() / "Agentes"

    def voz_dir(self) -> Path:
        """Modelos de voz e gravações de teste, fora do repositório: JARVIS_VOZ_DIR ou D:\\JARVIS-Voz."""
        return Path(_env("JARVIS_VOZ_DIR", "D:\\JARVIS-Voz"))

    def fontes_fiscais(self) -> Path:
        """Fontes oficiais do card tributário: JARVIS_FONTES_FISCAIS ou config/fontes_fiscais.json."""
        return Path(_env("JARVIS_FONTES_FISCAIS", str(ROOT / "config" / "fontes_fiscais.json")))

    def move_roots(self) -> list[Path]:
        """De onde o JARVIS pode mover/mandar para a Lixeira: pastas pessoais, nunca o projeto nem o arquivo."""
        excluir = {ROOT.resolve(), self.archive_dir().resolve() if self.archive_dir().exists() else None}
        return [r for r in self.tool_roots() if r not in excluir]

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
