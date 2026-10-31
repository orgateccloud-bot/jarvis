"""Painel fiscal, dados do cliente: adaptadores, precedência, fonte por campo, falha de fonte e PII fora do log.

Todos os dados são fictícios (o repositório é público): CNPJ 11.222.333/0001-81 e CPF 123.456.789-09 são exemplos.
"""

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from loguru import logger

from jarvis.painel.clientes import FonteQuebrada, montar_servico
from jarvis.painel.clientes.banco import BancoClientes
from jarvis.painel.clientes.base import FonteCliente, mascarado, para_log
from jarvis.painel.clientes.erp import ErpClientes
from jarvis.painel.clientes.planilha import PlanilhaClientes
from jarvis.painel.clientes.portais import PortaisClientes
from jarvis.painel.clientes.servico import ServicoClientes
from jarvis.painel.contratos import Certidao, ClienteEntrada, Contrato, Pendencia
from jarvis.painel.http import FonteIndisponivel

CNPJ = "11.222.333/0001-81"
DOC = "11222333000181"
AGORA = datetime(2026, 10, 31, 9, 0)

CSV = (
    "CNPJ;Razão Social;Regime;CNAE;Estados;Obrigações;Contato;E-mail;Honorário;Vencimento;"
    "Certidão;Certidão situação;Certidão validade\n"
    f"{CNPJ};Alfa Comércio Ltda (planilha);Lucro Presumido;4711-3/02;GO|TO;EFD-Contribuições|DCTFWeb;Maria;"
    "maria@exemplo.com;1.500,00;10;CND estadual GO;Negativa;30/11/2026\n"
    "98.765.432/0001-98;Beta Serviços;Simples Nacional;;GO;DAS;;;;;;;\n"
)


def entrada(**kw):
    base = {"documento": CNPJ, "razao_social": "Alfa Comércio Ltda", "regime_tributario": "lucro_presumido",
            "obrigacoes": ["EFD-Contribuições", "DCTFWeb", "ECD"], "ufs_operacao": ["GO"], "contato_nome": "João",
            "certidoes": [Certidao(tipo="CND federal", situacao="negativa", validade=date(2026, 12, 20))],
            "contratos": [Contrato(descricao="Assessoria contábil", honorario_mensal=1800.0, vencimento_dia=5)],
            "pendencias": [Pendencia(descricao="Enviar extratos", prazo=date(2026, 11, 5))]}
    return ClienteEntrada(**{**base, **kw})


class FonteFalsa(FonteCliente):
    def __init__(self, id_, nome, dados=None, erro=None):
        self.id, self.nome, self.dados, self.erro = id_, nome, dados or {}, erro

    def buscar(self, doc):
        if self.erro:
            raise FonteIndisponivel(self.erro)
        return self.dados.get(doc)


def servico(tmp_path, *outras):
    return ServicoClientes(BancoClientes(tmp_path / "j.db", relogio=lambda: AGORA), list(outras), salt="s",
                           relogio=lambda: AGORA)


# ── adaptadores ──────────────────────────────────────────────
def test_banco_salva_e_devolve_os_campos_canonicos(tmp_path):
    banco = BancoClientes(tmp_path / "j.db", relogio=lambda: AGORA)
    cid = banco.salvar(entrada())
    assert banco.salvar(entrada(razao_social="Alfa Comércio S.A.")) == cid       # mesmo documento: atualiza
    dados = banco.buscar(CNPJ)
    assert dados["razao_social"] == "Alfa Comércio S.A." and dados["obrigacoes"][0] == "EFD-Contribuições"
    assert dados["certidoes"] == [{"tipo": "CND federal", "situacao": "negativa", "validade": "2026-12-20",
                                   "observacao": None}]
    assert dados["contratos"][0]["honorario_mensal"] == 1800.0 and dados["contato"] == {"nome": "João"}
    assert banco.indice() == [(cid, DOC, "Alfa Comércio S.A.")]


def test_planilha_csv_ptbr(tmp_path):
    arq = tmp_path / "clientes.csv"
    arq.write_text(CSV, encoding="utf-8-sig")
    p = PlanilhaClientes(caminho=arq)
    assert {c["razao_social"] for c in p.listar()} == {"Alfa Comércio Ltda (planilha)", "Beta Serviços"}
    d = p.buscar(DOC)
    assert d["regime_tributario"] == "lucro_presumido" and d["ufs_operacao"] == ["GO", "TO"]
    assert d["obrigacoes"] == ["EFD-Contribuições", "DCTFWeb"] and d["contato"]["email"] == "maria@exemplo.com"
    assert d["contratos"][0]["honorario_mensal"] == 1500.0 and d["contratos"][0]["vencimento_dia"] == 10
    assert d["certidoes"][0] == {"tipo": "CND estadual GO", "situacao": "negativa", "validade": "2026-11-30"}
    assert p.buscar("00000000000000") is None and p.nome == "planilha clientes.csv"


def test_planilha_do_google_sheets_pela_url(tmp_path):
    url = "https://docs.google.com/spreadsheets/d/x/export?format=csv"
    p = PlanilhaClientes(url=url, fetch=lambda u: CSV.replace(";", ",").replace("|", "|") if u == url else "")
    assert p.buscar(DOC)["razao_social"] == "Alfa Comércio Ltda (planilha)" and p.nome == "Google Sheets"


def test_planilha_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    for linha in [lin.split(";") for lin in CSV.strip().splitlines()]:
        wb.active.append(linha)
    wb.save(tmp_path / "clientes.xlsx")
    assert PlanilhaClientes(caminho=tmp_path / "clientes.xlsx").buscar(DOC)["ufs_operacao"] == ["GO", "TO"]


def test_planilha_ausente_e_fonte_indisponivel(tmp_path):
    with pytest.raises(FonteIndisponivel, match="não encontrada"):
        PlanilhaClientes(caminho=tmp_path / "nao.csv").buscar(DOC)


def test_erp_mapeia_campos_e_manda_o_token_so_no_cabecalho():
    chamadas = []

    def fetch(url, headers=None):
        chamadas.append((url, headers))
        if url.endswith("/clientes"):
            return json.dumps({"itens": [{"cnpj": DOC, "nome": "Alfa do ERP"}]})
        return json.dumps([{"cnpj": DOC, "nome": "Alfa do ERP", "fiscal": {"regime": "lucro_real"}}])

    formato = {"caminho_lista": "/clientes", "lista_chave": "itens", "campo_documento": "cnpj",
               "caminho_busca": "/clientes?cnpj={documento}",
               "campos": {"razao_social": "nome", "regime_tributario": "fiscal.regime"}}
    erp = ErpClientes("https://erp.exemplo.com/api", "segredo-123", formato, fetch)
    assert erp.listar() == [{"documento": DOC, "razao_social": "Alfa do ERP"}]
    assert erp.buscar(CNPJ) == {"razao_social": "Alfa do ERP", "regime_tributario": "lucro_real"}
    assert all("segredo-123" not in url and h["Authorization"] == "Bearer segredo-123" for url, h in chamadas)
    with pytest.raises(ValueError, match="https"):
        ErpClientes("http://erp.local", "t", formato, fetch)


def _serpro_falso(dados=None, falha=False):
    class SerproError(Exception): ...
    class SerproNaoEncontrado(SerproError): ...
    class SerproConfigError(SerproError): ...

    class SerproClient:
        def __init__(self, consumer_key=None, consumer_secret=None, audit_salt=None):
            if not consumer_key:
                raise SerproConfigError("sem credencial")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def consultar_cnpj(self, doc):
            if falha:   # o erro real do SERPRO poderia citar o documento; o adaptador não repassa a mensagem
                raise SerproError(f"falha ao consultar {doc}")
            return SimpleNamespace(dados=dados)

    return SimpleNamespace(SerproClient=SerproClient, SerproError=SerproError, SerproNaoEncontrado=SerproNaoEncontrado)


def test_portais_serpro_mapeia_cnpj_e_nao_consulta_cpf():
    mod = _serpro_falso({"razao_social": "ALFA COMERCIO LTDA", "situacao_descricao": "ATIVA",
                         "cnae_principal": "Comércio varejista", "endereco": {"uf": "GO"}})
    p = PortaisClientes(mod, env={"SERPRO_CONSUMER_KEY": "k", "SERPRO_CONSUMER_SECRET": "s"})
    assert p.buscar(CNPJ) == {"razao_social": "ALFA COMERCIO LTDA", "situacao_cadastral": "ATIVA",
                              "cnae_principal": "Comércio varejista", "uf_sede": "GO"}
    assert p.buscar("123.456.789-09") is None                                    # CPF: não consulta
    with pytest.raises(FonteIndisponivel, match="sem credencial"):
        PortaisClientes(mod, env={}).buscar(CNPJ)
    with pytest.raises(FonteIndisponivel, match="não configurado"):
        PortaisClientes.certidoes(CNPJ)


def test_portais_nao_vaza_o_documento_no_erro():
    p = PortaisClientes(_serpro_falso(falha=True), env={"SERPRO_CONSUMER_KEY": "k"})
    with pytest.raises(FonteIndisponivel) as e:
        p.buscar(CNPJ)
    assert DOC not in str(e.value)


# ── consolidação ─────────────────────────────────────────────
def test_precedencia_fonte_por_campo_e_conflito(tmp_path):
    portais = FonteFalsa("portais", "SERPRO", {DOC: {"razao_social": "ALFA COMERCIO LTDA", "situacao_cadastral": "ATIVA",
                                                    "regime_tributario": "simples"}})
    planilha = FonteFalsa("planilha", "planilha clientes.csv", {DOC: {"razao_social": "Alfa (planilha)",
                                                                       "obrigacoes": ["DAS"]}})
    s = servico(tmp_path, portais, planilha)
    cid = s.banco.salvar(entrada())
    s.atualizar()
    c = s.consolidar(cid)
    assert c.campos["razao_social"].valor == "ALFA COMERCIO LTDA" and c.campos["razao_social"].fonte == "portais"
    assert c.campos["regime_tributario"].valor == "lucro_presumido" and c.campos["regime_tributario"].fonte == "banco"
    assert c.campos["obrigacoes"].fonte == "banco" and c.campos["situacao_cadastral"].fonte_nome == "SERPRO"
    assert c.campos["contratos"].fonte == "banco" and c.campos["documento"].valor == DOC
    conflitos = {x.campo: x.valores for x in c.conflitos}
    assert set(conflitos["razao_social"]) == {"portais", "banco", "planilha"}
    assert conflitos["regime_tributario"] == {"banco": "lucro_presumido", "portais": "simples"}


def test_cliente_so_da_planilha_entra_no_indice(tmp_path):
    arq = tmp_path / "clientes.csv"
    arq.write_text(CSV, encoding="utf-8")
    s = servico(tmp_path, PlanilhaClientes(caminho=arq))
    s.atualizar()
    nomes = {c.nome: c for c in s.listar()}
    assert "Beta Serviços" in nomes and nomes["Beta Serviços"].documento_mascarado == "98.***.***/0001-**"
    beta = s.consolidar(nomes["Beta Serviços"].id)
    assert beta.campos["regime_tributario"].valor == "simples" and beta.campos["regime_tributario"].fonte == "planilha"


def test_fonte_que_falha_mantem_os_ultimos_dados_marcados_e_sem_pii_no_log(tmp_path):
    erp = FonteFalsa("erp", "ERP (API)", {DOC: {"situacao_cadastral": "ATIVA", "cnae_principal": "4711-3/02"}})
    s = servico(tmp_path, erp)
    cid = s.banco.salvar(entrada())
    s.atualizar()
    assert s.consolidar(cid).campos["cnae_principal"].antigo is False

    erp.erro = "ERP fora do ar"
    mensagens = []
    sink = logger.add(lambda m: mensagens.append(str(m)), level="DEBUG")
    try:
        status = {st.id: st for st in s.atualizar()}
    finally:
        logger.remove(sink)
    c = s.consolidar(cid)
    assert c.campos["cnae_principal"].valor == "4711-3/02" and c.campos["cnae_principal"].antigo is True
    assert status["cliente_erp"].ok is False and "fora do ar" in status["cliente_erp"].erro
    assert status["cliente_erp"].ultimo_sucesso is not None
    log = "".join(mensagens)
    assert "erp falhou" in log and DOC not in log and CNPJ not in log and para_log(DOC, "s") in log


def test_cliente_inexistente(tmp_path):
    assert servico(tmp_path).consolidar(999) is None


def test_mascaras():
    assert mascarado(CNPJ) == "11.***.***/0001-**"
    assert mascarado("123.456.789-09") == "***.***.***-**"
    assert DOC not in para_log(DOC) and "#" in para_log(DOC)


def test_montar_servico_pela_configuracao(settings, tmp_path):
    arq = tmp_path / "c.csv"
    arq.write_text(CSV, encoding="utf-8")
    s = montar_servico(settings, env={"JARVIS_CLIENTES_PLANILHA": str(arq), "JARVIS_ERP_URL": "http://inseguro",
                                      "JARVIS_ERP_TOKEN": "t", "JARVIS_SERPRO_CLIENTE": str(tmp_path / "nao.py")})
    tipos = {f.id: f for f in s.outras}
    assert isinstance(tipos["planilha"], PlanilhaClientes)
    assert isinstance(tipos["erp"], FonteQuebrada) and "https" in tipos["erp"].erro
    assert isinstance(tipos["portais"], FonteQuebrada) and "não encontrado" in tipos["portais"].erro
    assert montar_servico(settings, env={}).outras == []                       # só o banco, por padrão
