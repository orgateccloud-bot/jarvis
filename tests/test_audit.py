"""Cadeia de auditoria: a conferência olha o registro gravado, não os contratos de hoje."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from jarvis.api.server import build_conversation, create_app
from jarvis.core.audit import GENESIS, AuditChain
from jarvis.core.contracts import AgentResult, Route

AUTH = {"Authorization": "Bearer token-de-teste"}

# Registro da época em que a rota "chat" existia. Os hashes deste arquivo foram calculados fora do
# audit.py e ficam congelados: se o JSON canônico mudar, os registros já gravados deixam de bater.
REGISTRO_ANTIGO = {
    "prev": GENESIS,
    "session_id": "default",
    "route": "chat",
    "model": "claude-haiku-5-5",
    "text": "Às ordens.",
    "cost_usd": 0.0012,
    "stop_reason": "end_turn",
    "at": "2026-10-23T09:15:00.123456",
    "audit_hash": "22ba4ae2a179089e1c73119182b3ed8c584bbe850849e3d402f8b49771b4112b",
}

LINHAS_SEM_HASH = [
    pytest.param(b"isto nao e json\n", id="nao-e-json"),
    pytest.param(b'{"prev": "', id="gravacao-cortada"),
    pytest.param(b"[1, 2]\n", id="lista"),
    pytest.param(b"null\n", id="nulo"),
    pytest.param(b"{}\n", id="objeto-vazio"),
    pytest.param(b'{"prev": "abc"}\n', id="sem-hash"),
    pytest.param(b'{"audit_hash": 123}\n', id="hash-que-nao-e-texto"),
    pytest.param(b"\xff\xfe\n", id="bytes-fora-do-utf8"),
    pytest.param(b"\x00\x00\x00\n", id="bytes-nulos"),
    pytest.param(b"[" * 200_000 + b"\n", id="aninhamento-profundo"),
]


def _gravar(path, *registros) -> None:
    linhas = [json.dumps(r, ensure_ascii=False) + "\n" for r in registros]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(linhas), encoding="utf-8")


def test_rota_antiga_valida_passa_e_a_cadeia_continua(tmp_path):
    with pytest.raises(ValueError):  # a premissa do teste: o enum de hoje recusa esta rota
        Route(REGISTRO_ANTIGO["route"])
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)

    chain = AuditChain(path)
    assert chain.verify()
    chain.seal(AgentResult(session_id="s", route=Route.LOCAL, model="m", text="depois da rota antiga"))
    assert chain.verify()


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("text", "Às ordens!"),
        ("route", "simples"),  # valor aceito pelo enum: passaria numa validação só de contrato
        ("cost_usd", 0.0),
        ("at", "2026-10-24T09:15:00.123456"),
        ("campo_novo", "acrescentado"),  # o modelo ignoraria um campo a mais; o hash não
    ],
)
def test_rota_antiga_adulterada_e_detectada(tmp_path, campo, valor):
    path = tmp_path / "audit.jsonl"
    _gravar(path, {**REGISTRO_ANTIGO, campo: valor})
    assert AuditChain(path).verify() is False


@pytest.mark.parametrize("campo", ["prev", "audit_hash"])
def test_elo_da_cadeia_adulterado_e_detectado(tmp_path, campo):
    path = tmp_path / "audit.jsonl"
    _gravar(path, {**REGISTRO_ANTIGO, campo: "f" * 64})
    assert AuditChain(path).verify() is False


def test_adulteracao_no_meio_quebra_o_resto_da_cadeia(tmp_path):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    chain = AuditChain(path)
    chain.seal(AgentResult(session_id="s", route=Route.LOCAL, model="m", text="segundo"))
    primeiro, segundo = path.read_text(encoding="utf-8").splitlines()
    assert chain.verify()

    _gravar(path, {**json.loads(primeiro), "text": "trocado"}, json.loads(segundo))
    assert chain.verify() is False


@pytest.mark.parametrize(
    "linha", [*LINHAS_SEM_HASH, pytest.param(b'{"audit_hash": "abc"}\n', id="sem-prev")]
)
def test_registro_ilegivel_nao_levanta(tmp_path, linha):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    chain = AuditChain(path)
    with path.open("ab") as f:
        f.write(linha)
    assert chain.verify() is False


@pytest.mark.parametrize("linha", LINHAS_SEM_HASH)
def test_sobe_com_linha_ilegivel_e_segue_do_ultimo_hash_legivel(tmp_path, linha):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    with path.open("ab") as f:
        f.write(linha)
    gravado = path.read_bytes()

    chain = AuditChain(path)
    assert chain.verify() is False
    novo = chain.seal(AgentResult(session_id="s", route=Route.LOCAL, model="m", text="depois da quebra"))

    depois = path.read_bytes()
    assert depois.startswith(gravado)  # append-only: nada do que estava gravado mudou
    ultimo = json.loads(depois.splitlines()[-1].decode("utf-8"))
    assert ultimo["prev"] == REGISTRO_ANTIGO["audit_hash"] and ultimo["audit_hash"] == novo.audit_hash
    assert chain.verify() is False  # selar depois da quebra não apaga a denúncia
    assert AuditChain(path)._last == novo.audit_hash  # o próximo reinício retoma do registro novo


def test_registro_novo_nao_cola_em_gravacao_cortada(tmp_path):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    with path.open("ab") as f:
        f.write(b'{"prev": "')

    AuditChain(path).seal(AgentResult(session_id="s", route=Route.LOCAL, model="m", text="novo"))

    linhas = path.read_bytes().splitlines()
    assert len(linhas) == 3 and linhas[1] == b'{"prev": "'
    assert json.loads(linhas[2].decode("utf-8"))["text"] == "novo"


def test_registro_inteiro_sem_quebra_final_mantem_a_cadeia_integra(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps(REGISTRO_ANTIGO, ensure_ascii=False), encoding="utf-8")

    chain = AuditChain(path)
    chain.seal(AgentResult(session_id="s", route=Route.LOCAL, model="m", text="novo"))

    assert len(path.read_bytes().splitlines()) == 2
    assert chain.verify()


def test_aviso_na_subida_diz_a_linha_sem_mostrar_o_conteudo(tmp_path):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    with path.open("ab") as f:
        f.write(b"conteudo sigiloso\n")

    avisos: list[str] = []
    sink = logger.add(lambda m: avisos.append(str(m)), level="WARNING")
    try:
        AuditChain(path)
    finally:
        logger.remove(sink)

    assert len(avisos) == 1 and "a primeira é a 2" in avisos[0]
    assert "sigiloso" not in avisos[0]


def test_texto_que_nao_vira_utf8_nao_levanta(tmp_path):
    path = tmp_path / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    chain = AuditChain(path)
    # o JSON é válido, mas a surrogate solta não pode ser codificada para o hash
    registro = json.dumps({**REGISTRO_ANTIGO, "prev": REGISTRO_ANTIGO["audit_hash"], "text": "\ud800"})
    with path.open("a", encoding="utf-8") as f:
        f.write(registro + "\n")
    assert chain.verify() is False


def test_compute_mantem_o_hash_dos_registros_ja_gravados():
    resultado = AgentResult(
        session_id="default", route=Route.LOCAL, model="claude-haiku-5-5", text="Às ordens.",
        cost_usd=0.0012, stop_reason="end_turn", at=datetime(2026, 10, 23, 9, 15, 0, 123456),
    )
    esperado = "b75869da685261ee6888d99038687d2d72d821daf05a4a217a5ed8c5bb100a0e"
    assert AuditChain.compute(GENESIS, resultado) == esperado


def _cliente(settings, fake):
    conv = build_conversation(settings, claude_client=fake)
    return TestClient(create_app(settings, conversation=conv))


def test_api_confere_rota_antiga_sem_500(settings, fake_claude):
    _gravar(settings.data_dir / "audit.jsonl", REGISTRO_ANTIGO)
    resp = _cliente(settings, fake_claude).get("/audit/verify", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"integra": True}


def test_api_responde_integra_false_para_registro_adulterado(settings, fake_claude):
    _gravar(settings.data_dir / "audit.jsonl", {**REGISTRO_ANTIGO, "text": "trocado"})
    resp = _cliente(settings, fake_claude).get("/audit/verify", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"integra": False}


def test_api_sobe_com_linha_ilegivel_e_responde_integra_false(settings, fake_claude):
    path = settings.data_dir / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    with path.open("ab") as f:
        f.write(b"isto nao e json\n")
    resp = _cliente(settings, fake_claude).get("/audit/verify", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"integra": False}


def test_api_responde_integra_false_para_registro_ilegivel(settings, fake_claude):
    path = settings.data_dir / "audit.jsonl"
    _gravar(path, REGISTRO_ANTIGO)
    client = _cliente(settings, fake_claude)
    with path.open("ab") as f:
        f.write(b"isto nao e json\n")
    resp = client.get("/audit/verify", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"integra": False}
