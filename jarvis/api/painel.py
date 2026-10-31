"""Rotas do painel fiscal (controllers finos): card tributário, clientes e atualização a pedido. Todas com token."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as Caminho

from ..painel import montagem
from ..painel.clientes import ServicoClientes
from ..painel.coleta import ServicoColeta
from ..painel.contratos import (
    ClienteConsolidado,
    ClienteEntrada,
    ClienteResumo,
    PainelTributario,
    StatusFonte,
)


def rotas(coleta: ServicoColeta, clientes: ServicoClientes, exigir_token, relogio=datetime.now) -> APIRouter:
    r = APIRouter(prefix="/painel", dependencies=[Depends(exigir_token)])

    def _cliente(cliente_id: int) -> ClienteConsolidado:
        c = clientes.consolidar(cliente_id)
        if c is None:
            raise HTTPException(status_code=404, detail="cliente inexistente")
        return c

    @r.get("/tributario", response_model=PainelTributario)
    async def tributario(cliente: int | None = Query(default=None, ge=1)):
        def montar():
            c = _cliente(cliente) if cliente else None
            return montagem.montar(coleta.itens(), coleta.status(), c, relogio())
        return await asyncio.to_thread(montar)

    @r.get("/clientes", response_model=list[ClienteResumo])
    async def listar():
        return await asyncio.to_thread(clientes.listar)

    @r.get("/clientes/{cliente_id}", response_model=ClienteConsolidado)
    async def detalhe(cliente_id: int = Caminho(ge=1)):
        return await asyncio.to_thread(_cliente, cliente_id)

    @r.post("/clientes")
    async def salvar(entrada: ClienteEntrada):
        return {"id": await asyncio.to_thread(clientes.banco.salvar, entrada)}

    @r.post("/atualizar", response_model=list[StatusFonte])
    async def atualizar():
        """Coleta agora as fontes oficiais e as fontes de clientes (a coleta leva alguns segundos)."""
        fiscais = await asyncio.to_thread(coleta.coletar)
        return fiscais + await asyncio.to_thread(clientes.atualizar)

    return r
