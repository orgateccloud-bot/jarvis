"""Base dos coletores: cada fonte oficial vira uma lista de ItemFiscal com link e data."""

from __future__ import annotations

import html
import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from ..contratos import ItemFiscal
from ..http import Fetch, FonteIndisponivel

MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def texto(fragmento: str) -> str:
    """HTML → texto de uma linha (sem tags, entidades resolvidas, espaços normalizados)."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", fragmento, flags=re.DOTALL | re.IGNORECASE)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def casa(t: str, palavras: list[str]) -> bool:
    """Alguma palavra-chave aparece no texto (sem acento, sem caixa). Lista vazia: tudo passa."""
    if not palavras:
        return True
    n = norm(t)
    return any(norm(p) in n for p in palavras)


def data_br(t: str) -> date | None:
    """dd/mm/aaaa, dd.mm.aa(aa) ou "13 de outubro de 2026"."""
    if m := re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", t):
        d, mth, a = (int(x) for x in m.groups())
        a = a + 2000 if a < 100 else a
        try:
            return date(a, mth, d)
        except ValueError:
            return None
    if m := re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", norm(t)):
        nome = m.group(2).replace("ç", "c")
        if nome in MESES:
            return date(int(m.group(3)), MESES.index(nome) + 1, int(m.group(1)))
    return None


def data_rss(t: str) -> date | None:
    """pubDate (RFC 822) ou dc:date (ISO 8601)."""
    t = t.strip()
    try:
        return parsedate_to_datetime(t).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(t).date()
    except ValueError:
        return None


def absoluto(base: str, href: str) -> str:
    url = urljoin(base, html.unescape(href.strip()))
    return "https://" + url[len("http://"):] if url.startswith("http://") else url


class Coletor(ABC):
    """Uma fonte. Levanta FonteIndisponivel se a página não vier ou não tiver o formato esperado."""

    def __init__(self, id: str, nome: str, url: str, palavras: list[str] | None = None, maximo: int = 15):
        self.id, self.nome, self.url = id, nome, url
        self.palavras = palavras or []
        self.maximo = maximo

    @abstractmethod
    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]: ...

    def _vazio(self, oque: str) -> FonteIndisponivel:
        return FonteIndisponivel(f"{self.nome}: {oque} (a página pode ter mudado de formato)")
