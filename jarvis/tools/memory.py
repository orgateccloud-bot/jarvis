"""Memória de longo prazo: ferramenta memory_20250818 da Anthropic com back-end local em dados/memories/.

O back-end em disco é o do SDK (caminhos presos a /memories, sem escapar por symlink). Aqui entram as regras do
JARVIS: CPF/CNPJ mascarados antes de gravar, teto de tamanho por arquivo e nada apagado em definitivo — apagar ou
sobrescrever guarda a versão anterior em .lixeira/ (oculta da listagem)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from anthropic.tools import BetaLocalFilesystemMemoryTool
from anthropic.tools import ToolError as SdkToolError
from pydantic import BaseModel, ConfigDict, model_validator

from ..core.privacy import sanitizar
from . import Tool, ToolContext, ToolError

LIMITE_ARQUIVO = 16_000  # caracteres; acima disso o modelo veria o arquivo truncado

PERFIL_INICIAL = """# Perfil de {nome}
Arquivo principal da memória do JARVIS. Atualize quando aprender algo duradouro.

## Áreas (a de cada pergunta vem do assunto)
- Direito Tributário e preparação para o Exame da OAB: citar lei e artigo; avisar quando a norma pode ter
  mudado (reforma tributária IBS/CBS).
- Contabilidade e auditoria: trabalha na ORGATEC (contabilidade, auditoria forense, conciliação bancária, laudos).
- TI e projetos próprios: JARVIS (este assistente), OrgConc, OrgAudi, MiniSaaS. Python, FastAPI, React.

## Preferências
- Tratamento: "{nome}". Português do Brasil.
- Respostas curtas e diretas; detalhar só quando ele pedir.
- Só Claude como IA. Ações com efeito sempre com confirmação; nada apagado em definitivo.
- Custo importa: teto de US$ 15 por mês.
"""


class JarvisMemory(BetaLocalFilesystemMemoryTool):
    """Arquivos em <base>/memories, vistos pelo modelo como /memories."""

    def __init__(self, base: Path, salt: str = ""):
        super().__init__(base_path=str(base))
        self.salt = salt
        self.lixeira = self.memory_root / ".lixeira"

    def _limpo(self, texto: str) -> str:
        return sanitizar(texto, salt=self.salt)

    def _cabe(self, path: str, tamanho: int) -> None:
        if tamanho > LIMITE_ARQUIVO:
            raise SdkToolError(f"{path} passaria de {LIMITE_ARQUIVO} caracteres; resuma ou divida em arquivos.")

    def _guardar(self, alvo: Path) -> None:
        """Move a versão atual para .lixeira/ (reversível) em vez de apagar."""
        self.lixeira.mkdir(exist_ok=True)
        shutil.move(str(alvo), str(self.lixeira / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{alvo.name}"))

    def _raiz(self, path: str) -> bool:
        return self._validate_path(path) == self.memory_root.resolve()

    def create(self, command):
        texto = self._limpo(command.file_text)
        self._cabe(command.path, len(texto))
        alvo = self._validate_path(command.path)
        if alvo.is_file():  # a descrição da ferramenta diz "cria ou sobrescreve": sobrescreve guardando a anterior
            self._guardar(alvo)
        return super().create(command.model_copy(update={"file_text": texto}))

    def str_replace(self, command):
        novo = self._limpo(command.new_str or "")
        alvo = self._validate_path(command.path)
        if alvo.is_file():
            atual = alvo.stat().st_size
            self._cabe(command.path, atual - len(command.old_str) + len(novo))
        return super().str_replace(command.model_copy(update={"new_str": novo}))

    def insert(self, command):
        texto = self._limpo(command.insert_text)
        alvo = self._validate_path(command.path)
        if alvo.is_file():
            self._cabe(command.path, alvo.stat().st_size + len(texto))
        return super().insert(command.model_copy(update={"insert_text": texto}))

    def delete(self, command):
        if self._raiz(command.path):
            raise SdkToolError("Cannot delete the /memories directory itself")
        alvo = self._validate_path(command.path)
        if not alvo.exists():
            raise SdkToolError(f"The path {command.path} does not exist")
        self._guardar(alvo)
        return f"Successfully deleted {command.path}"

    def rename(self, command):
        if self._raiz(command.old_path):
            raise SdkToolError("Cannot rename the /memories directory itself")
        return super().rename(command)

    def semear(self, nome: str) -> None:
        """Na primeira execução, cria o perfil inicial (multiárea). Nunca sobrescreve memória existente."""
        if not any(p for p in self.memory_root.iterdir() if not p.name.startswith(".")):
            (self.memory_root / "perfil.md").write_text(PERFIL_INICIAL.format(nome=nome), encoding="utf-8")


# ── ferramenta ───────────────────────────────────────────────
_OBRIGATORIOS = {
    "view": ("path",), "create": ("path", "file_text"), "str_replace": ("path", "old_str"),
    "insert": ("path", "insert_line", "insert_text"), "delete": ("path",), "rename": ("old_path", "new_path"),
}
_VERBO = {"view": "consultar", "create": "gravar", "str_replace": "atualizar", "insert": "acrescentar em",
          "delete": "arquivar", "rename": "renomear"}


class MemoriaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["view", "create", "str_replace", "insert", "delete", "rename"]
    path: str | None = None
    view_range: list[int] | None = None
    file_text: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None
    insert_text: str | None = None
    old_path: str | None = None
    new_path: str | None = None

    @model_validator(mode="after")
    def _campos(self):
        faltando = [c for c in _OBRIGATORIOS[self.command] if getattr(self, c) is None]
        if faltando:
            raise ValueError(f"{self.command} exige {', '.join(faltando)}")
        return self


def memoria(p: MemoriaParams, ctx: ToolContext) -> str:
    if ctx.memory is None:
        raise ToolError("A memória de longo prazo está desativada.")
    try:
        return ctx.memory.call(p.model_dump(exclude_none=True))
    except SdkToolError as e:
        raise ToolError(str(e)) from e


def _resumo(p: MemoriaParams) -> str:
    alvo = p.path or f"{p.old_path} → {p.new_path}"
    return f"memória: {_VERBO[p.command]} {alvo}"


MEMORY_TOOLS = [
    Tool(
        "memory",
        "Memória de longo prazo em /memories (perfil, preferências, decisões e pendências). Consulte no início de "
        "cada conversa nova.",
        MemoriaParams, memoria, _resumo,
        builtin={"type": "memory_20250818", "name": "memory"},
    ),
]
