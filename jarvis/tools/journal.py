"""Diário de movimentos (SQLite): cada lote movido pode ser listado e desfeito."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class MoveJournal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS movimentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, lote INTEGER NOT NULL, origem TEXT NOT NULL,
                    destino TEXT NOT NULL, bytes INTEGER NOT NULL, quando TEXT NOT NULL,
                    desfeito INTEGER DEFAULT 0)"""
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def new_batch(self) -> int:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT COALESCE(MAX(lote), 0) FROM movimentos").fetchone()
        return int(row[0]) + 1

    def record(self, lote: int, origem: Path, destino: Path, size: int) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO movimentos (lote, origem, destino, bytes, quando) VALUES (?,?,?,?,?)",
                (lote, str(origem), str(destino), size, datetime.now().isoformat(timespec="seconds")),
            )

    def batch(self, lote: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, origem, destino, bytes, desfeito FROM movimentos WHERE lote = ? ORDER BY id", (lote,)
            ).fetchall()
        return [{"id": r[0], "origem": r[1], "destino": r[2], "bytes": r[3], "desfeito": bool(r[4])} for r in rows]

    def last_batch(self) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT MAX(lote) FROM movimentos WHERE desfeito = 0").fetchone()
        return row[0]

    def mark_undone(self, ids: list[int]) -> None:
        with self._lock, self._conn() as c:
            c.executemany("UPDATE movimentos SET desfeito = 1 WHERE id = ?", [(i,) for i in ids])

    def recent(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT lote, COUNT(*), SUM(bytes), MIN(quando), MIN(desfeito), MAX(desfeito)
                   FROM movimentos GROUP BY lote ORDER BY lote DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [{
            "lote": r[0], "itens": r[1], "gb": round((r[2] or 0) / 2**30, 3), "quando": r[3],
            "estado": "desfeito" if r[4] else "parcialmente desfeito" if r[5] else "ativo",
        } for r in rows]
