"""Correção de 31/10: uma resposta cortada deixou um code_execution sem o resultado no histórico da sessão "hud";
a partir dali a API recusou toda pergunta com 400 ("... was found without a corresponding
`code_execution_tool_result` block") e o HUD mostrava "bad request". O histórico agora é fechado no fim de cada
turno e reparado ao carregar."""

import json

from jarvis.api.server import build_conversation
from jarvis.core.session import MAX_STEPS, SessionStore, fechar_ferramentas_orfas
from tests.conftest import FakeAnthropic, text_turn


def _pausado(n: int) -> dict:
    """Turno em que a ferramenta de servidor pausou (pause_turn): a chamada fica sem resultado."""
    return {"content": [{"type": "server_tool_use", "id": f"srvtoolu_{n}", "name": "code_execution",
                         "input": {"code": "print(1)"}}], "stop_reason": "pause_turn"}


def test_tira_so_as_chamadas_sem_resultado():
    hist = [
        {"role": "user", "content": "calcule"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srv_ok", "name": "code_execution", "input": {}},
            {"type": "code_execution_tool_result", "tool_use_id": "srv_ok", "content": {}},
            {"type": "server_tool_use", "id": "srv_orfao", "name": "code_execution", "input": {}},
        ]},
        {"role": "user", "content": "e então?"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                          {"type": "server_tool_use", "id": "srv_so", "name": "web_search",
                                           "input": {}}]},
    ]
    assert fechar_ferramentas_orfas(hist) == 2
    assert [b["type"] for b in hist[1]["content"]] == ["server_tool_use", "code_execution_tool_result"]
    assert [b["type"] for b in hist[3]["content"]] == ["thinking", "text"]   # nunca fica só com thinking
    assert fechar_ferramentas_orfas(hist) == 0                                 # idempotente


def test_sessao_gravada_quebrada_e_reparada_ao_carregar(tmp_path):
    (tmp_path / "hud.json").write_text(json.dumps([
        {"role": "user", "content": "rode isto"},
        {"role": "assistant", "content": [{"type": "server_tool_use", "id": "srvtoolu_01TB", "name": "code_execution",
                                           "input": {}}]},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": [{"type": "text", "text": "falha"}]},
    ]), encoding="utf-8")
    hist = SessionStore(tmp_path).history("hud")
    assert not any(b.get("type") == "server_tool_use" for m in hist for b in (m["content"] if isinstance(
        m["content"], list) else []))


async def test_pause_turn_ate_o_ultimo_passo_nao_deixa_o_historico_quebrado(settings):
    claude = FakeAnthropic(script=[_pausado(i) for i in range(MAX_STEPS)] + [text_turn("Pronto.")])
    conv = build_conversation(settings, claude_client=claude)
    async for _ in conv.turn("hud", "faça uma conta longa"):
        pass
    hist = conv.store.history("hud")
    orfaos = [b for m in hist if m["role"] == "assistant" and isinstance(m["content"], list)
              for b in m["content"] if b.get("type") == "server_tool_use"]
    assert orfaos == []
    # a pergunta seguinte segue normalmente (antes, era 400 para sempre)
    async for _ in conv.turn("hud", "e agora?"):
        pass
    assert conv.store.history("hud")[-1]["role"] == "assistant"
