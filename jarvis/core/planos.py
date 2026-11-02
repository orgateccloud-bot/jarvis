"""Planos de assinatura do JARVIS para alunos do Trilhum ULTRA: o modelo de cada plano e o teto mensal por aluno.

Cada aluno tem a própria instância do JARVIS-TRILHUM (chave da API, token de sincronização e dados próprios), então o
teto do aluno é o teto mensal que o JARVIS já tem (CostLedger), com o mesmo modo economia a 80%:

    plano    preço    modelo                      teto padrão (50% do preço, a R$ 5,50 por US$)
    haiku    R$ 20    Haiku 5.5                   US$ 1,82
    sonnet   R$ 35    Sonnet 5.5                  US$ 3,18
    opus     R$ 50    Opus 5.5                    US$ 4,55
    fable    R$ 75    Fable 5.1                   US$ 6,82
    router   R$ 100   o roteador do JARVIS        US$ 9,09   (Haiku, Sonnet, Opus ou Fable pela complexidade)

No modo economia o plano desce uma camada com effort low (Fable → Opus, Opus → Sonnet, Sonnet → Haiku); no teto, o
Claude pausa até o mês seguinte. O aluno não troca de modelo por prefixo (/opus, /fable): fica no plano que comprou.
Ver docs/analise-ultra-jarvis.md no Trilhum: o Fable a R$ 75 dá prejuízo no uso típico sem este teto.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from .contracts import BudgetState, Decision, Route
from .router import DEFAULT_TIERS, Tiers, decide, descer, effort_for, strip_force

CAMBIO_PADRAO = 5.5        # R$ por US$ (estimativa da análise de 02/11/2026; ajuste em JARVIS_CAMBIO)
FRACAO_TETO_PADRAO = 0.5   # parte do preço que pode virar API no mês (o resto paga taxas, WhatsApp e margem)


class PlanoJarvis(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    nome: str
    preco_brl: float
    rota: Route | None   # None = Router: a camada vem da complexidade da pergunta

    def teto_usd(self, cambio: float = CAMBIO_PADRAO, fracao: float = FRACAO_TETO_PADRAO) -> float:
        return round(self.preco_brl * fracao / cambio, 2)


PLANOS: dict[str, PlanoJarvis] = {p.id: p for p in (
    PlanoJarvis(id="haiku", nome="Haiku", preco_brl=20, rota=Route.SIMPLE),
    PlanoJarvis(id="sonnet", nome="Sonnet", preco_brl=35, rota=Route.MEDIUM),
    PlanoJarvis(id="opus", nome="Opus", preco_brl=50, rota=Route.COMPLEX),
    PlanoJarvis(id="fable", nome="Fable", preco_brl=75, rota=Route.FABLE),
    PlanoJarvis(id="router", nome="Router", preco_brl=100, rota=None),
)}


def plano_jarvis(valor: str | None) -> PlanoJarvis | None:
    """O plano pelo nome ("opus") ou pelo preço ("50", "R$ 50"); vazio = sem plano (o dono do JARVIS).
    ValueError para um valor que não é plano: melhor falhar no início que cobrar o modelo errado."""
    v = (valor or "").strip().lower()
    if not v:
        return None
    if v in PLANOS:
        return PLANOS[v]
    numero = re.sub(r"^r\$\s*", "", v).replace(",", ".")
    for p in PLANOS.values():
        try:
            if float(numero) == p.preco_brl:
                return p
        except ValueError:
            break
    raise ValueError(f"plano do JARVIS desconhecido: {valor!r} (use {', '.join(PLANOS)})")


def decidir(texto: str, estado: BudgetState, tiers: Tiers = DEFAULT_TIERS,
            plano: PlanoJarvis | None = None) -> Decision:
    """A decisão do roteador para o plano do aluno. Sem plano, o roteador de sempre."""
    if plano is None:
        return decide(texto, estado, tiers)
    d = decide(strip_force(texto), estado, tiers)   # sem prefixo de camada: o aluno fica no plano que comprou
    if d.route is Route.LOCAL:
        return d   # trivial (regras) ou teto atingido
    if plano.rota is None:
        if estado is BudgetState.ECONOMY and d.reason.startswith("forçado"):   # "pense bem" também desce
            route = descer(d.route)
            return d.model_copy(update={"route": route, "model": tiers.model(route), "effort": "low"})
        return d.model_copy(update={"reason": f"plano JARVIS Router; {d.reason}"})
    if estado is BudgetState.ECONOMY:
        route = descer(plano.rota)
        return Decision(route=route, model=tiers.model(route), effort="low", area=d.area,
                        reason=f"plano JARVIS {plano.nome}; modo economia (>=80% do teto do plano)")
    return Decision(route=plano.rota, model=tiers.model(plano.rota), effort=effort_for(plano.rota), area=d.area,
                    reason=f"plano JARVIS {plano.nome}")
