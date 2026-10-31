"""Etapa 3 na API: controllers finos dos agentes. Toda regra fica no orquestrador (o service).

Todas as rotas exigem o token da API: o usuário comanda o JARVIS, e só o orquestrador comanda os agentes.
Só existem com JARVIS_AGENTES ligado.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as Caminho
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..agentes.contratos import ID_AGENTE, AtualizacaoAgente, PedidoTarefa
from ..tools import ToolError

TAREFA_ID = r"^[a-f0-9]{16}$"


class PedidoApi(PedidoTarefa):
    """O pedido de tarefa, mais um CSV opcional nas pastas permitidas (o agente recebe só as linhas)."""

    arquivo: str | None = Field(default=None, max_length=400)


class Reversao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versao: int = Field(ge=1)
    motivo: str = Field(min_length=3, max_length=300)


def rotas_agentes(orq, exigir_token, tool_ctx) -> APIRouter:
    r = APIRouter(prefix="/agentes", dependencies=[Depends(exigir_token)])

    def agente(agente_id: str = Caminho(pattern=ID_AGENTE)) -> str:
        if agente_id not in orq.ids():
            raise HTTPException(status_code=404, detail=f"agente desconhecido: {agente_id}")
        return agente_id

    @r.get("")
    async def listar():
        return [e.model_dump(mode="json") for e in orq.observar_todos()]

    @r.get("/tarefas/{tarefa_id}")
    async def tarefa(tarefa_id: str = Caminho(pattern=TAREFA_ID)):
        resultado = orq.resultado(tarefa_id)
        if resultado is None:
            raise HTTPException(status_code=404, detail="tarefa inexistente")
        return resultado.model_dump(mode="json")

    @r.get("/tarefas/{tarefa_id}/verificar")
    async def verificar(tarefa_id: str = Caminho(pattern=TAREFA_ID)):
        try:
            return orq.verificar(tarefa_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail="tarefa inexistente ou ainda sem resultado") from e

    @r.get("/{agente_id}")
    async def detalhar(agente_id: str = Depends(agente)):
        return {"estado": orq.observar(agente_id).model_dump(mode="json"),
                "versoes": [v.model_dump(mode="json") for v in orq.registro.versoes(agente_id)]}

    @r.post("/{agente_id}/tarefas")
    async def comandar(corpo: PedidoApi, agente_id: str = Depends(agente)):
        from ..tools.agentes import ler_lancamentos

        lancamentos = corpo.lancamentos
        if corpo.arquivo:
            try:
                lancamentos = await asyncio.to_thread(ler_lancamentos, corpo.arquivo, tool_ctx)
            except ToolError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
        pedido = PedidoTarefa(**corpo.model_dump(exclude={"arquivo", "lancamentos", "cenario"}),
                              lancamentos=lancamentos, cenario=corpo.cenario)
        resultado = await orq.comandar(agente_id, pedido, "usuario_api")
        return JSONResponse(resultado.model_dump(mode="json"),
                            status_code=202 if resultado.estado == "em_andamento" else 200)

    @r.post("/{agente_id}/config")
    async def atualizar(mudanca: AtualizacaoAgente, agente_id: str = Depends(agente)):
        return orq.atualizar(agente_id, mudanca, "usuario_api")

    @r.post("/{agente_id}/config/reverter")
    async def reverter(corpo: Reversao, agente_id: str = Depends(agente)):
        try:
            return orq.reverter(agente_id, corpo.versao, "usuario_api", corpo.motivo)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"versão {corpo.versao} inexistente") from e

    @r.post("/{agente_id}/pausar")
    async def pausar(agente_id: str = Depends(agente)):
        return orq.pausar(agente_id, True)

    @r.post("/{agente_id}/retomar")
    async def retomar(agente_id: str = Depends(agente)):
        return orq.pausar(agente_id, False)

    return r
