"""Agenda Tributária da Receita Federal: vencimentos por dia (pagamentos e declarações), com a base normativa.

Índice do mês: {url}/{ano}/{Mês}; cada dia em .../dia-15-10-2026 (às vezes "Dia%2013-11-2026"). Cada página de dia tem
a tabela de pagamentos (código, tributo, descrição, período, documento, declaração, fundamentação) e a de declarações
(interessado, obrigação, período de referência, base normativa).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from ..contratos import ItemFiscal
from ..http import Fetch
from .base import Coletor, absoluto, texto

NOMES_MES = ["Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
             "Novembro", "Dezembro"]
_DIA = re.compile(r'href="([^"]*?/[Dd]ia(?:-|%20| )(\d{2})-(\d{2})-(\d{4})/?)"')


def _celulas(linha: str) -> list[str]:
    return [texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", linha, re.DOTALL)]


def _curto(obrigacao: str) -> str:
    """"EFD-Contribuições – Escrituração Fiscal Digital..." → "EFD-Contribuições"."""
    return re.split(r"\s+[–—-]\s+", obrigacao, maxsplit=1)[0].strip()


class AgendaReceita(Coletor):
    def __init__(self, *a, dias: int = 45, **kw):
        super().__init__(*a, **kw)
        self.dias = dias

    def _meses(self, hoje: date) -> list[tuple[int, int]]:
        fim = hoje + timedelta(days=self.dias)
        meses, d = [], date(hoje.year, hoje.month, 1)
        while d <= fim:
            meses.append((d.year, d.month))
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return meses

    def dias_do_mes(self, pagina: str, base: str) -> dict[date, str]:
        dias = {}
        for href, d, m, a in _DIA.findall(pagina):
            try:
                dias[date(int(a), int(m), int(d))] = absoluto(base, href)
            except ValueError:
                continue
        return dias

    def itens_do_dia(self, pagina: str, dia: date, url: str) -> list[ItemFiscal]:
        tabelas = re.findall(r"<table.*?</table>", pagina, re.DOTALL)
        itens: list[ItemFiscal] = []
        pagamentos: dict[str, list[list[str]]] = defaultdict(list)
        for tab in tabelas:
            linhas = [_celulas(lin) for lin in re.findall(r"<tr.*?</tr>", tab, re.DOTALL)]
            pendente: list[str] | None = None
            for c in linhas:
                # pagamento: cada registro ocupa duas linhas (código, tributo, descrição, período) e
                # (documento, declaração, fundamentação); numa linha só, vem com as 7 colunas
                if len(c) >= 7 and c[0][:1].isdigit():
                    pagamentos[c[1]].append(c)
                elif len(c) == 4 and c[0][:1].isdigit():
                    pendente = c
                elif len(c) == 3 and pendente is not None:
                    pagamentos[pendente[1]].append(pendente + c)
                    pendente = None
                elif len(c) == 4 and c[0] in ("PJ", "PF", "PJ/PF", "PF/PJ"):   # declaração
                    nome = _curto(c[1])
                    itens.append(ItemFiscal(
                        grupo="prazos", titulo=f"{nome} ({c[0]})", data=dia, tipo_data="vencimento",
                        detalhe=f"{c[1]}. Período de referência: {c[2]}. Base: {c[3]}."[:1000],
                        fonte_id=self.id, fonte_nome=self.nome, fonte_url=url, etiquetas=[nome, c[1]],
                    ))
        for tributo, linhas in pagamentos.items():
            docs = sorted({c[4] for c in linhas if c[4]})
            exemplo = linhas[0]
            itens.append(ItemFiscal(
                grupo="prazos", titulo=f"Pagamento: {tributo}", data=dia, tipo_data="vencimento",
                detalhe=(f"{len(linhas)} código(s) de receita ({', '.join(docs)}). Ex.: {exemplo[0]} – {exemplo[2]}, "
                         f"período {exemplo[3]}. Base: {exemplo[6]}.")[:1000],
                fonte_id=self.id, fonte_nome=self.nome, fonte_url=url,
                etiquetas=[tributo, *docs, *{c[2] for c in linhas}][:40],
            ))
        return itens

    def coletar(self, fetch: Fetch, hoje: date) -> list[ItemFiscal]:
        fim = hoje + timedelta(days=self.dias)
        itens: list[ItemFiscal] = []
        for ano, mes in self._meses(hoje):
            base = f"{self.url.rstrip('/')}/{ano}/{NOMES_MES[mes - 1]}"
            dias = self.dias_do_mes(fetch(base), base)
            if not dias:
                raise self._vazio(f"nenhum dia de vencimento no índice de {NOMES_MES[mes - 1]}/{ano}")
            for dia, url in sorted(dias.items()):
                if hoje <= dia <= fim:
                    itens += self.itens_do_dia(fetch(url), dia, url)
        return itens
