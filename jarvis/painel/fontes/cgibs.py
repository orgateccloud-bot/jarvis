"""Comitê Gestor do IBS: resoluções (PDF, ementa e "Publicada ... no site do CGIBS em dd/mm/aaaa").

As notícias do site do CGIBS são carregadas por JavaScript (o HTML não tem os itens); as resoluções vêm no HTML.
"""

from __future__ import annotations

import re
from datetime import date

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor, absoluto, casa, data_br, texto

_PAINEL = re.compile(r'<div class="panel-body">(.*?)</div>', re.DOTALL)


class ResolucoesCgibs(Coletor):
    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        pagina = fetch(self.url)
        vistos: dict[str, ItemFiscal] = {}
        for corpo in _PAINEL.findall(pagina):
            link = re.search(r'<a href="([^"]+\.pdf)"[^>]*>(.*?)</a>', corpo, re.DOTALL)
            quando = re.search(r"em\s+(\d{2}/\d{2}/\d{4})", texto(corpo))
            if not link or not quando or (dia := data_br(quando.group(1))) is None:
                continue
            url = absoluto(self.url, link.group(1))
            titulo = texto(link.group(2))
            ementa = texto(m.group(1)) if (m := re.search(r"<strong>(.*?)</strong>", corpo, re.DOTALL)) else ""
            if url in vistos and not ementa:
                continue                               # o mesmo PDF aparece de novo no acordeão, sem a ementa
            if casa(f"{titulo} {ementa}", self.palavras):
                vistos[url] = ItemFiscal(grupo="legislacao", titulo=titulo[:300], detalhe=ementa[:1000], data=dia,
                                         tipo_data="publicacao", fonte_id=self.id, fonte_nome=self.nome,
                                         fonte_url=url, etiquetas=["IBS", "CGIBS"])
        if not vistos:
            raise self._vazio("nenhuma resolução com data")
        return sorted(vistos.values(), key=lambda i: i.data, reverse=True)[: self.maximo]
