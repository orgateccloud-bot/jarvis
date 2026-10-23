"""Ledger de custos (SQLite local) e guarda de orçamento mensal."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .contracts import BudgetState, UsageRecord

# US$ por 1M tokens: (entrada, saída, leitura de cache, escrita de cache 5 min = 1,25x entrada)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
UNKNOWN_MODEL_PRICE = PRICES["claude-opus-5"]  # conservador: superestima em vez de subestimar
# Haiku 5.5 tem segunda tabela quando o prompt passa de 100 mil tokens.
HAIKU_LONG_PROMPT = (0.50, 2.50, 0.05, 0.625)


def price_usage(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, UNKNOWN_MODEL_PRICE)
    if model == "claude-haiku-5-5" and input_tokens + cache_read + cache_write > 100_000:
        p_in, p_out, p_read, p_write = HAIKU_LONG_PROMPT
    total = input_tokens * p_in + output_tokens * p_out + cache_read * p_read + cache_write * p_write
    return round(total / 1_000_000, 6)


class CostLedger:
    def __init__(self, db_path: Path, monthly_budget_usd: float, economy_threshold: float = 0.8):
        self.db_path = db_path
        self.budget = monthly_budget_usd
        self.economy_threshold = economy_threshold
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS usage (
                    at TEXT NOT NULL, session_id TEXT, model TEXT, route TEXT,
                    input_tokens INTEGER, output_tokens INTEGER,
                    cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL)"""
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record(self, rec: UsageRecord) -> UsageRecord:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rec.at.isoformat(), rec.session_id, rec.model, rec.route.value,
                    rec.input_tokens, rec.output_tokens, rec.cache_read_tokens,
                    rec.cache_write_tokens, rec.cost_usd,
                ),
            )
        return rec

    def _sum_since(self, prefix: str) -> float:
        with self._conn() as c:
            row = c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM usage WHERE at LIKE ?", (f"{prefix}%",)).fetchone()
        return float(row[0])

    def month_total(self, now: datetime | None = None) -> float:
        return self._sum_since((now or datetime.now()).strftime("%Y-%m"))

    def day_total(self, now: datetime | None = None) -> float:
        return self._sum_since((now or datetime.now()).strftime("%Y-%m-%d"))

    def state(self, now: datetime | None = None) -> BudgetState:
        spent = self.month_total(now)
        if spent >= self.budget:
            return BudgetState.LOCAL_ONLY
        if spent >= self.budget * self.economy_threshold:
            return BudgetState.ECONOMY
        return BudgetState.NORMAL

    def summary(self) -> dict:
        month = self.month_total()
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(input_tokens),0) "
                "FROM usage WHERE at LIKE ?",
                (datetime.now().strftime("%Y-%m") + "%",),
            ).fetchone()
        turns, cache_read, uncached = row
        hit = cache_read / (cache_read + uncached) if (cache_read + uncached) else 0.0
        return {
            "hoje_usd": round(self.day_total(), 4),
            "mes_usd": round(month, 4),
            "teto_usd": self.budget,
            "uso_pct": round(100 * month / self.budget, 1) if self.budget else 0.0,
            "estado": self.state().value,
            "turnos_claude_mes": turns,
            "cache_hit_pct": round(100 * hit, 1),
        }
