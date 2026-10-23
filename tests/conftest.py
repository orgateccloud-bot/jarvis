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


class FakeStream:
    def __init__(self, owner, kwargs):
        self.owner = owner
        self.kwargs = kwargs

    async def __aenter__(self):
        if self.owner.raise_exc:
            raise self.owner.raise_exc
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            yield _delta_event("thinking_delta", "pensando...")
            for piece in self.owner.reply_pieces:
                yield _delta_event("text_delta", piece)

        return gen()

    async def get_final_message(self):
        text = "".join(self.owner.reply_pieces)
        return SimpleNamespace(
            content=[_Block(type="thinking", thinking="pensando...", signature="sig"), _Block(type="text", text=text)],
            stop_reason=self.owner.stop_reasons[min(len(self.owner.calls), len(self.owner.stop_reasons)) - 1],
            model=self.kwargs["model"],
            usage=SimpleNamespace(
                input_tokens=800, output_tokens=300, cache_read_input_tokens=6000, cache_creation_input_tokens=0
            ),
        )


class FakeAnthropic:
    def __init__(self, reply_pieces=("Às ", "ordens."), stop_reason="end_turn", raise_exc=None):
        self.reply_pieces = list(reply_pieces)
        # str: mesmo stop_reason sempre; lista: um por chamada (o último se repete)
        self.stop_reasons = [stop_reason] if isinstance(stop_reason, str) else list(stop_reason)
        self.raise_exc = raise_exc
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        # cópia rasa da lista: o histórico real cresce depois da chamada
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self, kwargs)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TOKEN", "token-de-teste")
    s = Settings(data_dir=tmp_path / "dados", monthly_budget_usd=15.0, pii_salt="salt-teste")
    s.data_dir.mkdir(parents=True)
    return s


@pytest.fixture
def fake_claude():
    return FakeAnthropic()
