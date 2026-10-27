"""Fakes do SDK da Anthropic: nenhum teste chama a API real nem gasta dinheiro."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.config import Settings


class _Block(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)


def _delta_event(kind: str, value: str):
    attr = "thinking" if kind == "thinking_delta" else "text"
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type=kind, **{attr: value}))


def text_turn(text: str, stop_reason: str = "end_turn") -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}


def tool_turn(name: str, tool_input: dict, tool_id: str = "toolu_1", text: str = "") -> dict:
    content = [{"type": "text", "text": text}] if text else []
    content.append({"type": "tool_use", "id": tool_id, "name": name, "input": tool_input})
    return {"content": content, "stop_reason": "tool_use"}


class FakeStream:
    def __init__(self, owner, kwargs, turn):
        self.owner = owner
        self.kwargs = kwargs
        self.turn = turn

    async def __aenter__(self):
        if self.owner.raise_exc:
            raise self.owner.raise_exc
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            yield _delta_event("thinking_delta", "pensando...")
            for b in self.turn["content"]:
                if b["type"] == "text" and b["text"]:
                    yield _delta_event("text_delta", b["text"])

        return gen()

    async def get_final_message(self):
        blocks = [_Block(type="thinking", thinking="pensando...", signature="sig")]
        blocks += [_Block(**b) for b in self.turn["content"]]
        return SimpleNamespace(
            content=blocks,
            stop_reason=self.turn["stop_reason"],
            model=self.kwargs["model"],
            usage=SimpleNamespace(
                input_tokens=800, output_tokens=300, cache_read_input_tokens=6000, cache_creation_input_tokens=0
            ),
        )


class FakeAnthropic:
    """reply_pieces/stop_reason: resposta simples. script: lista de turnos (text_turn/tool_turn) em sequência;
    o último se repete. stop_reason também aceita lista (um por chamada)."""

    def __init__(self, reply_pieces=("Às ", "ordens."), stop_reason="end_turn", raise_exc=None, script=None):
        if script is None:
            reasons = [stop_reason] if isinstance(stop_reason, str) else list(stop_reason)
            script = [text_turn("".join(reply_pieces), r) for r in reasons]
        self.script = script
        self.raise_exc = raise_exc
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        # cópia rasa da lista: o histórico real cresce depois da chamada
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        turn = self.script[min(len(self.calls), len(self.script)) - 1]
        return FakeStream(self, kwargs, turn)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TOKEN", "token-de-teste")
    monkeypatch.setenv("JARVIS_PASTAS", str(tmp_path / "pasta_permitida"))
    monkeypatch.setenv("JARVIS_ARQUIVO", str(tmp_path / "arquivo"))
    monkeypatch.setenv("JARVIS_CONHECIMENTO", str(tmp_path / "conhecimento"))
    (tmp_path / "pasta_permitida").mkdir()
    (tmp_path / "arquivo").mkdir()
    s = Settings(data_dir=tmp_path / "dados", monthly_budget_usd=15.0, pii_salt="salt-teste")
    s.data_dir.mkdir(parents=True)
    return s


@pytest.fixture
def fake_claude():
    return FakeAnthropic()
