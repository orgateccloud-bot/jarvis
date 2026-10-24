"""Sessões de conversa: histórico append-only, roteamento, custo e audit por turno."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from pathlib import Path

from loguru import logger

from .approvals import Approvals
from .audit import AuditChain
from .contracts import AgentResult, BudgetState, Decision, Route, StreamEvent, UsageRecord
from .costs import CostLedger
from .llm import (
    NO_SERVER_FALLBACK,
    BrainUnavailable,
    ClaudeBrain,
    RuleResponder,
    ToolInputUnparseable,
    TurnOutcome,
    telemetry_note,
)
from .privacy import sanitizar
from .router import DEFAULT_TIERS, Tiers, decide, escalate, strip_force

MAX_STEPS = 6          # iterações do loop agêntico por turno
MAX_JSON_RETRIES = 2   # reemissões quando a entrada de ferramenta chega ilegível


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
        rules: RuleResponder,
        ledger: CostLedger,
        audit: AuditChain,
        store: SessionStore,
        salt: str,
        tiers: Tiers = DEFAULT_TIERS,
        tools: dict | None = None,
        tool_ctx=None,
        approvals: Approvals | None = None,
    ):
        self.claude = claude
        self.rules = rules
        self.ledger = ledger
        self.audit = audit
        self.store = store
        self.salt = salt
        self.tiers = tiers
        self.tools = tools or {}
        self.tool_ctx = tool_ctx
        self.approvals = approvals or Approvals()
        self._locks: dict[str, asyncio.Lock] = {}

    async def turn(self, session_id: str, message: str) -> AsyncIterator[StreamEvent]:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock, aclosing(self._turn(session_id, message)) as agen:
            async for ev in agen:
                yield ev

    async def _turn(self, session_id: str, message: str) -> AsyncIterator[StreamEvent]:
        budget = self.ledger.state()
        decision = decide(message, budget, self.tiers)
        quick = self.rules.answer(message) if decision.route is Route.LOCAL else None
        if decision.route is Route.LOCAL and quick is None and budget is not BudgetState.CAP_REACHED:
            # parecia trivial, mas nenhuma regra responde: vai para o modelo simples
            decision = Decision(route=Route.SIMPLE, model=self.tiers.simple, effort="low",
                                reason="sem resposta por regra: modelo simples")
        yield StreamEvent(
            type="route",
            data={"rota": decision.route.value, "modelo": decision.model or "regras", "effort": decision.effort,
                  "motivo": decision.reason, "orcamento": budget.value},
        )

        history = self.store.history(session_id)
        history.append({"role": "user", "content": sanitizar(strip_force(message), salt=self.salt)})
        route = decision.route
        texts: list[str] = []
        total = TurnOutcome(text="", model=decision.model or "regras")
        notice: str | None = None
        completed = False
        try:
            if route is Route.LOCAL:
                notice = quick or (
                    f"O teto mensal de US$ {self.ledger.budget:.2f} foi atingido, {self.rules.user_name}. "
                    "O Claude volta no próximo mês, ou antes se o teto (JARVIS_BUDGET_USD) for aumentado."
                )
            else:
                history.append({"role": "system", "content": telemetry_note()})
                try:
                    loop = self._agent_loop(session_id, history, route, decision, texts, total)
                    async with aclosing(loop) as agen:
                        async for ev in agen:
                            if isinstance(ev, Route):
                                route = ev
                            else:
                                yield ev
                except BrainUnavailable as e:
                    logger.warning(f"Claude indisponível: {e}")
                    yield StreamEvent(type="error", data=f"Claude indisponível: {e}.")
                    route = Route.LOCAL
                    notice = self.rules.answer(message) or (
                        f"Estou sem acesso ao Claude no momento, {self.rules.user_name}. Tente de novo em instantes."
                    )

            if notice is not None:
                yield StreamEvent(type="text", data=notice)
                texts.append(notice)
                history.append({"role": "assistant", "content": [{"type": "text", "text": notice}]})
            completed = True
        finally:
            if not completed:
                # turno interrompido (cliente desconectou, erro): fecha o histórico de forma válida
                self._close_dangling(history)
            self.store.save(session_id)

        result = self.audit.seal(
            AgentResult(
                session_id=session_id, route=route, model=total.model, text="".join(texts),
                cost_usd=round(total.cost_usd, 6), stop_reason=total.stop_reason,
            )
        )
        yield StreamEvent(
            type="usage",
            data={
                "modelo": total.model,
                "custo_usd": round(total.cost_usd, 6),
                "cache_read": total.cache_read_tokens,
                "cache_write": total.cache_write_tokens,
                "entrada": total.input_tokens,
                "saida": total.output_tokens,
                "buscas_web": total.web_searches,
                "audit_hash": result.audit_hash,
                "estado_orcamento": self.ledger.state().value,
            },
        )
        if self.ledger.state() is BudgetState.CAP_REACHED and budget is not BudgetState.CAP_REACHED:
            yield StreamEvent(type="error", data="Teto mensal atingido: o Claude fica pausado até o próximo mês.")
        yield StreamEvent(type="done")

    async def _agent_loop(self, session_id, history, route, decision, texts, total):
        """Loop agêntico: modelo → ferramentas (com aprovação) → modelo, até end_turn ou MAX_STEPS.
        Emite StreamEvent para o HUD e, quando escala de camada, o novo Route."""
        from ..tools import definitions_for

        model, effort = decision.model or self.tiers.simple, decision.effort or "low"
        json_retries = 0
        step = 0
        while step < MAX_STEPS:
            step += 1
            last_step = step == MAX_STEPS
            outcome: TurnOutcome | None = None
            defs = definitions_for(model, self.tools) if self.tools else None
            try:
                stream = self.claude.stream(
                    history, model, effort, tools=defs,
                    tool_choice={"type": "none"} if (last_step and defs) else None,
                )
                async with aclosing(stream) as agen:
                    async for item in agen:
                        if isinstance(item, TurnOutcome):
                            outcome = item
                        else:
                            yield item
            except ToolInputUnparseable as e:
                json_retries += 1
                logger.warning(f"entrada de ferramenta ilegível ({json_retries}): {e}")
                if json_retries > MAX_JSON_RETRIES:
                    raise BrainUnavailable("o modelo enviou entradas de ferramenta ilegíveis") from e
                step -= 1
                continue

            self._accumulate(total, outcome)
            self._record(session_id, route, outcome)

            # Haiku não tem fallback no servidor: uma recusa sobe para a camada seguinte (sem anexar a recusa)
            if outcome.stop_reason == "refusal" and model in NO_SERVER_FALLBACK:
                route = escalate(route)
                model = self.tiers.model(route)
                yield route
                yield StreamEvent(type="error", data=f"Recusa no modelo simples; escalando para {model}.")
                step -= 1
                continue

            history.append({"role": "assistant", "content": outcome.content})
            if outcome.text:
                texts.append(outcome.text)
            for b in outcome.content:
                if b.get("type") == "server_tool_use":
                    inp = b.get("input") or {}
                    alvo = inp.get("query") or inp.get("url") or ""
                    yield StreamEvent(type="tool", data={"fase": "fim", "nome": b.get("name"),
                                                         "resumo": f"{b.get('name')}: {alvo}"[:120], "ok": True})

            uses = [b for b in outcome.content if b.get("type") == "tool_use"]
            if uses and outcome.stop_reason != "tool_use":
                # max_tokens/refusal podem cortar um tool_use no meio: nunca executa, mas responde cada um
                history.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                     "content": f"Não executado: a resposta parou por {outcome.stop_reason}."} for b in uses]})
            if outcome.stop_reason == "pause_turn":
                continue  # ferramenta de servidor pausou: reenviar retoma sozinho
            if outcome.stop_reason == "refusal":
                if not outcome.text:
                    msg = f"Não posso ajudar com isso, {self.rules.user_name}."
                    texts.append(msg)
                    yield StreamEvent(type="text", data=msg)
                return
            if outcome.stop_reason != "tool_use" or not uses:
                return  # end_turn, max_tokens (entrada truncada nunca executa) ou sem ferramenta

            results: list[dict] = []
            try:
                for block in uses:
                    async with aclosing(self._run_tool(session_id, block, results)) as agen:
                        async for ev in agen:
                            yield ev
            finally:
                # todo tool_use precisa de um tool_result, mesmo se o turno for interrompido no meio
                answered = {r["tool_use_id"] for r in results}
                for block in uses:
                    if block["id"] not in answered:
                        results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                        "content": "Turno interrompido antes de executar a ferramenta."})
                history.append({"role": "user", "content": results})

    async def _run_tool(self, session_id: str, block: dict, results: list):
        name = block.get("name")
        tool = self.tools.get(name)

        def done(content: str, error: bool = False):
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content,
                            **({"is_error": True} if error else {})})

        if tool is None:
            done(f"Ferramenta desconhecida: {name}", True)
            return
        try:
            params = tool.parse(block.get("input"))
        except ValueError as e:
            done(json.dumps({"INVALID_INPUT": str(e)}, ensure_ascii=False), True)
            yield StreamEvent(type="tool", data={"fase": "fim", "nome": name, "resumo": "entrada inválida",
                                                 "ok": False})
            return
        resumo = tool.summary(params)

        if tool.needs_approval:
            approval_id = self.approvals.create()
            try:
                yield StreamEvent(type="approval", data={
                    "id": approval_id, "nome": name, "resumo": resumo,
                    "args": params.model_dump(mode="json"), "expira_s": int(self.approvals.timeout_s),
                })
                approved = await self.approvals.wait(approval_id)
            finally:
                self.approvals.discard(approval_id)  # turno interrompido no meio: não deixa pendência
            if not approved:
                done(f"O usuário NÃO autorizou: {resumo}. Não tente de novo sem um novo pedido dele.", True)
                yield StreamEvent(type="tool", data={"fase": "fim", "nome": name, "resumo": resumo,
                                                     "ok": False, "negado": True})
                self._seal_tool(session_id, name, f"NEGADO: {resumo}")
                return

        yield StreamEvent(type="tool", data={"fase": "inicio", "nome": name, "resumo": resumo})
        try:
            output = await asyncio.to_thread(tool.run, params, self.tool_ctx)
            done(output)
            yield StreamEvent(type="tool", data={"fase": "fim", "nome": name, "resumo": resumo, "ok": True})
            self._seal_tool(session_id, name, resumo)
        except Exception as e:  # noqa: BLE001 — qualquer falha de ferramenta volta ao modelo como erro
            from ..tools import ToolError

            msg = str(e) if isinstance(e, ToolError) else f"falha inesperada: {type(e).__name__}"
            if not isinstance(e, ToolError):
                logger.exception(f"ferramenta {name}")
            done(msg, True)
            yield StreamEvent(type="tool", data={"fase": "fim", "nome": name, "resumo": f"{resumo} — {msg}",
                                                 "ok": False})

    def _seal_tool(self, session_id: str, name: str, resumo: str) -> None:
        self.audit.seal(AgentResult(session_id=session_id, route=Route.LOCAL, model=f"tool:{name}", text=resumo))

    @staticmethod
    def _accumulate(total: TurnOutcome, o: TurnOutcome) -> None:
        total.model = o.model
        total.stop_reason = o.stop_reason
        total.input_tokens += o.input_tokens
        total.output_tokens += o.output_tokens
        total.cache_read_tokens += o.cache_read_tokens
        total.cache_write_tokens += o.cache_write_tokens
        total.web_searches += o.web_searches
        total.cost_usd += o.cost_usd

    @staticmethod
    def _close_dangling(history: list[dict]) -> None:
        """Garante histórico válido após interrupção: system/user no fim recebem um assistant depois."""
        if history and history[-1]["role"] in ("system", "user"):
            history.append({"role": "assistant", "content": [{"type": "text", "text": "(turno interrompido)"}]})

    def _record(self, session_id: str, route: Route, outcome: TurnOutcome) -> None:
        self.ledger.record(
            UsageRecord(
                session_id=session_id, model=outcome.model, route=route,
                input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
                cache_read_tokens=outcome.cache_read_tokens, cache_write_tokens=outcome.cache_write_tokens,
                cost_usd=outcome.cost_usd,
            )
        )
