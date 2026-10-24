"""Aprovações humanas: ações com efeito esperam um "sim" do usuário (HUD ou voz) antes de rodar."""

from __future__ import annotations

import asyncio
import secrets


class Approvals:
    def __init__(self, timeout_s: float = 60.0):
        self.timeout_s = timeout_s
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def create(self) -> str:
        approval_id = secrets.token_urlsafe(8)
        self._pending[approval_id] = asyncio.get_running_loop().create_future()
        return approval_id

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._pending.get(approval_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    async def wait(self, approval_id: str) -> bool:
        """True se aprovado; False se negado ou se o prazo expirar (silêncio nunca autoriza)."""
        fut = self._pending[approval_id]
        try:
            return await asyncio.wait_for(fut, timeout=self.timeout_s)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(approval_id, None)

    def discard(self, approval_id: str) -> None:
        fut = self._pending.pop(approval_id, None)
        if fut is not None and not fut.done():
            fut.cancel()

    @property
    def pending(self) -> list[str]:
        return list(self._pending)
