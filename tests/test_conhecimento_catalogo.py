from jarvis.conhecimento.catalogo import carregar_catalogos, dominio_permitido

CAB = """
[biblioteca]
id = "{bid}"
nome = "Teste"
area = "{area}"
descricao = "x"
versao_catalogo = 1
atualizado_em = "2026-10-30"

[seguranca]
dominios = ["planalto.gov.br", "*.sefaz.*.gov.br"]
"""

FONTE = """
[[fonte]]
id = "{fid}"
titulo = "Lei {fid}"
tipo = "lei"
esfera = "{esfera}"
uf = "BR"
url = "{url}"
adaptador = "html_simples"
situacao = "{situacao}"
prioridade = 1
frequencia = "mensal"
corte = "artigo"
obs = ""
"""


def catalogo(pasta, nome, bid="juridico", area="juridico", fontes=()):
    pasta.mkdir(exist_ok=True)
    texto = CAB.format(bid=bid, area=area)
    for f in fontes:
        texto += FONTE.format(**{"esfera": "federal", "url": "", "situacao": "proposto", **f})
    (pasta / nome).write_text(texto, encoding="utf-8")


def test_catalogo_valido_resolve_area_arquivo_e_fonte(tmp_path):
    catalogo(tmp_path, "01.toml", fontes=[{"fid": "ctn", "situacao": "aprovado",
                                            "url": "https://www.planalto.gov.br/ccivil_03/leis/l5172compilado.htm"},
                                           {"fid": "cpc"}])
    carga = carregar_catalogos(tmp_path)
    assert carga.erros == [] and [f.id for f in carga.fontes()] == ["ctn", "cpc"]
    assert carga.area_de("ctn") == "juridico" and carga.arquivo_de("ctn") == "juridico/ctn.md"
    assert carga.fonte_do_arquivo("juridico/cpc.md").id == "cpc" and carga.areas() == ["juridico"]


def test_erro_claro_sem_derrubar_o_resto(tmp_path):
    catalogo(tmp_path, "01.toml", fontes=[{"fid": "boa"}, {"fid": "ruim", "esfera": "galactica"},
                                           {"fid": "sem-https", "situacao": "aprovado", "url": "http://x.gov.br"}])
    catalogo(tmp_path, "02.toml", bid="outra", area="icms", fontes=[{"fid": "boa"}, {"fid": "icms-go"}])
    (tmp_path / "03.toml").write_text("[biblioteca\nid = ", encoding="utf-8")
    (tmp_path / "04.toml").write_text(CAB.format(bid="x", area="x") + "\n[extra]\na = 1\n", encoding="utf-8")
    carga = carregar_catalogos(tmp_path)
    assert [f.id for f in carga.fontes()] == ["boa", "icms-go"]
    texto = "\n".join(carga.erros)
    assert "01.toml: fonte 'ruim': esfera" in texto
    assert "01.toml: fonte 'sem-https'" in texto and "https" in texto
    assert "02.toml: fonte 'boa': id repetido (já existe em 01.toml)" in texto
    assert "03.toml: TOML inválido" in texto and "04.toml: seções desconhecidas: extra" in texto
    assert carga.areas() == ["icms", "juridico"]


def test_area_por_fonte_e_arquivo_antigo(tmp_path):
    catalogo(tmp_path, "01.toml", fontes=[{"fid": "ctn"}])
    texto = (tmp_path / "01.toml").read_text(encoding="utf-8")
    texto += 'area = "tributario"\narquivo = "tributario/ctn-lei-5172-1966.txt"\napelidos = ["ctn"]\n'
    (tmp_path / "01.toml").write_text(texto, encoding="utf-8")
    carga = carregar_catalogos(tmp_path)
    assert carga.area_de("ctn") == "tributario" and carga.areas() == ["juridico", "tributario"]
    assert carga.fonte_do_arquivo("tributario/ctn-lei-5172-1966.txt").apelidos == ["ctn"]


def test_arquivo_fora_da_base_e_recusado(tmp_path):
    for i, ruim in enumerate(["../fora.md", "C:/x.md", "_versoes/a.md"]):
        catalogo(tmp_path, "01.toml", fontes=[{"fid": "a"}])
        texto = (tmp_path / "01.toml").read_text(encoding="utf-8") + f'arquivo = "{ruim}"\n'
        (tmp_path / "01.toml").write_text(texto, encoding="utf-8")
        carga = carregar_catalogos(tmp_path)
        assert carga.fontes() == [] and "arquivo" in carga.erros[0], ruim


def test_pasta_sem_catalogo():
    from pathlib import Path
    carga = carregar_catalogos(Path("Z:/nao/existe"))
    assert carga.fontes() == [] and carga.erros == []


def test_dominios_permitidos():
    doms = ["planalto.gov.br", "stf.jus.br", "*.sefaz.*.gov.br"]
    assert dominio_permitido("https://www.planalto.gov.br/ccivil_03/x.htm", doms)
    assert dominio_permitido("https://portal.stf.jus.br/a", doms)
    assert dominio_permitido("https://www.sefaz.go.gov.br/a", doms)
    assert not dominio_permitido("http://www.planalto.gov.br/x", doms)         # só https
    assert not dominio_permitido("https://planalto.gov.br.mal.com/x", doms)    # sufixo de verdade
    assert not dominio_permitido("https://exemplo.com/x", doms)
    assert not dominio_permitido("https://stf.jus.br@mal.com/x", doms)         # host real é mal.com
