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


# --- 31/10, 12h: "source tool `srvtoolu_01QX...` not found for tool use block `srvtoolu_01Vy...`" ---------------
# A resposta parou para uma ferramenta local (tool_use) com um code_execution ainda rodando no servidor; o
# resultado dele, e a busca que o código fez (caller = o code_execution), vieram na resposta seguinte. A limpeza
# procurava o resultado só na mesma mensagem, tirou o code_execution e deixou a busca apontando para nada.

QX, VY = "srvtoolu_01QXtA8E5SM19ciLKL4oLnLS", "srvtoolu_01VyQ1SJzTQCQHRavGnGyV2b"
_PELO_CODIGO = {"type": "code_execution_20260120", "tool_id": QX}


def _blocos(m: dict) -> list[dict]:
    return m["content"] if isinstance(m["content"], list) else []


def _erros_da_api(messages: list[dict]) -> list[str]:
    """As regras de pareamento que a API cobra com 400 invalid_request_error (o Claude falso não confere)."""
    usos = {b["id"]: b["type"] for m in messages for b in _blocos(m) if b["type"] in ("server_tool_use", "tool_use")}
    resultados = {b["tool_use_id"]: b["type"] for m in messages for b in _blocos(m)
                  if b["type"].endswith("tool_result")}
    erros = [f"tool use {i} was found without a corresponding _tool_result block"
             for i, t in usos.items() if i not in resultados]
    erros += [f"unexpected tool_use_id {i} in {t}" for i, t in resultados.items() if i not in usos]
    erros += [f"source tool {b['caller']['tool_id']} not found for tool use block {b.get('id', b.get('tool_use_id'))}"
              for m in messages for b in _blocos(m)
              if (b.get("caller") or {}).get("tool_id") and b["caller"]["tool_id"] not in usos]
    return erros


def _codigo_esperando_ferramenta_local() -> dict:
    return {"content": [
        {"type": "server_tool_use", "id": QX, "name": "code_execution", "input": {"code": "busca()"}},
        {"type": "tool_use", "id": "toolu_status", "name": "status_sistema", "input": {}, "caller": {"type": "direct"}},
    ], "stop_reason": "tool_use"}


def _codigo_terminou_na_resposta_seguinte() -> dict:
    return {"content": [
        {"type": "server_tool_use", "id": VY, "name": "web_search", "input": {"query": "IBS"}, "caller": _PELO_CODIGO},
        {"type": "web_search_tool_result", "tool_use_id": VY, "content": [], "caller": _PELO_CODIGO},
        {"type": "code_execution_tool_result", "tool_use_id": QX,
         "content": {"type": "encrypted_code_execution_result", "encrypted_stdout": "x"}},
        {"type": "text", "text": "A base local não trouxe nada; achei isto na web."},
    ], "stop_reason": "end_turn"}


async def test_resultado_em_mensagem_seguinte_nao_e_orfao(settings):
    claude = FakeAnthropic(script=[_codigo_esperando_ferramenta_local(), _codigo_terminou_na_resposta_seguinte(),
                                   text_turn("Sim, Senhor.")])
    conv = build_conversation(settings, claude_client=claude)
    async for _ in conv.turn("hud", "pesquise o IBS"):
        pass
    hist = conv.store.history("hud")
    assert _erros_da_api(hist) == []
    assert QX in {b.get("id") for m in hist for b in _blocos(m)}           # nada da conversa se perdeu
    async for _ in conv.turn("hud", "obrigado, e o CBS?"):
        pass
    assert _erros_da_api(claude.calls[-1]["messages"]) == []


def test_tira_junto_o_que_dependia_da_chamada_orfa():
    """Chamada realmente sem resultado: some com ela tudo o que o código dela chamou (servidor e local)."""
    hist = [
        {"role": "user", "content": "pesquise"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": QX, "name": "code_execution", "input": {}},
            {"type": "server_tool_use", "id": VY, "name": "web_search", "input": {}, "caller": _PELO_CODIGO},
            {"type": "web_search_tool_result", "tool_use_id": VY, "content": [], "caller": _PELO_CODIGO},
            {"type": "tool_use", "id": "toolu_local", "name": "status_sistema", "input": {}, "caller": _PELO_CODIGO},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_local", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "(turno interrompido)"}]},
    ]
    assert fechar_ferramentas_orfas(hist) == 5
    assert _erros_da_api(hist) == []
    assert hist[1]["content"] == [{"type": "text", "text": "(a ferramenta foi interrompida antes do resultado)"}]
    assert [b["type"] for b in hist[2]["content"]] == ["text"]          # mensagem do usuário nunca fica vazia
    assert fechar_ferramentas_orfas(hist) == 0


def test_sessao_gravada_com_fonte_perdida_e_reparada_ao_carregar_sem_apagar_o_original(tmp_path):
    """O formato exato que travou a sessão "hud": o code_execution sumiu, a busca e o resultado dele ficaram."""
    quebrada = [
        {"role": "user", "content": "pesquise o IBS"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "tool_use", "id": "toolu_k", "name": "buscar_conhecimento", "input": {}, "caller": {"type": "direct"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_k", "content": "nada"}]},
        _codigo_terminou_na_resposta_seguinte() | {"role": "assistant"},
        {"role": "user", "content": "valeu"},
        {"role": "assistant", "content": [{"type": "text", "text": "Sempre um prazer, Senhor."}]},
    ]
    for m in quebrada:
        m.pop("stop_reason", None)
    original = json.dumps(quebrada, ensure_ascii=False)
    (tmp_path / "hud.json").write_text(original, encoding="utf-8")

    hist = SessionStore(tmp_path).history("hud")
    assert _erros_da_api(hist) == []
    assert [b["type"] for b in hist[3]["content"]] == ["text"]
    assert hist[3]["content"][0]["text"].startswith("A base local")       # a resposta continua na conversa
    assert len(hist) == len(quebrada)
    copias = list((tmp_path / "arquivo").glob("hud-antes-do-reparo-*.json"))
    assert [c.read_text(encoding="utf-8") for c in copias] == [original]  # reparo reversível
    assert (tmp_path / "hud.json").exists()
