import json
from types import SimpleNamespace

import pytest

from jarvis.conhecimento.base import KnowledgeBase
from jarvis.tools import ToolError, registry
from jarvis.tools.knowledge import LIMITE_DESCRICAO, BuscaParams, buscar_conhecimento, descricao
from tests.test_conhecimento_base import LEI_GO, LEI_TO, cabecalho
from tests.test_conhecimento_catalogo import catalogo


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "base"
    (root / "icms").mkdir(parents=True)
    (root / "icms" / "go.md").write_text(LEI_GO, encoding="utf-8")
    (root / "icms" / "to.md").write_text(LEI_TO, encoding="utf-8")
    (root / "juridico").mkdir()
    (root / "juridico" / "lei-x.md").write_text(
        cabecalho("lei-x", "26/10/2026 a", titulo="Lei X (Lei 1/2000)")
        + "Art. 1 Prescrição tributária em cinco anos.\nArt. 2 b\nArt. 3 c\n", encoding="utf-8")
    catalogo(root / "_catalogo", "03.toml", bid="fiscal", area="tributario")
    return KnowledgeBase(root)


def chamar(kb, **params):
    return json.loads(buscar_conhecimento(BuscaParams(**params), SimpleNamespace(knowledge=kb)))


def test_resultado_traz_fonte_url_data_e_situacao(kb):
    t = chamar(kb, consulta="prescrição tributária")[0]
    assert t["fonte"] == "Lei X (Lei 1/2000)" and t["trecho"] == "Art. 1" and t["fonte_id"] == "lei-x"
    assert t["url"] == "https://www.planalto.gov.br/lei-x.htm" and t["baixado_em"] == "26/10/2026"
    assert t["situacao"] == "vigente" and t["vigencia"] == "26/10/2026 a" and t["uf"] == "BR"
    assert "aviso" not in t                       # campo vazio não vai


def test_filtros_chegam_na_base(kb):
    assert {t["uf"] for t in chamar(kb, consulta="ICMS mercadorias", uf="go")} == {"GO"}
    assert all(t["tipo"] == "regulamento" for t in chamar(kb, consulta="ICMS", tipo="regulamento"))
    vazio = chamar(kb, consulta="ICMS", esfera="municipal")
    assert vazio["resultado"] == "nada encontrado na base local"
    antes = chamar(kb, consulta="prescrição tributária", vigente_em="2020-01-01")[0]
    assert "não há versão capturada vigente em 01/01/2020" in antes["aviso"]


def test_area_validada_em_tempo_de_execucao(kb):
    assert chamar(kb, consulta="ICMS", area="icms")[0]["arquivo"].startswith("icms/")
    with pytest.raises(ToolError, match="Área desconhecida: astrologia. Use uma destas: geral, icms, juridico"):
        chamar(kb, consulta="ICMS", area="astrologia")


def test_descricao_gerada_dos_catalogos_e_curta(kb):
    tool = registry(knowledge=kb)["buscar_conhecimento"]
    assert "(áreas: icms, juridico;" in tool.description and len(tool.description) <= LIMITE_DESCRICAO
    assert "tributario" in kb.areas() and "tributario" not in kb.areas_em_uso()   # catálogo sem texto: fora da lista
    longa = descricao([f"area_{i:02d}" for i in range(40)])
    assert len(longa) <= LIMITE_DESCRICAO and "area_00" in longa
    assert "enum" not in json.dumps(tool.definition()["input_schema"]["properties"]["area"])   # não é Literal
