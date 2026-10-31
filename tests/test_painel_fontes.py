"""Painel fiscal, fontes oficiais: parsing de recortes reais (31/10/2026). Todo item tem link https e data."""

from datetime import date
from pathlib import Path

import pytest

from jarvis.painel.contratos import ItemFiscal
from jarvis.painel.fontes import CONFIG_PADRAO, FonteConfig, carregar, coletor
from jarvis.painel.fontes.base import data_br, data_rss
from jarvis.painel.http import FonteIndisponivel, buscar

FIX = Path(__file__).parent / "fixtures" / "painel"
AGENDA = "https://www.gov.br/receitafederal/pt-br/assuntos/agenda-tributaria"


def ler(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8")


def fetch_de(mapa: dict[str, str]):
    """fetch falso: URL → conteúdo (prefixo também vale); o que não está no mapa é fonte fora do ar."""
    def fetch(url: str) -> str:
        for chave, conteudo in mapa.items():
            if url == chave or url.startswith(chave):
                return conteudo
        raise FonteIndisponivel(f"sem resposta: {url}")
    return fetch


def cfg(id_: str) -> FonteConfig:
    return next(f for f in carregar() if f.id == id_)


def verificavel(itens: list[ItemFiscal]):
    assert itens
    for i in itens:
        assert i.fonte_url.startswith("https://") and isinstance(i.data, date) and i.fonte_nome and i.id


def test_config_tem_todas_as_fontes_e_o_planalto_desligado():
    fontes = {f.id: f for f in carregar(CONFIG_PADRAO)}
    assert {"receita_agenda", "receita_noticias", "confaz", "cgibs", "sefaz_go", "sefaz_to", "marcos_reforma"} <= set(fontes)
    assert fontes["planalto"].ligada is False and "recusa" in fontes["planalto"].nota
    with pytest.raises(ValueError, match="não tem coletor"):
        coletor(fontes["planalto"])


def test_agenda_receita_le_declaracoes_e_agrupa_pagamentos():
    c = coletor(cfg("receita_agenda"))
    dia = ler("agenda_dia_15_10_2026.html")
    itens = c.itens_do_dia(dia, date(2026, 10, 15), f"{AGENDA}/2026/Outubro/dia-15-10-2026")
    verificavel(itens)
    titulos = [i.titulo for i in itens]
    assert "EFD-Contribuições (PJ)" in titulos                       # tabela de declarações
    efd = next(i for i in itens if i.titulo.startswith("EFD-Contribuições"))
    assert "Agosto/2026" in efd.detalhe and "1.252/2012" in efd.detalhe and efd.tipo_data == "vencimento"
    pag = next(i for i in itens if i.titulo == "Pagamento: IRRF")     # pagamentos agrupados por tributo
    assert "DARF" in pag.detalhe and "Lei" in pag.detalhe and "DARF" in pag.etiquetas


def test_agenda_receita_le_os_dias_do_mes_e_respeita_a_janela():
    c = coletor(cfg("receita_agenda"))
    base = f"{AGENDA}/2026/Novembro"
    dias = c.dias_do_mes(ler("agenda_mes_novembro_2026.html"), base)
    assert date(2026, 11, 13) in dias and date(2026, 11, 30) in dias        # inclusive o link "Dia%2013-11-2026"
    assert all(u.startswith("https://") for u in dias.values())
    dia = ler("agenda_dia_15_10_2026.html")
    fetch = fetch_de({
        f"{AGENDA}/2026/Novembro/": dia, f"{AGENDA}/2026/Dezembro/": dia,          # páginas dos dias
        base: ler("agenda_mes_novembro_2026.html"),
        f"{AGENDA}/2026/Dezembro": f'<a href="{AGENDA}/2026/Dezembro/dia-01-12-2026">1</a>',
    })
    c.dias = 20                                       # de 12/11 a 02/12: novembro e dezembro
    itens = c.coletar(fetch, date(2026, 11, 12))
    esperado = {date(2026, 11, d) for d in (13, 16, 19, 20, 23, 25, 30)} | {date(2026, 12, 1)}
    assert {i.data for i in itens} == esperado        # 05/11 e 10/11 já passaram


def test_agenda_sem_dias_e_fonte_indisponivel():
    c = coletor(cfg("receita_agenda"))
    with pytest.raises(FonteIndisponivel, match="mudado de formato"):
        c.coletar(fetch_de({AGENDA: "<html>sem calendário</html>"}), date(2026, 11, 12))


def test_rss_da_receita_descarta_paginas_que_nao_sao_noticia():
    c = coletor(cfg("receita_noticias"))
    c.palavras = []                                   # sem filtro de assunto: só o filtro de URL
    itens = c.coletar(fetch_de({c.url: ler("receita_noticias.rss")}), date(2026, 10, 31))
    verificavel(itens)
    for i in itens:
        assert not i.fonte_url.endswith(("/carrossel", "/colecao", ".png/view", "/todas-as-noticias"))
    assert any("DITR" in i.titulo for i in itens)
    assert itens == sorted(itens, key=lambda i: i.data, reverse=True)


def test_rss_filtra_por_assunto():
    c = coletor(cfg("receita_noticias"))
    itens = c.coletar(fetch_de({c.url: ler("receita_noticias.rss")}), date(2026, 10, 31))
    assert all("leilao" not in i.fonte_url for i in itens)    # "parada do sistema de leilão" não é assunto fiscal
    assert any("DITR" in i.titulo for i in itens)


def test_rss_2_do_wordpress_da_economia_go():
    c = coletor(cfg("sefaz_go"))
    c.palavras = []
    itens = c.coletar(fetch_de({c.url: ler("economia_go.rss")}), date(2026, 10, 31))
    verificavel(itens)
    assert any("Negocie" in i.titulo for i in itens) and itens[0].data == date(2026, 10, 29)


def test_confaz_pega_a_data_do_dou_na_pagina_do_convenio():
    c = coletor(cfg("confaz"))
    lista, item = ler("confaz_convenios_2026.html"), ler("confaz_cv121_26.html")
    fetch = fetch_de({f"{c.url}/2026/CV": item, f"{c.url}/2026": lista})
    itens = c.coletar(fetch, date(2026, 10, 31))
    verificavel(itens)
    assert itens[0].titulo.startswith("CONVÊNIO ICMS") and itens[0].data == date(2026, 10, 14)
    assert itens[0].detalhe                                              # ementa vem do title do link
    sem_data = fetch_de({f"{c.url}/2026/CV": "<div>sem data</div>", f"{c.url}/2026": lista})
    assert coletor(cfg("confaz")).coletar(sem_data, date(2026, 10, 31)) == []   # sem data verificável não entra


def test_cgibs_resolucoes_com_pdf_ementa_e_data():
    c = coletor(cfg("cgibs"))
    itens = c.coletar(fetch_de({c.url: ler("cgibs_resolucoes.html")}), date(2026, 10, 31))
    verificavel(itens)
    assert all(i.fonte_url.endswith(".pdf") for i in itens)
    assert len({i.fonte_url for i in itens}) == len(itens)                # o mesmo PDF não se repete
    assert any("RESOLUÇÃO CGIBS" in i.titulo.upper() for i in itens)


def test_sefaz_to_cartoes_de_noticia():
    c = coletor(cfg("sefaz_to"))
    itens = c.coletar(fetch_de({c.url: ler("sefaz_to_noticias.html")}), date(2026, 10, 31))
    verificavel(itens)
    assert itens[0].data == date(2026, 10, 29) and "IPVA" in itens[0].titulo


def test_marcos_da_reforma_tem_link_oficial_e_data_do_ato():
    itens = coletor(cfg("marcos_reforma")).coletar(fetch_de({}), date(2026, 10, 31))
    verificavel(itens)
    assert {i.titulo.split(" –")[0] for i in itens} == {"EC 132/2023", "LC 214/2025", "LC 227/2026"}
    assert all(i.tipo_data == "ato" and "planalto.gov.br" in i.fonte_url for i in itens)


def test_item_oficial_sem_link_https_nao_existe():
    with pytest.raises(ValueError):
        ItemFiscal(grupo="legislacao", titulo="x", data=date(2026, 1, 1), tipo_data="publicacao", fonte_id="f",
                   fonte_nome="F", fonte_url="http://inseguro")


def test_datas_brasileiras_e_do_rss():
    assert data_br("Publicado no DOU de 14.10.26") == date(2026, 10, 14)
    assert data_br("13 de março de 2026") == date(2026, 3, 13)
    assert data_rss("Thu, 29 Oct 2026 19:49:32 +0000") == date(2026, 10, 29)
    assert data_rss("2026-07-22T16:51:56Z") == date(2026, 7, 22)


def test_buscar_so_aceita_https():
    with pytest.raises(FonteIndisponivel, match="https"):
        buscar("http://www.gov.br")
