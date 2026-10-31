"""Filtro de eco, portado de jarvis-hud/src/lib/voice/echo.js: lembra as últimas frases que o JARVIS falou e
reconhece quando o microfone devolve uma delas. Vale para a fala em curso e por JANELA_MS depois do fim.

No serviço local o microfone fica mudo durante a fala (half-duplex); o filtro importa no modo fone
(JARVIS_VOZ_INTERROMPER=1), em que o microfone continua aberto, e na cauda logo depois da fala.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.voz.texto import palavras

MAX = 6
JANELA_MS = 8000
SOBREPOSICAO = 0.6
# palavras que aparecem em quase toda frase: não contam na sobreposição
COMUNS = {"que", "para", "com", "uma", "por", "mais", "como", "dos", "das", "nos", "nas", "seu", "sua", "isso",
          "esse", "essa", "este", "esta", "tem", "foi", "ser", "sao", "nao", "mas", "ele", "ela", "voce"}


def _conteudo(ts: list[str]) -> list[str]:
    c = [t for t in ts if len(t) >= 3 and t not in COMUNS]
    return c or ts


def _lcs(a: list[str], b: list[str]) -> int:
    """Maior subsequência comum, em palavras."""
    ant = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(ant[j] + 1 if x == y else max(ant[j + 1], cur[j]))
        ant = cur
    return ant[len(b)]


@dataclass
class _Dito:
    toks: list[str]
    linha: str
    fim_ms: float | None  # None enquanto a fala não terminou


class FiltroDeEco:
    def __init__(self, maximo: int = MAX, janela_ms: float = JANELA_MS,
                 agora_ms: Callable[[], float] = lambda: time.monotonic() * 1000):
        self.maximo = maximo
        self.janela_ms = janela_ms
        self.agora_ms = agora_ms
        self._ditos: list[_Dito] = []

    def _recentes(self) -> list[_Dito]:
        t = self.agora_ms()
        self._ditos = [s for s in self._ditos if s.fim_ms is None or t - s.fim_ms <= self.janela_ms]
        return self._ditos

    def lembrar(self, texto: str) -> None:
        toks = palavras(texto)
        if not toks:
            return
        self._ditos.append(_Dito(toks, f" {' '.join(toks)} ", None))
        self._ditos = self._ditos[-self.maximo:]

    def terminou(self) -> None:
        """A fala terminou (fim natural ou cancelada): começa a contar a janela."""
        t = self.agora_ms()
        for s in self._ditos:
            if s.fim_ms is None:
                s.fim_ms = t

    def e_eco(self, texto: str, resposta: bool = False) -> bool:
        """resposta: o texto parece "sim"/"não" a uma confirmação. Aí só conta o eco literal com 3+ palavras
        ("sim ou não"), para não engolir o "sim" do usuário logo depois de "Diga sim ou não"."""
        ouvido = palavras(texto)
        if not ouvido or (resposta and len(ouvido) < 3):
            return False
        linha = f" {' '.join(ouvido)} "
        lista = self._recentes()
        # o eco pode emendar o fim de uma frase com o começo da seguinte
        pares = [s.linha if i == 0 else f" {lista[i - 1].linha.strip()}{s.linha}" for i, s in enumerate(lista)]
        if any(linha in p for p in pares):
            return True
        if resposta or len(ouvido) < 3:
            return False
        # sobreposição na mesma ordem (o eco preserva a ordem; a pergunta nova que reaproveita palavras, não)
        h = _conteudo(ouvido)
        return any(_lcs(h, _conteudo(s.toks if i == 0 else lista[i - 1].toks + s.toks)) / len(h) >= SOBREPOSICAO
                   for i, s in enumerate(lista))

    def limpar(self) -> None:
        self._ditos = []
