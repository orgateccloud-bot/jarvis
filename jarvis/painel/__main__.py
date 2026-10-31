"""Coleta manual das fontes do card tributário: python -m jarvis.painel coletar [id ...]

Usa o mesmo banco da API (dados/jarvis.db) e a mesma configuração (config/fontes_fiscais.json); mostra o resultado de
cada fonte. Útil para conferir uma fonte nova ou depois de mudar a configuração.
"""

from __future__ import annotations

import sys

from ..config import get_settings
from .coleta import ArmazemPainel, ServicoColeta
from .fontes import carregar


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "coletar":
        print(__doc__)
        return 2
    s = get_settings()
    servico = ServicoColeta(ArmazemPainel(s.db_path), carregar(s.fontes_fiscais()))
    for st in servico.coletar(set(argv[1:]) or None):
        estado = "desligada" if not st.ligada else "ok" if st.ok else "FALHOU" if st.ok is False else "sem coleta"
        print(f"{st.id:18} {estado:10} {st.itens:3} itens  {st.erro or st.nota or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
