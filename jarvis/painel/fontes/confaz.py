"""CONFAZ: convênios ICMS do ano. A lista traz o número e a ementa (no title do link); a data de publicação no DOU
vem da página de cada convênio ("Publicado no DOU de 14.10.26"), só para os mais recentes, com cache por URL.
"""

from __future__ import annotations

import re
from datetime import date

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor, absoluto, casa, data_br, texto

_ITEM = re.compile(r'<a href="([^"]*/CV(\d{3})_(\d{2}))"\s+title="([^"]*)"[^>]*>\s*<span>(.*?)</span>', re.DOTALL)


class ConveniosConfaz(Coletor):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._datas: dict[str, date] = {}   # URL → data de publicação (não muda depois de publicada)

    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        url_ano = f"{self.url.rstrip('/')}/{hoje.year}"
        lista = {}
        for href, num, _ano, ementa, rotulo in _ITEM.findall(fetch(url_ano)):
            lista[int(num)] = (absoluto(url_ano, href), texto(ementa), texto(rotulo))
        if not lista:
            raise self._vazio(f"nenhum convênio na lista de {hoje.year}")
        itens: list[ItemFiscal] = []
        for num in sorted(lista, reverse=True):
            if len(itens) >= self.maximo:
                break
            url, ementa, rotulo = lista[num]
            if not casa(f"{rotulo} {ementa}", self.palavras):
                continue
            if url not in self._datas:
                pagina = fetch(url)
                m = re.search(r"Publicad[oa] no DOU de\s*([\d.]+)", texto(pagina))
                if not m or (quando := data_br(m.group(1))) is None:
                    continue                                   # sem data verificável, não entra
                self._datas[url] = quando
            itens.append(ItemFiscal(grupo="legislacao", titulo=rotulo, detalhe=ementa[:1000], data=self._datas[url],
                                    tipo_data="publicacao", fonte_id=self.id, fonte_nome=self.nome, fonte_url=url,
                                    etiquetas=["ICMS", "CONFAZ"]))
        return itens
