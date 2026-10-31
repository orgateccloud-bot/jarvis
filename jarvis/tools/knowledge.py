"""Ferramenta do especialista: busca na base de conhecimento local (catálogo TOML + índice FTS5).

É a porta única da base: os agentes também leem por aqui. A descrição é gerada dos catálogos na inicialização
(lista curta de áreas, até 300 caracteres: ela vai em toda chamada e custa tokens).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import Tool, ToolContext, ToolError

LIMITE_DESCRICAO = 300


class BuscaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consulta: str = Field(min_length=2, max_length=300,
                          description="O que procurar, de preferência com as palavras que a lei usaria")
    area: str | None = Field(default=None, max_length=40, description="Restringe a uma área da lista")
    uf: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$", description="UF (GO, TO...) ou BR")
    tipo: str | None = Field(default=None, max_length=40, description="lei, sumula, precedente, codigo...")
    esfera: Literal["federal", "estadual", "municipal", "profissional", "interno", "tecnico"] | None = None
    vigente_em: date | None = Field(default=None, description="AAAA-MM-DD: texto vigente nessa data")


def descricao(areas: list[str]) -> str:
    texto = ("Busca leis, súmulas e temas do STF/STJ na base local (áreas: {}; súmulas e temas entram em "
             "qualquer área). Filtros: area, uf, tipo, esfera, vigente_em. Cite fonte, URL e data da captura; "
             "repita o aviso se houver. Sem o artigo certo, use as palavras da lei.")
    lista = [a for a in areas if a != "geral"]
    while lista and len(texto.format(", ".join(lista))) > LIMITE_DESCRICAO:
        lista.pop()
    return texto.format(", ".join(lista) or "geral")


def buscar_conhecimento(p: BuscaParams, ctx: ToolContext) -> str:
    if ctx.knowledge is None:
        raise ToolError("A base de conhecimento está desativada.")
    if p.area and p.area not in (validas := ctx.knowledge.areas()):
        raise ToolError(f"Área desconhecida: {p.area}. Use uma destas: {', '.join(validas)}.")
    achados = ctx.knowledge.buscar(p.consulta, p.area, uf=p.uf and p.uf.upper(), tipo=p.tipo, esfera=p.esfera,
                                   vigente_em=p.vigente_em)
    if not achados:
        return json.dumps({"resultado": "nada encontrado na base local",
                           "dica": "tente as palavras da própria lei, outra área, ou diga que não há material local"},
                          ensure_ascii=False)
    saida = []
    for _, t in achados:
        item = {"fonte": t.fonte, "trecho": t.rotulo, "arquivo": t.arquivo, "texto": t.texto, "url": t.url,
                "baixado_em": t.baixado_em, "situacao": t.situacao, "vigencia": t.vigencia, "uf": t.uf,
                "tipo": t.tipo, "fonte_id": t.fonte_id, "aviso": t.aviso}
        saida.append({k: v for k, v in item.items() if v})       # campo vazio não gasta token
    return json.dumps(saida, ensure_ascii=False)


def knowledge_tools(areas: list[str] | None = None) -> list[Tool]:
    return [Tool(
        "buscar_conhecimento", descricao(areas or ["tributario", "oab", "contabil"]), BuscaParams, buscar_conhecimento,
        lambda p: f"base de conhecimento: {p.consulta}"[:120],
    )]


KNOWLEDGE_TOOLS = knowledge_tools()
