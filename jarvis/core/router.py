"""Roteador determinístico (sem LLM, sem custo): regras | Haiku | Sonnet | Opus | Fable conforme a complexidade.

Pontuação de complexidade:
  0     → simples       → Haiku 5.5,  effort low
  1-2   → intermediário → Sonnet 5.5, effort high
  3     → complexo      → Opus 5.5,   effort xhigh
  >= 4  → topo          → Fable 5.1,  effort high  (calibrado em ~3,5% das perguntas reais; JARVIS_FABLE_PONTOS)
Prefixos /haiku, /sonnet, /opus, /fable (ou "pense bem", que vai ao Opus) forçam a camada.
No modo economia (>= 80% do teto) tudo desce uma camada com effort low; no teto, o Claude pausa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .contracts import BudgetState, Decision, Route


@dataclass(frozen=True)
class Tiers:
    simple: str = "claude-haiku-5-5"
    medium: str = "claude-sonnet-5-5"
    complex: str = "claude-opus-5-5"
    fable: str = "claude-fable-5-1"
    fable_pontos: int = 4  # pontuação mínima para o Fable (o Opus fica com a faixa de 3 até aqui)

    def model(self, route: Route) -> str:
        return {Route.SIMPLE: self.simple, Route.MEDIUM: self.medium, Route.COMPLEX: self.complex,
                Route.FABLE: self.fable}[route]


DEFAULT_TIERS = Tiers()


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

# +1 cada: tarefa que pede algum trabalho além de conversar.
_TASK_HINTS = [
    "analise", "analisa", "resuma", "resume", "explique", "explica", "calcule", "calcula", "traduza",
    "escreva", "redija", "codigo", "script", "programa", "funcao", "sql", "planilha", "revise", "corrija",
    # busca na web (só Sonnet/Opus/Fable têm as ferramentas web)
    "pesquise", "pesquisa", "noticia", "cotacao", "previsao do tempo", "procure na internet",
]

# +2 cada: raciocínio profundo, várias etapas ou alto custo de erro.
_COMPLEX_HINTS = [
    "estrategia", "planeje", "planejamento", "arquitetura", "compare", "compara", "pros e contras",
    "detalhad", "profund", "passo a passo", "investigue", "depure", "debug", "relatorio", "parecer",
    "laudo", "tributar", "fiscal", "juridic", "contrato", "otimize", "refatore", "demonstre", "prove",
]

# Áreas do especialista (perfil multiárea: a área vem do assunto). Pergunta de área nunca fica no Haiku.
_AREAS = {
    "tributario": [r"\btribut", r"\bimposto", r"\breforma tributaria", r"\bfato gerador", r"\baliquota",
                   r"\bbase de calculo", r"\bdecadencia", r"\bprescricao", r"\bsimples nacional", r"\blc ?123\b",
                   r"\bexecucao fiscal", r"\breceita federal", r"\bcertidao negativa", r"\bmei\b",
                   r"\b(icms|ipi|iss|issqn|pis|cofins|irpf|irpj|csll|ibs|cbs|ctn|itcmd|itcd|itbi|iptu|ipva|pgfn|darf)\b"],
    "oab": [r"\boab\b", r"\badvoca", r"\badvogad", r"\bexame de ordem", r"\bcodigo de etica", r"\bhonorarios?\b",
            r"\bsigilo profissional", r"\b8\.?906\b", r"\bestatuto da (advocacia|oab|ordem)"],
    "contabil": [r"\bcontab", r"\bbalanco", r"\bbalancete", r"\bdre\b", r"\b(livro )?razao contabil|\blivro razao", r"\bconcilia", r"\bsped\b",
                 r"\becd\b", r"\becf\b", r"\bescritura", r"\bdepreciac", r"\bnota fiscal", r"\bauditoria",
                 r"\bpgdas", r"\bplano de contas"],
}

# "Jarvis, pede ao agente tributário..." (o Whisper às vezes escreve "a gente tributário")
_DELEGACAO = re.compile(r"\b(?:agente|a gente)\s+(tributari[oa])\b")
_AGENTE_DO_TERMO = {"tributario": "tributario", "tributaria": "tributario"}

_FORCE = {"/haiku": Route.SIMPLE, "/sonnet": Route.MEDIUM, "/opus": Route.COMPLEX, "/fable": Route.FABLE}
_EFFORT = {Route.SIMPLE: "low", Route.MEDIUM: "high", Route.COMPLEX: "xhigh", Route.FABLE: "high"}
_DOWN = {Route.FABLE: Route.COMPLEX, Route.COMPLEX: Route.MEDIUM, Route.MEDIUM: Route.SIMPLE,
         Route.SIMPLE: Route.SIMPLE}
_UP = {Route.SIMPLE: Route.MEDIUM, Route.MEDIUM: Route.COMPLEX, Route.COMPLEX: Route.COMPLEX,
       Route.FABLE: Route.FABLE}


def strip_force(text: str) -> str:
    """Remove o prefixo de camada (/opus etc.) antes de enviar a mensagem ao modelo."""
    return re.sub(r"^\s*/(haiku|sonnet|opus|fable)\b\s*", "", text, flags=re.IGNORECASE) or text


def complexity_score(t: str) -> int:
    score = sum(h in t for h in _TASK_HINTS) + 2 * sum(h in t for h in _COMPLEX_HINTS)
    if len(t) > 400:
        score += 2
    if len(t) > 1500:
        score += 2
    if "```" in t or t.count("\n") >= 6:
        score += 2
    if t.count("?") >= 2:
        score += 1
    if re.search(r"\b(depois|em seguida|alem disso|primeiro|segundo)\b", t):
        score += 1
    return score


def tier_for(score: int, fable_pontos: int = DEFAULT_TIERS.fable_pontos) -> Route:
    if score >= fable_pontos:
        return Route.FABLE
    if score >= 3:
        return Route.COMPLEX
    if score >= 1:
        return Route.MEDIUM
    return Route.SIMPLE


def escalate(route: Route) -> Route:
    return _UP[route]


def area_for(t: str) -> str | None:
    """Área especializada pelo assunto (texto já normalizado); empate fica com a ordem de _AREAS."""
    contagem = {a: sum(bool(re.search(p, t)) for p in pats) for a, pats in _AREAS.items()}
    melhor = max(contagem, key=contagem.get)
    return melhor if contagem[melhor] else None


def delegacao_para(t: str, agentes: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Agente pedido no texto (já normalizado), se estiver ativo."""
    m = _DELEGACAO.search(t)
    agente = _AGENTE_DO_TERMO.get(m.group(1)) if m else None
    return agente if agente in agentes else None


def decide(text: str, budget: BudgetState, tiers: Tiers = DEFAULT_TIERS,
           agentes: frozenset[str] | set[str] = frozenset()) -> Decision:
    t = _norm(text)

    if budget is BudgetState.CAP_REACHED:
        return Decision(route=Route.LOCAL, reason="teto mensal atingido: Claude pausado")

    forced = next((r for p, r in _FORCE.items() if t.startswith(p)), None)
    if forced is None and t.startswith("pense bem"):
        forced = Route.COMPLEX

    if forced is None and any(re.search(p, t) for p in _LOCAL_PATTERNS):
        return Decision(route=Route.LOCAL, reason="pedido trivial resolvido localmente")

    area = area_for(t)
    if (delegar := delegacao_para(t, agentes)) and not forced:
        # o trabalho pesado é do agente: o JARVIS só delega e relata (nada de Fable só para delegar)
        return Decision(route=Route.MEDIUM, model=tiers.model(Route.MEDIUM), effort="low", area=area,
                        delegar=delegar, reason=f"delegação ao agente {delegar}: intermediário com esforço baixo")

    score = complexity_score(t)
    route = forced or tier_for(score, tiers.fable_pontos)
    reason = "forçado pelo usuário" if forced else f"complexidade {score}"

    if budget is BudgetState.ECONOMY:
        route = route if forced else _DOWN[route]
    if area and not forced and route is Route.SIMPLE:
        route = Route.MEDIUM  # resposta jurídica/fiscal errada custa caro: no mínimo a camada intermediária
        reason += f"; área {area}: no mínimo intermediário"
    if budget is BudgetState.ECONOMY:
        return Decision(route=route, model=tiers.model(route), effort="low",
                        reason=f"{reason}; modo economia (>=80% do teto)", area=area, delegar=delegar)
    return Decision(route=route, model=tiers.model(route), effort=_EFFORT[route], reason=reason, area=area,
                    delegar=delegar)
