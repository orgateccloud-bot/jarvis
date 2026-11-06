"""Protocolo de soberania de dados (@Delta): anonimização determinística antes de enviar à nuvem."""

from __future__ import annotations

import hashlib
import re

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
# CNPJ numérico ou alfanumérico (novas inscrições desde julho de 2026): 12 caracteres e 2 dígitos verificadores
_CNPJ = re.compile(r"\b[0-9A-Za-z]{2}\.?[0-9A-Za-z]{3}\.?[0-9A-Za-z]{3}/?[0-9A-Za-z]{4}-?\d{2}\b")
_MASCARA_CNPJ = "**.***.***/****-**"
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
_MASCARA_EMAIL = "***@***"
# telefone brasileiro: +55 opcional, DDD com ou sem parênteses, 8 ou 9 dígitos (com hífen, ponto ou espaço)
_TELEFONE = re.compile(r"(?<!\d)(?:\+?55[\s.-]?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}(?!\d)")
# em sanitizar(), só o que tem cara de telefone: número puro de 10 dígitos pode ser protocolo, conta ou valor
_TELEFONE_FORMATADO = re.compile(
    r"(?<!\d)(?<!\d[./-])(?:\+55[\s.-]?)?(?:\(\d{2}\)[\s.-]?|\d{2}[\s.-])9?\d{4}[\s.-]\d{4}(?![./-]?\d)"
    r"|(?<!\d)\+55\d{10,11}(?!\d)"
)
_MASCARA_TELEFONE = "(**) *****-****"


def _cnpj_confere(cnpj: str) -> bool:
    """Dígitos verificadores do CNPJ alfanumérico: módulo 11 sobre o código ASCII de cada caractere menos 48."""
    valores = [ord(c) - 48 for c in cnpj.upper()]
    for n in (12, 13):
        pesos = [*range(n - 7, 1, -1), *range(9, 1, -1)]
        resto = sum(v * p for v, p in zip(valores, pesos, strict=False)) % 11
        if valores[n] != (0 if resto < 2 else 11 - resto):
            return False
    return True


def _mascarar_cnpj(m: re.Match) -> str:
    """Só dígitos e formato completo bastam; com letras e sem o formato, a conferência separa CNPJ de palavra comum."""
    achado = m.group()
    bruto = re.sub(r"[./-]", "", achado)
    if bruto.isdigit() or all(s in achado for s in "./-") or _cnpj_confere(bruto):
        return _MASCARA_CNPJ
    return achado


def anonimizar_cpf(texto: str) -> str:
    return _CPF.sub("***.***.***-**", texto)


def anonimizar_cnpj(texto: str) -> str:
    return _CNPJ.sub(_mascarar_cnpj, texto)


def anonimizar_contato(texto: str) -> str:
    """E-mail e qualquer número com cara de telefone (texto livre que o usuário escreve, como um questionário)."""
    return _TELEFONE.sub(_MASCARA_TELEFONE, _EMAIL.sub(_MASCARA_EMAIL, texto))


def pseudonimizar_nome(nome: str, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{nome}".encode()).hexdigest()[:8]
    return f"PESSOA_{h.upper()}"


def sanitizar(texto: str, nomes: list[str] | None = None, salt: str = "", inteiras: bool = False) -> str:
    """Mascara CNPJ (primeiro, por ser o padrão mais longo), CPF, e-mail e telefone, e pseudonimiza nomes conhecidos.
    Endereço e dado bancário não têm formato confiável e passam: esse dado não deve nem chegar aqui.
    inteiras=True só troca o nome como palavra inteira (para um primeiro nome não pegar pedaço de outra palavra)."""
    texto = anonimizar_cpf(anonimizar_cnpj(texto))
    texto = _TELEFONE_FORMATADO.sub(_MASCARA_TELEFONE, _EMAIL.sub(_MASCARA_EMAIL, texto))
    for nome in nomes or []:
        if nome.strip():
            padrao = rf"\b{re.escape(nome)}\b" if inteiras else re.escape(nome)
            texto = re.sub(padrao, pseudonimizar_nome(nome, salt), texto, flags=re.IGNORECASE)
    return texto
