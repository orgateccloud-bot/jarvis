"""Lembretes persistentes (SQLite). Criados por ferramenta, disparados pelo laço proativo."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class Reminder(BaseModel):
    id: int
    texto: str
    quando: datetime
    disparado: bool = False


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

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _row(r) -> Reminder:
        return Reminder(id=r[0], texto=r[1], quando=datetime.fromisoformat(r[2]), disparado=bool(r[3]))

    def add(self, texto: str, quando: datetime) -> Reminder:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO reminders (texto, quando, criado) VALUES (?,?,?)",
                (texto, quando.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")),
            )
            return Reminder(id=cur.lastrowid, texto=texto, quando=quando)

    def pending(self) -> list[Reminder]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, texto, quando, disparado FROM reminders WHERE disparado = 0 ORDER BY quando"
            ).fetchall()
        return [self._row(r) for r in rows]

    def cancel(self, reminder_id: int) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM reminders WHERE id = ? AND disparado = 0", (reminder_id,))
            return cur.rowcount > 0

    def take_due(self, now: datetime | None = None) -> list[Reminder]:
        """Devolve os lembretes vencidos e já os marca como disparados (não repetem)."""
        now = now or datetime.now()
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, texto, quando, disparado FROM reminders WHERE disparado = 0 AND quando <= ?",
                (now.isoformat(timespec="seconds"),),
            ).fetchall()
            if rows:
                c.executemany("UPDATE reminders SET disparado = 1 WHERE id = ?", [(r[0],) for r in rows])
        return [self._row(r) for r in rows]
