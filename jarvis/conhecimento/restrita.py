"""A base de conhecimento vista só pelas áreas jurídicas (perfil só Trilhum).

A base (D:\\JARVIS-Conhecimento) é abastecida pelo JARVIS-IurisNotitia: a coleta das leis, súmulas e precedentes
roda lá (python -m jarvis.conhecimento), e o JARVIS-TRILHUM só consulta. Aqui ficam de fora as áreas que não são
jurídicas (contábil, rural, técnica...): a busca sem área percorre só as permitidas, e uma área de fora é recusada.
"""

from __future__ import annotations

from typing import Any

AREAS_JURIDICAS = ("juridico", "oab", "tributario")


class BaseRestrita:
    def __init__(self, base: Any, areas: tuple[str, ...] | list[str] = AREAS_JURIDICAS):
        self.base = base
        self.permitidas = tuple(a.strip().lower() for a in areas if a.strip())

    def areas(self) -> list[str]:
        return [a for a in self.base.areas() if a in self.permitidas]

    def areas_em_uso(self) -> list[str]:
        return [a for a in self.base.areas_em_uso() if a in self.permitidas]

    def buscar(self, consulta: str, area: str | None = None, k: int = 5, **filtros) -> list:
        """Na área pedida (se for jurídica) ou em todas as jurídicas, os k melhores trechos, sem repetir."""
        if area is not None:
            return self.base.buscar(consulta, area, k, **filtros) if area in self.permitidas else []
        achados: dict[tuple, tuple] = {}
        for a in self.permitidas:
            for ponto, t in self.base.buscar(consulta, a, k, **filtros):
                chave = (t.arquivo, t.rotulo)   # súmulas e temas transversais aparecem em mais de uma área
                if chave not in achados or ponto > achados[chave][0]:
                    achados[chave] = (ponto, t)
        return sorted(achados.values(), key=lambda x: -x[0])[:k]

    def __getattr__(self, nome: str):   # o resto (sincronizar, catálogo...) vem da base
        return getattr(self.base, nome)
