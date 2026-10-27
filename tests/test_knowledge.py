import json
from types import SimpleNamespace

from jarvis import knowledge
from jarvis.api.server import build_conversation
from jarvis.core.contracts import BudgetState, Route
from jarvis.core.router import area_for, decide
from jarvis.knowledge import Fonte, KnowledgeBase, baixar, cortar, html_para_texto
from tests.conftest import FakeAnthropic, text_turn, tool_turn
from tests.test_tools import run_turn, tool_results

LEI = """Título: Código de Teste (Lei 1/2000)
Fonte: https://exemplo
---
Lei de teste.
Art. 1º Esta lei regula o teste.
Art. 173. O direito de a Fazenda Pública constituir o crédito tributário extingue-se após 5 (cinco) anos.
Art. 174. A ação para a cobrança do crédito tributário prescreve em cinco anos.
Art. 174-A. Artigo incluído depois.
ANEXO I
Tabela de alíquotas.
"""


def base(tmp_path) -> KnowledgeBase:
    root = tmp_path / "conhecimento"
    (root / "tributario").mkdir(parents=True)
    (root / "oab").mkdir()
    (root / "_versoes").mkdir()
    (root / "tributario" / "lei.txt").write_text(LEI, encoding="utf-8")
    (root / "oab" / "estatuto.md").write_text("Art. 1 Advocacia.\nArt. 2 Sigilo profissional do advogado.\n"
                                               "Art. 3 Honorários.\n", encoding="utf-8")
    (root / "_versoes" / "velha.txt").write_text("Art. 173. versão antiga revogada", encoding="utf-8")
    return KnowledgeBase(root)


def test_html_descarta_texto_riscado_e_junta_linhas():
    html = ("<p>Art. 1º O imposto\n incide <strike>sobre tudo</strike> sobre a renda.</p>"
            "<p><span style='text-decoration: line-through'>Art. 2º revogado</span></p><p>Art. 3º Vale.</p>")
    texto = html_para_texto(html)
    assert "Art. 1º O imposto incide sobre a renda." in texto and "revogado" not in texto
    assert "sobre tudo" not in texto and "Art. 3º Vale." in texto


def test_lei_cortada_por_artigo_e_anexo():
    rotulos = [r for r, _ in cortar(LEI.split("---\n", 1)[1])]
    assert rotulos == ["Preâmbulo", "Art. 1", "Art. 173", "Art. 174", "Art. 174-A", "Anexo I"]
    longo = "\n".join(f"Art. {i}. " + "texto " * 400 for i in range(1, 4))
    assert "Art. 1 (parte 2)" in [r for r, _ in cortar(longo)]


def test_bm25_acha_o_artigo_certo_e_respeita_area(tmp_path):
    kb = base(tmp_path)
    _, t = kb.buscar("o que diz a lei sobre decadência?")[0]
    assert t.rotulo == "Art. 173" and t.fonte == "Código de Teste (Lei 1/2000)" and t.area == "tributario"
    assert kb.buscar("art. 174")[0][1].rotulo == "Art. 174"
    assert all(t.area == "oab" for _, t in kb.buscar("sigilo profissional honorários", area="oab"))
    assert not any("antiga" in t.texto for _, t in kb.buscar("versão antiga revogada"))   # _versoes fora


def test_indice_se_refaz_quando_a_pasta_muda(tmp_path):
    kb = base(tmp_path)
    assert not kb.buscar("usucapião")
    (kb.root / "geral.txt").write_text("Usucapião extraordinária exige posse longa.\n", encoding="utf-8")
    achado = kb.buscar("usucapião")[0][1]
    assert achado.area == "geral" and achado.arquivo == "geral.txt"


def test_baixar_grava_cabecalho_e_guarda_a_versao_anterior(tmp_path, monkeypatch):
    html = "<html><body>" + "".join(f"<p>Art. {i}º Texto do artigo {i}.</p>" for i in range(1, 12)) + "</body></html>"

    class Resp:
        headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

        def read(self):
            return html.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(knowledge.urllib.request, "urlopen", lambda req, timeout: Resp())
    fonte = [Fonte("tributario/teste.txt", "Lei Teste", "https://www.planalto.gov.br/teste.htm")]
    baixar(tmp_path, fonte)
    baixar(tmp_path, fonte)
    texto = (tmp_path / "tributario" / "teste.txt").read_text(encoding="utf-8")
    assert texto.startswith("Título: Lei Teste\nFonte: https://www.planalto.gov.br/teste.htm") and "Art. 11º" in texto
    assert len(list((tmp_path / "_versoes").glob("teste.*.txt"))) == 1


def test_area_pelo_assunto_e_piso_no_intermediario():
    assert area_for("o que o ctn diz sobre decadencia") == "tributario"
    assert area_for("o advogado pode quebrar o sigilo profissional?") == "oab"
    assert area_for("como fecho o balancete do mes") == "contabil"
    assert area_for("qual a razao disso") is None and area_for("me conta uma curiosidade") is None
    d = decide("O que o CTN diz sobre decadência?", BudgetState.NORMAL)
    assert d.area == "tributario" and d.route is Route.MEDIUM
    assert decide("/haiku o que é ICMS?", BudgetState.NORMAL).route is Route.SIMPLE      # forçado vale
    e = decide("O que o CTN diz sobre decadência?", BudgetState.ECONOMY)
    assert e.route is Route.MEDIUM and e.effort == "low"


async def test_pergunta_tributaria_recebe_nota_de_area_e_busca_na_base(settings):
    root = settings.knowledge_dir()
    (root / "tributario").mkdir(parents=True)
    (root / "tributario" / "lei.txt").write_text(LEI, encoding="utf-8")
    fake = FakeAnthropic(script=[tool_turn("buscar_conhecimento", {"consulta": "decadência"}),
                                 text_turn("Art. 173 do CTN, Senhor.")])
    conv = build_conversation(settings, claude_client=fake)
    evs = await run_turn(conv, "O que o CTN diz sobre decadência?")
    assert evs[0].data["modelo"] == "claude-sonnet-5-5"
    nota = fake.calls[0]["messages"][-1]
    assert nota["role"] == "system" and "área provável: Direito Tributário" in nota["content"]
    achados = json.loads(tool_results(fake.calls[1])[0]["content"])
    assert achados[0]["trecho"] == "Art. 173" and "constituir o crédito tributário" in achados[0]["texto"]
