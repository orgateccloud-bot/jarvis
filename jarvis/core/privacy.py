"""Protocolo de soberania de dados (@Delta): anonimização determinística antes de enviar à nuvem."""

from __future__ import annotations

import hashlib
import re

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# telefone brasileiro: +55 opcional, DDD com ou sem parênteses, 8 ou 9 dígitos (com hífen, ponto ou espaço)
_TELEFONE = re.compile(r"(?<!\d)(?:\+?55[\s.-]?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}(?!\d)")


def anonimizar_cpf(texto: str) -> str:
    return _CPF.sub("***.***.***-**", texto)


def anonimizar_cnpj(texto: str) -> str:
    return _CNPJ.sub("**.***.***/****-**", texto)


def anonimizar_contato(texto: str) -> str:
    """E-mail e telefone (texto livre que o usuário escreve, como o questionário do Trilhum)."""
    return _TELEFONE.sub("(**) *****-****", _EMAIL.sub("***@***", texto))


def pseudonimizar_nome(nome: str, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{nome}".encode()).hexdigest()[:8]
    return f"PESSOA_{h.upper()}"


def sanitizar(texto: str, nomes: list[str] | None = None, salt: str = "", inteiras: bool = False) -> str:
    """Mascara CPF/CNPJ (CNPJ primeiro, por ser o padrão mais longo) e pseudonimiza nomes conhecidos.
    inteiras=True só troca o nome como palavra inteira (para um primeiro nome não pegar pedaço de outra palavra)."""
    texto = anonimizar_cpf(anonimizar_cnpj(texto))
    for nome in nomes or []:
        if nome.strip():
            padrao = rf"\b{re.escape(nome)}\b" if inteiras else re.escape(nome)
            texto = re.sub(padrao, pseudonimizar_nome(nome, salt), texto, flags=re.IGNORECASE)
    return texto
