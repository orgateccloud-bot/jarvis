"""Marcos da reforma tributária (EC 132/2023, LC 214/2025, LC 227/2026): dado fixo e versionado, com link oficial.

O Planalto recusa conexão automática; por isso os marcos não são "coletados", são referência permanente do card.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor


class MarcosReforma(Coletor):
    def __init__(self, *a, arquivo: Path, **kw):
        super().__init__(*a, **kw)
        self.arquivo = arquivo

    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        return [ItemFiscal(grupo="legislacao", titulo=m["titulo"], detalhe=m.get("detalhe", ""),
                           data=date.fromisoformat(m["data"]), tipo_data=m["tipo_data"], fonte_id=self.id,
                           fonte_nome=m.get("fonte_nome", self.nome), fonte_url=m["url"],
                           etiquetas=["reforma", *m.get("etiquetas", [])])
                for m in dados["marcos"]]
