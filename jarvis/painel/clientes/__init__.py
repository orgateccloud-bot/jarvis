"""Dados do cliente para o card: um adaptador por fonte (banco, planilha, ERP, portais) com a mesma interface.

Ligar ou desligar uma fonte é só configuração (variáveis JARVIS_CLIENTES_*, JARVIS_ERP_*, JARVIS_SERPRO_CLIENTE e
config/clientes_fontes.json); os cards e a API não mudam.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from ...config import ROOT, Settings
from ..http import Fetch, FonteIndisponivel, buscar
from .banco import BancoClientes
from .base import FonteCliente
from .erp import ErpClientes
from .planilha import PlanilhaClientes
from .portais import PortaisClientes, carregar_serpro
from .servico import ServicoClientes

FORMATOS = ROOT / "config" / "clientes_fontes.json"


class FonteQuebrada(FonteCliente):
    """Fonte configurada que não conseguiu subir (ex.: módulo ausente): aparece no card com o motivo."""

    def __init__(self, id: str, nome: str, erro: str):
        self.id, self.nome, self.erro = id, nome, erro

    def buscar(self, doc: str) -> dict[str, Any] | None:
        raise FonteIndisponivel(self.erro)


def montar_servico(settings: Settings, fetch: Fetch = buscar, env: dict[str, str] | None = None) -> ServicoClientes:
    env = os.environ if env is None else env
    outras: list[FonteCliente] = []
    if planilha := env.get("JARVIS_CLIENTES_PLANILHA", "").strip():
        outras.append(PlanilhaClientes(caminho=Path(planilha), fetch=fetch))
    elif sheets := env.get("JARVIS_CLIENTES_SHEETS_URL", "").strip():
        outras.append(PlanilhaClientes(url=sheets, fetch=fetch))
    erp_url, erp_token = env.get("JARVIS_ERP_URL", "").strip(), env.get("JARVIS_ERP_TOKEN", "").strip()
    if erp_url and erp_token:
        formato = json.loads(FORMATOS.read_text(encoding="utf-8"))["erp"] if FORMATOS.exists() else {}
        try:
            outras.append(ErpClientes(erp_url, erp_token, formato, fetch))
        except ValueError as e:
            outras.append(FonteQuebrada("erp", "ERP (API)", str(e)))
    if serpro := env.get("JARVIS_SERPRO_CLIENTE", "").strip():
        try:
            outras.append(PortaisClientes(carregar_serpro(Path(serpro)), env))
        except FonteIndisponivel as e:
            logger.warning("clientes: integração SERPRO não subiu: {}", e)
            outras.append(FonteQuebrada("portais", PortaisClientes.nome, str(e)))
    return ServicoClientes(BancoClientes(settings.db_path), outras, salt=settings.salt())
