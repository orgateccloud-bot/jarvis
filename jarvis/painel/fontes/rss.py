"""RSS 1.0 (RDF, como o da Receita) e RSS 2.0 (WordPress, como o da Economia GO), lidos sem parser XML externo.

O feed da Receita mistura páginas de pasta e imagens com as notícias: o filtro de URL descarta o que não é notícia.
"""

from __future__ import annotations

import html
import re
from datetime import date

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor, casa, data_rss, texto

_NAO_NOTICIA = re.compile(r"(\.(png|jpe?g|gif|pdf)(/view)?$|/(carrossel|colecao|todas-as-noticias|ultimas-noticias|"
                          r"noticias)/?$)", re.IGNORECASE)


def _campo(item: str, *tags: str) -> str:
    for tag in tags:
        if m := re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", item, re.DOTALL):
            valor = m.group(1)
            if c := re.fullmatch(r"\s*<!\[CDATA\[(.*?)\]\]>\s*", valor, re.DOTALL):
                valor = c.group(1)
            return valor.strip()
    return ""


class FeedRSS(Coletor):
    def __init__(self, *a, grupo: str = "legislacao", **kw):
        super().__init__(*a, **kw)
        self.grupo = grupo

    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        xml = fetch(self.url)
        itens_xml = re.findall(r"<item\b.*?</item>", xml, re.DOTALL)
        if not itens_xml:
            raise self._vazio("feed sem itens")
        itens: list[ItemFiscal] = []
        for bruto in itens_xml:
            link = html.unescape(_campo(bruto, "link") or (re.search(r'rdf:about="([^"]+)"', bruto) or [None, ""])[1])
            titulo = texto(_campo(bruto, "title"))
            quando = data_rss(_campo(bruto, "pubDate", "dc:date"))
            resumo = texto(_campo(bruto, "description"))[:400]
            if not link.startswith("https://") or not titulo or quando is None or quando > hoje:
                continue
            if _NAO_NOTICIA.search(link) or not casa(f"{titulo} {resumo}", self.palavras):
                continue
            itens.append(ItemFiscal(grupo=self.grupo, titulo=titulo[:300], detalhe=resumo, data=quando,
                                    tipo_data="publicacao", fonte_id=self.id, fonte_nome=self.nome, fonte_url=link))
        itens.sort(key=lambda i: i.data, reverse=True)
        return itens[: self.maximo]
