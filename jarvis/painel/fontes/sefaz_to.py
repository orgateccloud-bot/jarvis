"""SEFAZ do Tocantins: cartões de notícia (link, data dd/mm/aaaa e manchete) em to.gov.br/sefaz/noticias."""

from __future__ import annotations

import re
from datetime import date

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor, absoluto, casa, data_br, texto

_CARTAO = re.compile(r'<div class="news-card">(.*?)(?=<div class="news-card">|$)', re.DOTALL)


class NoticiasSefazTO(Coletor):
    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        pagina = fetch(self.url)
        itens: list[ItemFiscal] = []
        for cartao in _CARTAO.findall(pagina):
            manchete = re.search(r'<a href="([^"]+)"[^>]*>\s*<h4[^>]*>(.*?)</h4>', cartao, re.DOTALL)
            quando = re.search(r'news-card--data[^>]*>(.*?)</span>', cartao, re.DOTALL)
            if not manchete or not quando or (dia := data_br(texto(quando.group(1)))) is None or dia > hoje:
                continue
            titulo = texto(manchete.group(2))
            if casa(titulo, self.palavras):
                itens.append(ItemFiscal(grupo="legislacao", titulo=titulo[:300], data=dia, tipo_data="publicacao",
                                        fonte_id=self.id, fonte_nome=self.nome,
                                        fonte_url=absoluto(self.url, manchete.group(1)), etiquetas=["TO", "ICMS"]))
        if not _CARTAO.search(pagina):
            raise self._vazio("nenhum cartão de notícia")
        itens.sort(key=lambda i: i.data, reverse=True)
        return itens[: self.maximo]
