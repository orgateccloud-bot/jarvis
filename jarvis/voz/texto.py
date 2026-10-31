"""Lógica de texto da voz portada do HUD para o serviço local, com o mesmo comportamento:

- corrigir_termos  ← jarvis-hud/src/lib/voice/termos.js (corrigirTermos)
- depois_do_vocativo, e_comando_de_parar, WAKE_WORD, SIM, NAO, para_fala, DivisorDeFrases
  ← jarvis-hud/src/lib/voice/sentences.js (afterWakeWord, isStopCommand, YES, NO, paraFala, createSentenceSplitter)
- palavras ← jarvis-hud/src/lib/voice/echo.js (tokens)

A paridade é conferida pelos mesmos casos dos dois lados: tests/fixtures/voz/casos.json.
Os regex usam re.ASCII porque o \\b do JavaScript (sem a flag u) só conhece letras ASCII.
"""

from __future__ import annotations

import re
import unicodedata

# Variantes de "Jarvis" só valem no começo da fala (vocativo): "graves" e "Jarbas" no meio de uma frase são
# palavras comuns e não podem acordar o assistente.
_VARIANTES = r"jarvis|jarbas|jarvas|jarves|jervis|javis|jarvi|jarviz|djarvis|garvis|graves|travis|jar vis"
_VOCATIVO = re.compile(rf"^(\s*(?:ei|ok|oi|hey|ol[aá])[\s,]+)?(?:{_VARIANTES})\b", re.IGNORECASE | re.ASCII)

# (padrão, troca): siglas soletradas ou em minúsculas e nomes próprios
_TERMOS = [
    (re.compile(r"\b(?:d[aá]bli[ou]|w)[\s.]*(?:esse|s)[\s.]*(?:ele|l)\b", re.IGNORECASE | re.ASCII), "WSL"),
    (re.compile(r"\bo\.?\s?a\.?\s?b\b\.?", re.IGNORECASE | re.ASCII), "OAB"),
    (re.compile(r"\bc\.?\s?t\.?\s?n\b\.?", re.IGNORECASE | re.ASCII), "CTN"),
    (re.compile(r"\bi\.?\s?c\.?\s?m\.?\s?s\b\.?", re.IGNORECASE | re.ASCII), "ICMS"),
    (re.compile(r"\bi\.?\s?b\.?\s?s\b\.?", re.IGNORECASE | re.ASCII), "IBS"),
    (re.compile(r"\bc\.?\s?b\.?\s?s\b\.?", re.IGNORECASE | re.ASCII), "CBS"),
    (re.compile(r"\bp\.?\s?g\.?\s?f\.?\s?n\b\.?", re.IGNORECASE | re.ASCII), "PGFN"),
    (re.compile(r"\bmei\b", re.IGNORECASE | re.ASCII), "MEI"),
    (re.compile(r"\bIBS (?:barra|e) CBS\b", re.ASCII), "IBS/CBS"),
    (re.compile(r"\bvel+o[sz]+o\b", re.IGNORECASE | re.ASCII), "Veloso"),
]

WAKE_WORD = re.compile(r"\bjarvis\b", re.IGNORECASE | re.ASCII)
# interromper por voz só com comando curto no começo da fala: "Jarvis, pare", "Jarvis, silêncio" ou "pare"
_PARAR = re.compile(r"^(?:jarvis[\s,!.]+(?:pare|sil[eê]ncio)|pare)(?![^\W_])", re.IGNORECASE)


def corrigir_termos(texto: str) -> str:
    if not texto:
        return texto
    t = _VOCATIVO.sub(lambda m: f"{m.group(1) or ''}Jarvis", texto, count=1)
    for padrao, troca in _TERMOS:
        t = padrao.sub(troca, t)
    return t


def depois_do_vocativo(texto: str) -> str | None:
    """O pedido que veio junto da palavra de ativação ("Jarvis, que horas são?" → "que horas são?")."""
    m = WAKE_WORD.search(texto)
    if not m:
        return None
    resto = WAKE_WORD.sub("", texto[m.start():], count=1)
    return re.sub(r"^[\s,.!?:;-]+", "", resto).strip()


def e_comando_de_parar(texto: str) -> bool:
    t = (texto or "").strip()
    return bool(t) and len(t.split()) <= 3 and bool(_PARAR.match(t))


def sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def palavras(texto: str) -> list[str]:
    """Minúsculas, sem acento e sem pontuação (mesma normalização do filtro de eco)."""
    return re.sub(r"[^\w]+|_", " ", sem_acento((texto or "").lower())).split()


# Respostas a uma confirmação falada ("Confirma: abrir o Chrome? Diga sim ou não.")
SIM = re.compile(r"^\s*(sim|pode|pode sim|confirmo|confirma|autorizo|aprovado|aprovo|ok|claro|manda)\b",
                 re.IGNORECASE | re.ASCII)
NAO = re.compile(r"^\s*(n[aã]o|cancela|cancelar|negado|nega|nem pensar)\b", re.IGNORECASE | re.ASCII)


# ---------- texto falável e corte em frases (sentences.js) ----------
MIN_CHARS = 80
MAX_CHARS = 220


def _ponto_de_corte(texto: str) -> int:
    """A vírgula mais próxima do teto; sem vírgula, o último espaço (cutPoint)."""
    virgula = texto.rfind(", ", 0, MAX_CHARS + 2)
    if virgula >= MIN_CHARS / 2:
        return virgula + 1
    depois = texto.find(", ", MAX_CHARS)
    if 0 <= depois < MAX_CHARS * 1.5:
        return depois + 1
    espaco = texto.rfind(" ", 0, MAX_CHARS + 1)
    return espaco if espaco > 0 else MAX_CHARS


def _ultimo_segmento(caminho: str) -> str:
    """Último segmento de um caminho, mantendo a pontuação da frase que veio colada ("C:\\a\\c.txt;" → "c.txt;")."""
    m = re.match(r"^(.*?)([.,;:!?)]*)$", caminho, re.DOTALL)
    corpo, cauda = m.group(1), m.group(2)
    partes = [p for p in re.split(r"[\\/]", corpo) if p]
    return (partes[-1] if partes else "o caminho") + cauda


_URL = re.compile(r"\bhttps?://(?:www\.)?([^\s/?#)]+)[^\s)]*", re.IGNORECASE)
_WWW = re.compile(r"\bwww\.([^\s/?#)]+)[^\s)]*", re.IGNORECASE)
_CAMINHO_WIN = re.compile(r"(?:\b[A-Za-z]:\\|\\\\)[^\s\"'`<>|*?]*", re.ASCII)
_CAMINHO_UNIX = re.compile(r"(?:^|(?<=\s))(?:~|\.{1,2})?/[\w.-]+(?:/[\w.-]*)+", re.ASCII)
_REAIS = re.compile(r"R\$\s?(\d[\d.]*(?:,\d{1,2})?)(\s(?:mil|milh(?:ão|ões)|bilh(?:ão|ões)))?", re.ASCII)
_PORCENTO = re.compile(r"(\d(?:[\d.,]*\d)?)\s?%", re.ASCII)


def para_fala(texto: str) -> str:
    """Caminhos e URLs lidos letra a letra viram o nome final e o domínio; "_" vira espaço; aspas de código saem;
    "R$" e "%" vão por extenso (paraFala)."""
    t = _URL.sub(r"\1", texto)
    t = _WWW.sub(r"\1", t)
    t = _CAMINHO_WIN.sub(lambda m: _ultimo_segmento(m.group(0)), t)
    t = _CAMINHO_UNIX.sub(lambda m: _ultimo_segmento(m.group(0)), t)
    t = _REAIS.sub(lambda m: f"{m.group(1)}{m.group(2) or ''} reais", t)
    t = _PORCENTO.sub(r"\1 por cento", t)
    return re.sub("[\"“”`]", "", t.replace("_", " "))


def _limpar(texto: str) -> str:
    t = re.sub(r"^\s*([-*•]|\d+[.)])\s+", "", texto, count=1)     # marcador de lista
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)              # links/imagens → só o texto
    t = re.sub(r"[#*~>|]", "", para_fala(t))
    return re.sub(r"\s+", " ", t).strip()


class DivisorDeFrases:
    """Corta o texto que chega em streaming em frases faláveis, para a voz começar antes da resposta terminar.
    Pula código e tabelas, junta frases curtas e quebra as longas; corta só em . ! ? … e quebra de linha."""

    def __init__(self, emitir):
        self.emitir = emitir
        self._buf = ""
        self._pendente = ""
        self._em_codigo = False

    def _saida(self, texto: str, forcar: bool = False) -> None:
        c = _limpar(texto)
        if not c:
            return
        # ao juntar trechos curtos, garante uma pausa entre eles (itens de lista não têm ponto final)
        if self._pendente:
            self._pendente = f"{self._pendente}{'' if re.search(r'[.!?…;:,]$', self._pendente) else '.'} {c}"
        else:
            self._pendente = c
        while len(self._pendente) > MAX_CHARS:
            i = _ponto_de_corte(self._pendente)
            self.emitir(self._pendente[:i].strip())
            self._pendente = self._pendente[i:].strip()
        if forcar or len(self._pendente) >= MIN_CHARS:
            self.emitir(self._pendente)
            self._pendente = ""

    def _linha(self, linha: str, forcar: bool) -> None:
        if re.match(r"^\s*```", linha):
            self._em_codigo = not self._em_codigo
            return
        if self._em_codigo or re.match(r"^\s*\|", linha):
            return
        self._saida(linha, forcar)

    def push(self, delta: str) -> None:
        self._buf += delta
        while (nl := self._buf.find("\n")) >= 0:
            self._linha(self._buf[:nl], False)
            self._buf = self._buf[nl + 1:]
        if self._em_codigo or re.match(r"^\s*(```|\|)", self._buf):
            return
        # frases completas na linha corrente: pontuação seguida de espaço e mais texto
        while m := re.match(r"([\s\S]*?[.!?…])\s+(?=\S)", self._buf):
            self._saida(m.group(1))
            self._buf = self._buf[m.end():]
        # frase longa sem ponto ainda chegando: fala até a vírgula para a voz não esperar o fim
        while len(self._buf) > MAX_CHARS * 1.5:
            i = _ponto_de_corte(self._buf)
            self._saida(self._buf[:i])
            self._buf = self._buf[i:].lstrip()

    def flush(self) -> None:
        if self._buf.strip():
            self._linha(self._buf, True)
        if self._pendente:
            self.emitir(self._pendente)
            self._pendente = ""
        self._buf = ""
        self._em_codigo = False
