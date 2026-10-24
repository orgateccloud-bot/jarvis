"""Gestão do disco: analisar espaço, mover para o arquivo (reversível), desfazer e mandar para a Lixeira.
Nada é apagado em definitivo: mover copia, confere o tamanho e só então remove a origem."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

import psutil
from pydantic import BaseModel, ConfigDict, Field

from ..core.privacy import sanitizar
from . import Tool, ToolContext, ToolError
from .files import confinar

ANALISE_PRAZO_S = 8.0
VELHO = timedelta(days=180)


def _gb(b: int) -> float:
    return round(b / 2**30, 2)


def tamanho(p: Path, deadline: float | None = None) -> tuple[int, bool]:
    """Bytes de um arquivo ou pasta (sem seguir links/junções). Devolve (bytes, completo?)."""
    if p.is_symlink():
        return 0, True
    if p.is_file():
        return p.stat().st_size, True
    total = 0
    stack = [p]
    while stack:
        if deadline and time.monotonic() > deadline:
            return total, False
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink() or (e.is_dir(follow_symlinks=False) and _is_junction(e.path)):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, True


def _is_junction(path: str) -> bool:
    try:
        return os.path.isjunction(path)
    except (AttributeError, OSError):
        return False


# ── análise de espaço ────────────────────────────────────────
class AnalisarParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pasta: str = Field(default="C:\\", max_length=400, description="Pasta ou drive a analisar, ex.: C:\\ ou Downloads")
    top: int = Field(default=12, ge=3, le=30, description="Quantos itens maiores mostrar")


def _pasta_analisavel(caminho: str, ctx: ToolContext) -> Path:
    bruto = Path(caminho.strip().strip('"') or "C:\\")
    if not bruto.is_absolute():
        return confinar(caminho, ctx)
    alvo = bruto.resolve()
    if not alvo.exists() or not alvo.is_dir():
        raise ToolError(f"pasta inexistente: {caminho}")
    if alvo.drive.upper() not in ("C:", "D:"):
        raise ToolError("só analiso os drives C: e D:")
    return alvo


def analisar_espaco(p: AnalisarParams, ctx: ToolContext) -> str:
    pasta = _pasta_analisavel(p.pasta, ctx)
    deadline = time.monotonic() + ANALISE_PRAZO_S
    filhos, arquivos, velhos_bytes, parcial = [], [], 0, False
    limite_velho = time.time() - VELHO.total_seconds()
    try:
        entradas = list(os.scandir(pasta))
    except OSError as e:
        raise ToolError(f"sem acesso a {pasta}: {e.strerror or e}") from e
    for e in entradas:
        if time.monotonic() > deadline:
            parcial = True
            break
        try:
            if e.is_symlink() or _is_junction(e.path):
                continue
            if e.is_dir(follow_symlinks=False):
                b, completo = tamanho(Path(e.path), deadline)
                parcial |= not completo
                filhos.append({"nome": sanitizar(e.name, salt=ctx.salt), "tipo": "pasta", "gb": _gb(b),
                               **({} if completo else {"parcial": True})})
            else:
                st = e.stat(follow_symlinks=False)
                arquivos.append((st.st_size, e.name))
                if st.st_mtime < limite_velho:
                    velhos_bytes += st.st_size
                filhos.append({"nome": sanitizar(e.name, salt=ctx.salt), "tipo": "arquivo", "gb": _gb(st.st_size)})
        except OSError:
            continue
    filhos.sort(key=lambda x: x["gb"], reverse=True)
    drives = {}
    for d in ("C:\\", "D:\\"):
        try:
            u = psutil.disk_usage(d)
            drives[d] = {"livre_gb": _gb(u.free), "total_gb": _gb(u.total), "uso_percent": u.percent}
        except OSError:
            pass
    return json.dumps({
        "pasta": str(pasta), "maiores": filhos[: p.top],
        "arquivos_soltos_com_mais_de_180_dias_gb": _gb(velhos_bytes),
        "drives": drives, "arquivo_jarvis": str(ctx.archive),
        **({"parcial": True, "dica": "a análise estourou o prazo; analise uma subpasta para detalhar"} if parcial else {}),
    }, ensure_ascii=False)


# ── mover para o arquivo ─────────────────────────────────────
class MoverParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itens: list[str] = Field(min_length=1, max_length=50, description="Arquivos ou pastas a mover (caminhos)")
    subpasta: str | None = Field(default=None, max_length=80,
                                 description="Opcional: subpasta dentro do arquivo; se vazio, mantém a estrutura de origem")


def _origem_movel(caminho: str, ctx: ToolContext) -> Path:
    src = confinar(caminho, ctx)
    roots = [r.resolve() for r in ctx.move_roots]
    if src in roots:
        raise ToolError(f"não movo a pasta inteira {src.name}; mova o conteúdo dela")
    if not any(src.is_relative_to(r) for r in roots):
        raise ToolError(f"{src} não está numa pasta de onde posso mover (Downloads, Desktop, Documentos)")
    return src


def _unico(dst: Path) -> Path:
    if not dst.exists():
        return dst
    for n in range(1, 1000):
        cand = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
        if not cand.exists():
            return cand
    raise ToolError(f"nomes esgotados para {dst.name}")


def _destino(src: Path, ctx: ToolContext, subpasta: str | None) -> Path:
    archive = ctx.archive.resolve() if ctx.archive.exists() else ctx.archive
    if subpasta:
        limpa = "".join(ch for ch in subpasta if ch not in '<>:"|?*').strip(" .\\/")
        dst = archive / limpa / src.name
    else:
        root = next(r.resolve() for r in ctx.move_roots if src.is_relative_to(r.resolve()))
        dst = archive / src.relative_to(root.parent)  # ex.: Downloads\pasta\arquivo.zip
    if not dst.resolve().is_relative_to(archive.resolve() if archive.exists() else archive):
        raise ToolError("destino fora do arquivo do JARVIS")
    return _unico(dst)


def mover(src: Path, dst: Path, same_drive: bool | None = None) -> int:
    """Move com segurança: no mesmo drive renomeia; entre drives copia, confere o tamanho e só então remove.
    same_drive força o caminho (testes)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    size, _ = tamanho(src)
    if same_drive is None:
        same_drive = src.drive.upper() == dst.drive.upper()
    if same_drive:
        src.rename(dst)
        return size
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)
    copiado, _ = tamanho(dst)
    if copiado != size:
        raise ToolError(f"cópia de {src.name} incompleta ({copiado} de {size} bytes); origem mantida")
    if src.is_dir():
        shutil.rmtree(src)
    else:
        src.unlink()
    return size


def _detalhes_lote(itens: list[str], ctx: ToolContext) -> dict:
    nomes, total, deadline = [], 0, time.monotonic() + 3
    for c in itens:
        try:
            p = confinar(c, ctx)
            b, _ = tamanho(p, deadline)
            total += b
            nomes.append(p.name)
        except ToolError:
            nomes.append(f"{Path(c).name} (inválido)")
    return {"itens": nomes[:8], "outros": max(0, len(nomes) - 8), "total_gb": _gb(total), "total_bytes": total}


def mover_itens(p: MoverParams, ctx: ToolContext) -> str:
    lote = ctx.journal.new_batch()
    movidos, falhas, total = [], [], 0
    for caminho in p.itens:
        try:
            src = _origem_movel(caminho, ctx)
            dst = _destino(src, ctx, p.subpasta)
            size = mover(src, dst)
            ctx.journal.record(lote, src, dst, size)
            movidos.append(str(dst))
            total += size
        except (ToolError, OSError) as e:
            falhas.append({"item": caminho, "erro": str(e)})
    if not movidos:
        raise ToolError(f"nada foi movido: {falhas}")
    return json.dumps({"lote": lote, "movidos": len(movidos), "gb": _gb(total), "destinos": movidos[:10],
                       "falhas": falhas, "como_desfazer": f"desfazer_movimento(lote={lote})"}, ensure_ascii=False)


class DesfazerParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lote: int | None = Field(default=None, ge=1, description="Número do lote; vazio = o último ativo")


def desfazer_movimento(p: DesfazerParams, ctx: ToolContext) -> str:
    lote = p.lote or ctx.journal.last_batch()
    if not lote:
        raise ToolError("não há movimentos para desfazer")
    rows = [r for r in ctx.journal.batch(lote) if not r["desfeito"]]
    if not rows:
        raise ToolError(f"lote {lote} não existe ou já foi desfeito")
    voltaram, falhas = [], []
    for r in rows:
        src, dst = Path(r["origem"]), Path(r["destino"])
        try:
            if src.exists():
                raise ToolError(f"já existe algo em {src}; não sobrescrevo")
            if not dst.exists():
                raise ToolError(f"{dst} não está mais no arquivo")
            mover(dst, src)
            voltaram.append(r["id"])
        except (ToolError, OSError) as e:
            falhas.append({"item": r["origem"], "erro": str(e)})
    ctx.journal.mark_undone(voltaram)
    return json.dumps({"lote": lote, "devolvidos": len(voltaram), "falhas": falhas}, ensure_ascii=False)


class _Vazio(BaseModel):
    model_config = ConfigDict(extra="forbid")


def movimentos_recentes(_: _Vazio, ctx: ToolContext) -> str:
    rec = ctx.journal.recent()
    return json.dumps(rec, ensure_ascii=False) if rec else "Nenhum movimento registrado."


# ── Lixeira (recuperável) ────────────────────────────────────
class LixeiraParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itens: list[str] = Field(min_length=1, max_length=50, description="Arquivos ou pastas para a Lixeira")


def _para_lixeira(path: str) -> None:
    from send2trash import send2trash

    send2trash(path)


def enviar_para_lixeira(p: LixeiraParams, ctx: ToolContext) -> str:
    enviados, falhas, total = [], [], 0
    for caminho in p.itens:
        try:
            alvo = confinar(caminho, ctx)
            permitidas = [r.resolve() for r in [*ctx.move_roots, ctx.archive] if r.exists()]
            if alvo in permitidas or not any(alvo.is_relative_to(r) for r in permitidas):
                raise ToolError(f"{alvo} não pode ir para a Lixeira por mim")
            size, _ = tamanho(alvo)
            _para_lixeira(str(alvo))
            enviados.append(alvo.name)
            total += size
        except (ToolError, OSError) as e:
            falhas.append({"item": caminho, "erro": str(e)})
    if not enviados:
        raise ToolError(f"nada foi enviado: {falhas}")
    return json.dumps({"enviados": len(enviados), "gb": _gb(total), "falhas": falhas,
                       "observacao": "recuperável pela Lixeira do Windows"}, ensure_ascii=False)


DISK_TOOLS = [
    Tool(
        name="analisar_espaco",
        description="Mostra o que mais ocupa espaço numa pasta ou drive (maiores subpastas e arquivos, arquivos "
                    "antigos, espaço livre do C: e D:). Use quando o usuário falar de disco cheio, lentidão por "
                    "espaço ou limpeza. Comece pelo drive e depois detalhe a maior subpasta.",
        params=AnalisarParams, run=analisar_espaco, summary=lambda p: f"analisou o espaço em {p.pasta}",
    ),
    Tool(
        name="mover_itens",
        description="Move arquivos/pastas de Downloads, Desktop ou Documentos para o arquivo do JARVIS no D: "
                    "(reversível, nunca sobrescreve). Agrupe tudo num único pedido: uma aprovação cobre o lote.",
        params=MoverParams, run=mover_itens, needs_approval=True,
        summary=lambda p: f"mover {len(p.itens)} item(ns) para o arquivo no D:",
        details=lambda p, ctx: _detalhes_lote(p.itens, ctx),
    ),
    Tool(
        name="desfazer_movimento",
        description="Devolve um lote movido ao lugar original (por padrão, o último).",
        params=DesfazerParams, run=desfazer_movimento, needs_approval=True,
        summary=lambda p: f"desfazer o movimento {'do lote ' + str(p.lote) if p.lote else 'mais recente'}",
    ),
    Tool(
        name="movimentos_recentes",
        description="Lista os lotes movidos para o arquivo, com data, tamanho e se foram desfeitos.",
        params=_Vazio, run=movimentos_recentes, summary=lambda p: "listou os movimentos recentes",
    ),
    Tool(
        name="enviar_para_lixeira",
        description="Envia arquivos/pastas para a Lixeira do Windows (recuperável). Nunca esvazia a Lixeira. "
                    "Prefira mover_itens quando o usuário quiser guardar.",
        params=LixeiraParams, run=enviar_para_lixeira, needs_approval=True,
        summary=lambda p: f"enviar {len(p.itens)} item(ns) para a Lixeira",
        details=lambda p, ctx: _detalhes_lote(p.itens, ctx),
    ),
]
