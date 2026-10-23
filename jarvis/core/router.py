"""Roteador determinístico: decide sem LLM se o turno vai para o local, chat (low) ou tarefa (high)."""

from __future__ import annotations

import re
import unicodedata

from .contracts import BudgetState, Decision, Route


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


# Pedidos que o JARVIS resolve sozinho, sem custo.
_LOCAL_PATTERNS = [
    r"^(oi|ola|e ai|bom dia|boa tarde|boa noite|jarvis|hey jarvis|obrigad[oa]|valeu)[\s!.,?]*$",
    r"\b(que horas|horas sao|que dia e hoje|data de hoje)\b",
    r"\b(status|uso) d[oa] (pc|computador|sistema|cpu|ram|memoria|disco)\b",
    r"\b(quanto|qual).{0,20}(cpu|ram|memoria|disco)\b",
]

# Indícios de tarefa que pede raciocínio profundo ou várias etapas.
_TASK_HINTS = [
    "analise", "analisa", "compare", "compara", "pesquise", "pesquisa", "planeje", "planeja",
    "relatorio", "estrategia", "investigue", "calcule", "resuma o documento", "passo a passo",
    "codigo", "programa", "script", "depure", "revise",
]


def decide(text: str, budget: BudgetState) -> Decision:
    t = _norm(text)

    if budget is BudgetState.LOCAL_ONLY:
        return Decision(route=Route.LOCAL, reason="teto mensal atingido: somente modelo local")

    if any(re.search(p, t) for p in _LOCAL_PATTERNS):
        return Decision(route=Route.LOCAL, reason="pedido trivial resolvido localmente")

    is_task = len(t) > 400 or sum(h in t for h in _TASK_HINTS) >= 1
    if budget is BudgetState.ECONOMY:
        return Decision(
            route=Route.TASK if is_task else Route.CHAT,
            effort="low",
            reason="modo economia (>=80% do teto): effort low",
        )
    if is_task:
        return Decision(route=Route.TASK, effort="high", reason="tarefa com raciocínio/etapas")
    return Decision(route=Route.CHAT, effort="low", reason="conversa")
