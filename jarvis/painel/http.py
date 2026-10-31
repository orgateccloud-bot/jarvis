"""Busca HTTP das fontes oficiais: urllib, User-Agent identificado (nunca disfarçado), timeout e limite de tamanho."""

from __future__ import annotations

import urllib.request
from collections.abc import Callable

USER_AGENT = "JARVIS/4.0 (painel tributario; uso pessoal)"
TIMEOUT_S = 15
MAX_BYTES = 3_000_000

Fetch = Callable[[str], str]


class FonteIndisponivel(Exception):
    """A fonte não respondeu, respondeu com erro ou mudou de formato."""


def buscar(url: str, timeout: float = TIMEOUT_S, headers: dict[str, str] | None = None) -> str:
    """Texto da página. Só https: as fontes são portais oficiais (ou o ERP, com o token no cabeçalho)."""
    if not url.startswith("https://"):
        raise FonteIndisponivel(f"só https é aceito: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 — esquema https conferido acima
            dados = r.read(MAX_BYTES + 1)
            charset = r.headers.get_content_charset() or "utf-8"
    except Exception as e:
        raise FonteIndisponivel(f"{type(e).__name__}: {e}") from e
    if len(dados) > MAX_BYTES:
        raise FonteIndisponivel(f"resposta maior que {MAX_BYTES} bytes")
    return dados.decode(charset, errors="replace")
