from datetime import date

from jarvis.conhecimento.corte import TAM_TRECHO, cortar, meta_do_item
from jarvis.conhecimento.documento import (
    Cabecalho,
    escrever_cabecalho,
    hash_texto,
    html_para_texto,
    ler_cabecalho,
)

ANTIGO = "Título: Lei Velha\nFonte: https://www.planalto.gov.br/x.htm\nBaixado em: 26/10/2026\n---\nArt. 1º Texto.\n"


def test_cabecalho_antigo_continua_valido():
    cab, corpo = ler_cabecalho(ANTIGO)
    assert cab.titulo == "Lei Velha" and cab.fonte.endswith("x.htm") and corpo == "Art. 1º Texto.\n"
    assert cab.fonte_id == "" and cab.situacao == "" and cab.baixado() == date(2026, 10, 26)
    assert cab.periodo() == (date(2026, 10, 26), None)          # sem Vigência: começa na captura


def test_cabecalho_v2_ida_e_volta():
    cab = Cabecalho(titulo="CTN", fonte="https://www.planalto.gov.br/l5172compilado.htm", baixado_em="31/10/2026",
                    biblioteca="juridico", fonte_id="ctn", tipo="lei", esfera="federal", uf="BR",
                    vigencia="26/10/2026 a 31/10/2026", situacao="histórico", hash=hash_texto("Art. 1"))
    texto = escrever_cabecalho(cab) + "Art. 1\n"
    lido, corpo = ler_cabecalho(texto)
    assert lido == cab and corpo == "Art. 1\n"
    assert lido.periodo() == (date(2026, 10, 26), date(2026, 10, 31))
    assert escrever_cabecalho(Cabecalho(titulo="X")) == "Título: X\n---\n"   # campo vazio não é escrito


def test_sem_cabecalho_nao_engole_o_texto():
    texto = "Introdução\n---\nResto do documento em markdown.\n"
    cab, corpo = ler_cabecalho(texto)
    assert cab == Cabecalho() and corpo == texto


def test_hash_ignora_fim_de_linha_windows():
    assert hash_texto("Art. 1\r\nArt. 2") == hash_texto("Art. 1\nArt. 2\n")


def test_html_tachado_pode_ser_mantido():
    html = "<p>Art. 1º <strike>velho</strike> novo</p>"
    assert "velho" not in html_para_texto(html) and "velho" in html_para_texto(html, remover_tachado=False)


def test_corte_artigo_sem_tipo_e_igual_ao_antigo():
    texto = "Lei.\nArt. 1º Um.\nArt. 2 Dois.\nArt. 2-A Dois-A.\nANEXO I\nTabela.\n"
    assert [r for r, _ in cortar(texto)] == ["Preâmbulo", "Art. 1", "Art. 2", "Art. 2-A", "Anexo I"]
    assert [r for r, _ in cortar(texto, "artigo")] == [r for r, _ in cortar(texto)]
    assert [r for r, _ in cortar(texto, "anexo")] == ["Preâmbulo", "Anexo I"]


def test_divisao_tem_sobreposicao_curta():
    longo = "Art. 1. " + " ".join(f"palavra{i}" for i in range(600))
    partes = cortar(longo + "\nArt. 2. b\nArt. 3. c\n")
    assert [r for r, _ in partes][:2] == ["Art. 1", "Art. 1 (parte 2)"]
    fim_da_1 = partes[0][1].split()[-1]
    assert partes[1][1].startswith("…") and fim_da_1 in partes[1][1][:200]
    assert all(len(t) <= TAM_TRECHO + 200 for _, t in partes)


SUMULAS = """Súmulas do STF.

### Súmula Vinculante 8
Situação: vigente
Data: 12/06/2008
URL: https://portal.stf.jus.br/jurisprudencia/sumariosumulas.asp?base=26&sumula=1209
São inconstitucionais o parágrafo único do artigo 5º do Decreto-Lei 1.569/1977 e os artigos 45 e 46 da Lei
8.212/1991, que tratam da prescrição e decadência do crédito tributário.

### Súmula Vinculante 9
Situação: cancelada
O disposto no artigo 127 da Lei 7.210/1984 foi recebido pela ordem constitucional vigente.
"""


def test_corte_sumula_um_item_por_trecho_com_metadados():
    trechos = cortar(SUMULAS, "sumula")
    assert [r for r, _ in trechos] == ["Preâmbulo", "Súmula Vinculante 8", "Súmula Vinculante 9"]
    meta = meta_do_item(trechos[1][1])
    assert meta["situacao"] == "vigente" and meta["data"] == "12/06/2008" and "sumula=1209" in meta["url"]
    assert meta_do_item(trechos[2][1]) == {"situacao": "cancelada"}


def test_corte_secao_e_pagina():
    md = "# Manual\nIntro.\n## Capítulo 1\nTexto um.\n## Capítulo 2\nTexto dois.\n"
    assert [r for r, _ in cortar(md, "secao")] == ["Manual", "Capítulo 1", "Capítulo 2"]
    lei = "TÍTULO I\nDisposições.\nCAPÍTULO II - Do Imposto\nTexto.\n"
    assert [r for r, _ in cortar(lei, "secao")] == ["TÍTULO I", "CAPÍTULO II - Do Imposto"]
    assert [r for r, _ in cortar("pág um\n\f\npág dois\n\f\n\n", "pagina")] == ["página 1", "página 2"]
    assert cortar("sem marca nenhuma", "sumula") == [("parágrafo 1", "sem marca nenhuma")]
