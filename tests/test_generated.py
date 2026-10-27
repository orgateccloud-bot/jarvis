from datetime import date

from jarvis.api.server import build_conversation
from jarvis.tools.generated import file_ids, nome_seguro, salvar_gerados
from tests.conftest import FakeAnthropic, FakeFiles, sandbox_file_turn, text_turn, tool_turn
from tests.test_tools import run_turn

HOJE = date(2026, 10, 26)


def test_file_ids_so_dos_arquivos_deixados_em_output_dir():
    content = sandbox_file_turn(["file_a", "file_b"])["content"] + [
        {"type": "code_execution_tool_result",
         "content": {"type": "encrypted_code_execution_result", "content": [], "encrypted_stdout": "x"}},
        {"type": "bash_code_execution_tool_result", "content": {"type": "bash_code_execution_result", "content": []}},
    ]
    assert file_ids(content) == ["file_a", "file_b"]


def test_nome_seguro_tira_caminho_e_nomes_reservados():
    assert nome_seguro("../../etc/passwd") == "passwd"
    assert nome_seguro("C:\\Windows\\System32\\x.bat") == "x.bat"
    assert nome_seguro("CON.txt") == "_CON.txt"
    assert nome_seguro('a:b?"c.csv') == "a_b__c.csv"
    assert nome_seguro("") == "arquivo" and nome_seguro("..") == "arquivo"


async def test_salva_sem_sobrescrever_e_registra_falhas(tmp_path):
    files = FakeFiles()
    files.store = {"f1": ("relatorio.csv", b"a;b\n1;2\n"), "f2": ("relatorio.csv", b"outro\n")}
    client = type("C", (), {"files": files})()
    regs = await salvar_gerados(client, ["f1", "f2", "sumiu"], tmp_path, HOJE)
    pasta = tmp_path / "Gerados" / "2026-10-26"
    assert (pasta / "relatorio.csv").read_bytes() == b"a;b\n1;2\n"
    assert (pasta / "relatorio (2).csv").read_bytes() == b"outro\n"
    assert regs[0]["caminho"] == str(pasta / "relatorio.csv") and "erro" in regs[2]


async def test_arquivo_do_sandbox_vira_chip_e_aviso_na_proxima_conversa(settings):
    fake = FakeAnthropic(script=[sandbox_file_turn(["file_csv"], "Gerei o CSV."), text_turn("Está em Gerados.")])
    fake.files.store = {"file_csv": ("vendas.csv", b"mes;total\nout;10\n")}
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "pesquise e me gere um csv com as vendas")
    chip = next(e.data for e in evs if e.type == "tool" and e.data["nome"] == "arquivo_gerado")
    salvo = settings.archive_dir() / "Gerados" / f"{date.today():%Y-%m-%d}" / "vendas.csv"
    assert chip["ok"] and str(salvo) in chip["resumo"] and salvo.read_bytes() == b"mes;total\nout;10\n"
    await run_turn(conv, "onde ficou o arquivo?")
    nota = fake.calls[1]["messages"][-1]
    assert nota["role"] == "system" and str(salvo) in nota["content"]
    await run_turn(conv, "e agora?")
    assert str(salvo) not in fake.calls[2]["messages"][-1]["content"]           # avisa uma vez só


async def test_aviso_vai_junto_dos_tool_result_quando_o_loop_continua(settings):
    extra = tool_turn("status_sistema", {}, "toolu_9")["content"][0]
    fake = FakeAnthropic(script=[sandbox_file_turn(["f"], "Gerando.", extra=extra), text_turn("Feito.")])
    fake.files.store = {"f": ("grafico.png", b"\x89PNG")}
    conv = build_conversation(settings, claude_client=fake)
    await run_turn(conv, "pesquise e gere um gráfico do uso de cpu")
    ultimo_user = fake.calls[1]["messages"][-1]
    assert ultimo_user["role"] == "user" and ultimo_user["content"][0]["type"] == "tool_result"
    assert ultimo_user["content"][-1]["type"] == "text" and "grafico.png" in ultimo_user["content"][-1]["text"]
