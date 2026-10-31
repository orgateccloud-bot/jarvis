"""Lógica de texto da voz portada do HUD para o serviço local, com o mesmo comportamento:

- corrigir_termos  ← jarvis-hud/src/lib/voice/termos.js (corrigirTermos)
- depois_do_vocativo, e_comando_de_parar, WAKE_WORD ← jarvis-hud/src/lib/voice/sentences.js
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


def palavras(texto: str) -> list[str]:
    """Minúsculas, sem acento e sem pontuação (mesma normalização do filtro de eco)."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w]+|_", " ", t).split()
