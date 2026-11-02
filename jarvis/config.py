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
    assistente: str = Field(default_factory=lambda: _env("JARVIS_ASSISTENTE", "JARVIS-TRILHUM"))
    proactive: bool = Field(default_factory=lambda: _env("JARVIS_PROATIVO", "1") != "0")
    session_idle_min: int = Field(default_factory=lambda: int(_env("JARVIS_SESSAO_OCIOSA_MIN", "30")))
    pii_salt: str = Field(default_factory=lambda: _env("JARVIS_PII_SALT", ""))
    # Etapa 2: escuta por voz local (microfone → "Jarvis" → Whisper → fala), sem o HUD. Desligada por padrão.
    voz_local: bool = Field(default_factory=lambda: _env("JARVIS_VOZ_LOCAL", "0") == "1")
    # Aluno do Trilhum ULTRA (uma instância por aluno): plano do JARVIS (haiku, sonnet, opus, fable ou router; vazio =
    # o dono, sem plano) e o teto mensal = preço do plano x fração / câmbio (JARVIS_BUDGET_USD só pode baixar)
    plano_jarvis: str = Field(default_factory=lambda: _env("JARVIS_PLANO", ""))
    cambio: float = Field(default_factory=lambda: float(_env("JARVIS_CAMBIO", "5.5")))
    teto_fracao: float = Field(default_factory=lambda: float(_env("JARVIS_TETO_FRACAO", "0.5")))
    # Avisos pelo WhatsApp 30 min antes de cada bloco (0 = desligado)
    whatsapp_avisos: bool = Field(default_factory=lambda: _env("JARVIS_WHATSAPP_AVISOS", "0") == "1")

    def coach(self) -> bool:
        """Coach de constância nas conversas: ligado por padrão para um aluno (JARVIS_PLANO), opcional para o dono."""
        return _env("JARVIS_COACH", "1" if self.plano_jarvis else "0") == "1"

    def whatsapp_destino(self) -> tuple[str, str]:
        """Número e data do consentimento (LGPD) do aluno. No Trilhum ficam em assinantes/{uid}.whatsapp e
        whatsappConsentimento (Firestore); sem JARVIS_TRILHUM_UID, valem estes. Lidos na hora: fora do repr."""
        return _env("JARVIS_WHATSAPP_NUMERO", ""), _env("JARVIS_WHATSAPP_CONSENTIMENTO", "")

    def firebase(self) -> tuple[str, str, str, str]:
        """Firestore do Trilhum (assinantes/{uid}, só leitura): uid do aluno, projeto, arquivo da conta de serviço
        (fora do Git) e, no modo teste, o emulador local (127.0.0.1:8085, projeto demo-trilhum). Com o uid, o número e
        o consentimento vêm de lá e a configuração local é ignorada."""
        return (_env("JARVIS_TRILHUM_UID", ""), _env("JARVIS_FIREBASE_PROJETO", "trilha-estudos-2026"),
                _env("JARVIS_FIREBASE_CREDENCIAIS", ""), _env("JARVIS_FIRESTORE_EMULADOR", ""))

    def whatsapp_dry_run(self) -> bool:
        """1 (padrão) = os avisos só vão para o log, mesmo com a conta da Meta configurada."""
        return _env("JARVIS_WHATSAPP_DRY_RUN", "1") != "0"

    def whatsapp_antecedencia_min(self) -> int:
        return int(_env("JARVIS_WHATSAPP_ANTECEDENCIA_MIN", "30"))

    def whatsapp_feriado(self) -> bool:
        """1 (padrão) = avisa nos feriados (o Trilhum mantém os blocos); 0 = não avisa."""
        return _env("JARVIS_WHATSAPP_FERIADO", "1") != "0"

    def meta_whatsapp(self) -> tuple[str, str, str, str, str]:
        """Meta Cloud API: token, id do número, nome do modelo aprovado, idioma e versão da Graph API."""
        return (_env("JARVIS_META_TOKEN", ""), _env("JARVIS_META_NUMERO_ID", ""), _env("JARVIS_META_MODELO", ""),
                _env("JARVIS_META_IDIOMA", ""), _env("JARVIS_META_VERSAO", ""))

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

    def trilhum_dir(self) -> Path:
        """Projeto do Trilhum (planos de estudo, só leitura): JARVIS_TRILHUM_DIR ou D:\\01_Projetos_Ativos\\Trilha."""
        return Path(_env("JARVIS_TRILHUM_DIR", "D:\\01_Projetos_Ativos\\Trilha"))

    def trilhum_plano(self) -> str:
        """Plano usado quando o pedido não diz qual (JARVIS_TRILHUM_PLANO); vazio = o em andamento."""
        return _env("JARVIS_TRILHUM_PLANO", "")

    def trilhum_sync(self) -> tuple[str, str, str]:
        """Sincronização do Trilhum (progresso, só leitura): endereço do Supabase da Trilha, chave publishable e o
        token de sincronização do usuário. Lidos do ambiente na hora: não são campos, então não aparecem no repr."""
        return (_env("JARVIS_TRILHUM_SYNC_URL", ""), _env("JARVIS_TRILHUM_SYNC_CHAVE", ""),
                _env("JARVIS_TRILHUM_SYNC_TOKEN", ""))

    def voz_dir(self) -> Path:
        """Modelos de voz e gravações de teste, fora do repositório: JARVIS_VOZ_DIR ou D:\\JARVIS-Voz."""
        return Path(_env("JARVIS_VOZ_DIR", "D:\\JARVIS-Voz"))

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
