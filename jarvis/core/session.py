"""Sessões de conversa: histórico append-only, roteamento, custo e audit por turno."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from loguru import logger

from .audit import AuditChain
from .contracts import AgentResult, BudgetState, Route, StreamEvent, UsageRecord
from .costs import CostLedger
from .llm import NO_SERVER_FALLBACK, BrainUnavailable, ClaudeBrain, LocalBrain, TurnOutcome, telemetry_note
from .privacy import sanitizar
from .router import DEFAULT_TIERS, Tiers, decide, escalate, strip_force


class SessionStore:
    """Persiste cada histórico em dados/sessions/<id>.json para sobreviver a reinícios."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[dict]] = {}

    def history(self, session_id: str) -> list[dict]:
        if session_id not in self._cache:
            path = self.root / f"{session_id}.json"
            self._cache[session_id] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return self._cache[session_id]

    def save(self, session_id: str) -> None:
        path = self.root / f"{session_id}.json"
        path.write_text(json.dumps(self._cache[session_id], ensure_ascii=False), encoding="utf-8")


class Conversation:
    def __init__(
        self,
        claude: ClaudeBrain,
        local: LocalBrain,
        ledger: CostLedger,
        audit: AuditChain,
        store: SessionStore,
        salt: str,
        tiers: Tiers = DEFAULT_TIERS,
    ):
        self.claude = claude
        self.local = local
        self.ledger = ledger
        self.audit = audit
        self.store = store
        self.salt = salt
        self.tiers = tiers
        self._locks: dict[str, asyncio.Lock] = {}

    async def turn(self, session_id: str, message: str) -> AsyncIterator[StreamEvent]:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            async for ev in self._turn(session_id, message):
                yield ev

    async def _turn(self, session_id: str, message: str) -> AsyncIterator[StreamEvent]:
        budget = self.ledger.state()
        decision = decide(message, budget, self.tiers)
        yield StreamEvent(
            type="route",
            data={"rota": decision.route.value, "modelo": decision.model or "local", "effort": decision.effort,
                  "motivo": decision.reason, "orcamento": budget.value},
        )

        history = self.store.history(session_id)
        history.append({"role": "user", "content": sanitizar(strip_force(message), salt=self.salt)})

        outcome: TurnOutcome | None = None
        route = decision.route
        if route is not Route.LOCAL:
            history.append({"role": "system", "content": telemetry_note()})
            model, effort = decision.model or self.tiers.simple, decision.effort or "low"
            try:
                while True:
                    async for item in self.claude.stream(history, model, effort):
                        if isinstance(item, TurnOutcome):
                            outcome = item
                        else:
                            yield item
                    # Haiku não tem fallback no servidor: uma recusa sobe para a camada seguinte.
                    if outcome and outcome.stop_reason == "refusal" and model in NO_SERVER_FALLBACK:
                        self._record(session_id, route, outcome)  # a tentativa recusada também custou
                        route = escalate(route)
                        model = self.tiers.model(route)
                        yield StreamEvent(type="error", data=f"Recusa no modelo simples; escalando para {model}.")
                        outcome = None
                        continue
                    break
            except BrainUnavailable as e:
                logger.warning(f"Claude indisponível, caindo para o local: {e}")
                yield StreamEvent(type="error", data=f"Claude indisponível ({e}); usando modelo local.")
                route = Route.LOCAL
            if outcome and outcome.stop_reason == "refusal" and not outcome.text:
                outcome.text = f"Não posso ajudar com isso, {self.local.user_name}."
                yield StreamEvent(type="text", data=outcome.text)

        if outcome is None:
            async for item in self.local.stream(history, self.claude.system):
                if isinstance(item, TurnOutcome):
                    outcome = item
                else:
                    yield item

        if outcome is None:
            raise RuntimeError("nenhum cérebro produziu resposta")
        history.append({"role": "assistant", "content": outcome.content})
        self.store.save(session_id)

        if route is not Route.LOCAL:
            self._record(session_id, route, outcome)
        result = self.audit.seal(
            AgentResult(
                session_id=session_id, route=route, model=outcome.model, text=outcome.text,
                cost_usd=outcome.cost_usd, stop_reason=outcome.stop_reason,
            )
        )
        yield StreamEvent(
            type="usage",
            data={
                "modelo": outcome.model,
                "custo_usd": outcome.cost_usd,
                "cache_read": outcome.cache_read_tokens,
                "cache_write": outcome.cache_write_tokens,
                "entrada": outcome.input_tokens,
                "saida": outcome.output_tokens,
                "audit_hash": result.audit_hash,
                "estado_orcamento": self.ledger.state().value,
            },
        )
        if self.ledger.state() is BudgetState.LOCAL_ONLY and budget is not BudgetState.LOCAL_ONLY:
            yield StreamEvent(type="error", data="Teto mensal atingido: a partir de agora, só o modelo local.")
        yield StreamEvent(type="done")

    def _record(self, session_id: str, route: Route, outcome: TurnOutcome) -> None:
        self.ledger.record(
            UsageRecord(
                session_id=session_id, model=outcome.model, route=route,
                input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
                cache_read_tokens=outcome.cache_read_tokens, cache_write_tokens=outcome.cache_write_tokens,
                cost_usd=outcome.cost_usd,
            )
        )
