"""Montagem do card tributário: itens das fontes oficiais + itens do cliente (situação e pendências internas)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from .contratos import ClienteConsolidado, Grupo, ItemFiscal, PainelTributario, Severidade, StatusFonte
from .fontes.base import norm

MAX_PRAZOS, MAX_LEGISLACAO = 12, 14
REGIME_PALAVRAS = {   # pagamentos ligados ao regime, quando o cliente não lista as obrigações
    "simples": ["simples nacional", "das"], "mei": ["simples nacional", "das", "mei"],
    "lucro_presumido": ["irpj", "csll", "pis", "cofins", "irrf", "inss"],
    "lucro_real": ["irpj", "csll", "pis", "cofins", "irrf", "inss"],
    "produtor_rural": ["lcdpr", "itr", "inss", "irpf"], "pessoa_fisica": ["irpf", "carne-leao", "itr"],
}
SITUACAO_CERTIDAO = {"negativa": "negativa", "positiva_efeito_negativa": "positiva com efeito de negativa",
                     "positiva": "positiva (há débitos)", "irregular": "irregular", "desconhecida": "não verificada"}


def _valor(cliente: ClienteConsolidado | None, campo: str, padrao=None):
    c = cliente.campos.get(campo) if cliente else None
    return padrao if c is None or c.valor in (None, "", []) else c.valor


def _origem(cliente: ClienteConsolidado, campo: str) -> tuple[str, str]:
    """(origem do ItemFiscal, nome da fonte) do campo, segundo quem venceu a precedência."""
    c = cliente.campos[campo]
    origem = "integracao" if c.fonte in ("portais", "erp") else "interna"
    return origem, c.fonte_nome + (" (último dado válido)" if c.antigo else "")


def _prazo_do_cliente(item: ItemFiscal, palavras: list[str]) -> bool:
    alvo = norm(" ".join([item.titulo, *item.etiquetas]))
    return any(norm(p) in alvo for p in palavras)


def prazos(itens: list[ItemFiscal], cliente: ClienteConsolidado | None, hoje: date) -> list[ItemFiscal]:
    proximos = sorted((i for i in itens if i.grupo == "prazos" and i.data >= hoje), key=lambda i: (i.data, i.titulo))
    palavras = list(_valor(cliente, "obrigacoes", []))
    if regime := _valor(cliente, "regime_tributario"):
        palavras += REGIME_PALAVRAS.get(regime, [])
    if palavras:
        proximos = [i for i in proximos if _prazo_do_cliente(i, palavras)]
    else:   # sem cliente: as obrigações acessórias primeiro, depois os pagamentos
        proximos.sort(key=lambda i: (i.titulo.startswith("Pagamento"), i.data))
    return [i.model_copy(update={"severidade": _severidade_prazo(i.data, hoje)}) for i in proximos[:MAX_PRAZOS]]


def _severidade_prazo(d: date, hoje: date) -> Severidade:
    dias = (d - hoje).days
    return "critico" if dias <= 2 else "atencao" if dias <= 7 else "info"


def _proximo_dia(dia: int, hoje: date) -> date:
    """Próxima data com aquele dia do mês (o último dia, em meses mais curtos)."""
    ano, mes = hoje.year, hoje.month
    for _ in range(2):
        d = date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))
        if d >= hoje:
            return d
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return d


def _item(grupo: Grupo, titulo: str, data: date, tipo: str, origem: tuple[str, str], cliente_id: int,
          detalhe: str = "", severidade: Severidade = "info") -> ItemFiscal:
    return ItemFiscal(grupo=grupo, titulo=titulo, detalhe=detalhe, data=data, tipo_data=tipo, origem=origem[0],
                      fonte_id=f"cliente:{cliente_id}", fonte_nome=origem[1], severidade=severidade)


def itens_do_cliente(cliente: ClienteConsolidado, hoje: date) -> list[ItemFiscal]:
    """Situação (regime, cadastro, certidões) e pendências internas (contratos, honorários, pendências)."""
    itens: list[ItemFiscal] = []

    def atual(campo: str) -> date:
        return (cliente.campos[campo].atualizado_em or cliente.gerado_em).date()

    if regime := _valor(cliente, "regime_tributario"):
        itens.append(_item("situacao", f"Regime tributário: {regime.replace('_', ' ')}", atual("regime_tributario"),
                           "vigencia", _origem(cliente, "regime_tributario"), cliente.id))
    if situacao := _valor(cliente, "situacao_cadastral"):
        ruim = norm(str(situacao)) not in ("ativa", "ativo")
        itens.append(_item("situacao", f"Situação cadastral: {situacao}", atual("situacao_cadastral"), "vigencia",
                           _origem(cliente, "situacao_cadastral"), cliente.id, severidade="critico" if ruim else "info"))
    for cert in _valor(cliente, "certidoes", []):
        validade = date.fromisoformat(cert["validade"]) if cert.get("validade") else None
        situacao = cert.get("situacao", "desconhecida")
        sev: Severidade = "info"
        if situacao in ("positiva", "irregular") or (validade and validade < hoje):
            sev = "critico"
        elif situacao == "desconhecida" or (validade and validade <= hoje + timedelta(days=15)):
            sev = "atencao"
        estado = "vencida" if validade and validade < hoje else SITUACAO_CERTIDAO.get(situacao, situacao)
        itens.append(_item("situacao", f"{cert['tipo']}: {estado}", validade or atual("certidoes"),
                           "vigencia" if validade else "competencia", _origem(cliente, "certidoes"), cliente.id,
                           detalhe=cert.get("observacao") or "", severidade=sev))
    for ct in _valor(cliente, "contratos", []):
        if ct.get("honorario_mensal") and ct.get("vencimento_dia"):
            venc = _proximo_dia(int(ct["vencimento_dia"]), hoje)
            valor = f"R$ {ct['honorario_mensal']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            itens.append(_item("interno", f"Honorários {valor} – {ct['descricao']}", venc, "vencimento",
                               _origem(cliente, "contratos"), cliente.id, severidade=_severidade_prazo(venc, hoje)))
        if ct.get("fim"):
            fim = date.fromisoformat(ct["fim"])
            if fim >= hoje - timedelta(days=30):
                sev = "critico" if fim < hoje else "atencao" if fim <= hoje + timedelta(days=30) else "info"
                itens.append(_item("interno", f"Contrato termina: {ct['descricao']}", fim, "vigencia",
                                   _origem(cliente, "contratos"), cliente.id,
                                   detalhe=f"Reajuste: {ct['reajuste']}" if ct.get("reajuste") else "", severidade=sev))
    for pd in _valor(cliente, "pendencias", []):
        if pd.get("status", "aberta") != "aberta":
            continue
        prazo = date.fromisoformat(pd["prazo"]) if pd.get("prazo") else None
        sev = "critico" if prazo and prazo < hoje else _severidade_prazo(prazo, hoje) if prazo else "atencao"
        itens.append(_item("interno", f"Pendência: {pd['descricao']}", prazo or atual("pendencias"),
                           "vencimento" if prazo else "competencia", _origem(cliente, "pendencias"), cliente.id,
                           severidade=sev))
    return itens


def montar(itens: list[ItemFiscal], fontes: list[StatusFonte], cliente: ClienteConsolidado | None,
           agora: datetime) -> PainelTributario:
    hoje = agora.date()
    legislacao = sorted((i for i in itens if i.grupo == "legislacao" and i.tipo_data != "ato"),
                        key=lambda i: i.data, reverse=True)[:MAX_LEGISLACAO]
    legislacao += [i for i in itens if i.grupo == "legislacao" and i.tipo_data == "ato"]   # marcos sempre no fim
    do_cliente = itens_do_cliente(cliente, hoje) if cliente else []
    ordem = {"critico": 0, "atencao": 1, "info": 2}
    sucessos = [f.ultimo_sucesso for f in fontes if f.ultimo_sucesso]
    return PainelTributario(
        grupos={
            "prazos": prazos(itens, cliente, hoje),
            "legislacao": legislacao,
            "situacao": sorted((i for i in do_cliente if i.grupo == "situacao"), key=lambda i: ordem[i.severidade]),
            "interno": sorted((i for i in do_cliente if i.grupo == "interno"), key=lambda i: (ordem[i.severidade], i.data)),
        },
        atualizado_em=max(sucessos) if sucessos else None,
        gerado_em=agora,
        fontes=fontes + (cliente.fontes if cliente else []),
        cliente_id=cliente.id if cliente else None,
    )
