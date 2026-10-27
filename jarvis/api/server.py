"""API do JARVIS: só em 127.0.0.1, protegida por token, com streaming SSE para o HUD."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
from datetime import datetime, timedelta

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger

from .. import __version__
from ..config import Settings, get_settings
from ..core.approvals import Approvals
from ..core.audit import AuditChain
from ..core.contracts import ApprovalDecision, ChatRequest
from ..core.costs import CostLedger
from ..core.llm import ClaudeBrain, RuleResponder
from ..core.router import Tiers
from ..core.session import Conversation, SessionStore
from ..proactive.bus import EventBus, event_source
from ..proactive.monitors import Monitor, run_monitor
from ..proactive.reminders import ReminderStore
from ..tools import ToolContext, manifesto, registry
from ..tools.journal import MoveJournal


def build_conversation(settings: Settings, claude_client=None, approval_timeout_s: float = 60.0) -> Conversation:
    ledger = CostLedger(settings.db_path, settings.monthly_budget_usd, settings.economy_threshold)
    salt = settings.salt()
    reminders = ReminderStore(settings.db_path)
    tools = registry()
    return Conversation(
        claude=ClaudeBrain(settings.max_tokens, settings.user_name, client=claude_client, manifesto=manifesto(tools)),
        rules=RuleResponder(settings.user_name),
        ledger=ledger,
        audit=AuditChain(settings.data_dir / "audit.jsonl"),
        store=SessionStore(settings.data_dir / "sessions", idle=timedelta(minutes=settings.session_idle_min)),
        salt=salt,
        tiers=Tiers(settings.model_simple, settings.model_medium, settings.model_complex),
        tools=tools,
        tool_ctx=ToolContext(
            roots=settings.tool_roots(), ledger=ledger, reminders=reminders, salt=salt,
            archive=settings.archive_dir(), move_roots=settings.move_roots(), journal=MoveJournal(settings.db_path),
        ),
        approvals=Approvals(timeout_s=approval_timeout_s),
    )


def create_app(settings: Settings | None = None, conversation: Conversation | None = None,
               monitor: Monitor | None = None, proactive: bool | None = None) -> FastAPI:
    settings = settings or get_settings()
    token = settings.api_token()
    conv = conversation or build_conversation(settings)
    logger.add(settings.data_dir.parent / "logs" / "jarvis.log", rotation="10 MB", retention="30 days")
    bus = EventBus()
    monitor = monitor or Monitor(conv.ledger, conv.tool_ctx.reminders, settings.user_name)
    proactive = settings.proactive if proactive is None else proactive

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(run_monitor(monitor, bus)) if proactive else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="JARVIS", version=__version__, lifespan=lifespan)
    app.state.bus = bus
    app.state.monitor = monitor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not given or not hmac.compare_digest(given, token):
            raise HTTPException(status_code=401, detail="token inválido")

    @app.get("/health")
    async def health():
        return {
            "status": "online",
            "versao": __version__,
            "modelos": [settings.model_simple, settings.model_medium, settings.model_complex],
            "hora": datetime.now().isoformat(),
        }

    @app.post("/chat/stream", dependencies=[Depends(require_token)])
    async def chat_stream(req: ChatRequest):
        async def sse():
            try:
                async for ev in conv.turn(req.session_id, req.message):
                    yield f"data: {ev.model_dump_json()}\n\n"
            except Exception as e:  # noqa: BLE001 — nunca deixar o stream morrer sem aviso
                logger.exception("falha no turno")
                yield f'data: {{"type":"error","data":"falha interna: {type(e).__name__}"}}\n\n'
                yield 'data: {"type":"done"}\n\n'

        return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/events", dependencies=[Depends(require_token)])
    async def events(saudacao: bool = Query(default=True, description="saudação ao conectar")):
        greeting = await asyncio.to_thread(monitor.greeting) if saudacao else None
        return StreamingResponse(event_source(bus, greeting), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.post("/approvals/{approval_id}", dependencies=[Depends(require_token)])
    async def decide_approval(approval_id: str, body: ApprovalDecision):
        if not conv.approvals.resolve(approval_id, body.aprovar):
            raise HTTPException(status_code=404, detail="aprovação inexistente ou já decidida")
        return {"ok": True, "aprovado": body.aprovar}

    @app.get("/costs", dependencies=[Depends(require_token)])
    async def costs():
        return conv.ledger.summary()

    @app.get("/system/status", dependencies=[Depends(require_token)])
    async def system_status():
        mem = psutil.virtual_memory()
        boot = datetime.fromtimestamp(psutil.boot_time())
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": mem.percent,
            "disk_percent": psutil.disk_usage("C:\\").percent,
            "process_count": len(psutil.pids()),
            "uptime_hours": round((datetime.now() - boot).total_seconds() / 3600, 1),
        }

    @app.get("/audit/verify", dependencies=[Depends(require_token)])
    async def audit_verify():
        return {"integra": conv.audit.verify()}

    return app
