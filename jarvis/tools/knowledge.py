"""Ferramenta do especialista: busca na base de conhecimento local (leis cortadas por artigo, BM25)."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import Tool, ToolContext, ToolError


class BuscaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consulta: str = Field(min_length=2, max_length=300,
                          description="O que procurar, de preferência com as palavras que a lei usaria")
    area: Literal["tributario", "oab", "contabil", "geral"] | None = Field(
        default=None, description="Restringe a busca a uma área")


def buscar_conhecimento(p: BuscaParams, ctx: ToolContext) -> str:
    if ctx.knowledge is None:
        raise ToolError("A base de conhecimento está desativada.")
    achados = ctx.knowledge.buscar(p.consulta, p.area)
    if not achados:
        return json.dumps({"resultado": "nada encontrado na base local",
                           "dica": "tente as palavras da própria lei, outra área, ou diga que não há material local"},
                          ensure_ascii=False)
    return json.dumps([{"fonte": t.fonte, "trecho": t.rotulo, "arquivo": t.arquivo, "texto": t.texto}
                       for _, t in achados], ensure_ascii=False)


KNOWLEDGE_TOOLS = [
    Tool(
        "buscar_conhecimento",
        "Busca trechos de leis e documentos na base local (CTN, LC 123/2006, Estatuto da OAB e o que o usuário "
        "adicionar). Devolve até 5 trechos com lei e artigo; se a primeira busca não trouxer o artigo certo, "
        "tente de novo com as palavras que a lei usaria. Cite lei e artigo na resposta.",
        BuscaParams, buscar_conhecimento,
        lambda p: f"base de conhecimento: {p.consulta}"[:120],
    ),
]
