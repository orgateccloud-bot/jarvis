"""Interface comum das fontes de dados do cliente. Os cards não conhecem as fontes: só o serviço de clientes."""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

from ...core.privacy import anonimizar_cnpj, anonimizar_cpf
from ..http import FonteIndisponivel  # noqa: F401 — a exceção comum das fontes também vale aqui

# Campos canônicos do cliente e o grupo de precedência de cada um.
GRUPOS: dict[str, list[str]] = {
    "cadastral": ["razao_social", "nome_fantasia", "situacao_cadastral", "cnae_principal", "uf_sede"],
    "fiscal": ["regime_tributario", "obrigacoes", "ufs_operacao", "cnaes_secundarios", "atividades"],
    "comercial": ["contratos", "pendencias", "contato"],
    "certidoes": ["certidoes"],
}
# Quem vence quando duas fontes discordam (a primeira da lista ganha).
PRECEDENCIA: dict[str, list[str]] = {
    "cadastral": ["portais", "erp", "banco", "planilha"],   # o cadastro oficial vale mais que o digitado
    "fiscal": ["banco", "erp", "planilha", "portais"],      # o escritório define regime e obrigações
    "comercial": ["banco", "erp", "planilha"],              # contrato e honorário são do escritório
    "certidoes": ["portais", "banco", "planilha"],
}
CAMPOS = [c for grupo in GRUPOS.values() for c in grupo]


def documento(valor: str) -> str:
    """Só os caracteres do CNPJ/CPF (o CNPJ alfanumérico de 2026 mantém as letras)."""
    return re.sub(r"[^0-9A-Z]", "", str(valor).upper())


def mascarado(doc: str) -> str:
    """Para tela e lista: CNPJ com os 8 primeiros (raiz) visíveis só nas posições de praxe; CPF todo mascarado."""
    d = documento(doc)
    if len(d) == 14:
        return f"{d[:2]}.***.***/{d[8:12]}-**"
    return anonimizar_cpf(f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}") if len(d) == 11 else "***"


def para_log(doc: str, salt: str = "") -> str:
    """Nunca o documento em claro no log: máscara + hash curto para correlacionar."""
    d = documento(doc)
    h = hashlib.sha256(f"{salt}:{d}".encode()).hexdigest()[:10]
    return f"{anonimizar_cnpj(anonimizar_cpf(d)) if d else '***'}#{h}"


class FonteCliente(ABC):
    id: str          # banco | planilha | erp | portais (o grupo de precedência usa este id)
    nome: str        # aparece no card como a origem do campo

    def listar(self) -> list[dict[str, Any]]:
        """Clientes que esta fonte conhece: [{"documento", "razao_social"}]. Nem toda fonte lista."""
        return []

    @abstractmethod
    def buscar(self, doc: str) -> dict[str, Any] | None:
        """Campos canônicos do cliente (só os que a fonte tem); None se a fonte não conhece o cliente.
        Levanta FonteIndisponivel se a fonte falhar."""
