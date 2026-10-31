"""Protocolo de soberania de dados (@Delta): anonimização determinística antes de enviar à nuvem."""

from __future__ import annotations

import hashlib
import re

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
# CNPJ alfanumérico (desde julho de 2026): só com a pontuação, para não mascarar códigos quaisquer de 14 caracteres
_CNPJ_ALFA = re.compile(r"\b[A-Z0-9]{2}\.[A-Z0-9]{3}\.[A-Z0-9]{3}/[A-Z0-9]{4}-\d{2}\b", re.IGNORECASE)


def anonimizar_cpf(texto: str) -> str:
    return _CPF.sub("***.***.***-**", texto)


def anonimizar_cnpj(texto: str) -> str:
    return _CNPJ_ALFA.sub("**.***.***/****-**", _CNPJ.sub("**.***.***/****-**", texto))


def pseudonimizar_nome(nome: str, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{nome}".encode()).hexdigest()[:8]
    return f"PESSOA_{h.upper()}"


def sanitizar(texto: str, nomes: list[str] | None = None, salt: str = "") -> str:
    """Mascara CPF/CNPJ (CNPJ primeiro, por ser o padrão mais longo) e pseudonimiza nomes conhecidos."""
    texto = anonimizar_cpf(anonimizar_cnpj(texto))
    for nome in nomes or []:
        if nome.strip():
            texto = re.sub(re.escape(nome), pseudonimizar_nome(nome, salt), texto, flags=re.IGNORECASE)
    return texto
