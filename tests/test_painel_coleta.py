"""Painel fiscal, coleta e montagem: fonte que falha mantém os últimos dados, sinaliza e registra; o card se monta."""

import asyncio
from datetime import date, datetime

from loguru import logger

from jarvis.painel import montagem
from jarvis.painel.coleta import ArmazemPainel, ServicoColeta, run_coleta
from jarvis.painel.contratos import CampoComFonte, ClienteConsolidado, ItemFiscal
from jarvis.painel.fontes import FonteConfig
from jarvis.painel.http import FonteIndisponivel
from tests.test_painel_fontes import fetch_de, ler

GO = "https://goias.gov.br/economia/feed/"
TO = "https://www.to.gov.br/sefaz/noticias"
AGORA = datetime(2026, 10, 31, 9, 0)


def fontes():
    return [FonteConfig(id="sefaz_go", tipo="rss", nome="Economia GO", url=GO),
            FonteConfig(id="sefaz_to", tipo="sefaz_to", nome="SEFAZ-TO", url=TO),
            FonteConfig(id="planalto", tipo="planalto", nome="Planalto", url="https://www.planalto.gov.br/",
                        ligada=False, nota="recusa coleta automática")]


class Rede:
    """fetch trocável: liga e desliga uma fonte entre coletas."""

    def __init__(self):
        self.mapa = {GO: ler("economia_go.rss"), TO: ler("sefaz_to_noticias.html")}

    def __call__(self, url):
        return fetch_de(self.mapa)(url)


def servico(tmp_path, rede=None):
    return ServicoColeta(ArmazemPainel(tmp_path / "j.db"), fontes(), fetch=rede or Rede(), relogio=lambda: AGORA)


def test_fonte_que_falha_mantem_os_ultimos_dados_e_sinaliza(tmp_path):
    rede = Rede()
    s = servico(tmp_path, rede)
    s.coletar()
    antes = [i for i in s.itens() if i.fonte_id == "sefaz_to"]
    assert antes

    del rede.mapa[TO]                                     # a SEFAZ-TO sai do ar
    mensagens = []
    sink = logger.add(lambda m: mensagens.append(m.record["message"]), level="WARNING")
    try:
        status = {st.id: st for st in s.coletar()}
    finally:
        logger.remove(sink)
    assert status["sefaz_to"].ok is False and "FonteIndisponivel" in status["sefaz_to"].erro
    assert status["sefaz_to"].ultimo_sucesso is not None                  # o último sucesso continua registrado
    assert status["sefaz_go"].ok is True                                  # uma fonte não derruba a outra
    assert [i.id for i in s.itens() if i.fonte_id == "sefaz_to"] == [i.id for i in antes]
    assert any("sefaz_to falhou" in m for m in mensagens)


def test_fonte_desligada_nao_e_coletada_e_mostra_a_nota(tmp_path):
    s = servico(tmp_path)
    status = {st.id: st for st in s.coletar()}
    assert status["planalto"].ligada is False and status["planalto"].ok is None
    assert "recusa" in status["planalto"].nota


def test_fonte_com_formato_novo_vira_erro_sem_quebrar(tmp_path):
    rede = Rede()
    rede.mapa[GO] = "<html>o portal mudou</html>"
    status = {st.id: st for st in servico(tmp_path, rede).coletar()}
    assert status["sefaz_go"].ok is False and "mudado de formato" in status["sefaz_go"].erro


def test_dados_sobrevivem_a_reinicio(tmp_path):
    servico(tmp_path).coletar()
    novo = ServicoColeta(ArmazemPainel(tmp_path / "j.db"), fontes(), fetch=fetch_de({}), relogio=lambda: AGORA)
    assert novo.itens()                                                   # sem rede: o que já tinha continua


async def test_laco_agendado_coleta_e_sobrevive_a_erro(tmp_path):
    chamadas = []

    class Falso:
        def coletar(self):
            chamadas.append(1)
            if len(chamadas) == 1:
                raise FonteIndisponivel("primeira falha")

    tarefa = asyncio.create_task(run_coleta(Falso(), intervalo_s=0.01, espera_inicial_s=0))
    while len(chamadas) < 3:
        await asyncio.sleep(0.01)
    tarefa.cancel()
    assert len(chamadas) >= 3                           # o laço seguiu depois da exceção


# ── montagem do card ─────────────────────────────────────────
def _item(grupo, titulo, d, tipo="vencimento", etiquetas=()):
    return ItemFiscal(grupo=grupo, titulo=titulo, data=d, tipo_data=tipo, fonte_id="f", fonte_nome="Fonte",
                      fonte_url="https://www.gov.br/x", etiquetas=list(etiquetas))


def _cliente(**campos):
    return ClienteConsolidado(id=7, gerado_em=AGORA, campos={
        k: CampoComFonte(valor=v, fonte="banco", fonte_nome="banco do JARVIS", atualizado_em=AGORA)
        for k, v in campos.items()})


def test_montagem_ordena_prazos_e_poe_os_marcos_no_fim():
    itens = [_item("prazos", "Pagamento: IRRF", date(2026, 11, 2), etiquetas=["IRRF"]),
             _item("prazos", "EFD-Contribuições (PJ)", date(2026, 11, 13), etiquetas=["EFD-Contribuições"]),
             _item("prazos", "DCTFWeb (PJ)", date(2026, 10, 15)),                       # já passou
             _item("legislacao", "Notícia nova", date(2026, 10, 30), "publicacao"),
             _item("legislacao", "LC 214/2025", date(2025, 1, 16), "ato")]
    p = montagem.montar(itens, [], None, AGORA)
    assert [i.titulo for i in p.grupos["prazos"]] == ["EFD-Contribuições (PJ)", "Pagamento: IRRF"]
    assert p.grupos["prazos"][1].severidade == "critico"                       # vence em 2 dias
    assert [i.titulo for i in p.grupos["legislacao"]] == ["Notícia nova", "LC 214/2025"]
    assert p.grupos["situacao"] == [] and p.cliente_id is None


def test_montagem_filtra_prazos_pelas_obrigacoes_do_cliente():
    itens = [_item("prazos", "EFD-Contribuições (PJ)", date(2026, 11, 13), etiquetas=["EFD-Contribuições"]),
             _item("prazos", "ECD (PJ)", date(2026, 11, 20), etiquetas=["ECD"])]
    p = montagem.montar(itens, [], _cliente(obrigacoes=["ECD"]), AGORA)
    assert [i.titulo for i in p.grupos["prazos"]] == ["ECD (PJ)"]


def test_itens_do_cliente_marcam_origem_interna_e_severidade():
    cli = _cliente(
        regime_tributario="lucro_presumido", situacao_cadastral="ATIVA",
        certidoes=[{"tipo": "CND federal", "situacao": "negativa", "validade": "2026-10-20"},
                   {"tipo": "CND estadual GO", "situacao": "negativa", "validade": "2026-11-10"}],
        contratos=[{"descricao": "Assessoria contábil", "honorario_mensal": 1500.0, "vencimento_dia": 10,
                    "fim": "2026-11-15", "reajuste": "IPCA"}],
        pendencias=[{"descricao": "Enviar extratos de setembro", "prazo": "2026-10-25", "status": "aberta"},
                    {"descricao": "Assinar procuração", "status": "concluida"}],
    )
    p = montagem.montar([], [], cli, AGORA)
    sit = {i.titulo: i for i in p.grupos["situacao"]}
    assert sit["CND federal: vencida"].severidade == "critico"
    assert sit["CND estadual GO: negativa"].severidade == "atencao"            # vence em 10 dias
    assert all(i.origem == "interna" and i.fonte_nome == "banco do JARVIS" and i.fonte_url is None
               for i in p.grupos["situacao"] + p.grupos["interno"])
    interno = {i.titulo: i for i in p.grupos["interno"]}
    assert interno["Honorários R$ 1.500,00 – Assessoria contábil"].data == date(2026, 11, 10)
    assert interno["Contrato termina: Assessoria contábil"].severidade == "atencao"
    assert interno["Pendência: Enviar extratos de setembro"].severidade == "critico"   # atrasada
    assert not any("procuração" in t for t in interno)                                 # concluída não aparece
