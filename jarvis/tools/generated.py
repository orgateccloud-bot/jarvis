"""Arquivos gerados no sandbox de código da Anthropic, baixados pela Files API para o PC do usuário.

Só voltam com file_id os arquivos que o modelo grava no topo de $OUTPUT_DIR dentro de um comando bash; o que fica em
outra pasta do sandbox some com ele. Destino: <arquivo>/Gerados/<AAAA-MM-DD>/, sem nunca sobrescrever."""

from __future__ import annotations

import asyncio
import posixpath
import re
from datetime import date
from pathlib import Path

import anthropic
from loguru import logger

LIMITE_BYTES = 200 * 2**20
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def file_ids(content: list[dict]) -> list[str]:
    """file_id de cada arquivo que um comando bash deixou em $OUTPUT_DIR nesta resposta."""
    ids = []
    for b in content:
        res = b.get("content") if b.get("type") == "bash_code_execution_tool_result" else None
        if isinstance(res, dict) and res.get("type") == "bash_code_execution_result":
            ids += [o["file_id"] for o in res.get("content") or [] if isinstance(o, dict) and o.get("file_id")]
    return ids


def nome_seguro(nome: str) -> str:
    """Só o nome do arquivo (nada de caminho), sem caracteres proibidos nem nomes reservados do Windows."""
    base = _PROIBIDOS.sub("_", posixpath.basename((nome or "").replace("\\", "/"))).strip(" .") or "arquivo"
    if base.split(".")[0].lower() in _RESERVADOS:
        base = f"_{base}"
    return base[:150]


def _gravar(alvo: Path, dados: bytes) -> None:
    with open(alvo, "xb") as f:  # "x": nunca sobrescreve
        f.write(dados)


def destino_livre(pasta: Path, nome: str) -> Path:
    alvo, n = pasta / nome, 2
    while alvo.exists():
        alvo = pasta / f"{Path(nome).stem} ({n}){Path(nome).suffix}"
        n += 1
    return alvo


async def salvar_gerados(client, ids: list[str], raiz: Path, hoje: date | None = None) -> list[dict]:
    """Baixa cada arquivo e grava em raiz/Gerados/<data>/. Devolve um registro por arquivo (caminho ou erro)."""
    pasta = raiz / "Gerados" / f"{hoje or date.today():%Y-%m-%d}"
    salvos = []
    for fid in ids:
        try:
            meta = await client.files.retrieve_metadata(fid)
            if (getattr(meta, "size_bytes", 0) or 0) > LIMITE_BYTES:
                salvos.append({"file_id": fid, "nome": meta.filename, "erro": "maior que 200 MB; não baixei"})
                continue
            dados = await (await client.files.download(fid)).read()
            pasta.mkdir(parents=True, exist_ok=True)
            alvo = destino_livre(pasta, nome_seguro(meta.filename))
            await asyncio.to_thread(_gravar, alvo, dados)
        except (anthropic.APIError, OSError) as e:
            logger.warning(f"arquivo gerado {fid}: {e}")
            salvos.append({"file_id": fid, "erro": f"não consegui baixar ({type(e).__name__})"})
            continue
        logger.info(f"arquivo gerado salvo: {alvo} ({len(dados)} bytes)")
        salvos.append({"file_id": fid, "nome": alvo.name, "caminho": str(alvo), "bytes": len(dados)})
    return salvos


def aviso(registro: dict) -> str:
    """Frase para o modelo (e o HUD) sobre um arquivo salvo ou que falhou."""
    if "caminho" in registro:
        kb = max(1, round(registro["bytes"] / 1024))
        return f"o sistema salvou {registro['nome']} no PC do usuário em {registro['caminho']} ({kb} KB)"
    return f"o arquivo {registro.get('nome') or registro['file_id']} do sandbox não foi salvo: {registro['erro']}"
