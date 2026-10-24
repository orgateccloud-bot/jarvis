"""Ferramentas de arquivos — somente leitura e confinadas às pastas permitidas."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..core.privacy import sanitizar
from . import Tool, ToolContext, ToolError

MAX_BYTES = 20_000
MAX_ITENS = 200
MAX_ACHADOS = 100


def confinar(caminho: str, ctx: ToolContext) -> Path:
    """Resolve o caminho (inclusive links simbólicos) e recusa tudo que sair das pastas permitidas."""
    bruto = Path(caminho.strip().strip('"')).expanduser()
    candidatos = [bruto] if bruto.is_absolute() else [root / bruto for root in ctx.roots]
    for c in candidatos:
        alvo = c.resolve()
        if any(alvo.is_relative_to(root.resolve()) for root in ctx.roots) and alvo.exists():
            return alvo
    permitidas = ", ".join(str(r) for r in ctx.roots)
    raise ToolError(f"caminho fora das pastas permitidas ou inexistente: {caminho}. Permitidas: {permitidas}")


class CaminhoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caminho: str = Field(min_length=1, max_length=400, description="Caminho absoluto ou relativo a uma pasta permitida")


def listar_pasta(p: CaminhoParams, ctx: ToolContext) -> str:
    pasta = confinar(p.caminho, ctx)
    if not pasta.is_dir():
        raise ToolError(f"{pasta} não é uma pasta")
    itens = []
    for e in sorted(pasta.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:MAX_ITENS]:
        try:
            st = e.stat()
        except OSError:
            continue
        itens.append({
            "nome": e.name, "tipo": "pasta" if e.is_dir() else "arquivo",
            "tamanho_kb": None if e.is_dir() else round(st.st_size / 1024, 1),
            "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })
    return json.dumps({"pasta": str(pasta), "itens": itens}, ensure_ascii=False)


def ler_arquivo(p: CaminhoParams, ctx: ToolContext) -> str:
    arq = confinar(p.caminho, ctx)
    if not arq.is_file():
        raise ToolError(f"{arq} não é um arquivo")
    dados = arq.read_bytes()[:MAX_BYTES]
    if b"\x00" in dados:
        raise ToolError("arquivo binário — só leio arquivos de texto")
    texto = dados.decode("utf-8", errors="replace")
    corte = " [cortado em 20 KB]" if arq.stat().st_size > MAX_BYTES else ""
    # soberania de dados: CPF/CNPJ mascarados antes de irem ao modelo
    return f"{arq}{corte}\n\n{sanitizar(texto, salt=ctx.salt)}"


class BuscarParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pasta: str = Field(min_length=1, max_length=400, description="Pasta onde buscar (dentro das permitidas)")
    padrao: str = Field(min_length=1, max_length=80, description="Padrão glob, ex.: *.pdf ou *relatorio*")


def buscar_arquivos(p: BuscarParams, ctx: ToolContext) -> str:
    pasta = confinar(p.pasta, ctx)
    if ".." in p.padrao or p.padrao.startswith(("/", "\\")):
        raise ToolError("padrão inválido")
    achados = []
    for f in pasta.rglob(p.padrao):
        if len(achados) >= MAX_ACHADOS:
            break
        if f.resolve().is_relative_to(pasta):
            achados.append(str(f.relative_to(pasta)))
    return json.dumps({"pasta": str(pasta), "achados": achados, "limite": MAX_ACHADOS}, ensure_ascii=False)


FILE_TOOLS = [
    Tool(
        name="listar_pasta",
        description="Lista o conteúdo de uma pasta permitida (Documentos, Downloads, Desktop, projeto). "
                    "Use quando o usuário perguntar o que tem numa pasta.",
        params=CaminhoParams, run=listar_pasta, summary=lambda p: f"listou {p.caminho}",
    ),
    Tool(
        name="ler_arquivo",
        description="Lê até 20 KB de um arquivo de texto numa pasta permitida (CPF/CNPJ chegam mascarados).",
        params=CaminhoParams, run=ler_arquivo, summary=lambda p: f"leu {Path(p.caminho).name}",
    ),
    Tool(
        name="buscar_arquivos",
        description="Procura arquivos por padrão glob dentro de uma pasta permitida, incluindo subpastas.",
        params=BuscarParams, run=buscar_arquivos, summary=lambda p: f"buscou {p.padrao} em {p.pasta}",
    ),
]
