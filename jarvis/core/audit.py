"""Audit trail: cada AgentResult recebe um hash SHA-256 encadeado ao anterior (append-only em JSONL)."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from .contracts import AgentResult

GENESIS = "0" * 64


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
        payload = result.model_dump(mode="json", exclude={"audit_hash"})
        canon = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(f"{prev}|{canon}".encode()).hexdigest()

    def seal(self, result: AgentResult) -> AgentResult:
        with self._lock:
            result.audit_hash = self.compute(self._last, result)
            record = {"prev": self._last, **result.model_dump(mode="json")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last = result.audit_hash
        return result

    def encontrar(self, audit_hash: str) -> dict | None:
        """O registro selado com este hash, ou None."""
        if not self.path.exists():
            return None
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if audit_hash in line:
                    rec = json.loads(line)
                    if rec.get("audit_hash") == audit_hash:
                        return rec
        return None

    def verify(self) -> bool:
        """Revalida a cadeia inteira; False se algum registro foi adulterado."""
        if not self.path.exists():
            return True
        prev = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.pop("prev") != prev:
                    return False
                result = AgentResult.model_validate(rec)
                if self.compute(prev, result) != rec["audit_hash"]:
                    return False
                prev = rec["audit_hash"]
        return True
