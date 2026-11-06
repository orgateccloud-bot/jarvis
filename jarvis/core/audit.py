"""Audit trail: cada AgentResult recebe um hash SHA-256 encadeado ao anterior (append-only em JSONL)."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .contracts import AgentResult

GENESIS = "0" * 64


def _digest(prev: str, payload: dict[str, Any]) -> str:
    """JSON canônico da cadeia: quem sela e quem confere precisam passar por aqui."""
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{prev}|{canon}".encode()).hexdigest()


class AuditChain:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._last = self._read_last()

    def _read_last(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["audit_hash"]
        return last

    @staticmethod
    def compute(prev: str, result: AgentResult) -> str:
        return _digest(prev, result.model_dump(mode="json", exclude={"audit_hash"}))

    def seal(self, result: AgentResult) -> AgentResult:
        with self._lock:
            result.audit_hash = self.compute(self._last, result)
            record = {"prev": self._last, **result.model_dump(mode="json")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last = result.audit_hash
        return result

    def verify(self) -> bool:
        """Revalida a cadeia inteira; False se algum registro foi adulterado ou está ilegível.

        O hash é recalculado sobre o registro como foi gravado, sem passar pelo AgentResult: o arquivo
        é append-only e guarda valores que os contratos de hoje não aceitam mais (ex.: a rota "chat").
        """
        if not self.path.exists():
            return True
        prev = GENESIS
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    selado = rec["audit_hash"]
                    if rec["prev"] != prev:
                        return False
                    payload = {k: v for k, v in rec.items() if k not in ("prev", "audit_hash")}
                    if _digest(prev, payload) != selado:
                        return False
                    prev = selado
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            return False
        return True
