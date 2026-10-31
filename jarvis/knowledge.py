"""Atalho de compatibilidade: a base de conhecimento mora em jarvis.conhecimento (catálogo TOML, cabeçalho v2, corte
por tipo, índice SQLite FTS5 e coleta). As fontes saíram do código (R12): ficam em <base>/_catalogo/*.toml.

Uso: python -m jarvis.knowledge baixar      → o mesmo que python -m jarvis.conhecimento atualizar
     python -m jarvis.knowledge buscar "decadência do crédito tributário"
"""

from __future__ import annotations

import sys

from .conhecimento.base import KnowledgeBase
from .conhecimento.corte import TAM_TRECHO, cortar
from .conhecimento.documento import html_para_texto, ler_documento
from .conhecimento.indice import SINONIMOS, Trecho, tokens

__all__ = ["SINONIMOS", "TAM_TRECHO", "KnowledgeBase", "Trecho", "cortar", "html_para_texto", "ler_documento",
           "tokens"]


def _main(argv: list[str]) -> int:
    from .conhecimento.__main__ import main

    if argv[:1] == ["baixar"]:
        return main(["atualizar", *argv[1:]])
    if argv[:1] == ["buscar"] and len(argv) > 1:
        return main(["buscar", " ".join(argv[1:])])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
