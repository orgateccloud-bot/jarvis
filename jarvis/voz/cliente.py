"""Cliente HTTP do serviço de voz para a API local (127.0.0.1): o mesmo fluxo de pergunta do HUD.

A trava de rede do processo de voz (offline.py) só deixa sair para 127.0.0.1; a chamada ao Claude é da API.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

SESSAO = "hud"  # a mesma conversa do HUD (api.js:73): voz e tela compartilham o contexto


class ApiIndisponivel(ConnectionError):
    """A API local não respondeu."""


class Cliente:
    def __init__(self, base: str, token: str, timeout: float = 10.0):
        # trust_env=False: nenhum proxy do ambiente; a conexão é sempre direta com a API local
        self._http = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
                                  trust_env=False)

    def _sse(self, metodo: str, url: str, **kw) -> Iterator[dict]:
        try:
            with self._http.stream(metodo, url, timeout=httpx.Timeout(10.0, read=None), **kw) as r:
                r.raise_for_status()
                for linha in r.iter_lines():
                    if linha.startswith("data: "):
                        yield json.loads(linha[6:])
        except httpx.TransportError as e:
            raise ApiIndisponivel(str(e)) from e

    def perguntar(self, texto: str) -> Iterator[dict]:
        """Eventos do turno: route, thinking, text (trecho), tool, approval ({id, resumo, ...}), usage, error, done."""
        yield from self._sse("POST", "/chat/stream", json={"message": texto, "session_id": SESSAO})

    def eventos(self) -> Iterator[dict]:
        """Avisos proativos (lembretes, alertas). Os com "falar" o serviço fala quando é o dono do alto-falante."""
        yield from self._sse("GET", "/events", params={"saudacao": "false"})

    def _post(self, url: str, corpo: dict) -> dict:
        try:
            r = self._http.post(url, json=corpo)
        except httpx.TransportError as e:
            raise ApiIndisponivel(str(e)) from e
        r.raise_for_status()
        return r.json()

    def aprovar(self, aprovacao_id: str, ok: bool) -> None:
        try:
            self._post(f"/approvals/{aprovacao_id}", {"aprovar": ok})
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:  # 404: já decidida (pelo HUD ou por tempo)
                raise

    def batimento(self, estado: str) -> dict:
        """Conta à API o estado do serviço; a resposta diz quem é o dono do microfone e traz comandos do HUD."""
        return self._post("/voz/estado", {"estado": estado})

    def nova_conversa(self) -> None:
        self._post(f"/sessions/{SESSAO}/nova", {})

    def fechar(self) -> None:
        self._http.close()
