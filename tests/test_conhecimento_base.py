import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from jarvis.conhecimento import base as base_mod
from jarvis.conhecimento.base import KnowledgeBase
from tests.test_conhecimento_catalogo import catalogo
from tests.test_conhecimento_documento import SUMULAS

FIXTURES = Path(__file__).parent / "fixtures" / "conhecimento"
MOTORES = pytest.mark.parametrize("fts", [True, False], ids=["fts5", "memoria"])

LEI_GO = "Título: RICMS-GO\nFonte-id: go-ricms\nTipo: regulamento\nEsfera: estadual\nUF: GO\n---\n" \
         "Art. 1º O ICMS incide sobre a circulação de mercadorias em Goiás.\nArt. 2 Diferimento.\nArt. 3 Crédito.\n"
LEI_TO = LEI_GO.replace("GO", "TO").replace("go-ricms", "to-ricms").replace("Goiás", "Tocantins")


def cabecalho(fid, vig, situacao="vigente", titulo="Lei X"):
    return (f"Título: {titulo}\nFonte: https://www.planalto.gov.br/{fid}.htm\nBaixado em: {vig.split(' a')[0]}\n"
            f"Fonte-id: {fid}\nTipo: lei\nEsfera: federal\nUF: BR\nVigência: {vig}\nSituação: {situacao}\n---\n")


@MOTORES
def test_area_nova_e_filtros_sem_mudar_codigo(tmp_path, fts):
    root = tmp_path / "base"
    (root / "icms").mkdir(parents=True)
    (root / "icms" / "go.md").write_text(LEI_GO, encoding="utf-8")
    (root / "icms" / "to.md").write_text(LEI_TO, encoding="utf-8")
    (root / "rural").mkdir()
    (root / "rural" / "itr.txt").write_text("Art. 1 O ITR incide sobre a propriedade rural.\n", encoding="utf-8")
    catalogo(root / "_catalogo", "05.toml", bid="agro", area="agro")
    kb = KnowledgeBase(root, fts=fts)
    assert {"agro", "icms", "rural", "geral"} <= set(kb.areas())
    achados = kb.buscar("ICMS circulação de mercadorias", uf="GO")
    assert achados and all(t.uf == "GO" for _, t in achados)
    assert {t.uf for _, t in kb.buscar("ICMS circulação de mercadorias")} == {"GO", "TO"}
    assert all(t.esfera == "estadual" for _, t in kb.buscar("ICMS", esfera="estadual"))
    assert not kb.buscar("ICMS", tipo="sumula") and kb.buscar("ICMS", tipo="regulamento")
    assert [t.area for _, t in kb.buscar("propriedade rural", area="rural")] == ["rural"]


@MOTORES
def test_vigente_em_escolhe_a_versao_certa(tmp_path, fts):
    root = tmp_path / "base"
    (root / "juridico").mkdir(parents=True)
    (root / "_versoes" / "lei-x").mkdir(parents=True)
    (root / "juridico" / "lei-x.md").write_text(
        cabecalho("lei-x", "01/03/2026 a") + "Art. 1 A alíquota é de vinte por cento.\nArt. 2 b\nArt. 3 c\n",
        encoding="utf-8")
    (root / "_versoes" / "lei-x" / "2026-01-01.md").write_text(
        cabecalho("lei-x", "01/01/2026 a 01/03/2026", "histórico")
        + "Art. 1 A alíquota é de dez por cento.\nArt. 2 b\nArt. 3 c\n", encoding="utf-8")
    kb = KnowledgeBase(root, fts=fts)
    atual = kb.buscar("alíquota")[0][1]
    assert "vinte" in atual.texto and atual.atual and atual.vigencia == "01/03/2026 a"
    assert atual.aviso == "capturado em 01/03/2026; pode estar desatualizado"   # sem catálogo: 60 dias
    velha = kb.buscar("alíquota", vigente_em=date(2026, 2, 10))[0][1]
    assert "dez" in velha.texto and not velha.atual and velha.situacao == "histórico"
    assert "não use como norma vigente" in velha.aviso
    assert "vinte" in kb.buscar("alíquota", vigente_em=date(2026, 5, 1))[0][1].texto
    antes = kb.buscar("alíquota", vigente_em=date(2025, 6, 1))[0][1]
    assert "dez" in antes.texto and "não há versão capturada vigente em 01/06/2025" in antes.aviso


@MOTORES
def test_sumula_cancelada_vem_marcada_e_resultado_traz_fonte(tmp_path, fts):
    root = tmp_path / "base"
    (root / "juridico").mkdir(parents=True)
    catalogo(root / "_catalogo", "01.toml", fontes=[{"fid": "sv-stf"}])
    toml = (root / "_catalogo" / "01.toml").read_text(encoding="utf-8").replace('corte = "artigo"', 'corte = "sumula"')
    (root / "_catalogo" / "01.toml").write_text(toml.replace('tipo = "lei"', 'tipo = "sumula"'), encoding="utf-8")
    cab = "Título: Súmulas vinculantes do STF\nFonte: https://portal.stf.jus.br/sv\nBaixado em: 31/10/2026\n---\n"
    (root / "juridico" / "sv-stf.md").write_text(cab + SUMULAS, encoding="utf-8")
    kb = KnowledgeBase(root, fts=fts)
    _, sv8 = kb.buscar("súmula vinculante 8 prescrição decadência tributária")[0]
    assert sv8.rotulo == "Súmula Vinculante 8" and "decadência do crédito tributário" in sv8.texto
    assert sv8.url.endswith("sumula=1209") and sv8.baixado_em == "31/10/2026" and sv8.situacao == "vigente"
    assert sv8.fonte_id == "sv-stf" and sv8.tipo == "sumula"
    _, sv9 = kb.buscar("artigo 127 da Lei 7.210/1984 recebido")[0]
    assert sv9.situacao == "cancelada" and "não use como norma vigente" in sv9.aviso
    assert sv9.url == "https://portal.stf.jus.br/sv"      # item sem URL própria: a do arquivo


@MOTORES
def test_item_citado_pelo_numero_vem_primeiro(tmp_path, fts):
    """O "8" tem um dígito e não vira termo de busca: a SV 8 é achada pela chave do rótulo."""
    root = tmp_path / "base"
    (root / "juridico").mkdir(parents=True)
    catalogo(root / "_catalogo", "01.toml", fontes=[{"fid": "sv-stf"}, {"fid": "rep"}])
    toml = (root / "_catalogo" / "01.toml").read_text(encoding="utf-8").replace('corte = "artigo"', 'corte = "sumula"')
    (root / "_catalogo" / "01.toml").write_text(toml, encoding="utf-8")
    isca = "\n### Súmula Vinculante 4\nSituação: vigente\n" + "Ver Súmula Vinculante 15 e Súmula Vinculante 37. " * 5
    precedentes = "\n".join("Precedente: a súmula vinculante 8 e a súmula vinculante citada." for _ in range(60))
    SUMULAS_LONGAS = SUMULAS.replace("tratam da prescrição e decadência do crédito tributário.",
                                     "tratam da prescrição e decadência do crédito tributário.\n" + precedentes)
    (root / "juridico" / "sv-stf.md").write_text(SUMULAS_LONGAS + isca, encoding="utf-8")
    (root / "juridico" / "rep.md").write_text(
        "### Tema Repetitivo 1001 (STJ)\nSituação: Afetado\nTese firmada: frete na base do PIS.\n"
        "### Tema 1001 (repercussão geral)\nSituação: Trânsito em Julgado\nTese: outra coisa.\n", encoding="utf-8")
    kb = KnowledgeBase(root, fts=fts)
    _, sv8 = kb.buscar("súmula vinculante 8")[0]
    assert sv8.rotulo == "Súmula Vinculante 8" and "decadência do crédito tributário" in sv8.texto
    assert kb.buscar("tema repetitivo 1001")[0][1].rotulo == "Tema Repetitivo 1001 (STJ)"
    assert {t.rotulo for _, t in kb.buscar("tema 1001")[:2]} == {"Tema Repetitivo 1001 (STJ)",
                                                                 "Tema 1001 (repercussão geral)"}


def test_reindexa_so_o_arquivo_alterado_e_remove_apagado(tmp_path):
    root = tmp_path / "base"
    (root / "a").mkdir(parents=True)
    for nome in ("um", "dois", "tres"):
        (root / "a" / f"{nome}.txt").write_text(f"Texto {nome} sobre tributos.\n", encoding="utf-8")
    kb = KnowledgeBase(root, fts=True)
    kb.buscar("tributos")
    assert len(kb.ultima_sincronizacao["cortados"]) == 3
    alvo = root / "a" / "dois.txt"
    alvo.write_text("Texto dois mudou: decadência.\n", encoding="utf-8")
    os.utime(alvo, ns=(alvo.stat().st_atime_ns, alvo.stat().st_mtime_ns + 10**9))
    (root / "a" / "tres.txt").unlink()
    assert kb.buscar("decadência")[0][1].arquivo == "a/dois.txt"
    assert kb.ultima_sincronizacao == {"cortados": ["a/dois.txt"], "removidos": ["a/tres.txt"]}
    novo = KnowledgeBase(root, fts=True)          # outro processo: o índice em disco já está pronto
    assert novo.buscar("decadência") and novo.ultima_sincronizacao["cortados"] == []
    assert novo.resumo()["arquivos"] == 2 and novo.resumo()["motor"] == "fts5"


def test_sem_fts5_cai_no_indice_em_memoria(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod, "_FTS", None)
    monkeypatch.setattr(base_mod, "fts5_disponivel", lambda: False)
    root = tmp_path / "base"
    root.mkdir()
    (root / "x.txt").write_text("Usucapião extraordinária.\n", encoding="utf-8")
    kb = KnowledgeBase(root)
    assert kb.buscar("usucapião")[0][1].area == "geral" and kb.resumo()["motor"] == "memória"
    assert not (root / "_indice").exists()


def test_pasta_inexistente_nao_cria_nada(tmp_path):
    kb = KnowledgeBase(tmp_path / "nao-existe")
    assert kb.buscar("qualquer coisa") == [] and kb.areas() == ["geral"]
    assert not (tmp_path / "nao-existe").exists()


def test_indice_corrompido_e_guardado_e_refeito(tmp_path):
    root = tmp_path / "base"
    (root / "_indice").mkdir(parents=True)
    (root / "_indice" / "base.db").write_bytes(b"isto nao e um sqlite" * 100)
    (root / "x.txt").write_text("Texto sobre imposto.\n", encoding="utf-8")
    assert KnowledgeBase(root, fts=True).buscar("imposto")
    assert list((root / "_indice").glob("base.db.corrompido-*"))


def _catalogo_das_3_leis(pasta):
    """O que a R12 pôs no catalogo_01: área, arquivo e apelidos que estavam em FONTES."""
    leis = [("ctn", "tributario", "tributario/ctn-lei-5172-1966.txt", '["ctn", "codigo tributario", "5172"]'),
            ("lc-123-2006", "tributario", "tributario/lc-123-2006-simples-nacional.txt",
             '["lc 123", "simples nacional", "mei"]'),
            ("estatuto-oab", "oab", "oab/estatuto-oab-lei-8906-1994.txt", '["estatuto", "8906", "advocacia"]')]
    catalogo(pasta, "01.toml", fontes=[{"fid": fid, "situacao": "aprovado", "url": f"https://www.planalto.gov.br/{fid}"}
                                       for fid, *_ in leis])
    texto = (pasta / "01.toml").read_text(encoding="utf-8")
    for fid, area, arquivo, apelidos in leis:
        bloco = f'id = "{fid}"\n'
        texto = texto.replace(bloco, bloco + f'area = "{area}"\narquivo = "{arquivo}"\napelidos = {apelidos}\n')
    (pasta / "01.toml").write_text(texto, encoding="utf-8")


@MOTORES
def test_regressao_as_3_leis_respondem_igual(tmp_path, fts):
    """Golden gravado com o BM25 antigo (31/10/2026): mesmo 1º lugar (lei e artigo) e os artigos do top 3 antigo
    dentro do top 5 novo. A ordem do 2º/3º lugar pode trocar: a R7 pôs sobreposição nas partes de artigos longos e o
    FTS5 usa k1=1,2 (o antigo usava 1,5)."""
    root = tmp_path / "base"
    shutil.copytree(FIXTURES / "leis", root)
    _catalogo_das_3_leis(root / "_catalogo")
    golden = json.loads((FIXTURES / "golden_3_leis.json").read_text(encoding="utf-8"))
    kb = KnowledgeBase(root, fts=fts)

    def artigos(itens):
        return {(arq, rot.split(" (")[0]) for arq, rot in itens}

    for pergunta, esperado in golden.items():
        achados = kb.buscar(pergunta)
        assert (achados[0][1].arquivo, achados[0][1].rotulo) == (esperado[0]["arquivo"], esperado[0]["rotulo"]), \
            pergunta
        assert artigos((e["arquivo"], e["rotulo"]) for e in esperado[:3]) <= \
            artigos((t.arquivo, t.rotulo) for _, t in achados[:5]), pergunta
        assert achados[0][1].fonte == esperado[0]["fonte"] and achados[0][1].area == esperado[0]["area"]
        assert achados[0][1].url.startswith("https://www.planalto.gov.br/") and achados[0][1].baixado_em == "26/10/2026"
