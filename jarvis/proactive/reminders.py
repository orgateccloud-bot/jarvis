"""Lembretes persistentes (SQLite). Criados por ferramenta, disparados pelo laço proativo; os recorrentes
(diário, dias úteis, semanal) são reagendados para a próxima ocorrência em vez de encerrar."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel


class Reminder(BaseModel):
    id: int
    texto: str
    quando: datetime
    disparado: bool = False
    repetir: str | None = None  # diario | dias_uteis | semanal


REPETICOES = ("diario", "dias_uteis", "semanal")


def proxima(quando: datetime, repetir: str, depois_de: datetime) -> datetime:
    """Próxima ocorrência estritamente depois de `depois_de` (PC desligado por dias dispara uma vez só)."""
    passo = timedelta(days=7 if repetir == "semanal" else 1)
    n = quando + passo
    while n <= depois_de or (repetir == "dias_uteis" and n.weekday() >= 5):
        n += passo
    return n


class ReminderStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT NOT NULL,
                    quando TEXT NOT NULL, criado TEXT NOT NULL, disparado INTEGER DEFAULT 0)"""
            )
            if "repetir" not in {r[1] for r in c.execute("PRAGMA table_info(reminders)")}:
                c.execute("ALTER TABLE reminders ADD COLUMN repetir TEXT")  # migração: lembretes recorrentes

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _row(r) -> Reminder:
        return Reminder(id=r[0], texto=r[1], quando=datetime.fromisoformat(r[2]), disparado=bool(r[3]),
                        repetir=r[4])

    def add(self, texto: str, quando: datetime, repetir: str | None = None) -> Reminder:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO reminders (texto, quando, criado, repetir) VALUES (?,?,?,?)",
                (texto, quando.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"),
                 repetir),
            )
            return Reminder(id=cur.lastrowid, texto=texto, quando=quando, repetir=repetir)

    def pending(self) -> list[Reminder]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, texto, quando, disparado, repetir FROM reminders WHERE disparado = 0 ORDER BY quando"
            ).fetchall()
        return [self._row(r) for r in rows]

    def cancel(self, reminder_id: int) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM reminders WHERE id = ? AND disparado = 0", (reminder_id,))
            return cur.rowcount > 0

    def take_due(self, now: datetime | None = None) -> list[Reminder]:
        """Devolve os lembretes vencidos; os únicos ficam marcados como disparados e os recorrentes vão para a
        próxima ocorrência."""
        now = now or datetime.now()
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, texto, quando, disparado, repetir FROM reminders WHERE disparado = 0 AND quando <= ?",
                (now.isoformat(timespec="seconds"),),
            ).fetchall()
            for r in rows:
                if r[4]:
                    nova = proxima(datetime.fromisoformat(r[2]), r[4], now)
                    c.execute("UPDATE reminders SET quando = ? WHERE id = ?", (nova.isoformat(timespec="seconds"), r[0]))
                else:
                    c.execute("UPDATE reminders SET disparado = 1 WHERE id = ?", (r[0],))
        return [self._row(r) for r in rows]
