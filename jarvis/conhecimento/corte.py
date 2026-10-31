"""Corte em trechos por tipo (R7): artigo, anexo, sumula, ementa, secao, pagina.

Sem tipo (arquivo que não vem do catálogo): artigos e anexos se houver ao menos 3 marcas, senão blocos de parágrafos.
Trecho máximo ~1.500 caracteres; quando divide, a parte seguinte repete o fim da anterior (sobreposição curta).
Itens de jurisprudência vêm em blocos "### Súmula 4" seguidos de linhas "Situação:", "Data:", "URL:" (metadados
do próprio item: uma súmula cancelada fica marcada mesmo dentro de um arquivo vigente).
"""

from __future__ import annotations

import re
import textwrap

TAM_TRECHO = 1500
SOBREPOSICAO = 150

_ARTIGO = re.compile(r"^Art\.?\s*(\d+)\s*[ºo°]?\s*(-\s*[A-Z]{1,2}\b)?", re.MULTILINE)
_ANEXO = re.compile(r"^ANEXO\s+([IVXL]+)\b", re.MULTILINE)
_ITEM = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)
_SECAO = re.compile(r"^(?:#{1,6}\s+(.+?)|((?:T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|PARTE|LIVRO)\s+[IVXLC\d]+.*?))\s*$",
                    re.MULTILINE)
_META_ITEM = re.compile(r"^(Situação|Data|URL):\s*(.*)$", re.MULTILINE)


def _fatiar(texto: str, rotulo: str) -> list[tuple[str, str]]:
    """Divide trechos longos em partes de até TAM_TRECHO, quebrando em linha, com sobreposição curta."""
    if len(texto) <= TAM_TRECHO:
        return [(rotulo, texto)]
    linhas = []
    for ln in texto.splitlines(keepends=True):  # linha única enorme (PDF, tabela): quebra nos espaços
        linhas += [w + "\n" for w in textwrap.wrap(ln, TAM_TRECHO)] if len(ln) > TAM_TRECHO else [ln]
    partes, atual = [], ""
    for ln in linhas:
        if atual and len(atual) + len(ln) > TAM_TRECHO:
            partes.append(atual)
            atual = ""
        atual += ln
    partes.append(atual)
    out = [(rotulo, partes[0])]
    for i, p in enumerate(partes[1:], 2):
        cauda = partes[i - 2][-SOBREPOSICAO:]
        cauda = cauda[cauda.find(" ") + 1:] if " " in cauda else cauda   # começa numa palavra inteira
        out.append((f"{rotulo} (parte {i})", f"…{cauda.strip()}\n{p}"))
    return out


def _por_marcas(texto: str, marcas: list[tuple[int, str]]) -> list[tuple[str, str]]:
    pedacos = [(0, "Preâmbulo")] + marcas if marcas[0][0] > 0 else marcas
    out = []
    for i, (ini, rot) in enumerate(pedacos):
        fim = pedacos[i + 1][0] if i + 1 < len(pedacos) else len(texto)
        trecho = texto[ini:fim].strip()
        if trecho:
            out += _fatiar(trecho, rot)
    return out


def _paragrafos(texto: str) -> list[tuple[str, str]]:
    blocos, atual, n = [], "", 0
    for par in re.split(r"\n\s*\n", texto):
        if atual and len(atual) + len(par) > TAM_TRECHO:
            n += 1
            blocos.append((f"parágrafo {n}", atual.strip()))
            atual = ""
        atual += par + "\n\n"
    if atual.strip():
        blocos.append((f"parágrafo {n + 1}", atual.strip()))
    return [p for rot, t in blocos for p in _fatiar(t, rot)]


def _marcas_artigo(texto: str) -> list[tuple[int, str]]:
    return [(m.start(), f"Art. {m.group(1)}{(m.group(2) or '').replace(' ', '')}") for m in _ARTIGO.finditer(texto)]


def _marcas_anexo(texto: str) -> list[tuple[int, str]]:
    return [(m.start(), f"Anexo {m.group(1)}") for m in _ANEXO.finditer(texto)]


def cortar(texto: str, corte: str | None = None) -> list[tuple[str, str]]:
    """Texto → [(rótulo, trecho)]. `corte` vem do catálogo; None = detecção automática (comportamento antigo)."""
    if corte in (None, "artigo"):
        marcas = sorted(_marcas_artigo(texto) + _marcas_anexo(texto))
    elif corte == "anexo":
        marcas = _marcas_anexo(texto)
    elif corte in ("sumula", "ementa"):
        marcas = [(m.start(), m.group(1)[:120]) for m in _ITEM.finditer(texto)]
    elif corte == "secao":
        marcas = [(m.start(), (m.group(1) or m.group(2))[:120]) for m in _SECAO.finditer(texto)]
    elif corte == "pagina":
        paginas = texto.split("\f")
        if len(paginas) > 1:
            return [p for i, pg in enumerate(paginas, 1) if pg.strip() for p in _fatiar(pg.strip(), f"página {i}")]
        marcas = []
    else:
        raise ValueError(f"corte desconhecido: {corte}")
    minimo = 3 if corte in (None, "artigo") else 1
    return _por_marcas(texto, marcas) if len(marcas) >= minimo else _paragrafos(texto)


def meta_do_item(trecho: str) -> dict[str, str]:
    """Situação/Data/URL declaradas nas primeiras linhas de um item (bloco ### do corte sumula/ementa)."""
    return {k.lower().replace("ç", "c").replace("ã", "a"): v.strip()
            for k, v in _META_ITEM.findall("\n".join(trecho.splitlines()[:6]))}
