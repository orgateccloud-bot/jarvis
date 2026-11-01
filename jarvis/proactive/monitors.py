"""Monitores proativos: regras determinísticas (custo zero) que decidem quando o JARVIS fala primeiro."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

import psutil
from loguru import logger

from ..core.contracts import BudgetState
from ..core.costs import CostLedger
from .bus import EventBus, ProactiveEvent
from .notify import notify
from .reminders import ReminderStore

RAM_LIMIT = 90.0
DISK_LIMIT = 95.0
CPU_LIMIT = 90.0
CPU_SUSTAIN = timedelta(seconds=60)
COOLDOWN = timedelta(minutes=30)


def sample_system() -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    return {
        "cpu": psutil.cpu_percent(interval=0.5),
        "ram": mem.percent, "ram_used_gb": mem.used / 2**30, "ram_total_gb": mem.total / 2**30,
        "disk": disk.percent, "disk_free_gb": disk.free / 2**30,
    }


def _gb(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


class Monitor:
    def __init__(self, ledger: CostLedger, reminders: ReminderStore, user_name: str = "Senhor",
                 sampler: Callable[[], dict] = sample_system, clock: Callable[[], datetime] = datetime.now,
                 assistente: str = "Sistemas"):
        self.ledger = ledger
        self.assistente = assistente
        self.reminders = reminders
        self.user = user_name
        self.sampler = sampler
        self.clock = clock
        self._ram_hits = 0
        self._cpu_since: datetime | None = None
        self._last: dict[str, datetime] = {}
        self._budget = ledger.state()

    def _cooled(self, kind: str, now: datetime) -> bool:
        last = self._last.get(kind)
        if last and now - last < COOLDOWN:
            return False
        self._last[kind] = now
        return True

    def check(self) -> list[ProactiveEvent]:
        now = self.clock()
        s = self.sampler()
        out: list[ProactiveEvent] = []

        self._ram_hits = self._ram_hits + 1 if s["ram"] >= RAM_LIMIT else 0
        if self._ram_hits >= 2 and self._cooled("alerta_ram", now):
            nivel = "critico" if s["ram"] >= 95 else "aviso"
            out.append(ProactiveEvent(
                kind="alerta_ram", nivel=nivel, titulo="Memória alta",
                texto=f"{self.user}, a RAM está em {s['ram']:.0f}% ({_gb(s['ram_used_gb'])} de "
                      f"{_gb(s['ram_total_gb'])} GB). Posso listar os processos mais pesados.",
            ))

        if s["disk"] >= DISK_LIMIT and self._cooled("alerta_disco", now):
            out.append(ProactiveEvent(
                kind="alerta_disco", nivel="critico", titulo="Disco C: quase cheio",
                texto=f"{self.user}, o disco C: está em {s['disk']:.0f}%, com {_gb(s['disk_free_gb'])} GB livres. "
                      "Isso deixa o sistema lento e pode travar atualizações.",
            ))

        if s["cpu"] >= CPU_LIMIT:
            self._cpu_since = self._cpu_since or now
            if now - self._cpu_since >= CPU_SUSTAIN and self._cooled("alerta_cpu", now):
                out.append(ProactiveEvent(
                    kind="alerta_cpu", nivel="aviso", titulo="Processador sobrecarregado",
                    texto=f"{self.user}, a CPU está acima de {CPU_LIMIT:.0f}% há mais de um minuto.",
                ))
        else:
            self._cpu_since = None

        budget = self.ledger.state()
        if budget is not self._budget:
            if budget is BudgetState.ECONOMY:
                out.append(ProactiveEvent(kind="orcamento", nivel="aviso", titulo="Modo economia",
                                          texto="Passamos de 80% do teto mensal; vou usar modelos mais leves."))
            elif budget is BudgetState.CAP_REACHED:
                out.append(ProactiveEvent(kind="orcamento", nivel="critico", titulo="Teto mensal atingido",
                                          texto="O teto mensal do Claude foi atingido; fico só com respostas por regra."))
            self._budget = budget

        for r in self.reminders.take_due(now):
            out.append(ProactiveEvent(kind="lembrete", nivel="aviso", titulo="Lembrete",
                                      texto=f"{self.user}, lembrete: {r.texto}."))
        return out

    def greeting(self) -> ProactiveEvent:
        h = self.clock().hour
        saud = "Bom dia" if 5 <= h < 12 else "Boa tarde" if h < 18 else "Boa noite"
        s = self.sampler()
        alertas = []
        if s["disk"] >= DISK_LIMIT:
            alertas.append(f"o disco C: está em {s['disk']:.0f}%")
        if s["ram"] >= RAM_LIMIT:
            alertas.append(f"a RAM está em {s['ram']:.0f}%")
        pend = self.reminders.pending()
        extra = f" Atenção: {' e '.join(alertas)}." if alertas else " Todos os sistemas estáveis."
        if pend:
            extra += f" Você tem {len(pend)} lembrete(s) pendente(s)."
        return ProactiveEvent(kind="saudacao", titulo=saud, texto=f"{saud}, {self.user}. {self.assistente} online.{extra}")


async def run_monitor(monitor: Monitor, bus: EventBus, interval_s: float = 15.0, toast: bool = True) -> None:
    """Laço proativo: checa, publica no barramento e manda notificação nativa nos avisos."""
    while True:
        try:
            for ev in await asyncio.to_thread(monitor.check):
                bus.publish(ev)
                if toast and ev.nivel != "info":
                    await asyncio.to_thread(notify, ev.titulo, ev.texto)
        except Exception:  # noqa: BLE001 — o laço proativo nunca pode morrer
            logger.exception("monitor proativo")
        await asyncio.sleep(interval_s)
