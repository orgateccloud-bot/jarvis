"""Recursos de um agente: a única coisa que ele recebe do JARVIS (objeto-capacidade).

Não há aqui orquestrador, outros agentes, ferramentas do JARVIS nem cliente de rede: o agente não tem como dar ordem a
ninguém. O Claude só é alcançado pelo gateway, que mascara PII e confere custo e teto antes de cada chamada.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..core.contracts import BudgetState, Route, UsageRecord
from ..core.costs import PRICES, UNKNOWN_MODEL_PRICE, CostLedger
from ..core.llm import ClaudeBrain, TurnOutcome, formato_json
from ..core.privacy import sanitizar
from .contratos import TarefaRecusada


class ConsultaConhecimento:
    """A base de conhecimento só para leitura: o agente busca trechos, não reindexa nem baixa nada."""

    def __init__(self, base: Any):
        self._base = base

    def buscar(self, consulta: str, area: str | None = "tributario", k: int = 5) -> list[dict]:
        if self._base is None:
            return []
        return [{"fonte": t.fonte, "trecho": t.rotulo, "arquivo": t.arquivo, "texto": t.texto}
                for _, t in self._base.buscar(consulta, area, k)]


@dataclass
class RespostaClaude:
    dados: dict | None   # JSON validado pelo esquema pedido (None sem esquema)
    texto: str
    modelo: str
    custo_usd: float


def rota_do_modelo(modelo: str) -> Route:
    for prefixo, rota in (("claude-haiku", Route.SIMPLE), ("claude-sonnet", Route.MEDIUM),
                          ("claude-opus", Route.COMPLEX), ("claude-fable", Route.FABLE)):
        if modelo.startswith(prefixo):
            return rota
    return Route.MEDIUM


class GatewayClaude:
    """Único caminho de um agente até o Claude: PII mascarada, teto conferido no pior caso, custo no mesmo ledger.

    Uma tarefa por agente por vez (semáforo do orquestrador): `custo` e `modelo` acumulam a tarefa em andamento."""

    MAX_TOKENS = 12_000
    CHARS_POR_TOKEN = 3   # conservador para português: superestima a entrada

    def __init__(self, client: Any, ledger: CostLedger, agente_id: str, salt: str,
                 teto_agente: Callable[[], float]):
        self.client = client
        self.ledger = ledger
        self.sessao = f"agente-{agente_id}"
        self.salt = salt
        self.teto_agente = teto_agente
        self.custo = 0.0
        self.modelo = "regras"

    def zerar(self) -> None:
        self.custo, self.modelo = 0.0, "regras"

    def pior_caso(self, modelo: str, caracteres: int) -> float:
        """US$ se a entrada for toda escrita no cache e a saída chegar ao max_tokens."""
        _, p_out, _, p_write = PRICES.get(modelo, UNKNOWN_MODEL_PRICE)
        entrada = caracteres / self.CHARS_POR_TOKEN + 500
        return round((entrada * p_write + self.MAX_TOKENS * p_out) / 1_000_000, 6)

    def conferir_teto(self, modelo: str, caracteres: int) -> BudgetState:
        estado = self.ledger.state()
        if estado is BudgetState.CAP_REACHED:
            raise TarefaRecusada(f"o teto mensal de US$ {self.ledger.budget:.2f} foi atingido; as tarefas com "
                                 "Claude voltam no próximo mês (as locais continuam)")
        pior = self.pior_caso(modelo, caracteres)
        if self.ledger.month_total() + pior > self.ledger.budget:
            raise TarefaRecusada(f"esta tarefa pode passar do teto mensal de US$ {self.ledger.budget:.2f} "
                                 f"(pior caso US$ {pior:.2f})")
        teto, gasto = self.teto_agente(), self.ledger.month_total(sessao=self.sessao)
        if gasto + pior > teto:
            raise TarefaRecusada(f"o subteto do agente (US$ {teto:.2f}) não comporta esta tarefa "
                                 f"(gasto no mês US$ {gasto:.2f}, pior caso US$ {pior:.2f})")
        return estado

    async def chamar(self, system: str, mensagem: str, modelo: str, effort: str,
                     esquema: type[BaseModel] | None = None, nomes: Sequence[str] = ()) -> RespostaClaude:
        """Uma chamada, sem ferramentas. Com `esquema`, a resposta vem em JSON (saída estruturada) e é validada."""
        system = sanitizar(system, list(nomes), self.salt)
        texto = sanitizar(mensagem, list(nomes), self.salt)
        if self.conferir_teto(modelo, len(system) + len(texto)) is BudgetState.ECONOMY:
            effort = "low"   # modo economia: menos esforço, mas nunca um modelo abaixo (resposta fiscal errada custa)
        cerebro = ClaudeBrain(self.MAX_TOKENS, "", client=self.client, system=system)
        saida: TurnOutcome | None = None
        async for item in cerebro.stream([{"role": "user", "content": texto}], modelo, effort,
                                         formato=formato_json(esquema) if esquema else None):
            if isinstance(item, TurnOutcome):
                saida = item
        self.ledger.record(UsageRecord(
            session_id=self.sessao, model=saida.model, route=rota_do_modelo(saida.model),
            input_tokens=saida.input_tokens, output_tokens=saida.output_tokens, cache_read_tokens=saida.cache_read_tokens,
            cache_write_tokens=saida.cache_write_tokens, cost_usd=saida.cost_usd,
        ))
        self.custo += saida.cost_usd
        self.modelo = saida.model
        if saida.stop_reason == "refusal":
            raise TarefaRecusada("o modelo recusou o pedido")
        if saida.stop_reason == "max_tokens":
            raise RuntimeError("a resposta do modelo foi cortada no limite de tokens")
        dados = None
        if esquema is not None:
            try:
                dados = esquema.model_validate_json(saida.text).model_dump(mode="json")
            except ValidationError as e:
                raise ValueError("a resposta do modelo veio fora do formato pedido") from e
        return RespostaClaude(dados=dados, texto=saida.text, modelo=saida.model, custo_usd=saida.cost_usd)


@dataclass(frozen=True)
class Recursos:
    claude: GatewayClaude | None         # None: o agente só roda tarefas locais
    conhecimento: ConsultaConhecimento
    pasta: Path                          # onde o agente grava o que entrega (laudos)
    salt: str                            # pseudonimização determinística de nomes
