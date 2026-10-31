import io
import zipfile
from datetime import date
from email.message import Message

import pytest

from jarvis.conhecimento.base import KnowledgeBase
from jarvis.conhecimento.catalogo import carregar_catalogos
from jarvis.conhecimento.coleta import FalhaColeta, Http, RecusaColeta, atualizar
from jarvis.conhecimento.documento import ler_cabecalho

LEI = "<html><body>" + "".join(f"<p>Art. {i}º Texto do artigo {i}.</p>" for i in range(1, 12)) + "</body></html>"


class Resp:
    def __init__(self, url, corpo, tipo="text/html; charset=utf-8", tamanho=None):
        self.url, self.corpo = url, corpo
        self.headers = Message()
        self.headers["Content-Type"] = tipo
        if tamanho is not None:
            self.headers["Content-Length"] = str(tamanho)

    def read(self, n=-1):
        return self.corpo[:n] if n >= 0 else self.corpo

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Web:
    """Internet falsa: url → bytes (ou exceção, ou lista de respostas em sequência)."""

    def __init__(self, paginas):
        self.paginas, self.pedidos, self.esperas, self.t = paginas, [], [], 0.0

    def abrir(self, req, timeout):
        self.pedidos.append(req.full_url)
        assert req.headers["User-agent"].startswith("JARVIS-conhecimento/")
        item = self.paginas[req.full_url]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, Resp) else Resp(req.full_url, item.encode() if isinstance(item, str) else item)

    def http(self, **kw):
        def dormir(s):
            self.esperas.append(round(s, 1))
            self.t += s
        return Http(abrir=self.abrir, relogio=lambda: self.t, dormir=dormir, **kw)


def base_com(tmp_path, fontes_toml, dominios='["planalto.gov.br", "stf.jus.br", "stj.jus.br"]'):
    root = tmp_path / "base"
    (root / "_catalogo").mkdir(parents=True)
    (root / "_catalogo" / "01.toml").write_text(f"""
[biblioteca]
id = "juridico"
nome = "Jurídico"
area = "juridico"
versao_catalogo = 1
atualizado_em = "2026-10-31"
[seguranca]
dominios = {dominios}
{fontes_toml}""", encoding="utf-8")
    return root


def fonte(fid, url, adaptador="html_simples", corte="artigo", situacao="aprovado", tipo="lei", extra=""):
    return f"""
[[fonte]]
id = "{fid}"
titulo = "Fonte {fid}"
tipo = "{tipo}"
esfera = "federal"
uf = "BR"
url = "{url}"
adaptador = "{adaptador}"
situacao = "{situacao}"
prioridade = 1
frequencia = "mensal"
corte = "{corte}"
{extra}
"""


URL = "https://www.planalto.gov.br/ccivil_03/leis/l1.htm"


def test_versoes_relatorio_e_busca_de_ponta_a_ponta(tmp_path):
    root = base_com(tmp_path, fonte("lei-1", URL))
    web = Web({URL: [LEI, LEI, LEI.replace("Texto do artigo 3.", "Texto NOVO do artigo 3.")]})
    carga = carregar_catalogos(root / "_catalogo")
    r1 = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert r1.novos == ["lei-1: juridico/lei-1.md"]
    cab, _ = ler_cabecalho((root / "juridico" / "lei-1.md").read_text(encoding="utf-8"))
    assert (cab.fonte_id, cab.biblioteca, cab.situacao, cab.vigencia, cab.baixado_em) == \
        ("lei-1", "juridico", "vigente", "01/10/2026 a", "01/10/2026") and len(cab.hash) == 64
    r2 = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 11, 5))
    assert r2.sem_mudanca == ["lei-1: juridico/lei-1.md"] and not (root / "_versoes").exists()
    r3 = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 12, 10))
    assert r3.alterados == ["lei-1: versão anterior em _versoes/lei-1/2026-10-01.md"]
    velha, _ = ler_cabecalho((root / "_versoes" / "lei-1" / "2026-10-01.md").read_text(encoding="utf-8"))
    assert velha.vigencia == "01/10/2026 a 10/12/2026" and velha.situacao == "histórico"
    relatorio = (root / "_relatorios" / "2026-12-10.md").read_text(encoding="utf-8")
    assert "- Alterados (1)" in relatorio and "- Falhas (0)" in relatorio
    kb = KnowledgeBase(root)
    assert "NOVO" in kb.buscar("texto do artigo 3")[0][1].texto
    antigo = kb.buscar("texto do artigo 3", vigente_em=date(2026, 11, 1))[0][1]
    assert "NOVO" not in antigo.texto and antigo.situacao == "histórico"


def test_so_aprovada_e_baixada_e_dentro_da_frequencia_fica_em_dia(tmp_path):
    root = base_com(tmp_path, fonte("lei-1", URL) + fonte("cpc", URL.replace("l1", "cpc"), situacao="proposto"))
    web = Web({URL: LEI})
    carga = carregar_catalogos(root / "_catalogo")
    r = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert r.nao_aprovadas == ["cpc"] and web.pedidos == [URL]
    r = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 20))
    assert r.em_dia == ["lei-1"] and web.pedidos == [URL]                   # mensal: nada a fazer em 19 dias
    r = atualizar(root, carga, fonte="cpc", http_cliente=web.http(), hoje=date(2026, 10, 20))
    assert "só fonte aprovada é baixada" in r.avisos[0] and not (root / "juridico" / "cpc.md").exists()


def test_seco_nao_grava(tmp_path):
    root = base_com(tmp_path, fonte("lei-1", URL))
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), seco=True, http_cliente=Web({URL: LEI}).http(),
                  hoje=date(2026, 10, 1))
    assert r.novos == ["lei-1: juridico/lei-1.md"] and not (root / "juridico").exists()


def test_dominio_fora_da_lista_e_recusado_sem_requisicao(tmp_path):
    root = base_com(tmp_path, fonte("blog", "https://blog-de-terceiro.com/lei.htm"))
    web = Web({})
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert r.recusados and "domínio fora da lista" in r.recusados[0] and web.pedidos == []
    assert "Recusados (segurança) (1)" in (root / "_relatorios" / "2026-10-01.md").read_text(encoding="utf-8")


def test_redirecionamento_e_tamanho_sao_conferidos():
    web = Web({URL: Resp("https://mal.com/x", b"oi"),
               URL + "?g": Resp(URL, b"x", tamanho=60 * 2**20),
               URL + "?m": Resp(URL, b"x" * 101)})
    with pytest.raises(RecusaColeta, match="fora da lista"):
        web.http().baixar(URL, ["planalto.gov.br"])
    with pytest.raises(RecusaColeta, match="maior que 50 MB"):
        web.http().baixar(URL + "?g", ["planalto.gov.br"])
    with pytest.raises(RecusaColeta, match="maior que"):
        web.http(limite=100).baixar(URL + "?m", ["planalto.gov.br"])


def test_tres_tentativas_e_ritmo_de_2s_por_dominio():
    web = Web({URL: [ConnectionResetError("caiu"), ConnectionResetError("caiu"), LEI],
               URL + "?b": LEI, URL + "?x": [ConnectionResetError("1"), ConnectionResetError("2"),
                                             ConnectionResetError("3")]})
    http = web.http()
    assert b"Art. 11" in http.baixar(URL, ["planalto.gov.br"]).conteudo
    assert web.esperas == [2.0, 4.0]                       # espera entre tentativas (2 s, 4 s)
    http.baixar(URL + "?b", ["planalto.gov.br"])
    assert web.esperas[-1] == 2.0                          # mesmo domínio: 1 requisição a cada 2 s
    with pytest.raises(FalhaColeta, match="após 3 tentativas"):
        http.baixar(URL + "?x", ["planalto.gov.br"])


def test_site_recusou_usa_a_pagina_salva_pelo_senhor(tmp_path):
    root = base_com(tmp_path, fonte("lei-1", URL))
    web = Web({URL: [ConnectionResetError("RemoteDisconnected")] * 3})
    carga = carregar_catalogos(root / "_catalogo")
    r = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert "salve a página pelo navegador em _entrada/lei-1.htm" in r.falhas[0]
    (root / "_entrada").mkdir()
    (root / "_entrada" / "lei-1.htm").write_text(LEI, encoding="cp1252")
    web.paginas[URL] = [ConnectionResetError("RemoteDisconnected")] * 3
    r = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert r.novos and any("_entrada/lei-1.htm" in a for a in r.avisos)
    assert "Art. 11º" in (root / "juridico" / "lei-1.md").read_text(encoding="utf-8")


def test_manual_aguarda_o_arquivo(tmp_path):
    root = base_com(tmp_path, fonte("prova", "", adaptador="manual", corte="pagina", tipo="prova"))
    carga = carregar_catalogos(root / "_catalogo")
    assert "salve o arquivo em _entrada/prova.htm" in atualizar(root, carga, hoje=date(2026, 10, 1)).aguardando[0]


INDICE = """<a href="sumariosumulas.asp?base=26&sumula=1209">Súmula Vinculante 8</a>
<a href="sumariosumulas.asp?base=26&sumula=1210">Súmula Vinculante 9 (cance\u200blada)</a>
<a href="/outra/pagina.asp">Notícias</a>"""
PAGINA = "<div>menu</div><p>Aplicação das Súmulas no STF</p><p>{}</p><p>Precedentes Representativos</p><p>x</p>"
SV = "https://portal.stf.jus.br/jurisprudencia/sumariosumulas.asp?base=26"


def test_lista_links_marca_situacao_e_recorta(tmp_path):
    extra = ('padrao_links = "sumula=\\\\d+"\n'
             'padrao_rotulo = "^(?P<nome>Súmula Vinculante \\\\d+)(?: \\\\((?P<situacao>[^)]+)\\\\))?"\n'
             'inicio = "Aplicação das Súmulas no STF"\nfim = "Precedentes Representativos"')
    root = base_com(tmp_path, fonte("sv-stf", SV, adaptador="lista_links", corte="sumula", tipo="sumula",
                                    extra=extra))
    web = Web({SV: INDICE, SV + "&sumula=1209": PAGINA.format("Prescrição e decadência do crédito tributário."),
               SV + "&sumula=1210": PAGINA.format("Execução penal, art. 127.")})
    carga = carregar_catalogos(root / "_catalogo")
    seco = atualizar(root, carga, seco=True, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert "2 itens no índice" in seco.sem_mudanca[0] and web.pedidos == [SV]
    r = atualizar(root, carga, http_cliente=web.http(), hoje=date(2026, 10, 1))
    assert r.novos == ["sv-stf: juridico/sv-stf.md (2 itens)"]
    texto = (root / "juridico" / "sv-stf.md").read_text(encoding="utf-8")
    assert "### Súmula Vinculante 9\nSituação: cancelada\nURL: " in texto and "menu" not in texto
    kb = KnowledgeBase(root)
    _, sv8 = kb.buscar("súmula vinculante 8 decadência tributária")[0]
    assert sv8.rotulo == "Súmula Vinculante 8" and sv8.situacao == "vigente" and sv8.url.endswith("sumula=1209")
    assert kb.buscar("execução penal")[0][1].situacao == "cancelada"


def test_recorte_com_varios_marcadores_de_fim():
    from jarvis.conhecimento.adaptadores import recortar
    from jarvis.conhecimento.catalogo import FonteCatalogo
    f = FonteCatalogo(id="x", titulo="x", tipo="sumula", esfera="federal", uf="BR", adaptador="manual",
                      situacao="proposto", prioridade=1, frequencia="mensal", corte="sumula", inicio="INÍCIO",
                      fim=["Para informações adicionais", "Mapa do Site"])
    avisos = []
    assert recortar("menu INÍCIO SV 30 pendente. Mapa do Site rodapé", f, avisos) == "SV 30 pendente."
    assert recortar("INÍCIO a Para informações adicionais b Mapa do Site", f, avisos) == "a" and avisos == []


CSV = ("sequencialPrecedente,tipoPrecedente,numeroPrecedente,situacao,dataJulgamento,teseFirmada\n"
       '1,Tema,1001,Trânsito em Julgado,2020-05-10,"A tese, com vírgula."\n'
       "2,Controvérsia,9,Cancelada,,x\n"
       "3,IAC,5,Cancelado,2019-01-01,Tese do IAC.\n"
       '4,Tema,1002,Afetado,,"Definir se o termo ""insumo"" alcança\nfrete, em duas linhas."\n')
TEMAS = "https://dadosabertos.web.stj.jus.br/dataset/x/temas.csv"


def test_tabela_csv_com_filtro_e_modelos(tmp_path):
    extra = ('formato = "csv"\nfiltro = { tipoPrecedente = ["Tema", "IAC"] }\n'
             'colunas = { rotulo = "{tipoPrecedente} {numeroPrecedente}", texto = ["Tese firmada=teseFirmada"], '
             'situacao = "situacao", data = "dataJulgamento", url = "https://stj.jus.br/tema/{numeroPrecedente}" }')
    root = base_com(tmp_path, fonte("rep-stj", TEMAS, adaptador="tabela", corte="ementa", tipo="precedente",
                                    extra=extra))
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), http_cliente=Web({TEMAS: CSV}).http(),
                  hoje=date(2026, 10, 1))
    assert r.novos == ["rep-stj: juridico/rep-stj.md (3 itens)"]
    texto = (root / "juridico" / "rep-stj.md").read_text(encoding="utf-8")
    assert "### Tema 1001\nSituação: Trânsito em Julgado\nData: 2020-05-10\nURL: https://stj.jus.br/tema/1001\n" \
           "Tese firmada: A tese, com vírgula." in texto and "Controvérsia" not in texto
    assert 'Tese firmada: Definir se o termo "insumo" alcança\nfrete, em duas linhas.' in texto   # "" = aspas
    assert KnowledgeBase(root).buscar("tese do IAC")[0][1].situacao == "Cancelado"


RG = ("<html><body><table border='2'><thead><tr><th>Tema</th><th>Título</th><th>Situação do Tema</th>"
      "<th>Tese</th></tr></thead><tr><td>0008</td><td>Imunidade do lucro da exportação à CSLL.</td>"
      "<td>Trânsito em Julgado</td><td>A CSLL incide sobre o lucro das exportações.</td></tr>"
      "<tr><td>0010</td><td>Tema cancelado.</td><td>Cancelado</td><td></td></tr></table></body></html>")
RG_URL = "https://portal.stf.jus.br/jurisprudenciaRepercussao/exportarDados.asp"


def test_tabela_html_tira_zeros_e_marca_cancelado(tmp_path):
    extra = ('formato = "html"\ncolunas = { rotulo = "Tema {Tema} (repercussão geral)", texto = ["Título", '
             '"Tese=Tese"], situacao = "Situação do Tema", url = "https://portal.stf.jus.br/t?n={Tema}" }')
    root = base_com(tmp_path, fonte("rg-stf", RG_URL, adaptador="tabela", corte="ementa", tipo="precedente",
                                    extra=extra))
    r = atualizar(root, carregar_catalogos(root / "_catalogo"),
                  http_cliente=Web({RG_URL: Resp(RG_URL, RG.encode(), "application / vnd.ms-excel; Charset=UTF-8")})
                  .http(), hoje=date(2026, 10, 1))
    assert r.novos == ["rg-stf: juridico/rg-stf.md (2 itens)"]
    kb = KnowledgeBase(root)
    _, t8 = kb.buscar("tema 8 repercussão geral CSLL exportação")[0]
    assert t8.rotulo == "Tema 8 (repercussão geral)" and "Tese: A CSLL incide" in t8.texto
    assert t8.url == "https://portal.stf.jus.br/t?n=0008" and t8.situacao == "Trânsito em Julgado"
    assert "não use como norma vigente" in kb.buscar("tema cancelado")[0][1].aviso


SUMULAS_PDF = ("Súmulas do STJ\n●SÚMULA 673 VEJA MAIS\nTexto da súmula 673 sobre tributo. (PRIMEIRA SEÇÃO,\n"
               "julgado em 11/9/2024)\n(SÚMULA 650, PRIMEIRA SEÇÃO, julgado em 22/09/2021)\n"
               "●SÚMULA 603 (SÚMULA CANCELADA) VEJA MAIS\nTexto antigo cancelado.\n")


def test_padrao_item_marca_sumulas_em_texto_corrido(tmp_path):
    """Formato real do PDF de súmulas do STJ (conferido em 31/10/2026) e a regex do catálogo 01."""
    padrao = (r"padrao_item = '^●?\s*(?P<nome>S[ÚU]MULA \d+)\s*(?:\((?:S[ÚU]MULA\s+)?(?P<situacao>[A-ZÇÃÕÉÍ ]+)\))?"
              r"\s*VEJA MAIS\s*$'")
    root = base_com(tmp_path, fonte("sumulas-stj", "", adaptador="manual", corte="sumula", tipo="sumula",
                                    extra=padrao))
    (root / "_entrada").mkdir()
    (root / "_entrada" / "sumulas-stj.txt").write_text(SUMULAS_PDF, encoding="utf-8")
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), hoje=date(2026, 10, 1))
    assert r.novos == ["sumulas-stj: juridico/sumulas-stj.md (2 itens)"]
    kb = KnowledgeBase(root)
    _, s = kb.buscar("súmula 673")[0]
    assert s.rotulo == "SÚMULA 673" and s.situacao == "vigente" and "(SÚMULA 650" in s.texto   # citação não abre item
    _, c = kb.buscar("súmula 603 do STJ")[0]
    assert c.rotulo == "SÚMULA 603" and c.situacao == "CANCELADA" and "não use como norma vigente" in c.aviso


def _zip(arquivos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return buf.getvalue()


@pytest.mark.parametrize("arquivos, motivo", [
    ({"../fora.txt": "x"}, "caminho perigoso"),
    ({"/etc/passwd": "x"}, "caminho perigoso"),
    ({"C:/Windows/x.txt": "x"}, "caminho perigoso"),
    ({"leia.txt": "ok", "setup.exe": "MZ"}, "executável"),
], ids=["ponto-ponto", "absoluto", "drive", "exe"])
def test_zip_malicioso_e_recusado(tmp_path, arquivos, motivo):
    url = "https://www.planalto.gov.br/pacote.zip"
    root = base_com(tmp_path, fonte("pacote", url, adaptador="zip", corte="secao", tipo="manual"))
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), http_cliente=Web({url: _zip(arquivos)}).http(),
                  hoje=date(2026, 10, 1))
    assert r.recusados and motivo in r.recusados[0] and not (root / "juridico").exists()


def test_zip_bomba_e_recusado(tmp_path, monkeypatch):
    from jarvis.conhecimento import adaptadores
    monkeypatch.setattr(adaptadores, "LIMITE_ZIP", 1000)
    url = "https://www.planalto.gov.br/pacote.zip"
    root = base_com(tmp_path, fonte("pacote", url, adaptador="zip", corte="secao", tipo="manual"))
    bomba = _zip({"a.txt": "0" * 5000})
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), http_cliente=Web({url: bomba}).http(),
                  hoje=date(2026, 10, 1))
    assert "passaria de" in r.recusados[0]
    bom = _zip({"manual/cap1.md": "# Cap 1\nTexto um.", "manual/cap2.txt": "Texto dois."})
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), http_cliente=Web({url: bom}).http(),
                  hoje=date(2026, 10, 1))
    assert r.novos == ["pacote: juridico/pacote.md (2 itens)"]


def test_pasta_local_interna_mascara_pii(tmp_path):
    origem = tmp_path / "modelos"
    origem.mkdir()
    (origem / "procuracao.txt").write_text("Outorgante: Maria Souza, CPF 123.456.789-09, empresa "
                                           "12.345.678/0001-90.\n", encoding="utf-8")
    root = base_com(tmp_path, fonte("modelos", "", adaptador="pasta_local", corte="secao", tipo="modelo",
                                    extra=f'pasta = "{origem.as_posix()}"').replace('"federal"', '"interno"'))
    (root / "_catalogo" / "pii_nomes.txt").write_text("Maria Souza\n", encoding="utf-8")
    r = atualizar(root, carregar_catalogos(root / "_catalogo"), hoje=date(2026, 10, 1), salt="s")
    assert r.novos
    texto = (root / "juridico" / "modelos.md").read_text(encoding="utf-8")
    assert "123.456.789-09" not in texto and "12.345.678/0001-90" not in texto and "Maria Souza" not in texto
    assert "PESSOA_" in texto and "***.***.***-**" in texto
