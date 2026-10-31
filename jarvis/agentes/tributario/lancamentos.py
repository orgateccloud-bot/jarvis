"""Lançamentos: leitura de CSV brasileiro, classificação e análise de risco, tudo local e sem custo.

O agente recebe bytes ou linhas, nunca um caminho: quem lê o arquivo (já confinado às pastas permitidas) é a ferramenta
ou a rota da API. A saída já vem com memo, nomes e documentos mascarados, pronta para seguir ao Claude se for preciso.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime

from ...core.privacy import pseudonimizar_nome, sanitizar
from ..contratos import Lancamento, Regra
from .fiscal_base import REGRAS_PADRAO, classificar, fatores_risco

MAX_LINHAS = 50_000
MAX_GRUPOS = 10

# Depois das regras do Mini (a última que casar vence). Palavras com espaço nas pontas casam só como palavra inteira:
# o texto é classificado com um espaço antes e depois (" DAS " não pega "VENDAS"; "ISSQN" não pega "COMISSAO").
REGRAS_FISCAIS: list[tuple[str, str]] = [
    ("RECEITA FEDERAL", "Tributos federais (DARF)"),
    ("DARF", "Tributos federais (DARF)"),
    ("SIMPLES NACIONAL", "Simples Nacional (DAS)"),
    (" DAS ", "Simples Nacional (DAS)"),
    ("PGDAS", "Simples Nacional (DAS)"),
    ("INSS", "INSS (GPS)"),
    (" GPS ", "INSS (GPS)"),
    ("FGTS", "FGTS"),
    ("GRRF", "FGTS"),
    ("ICMS", "ICMS"),
    ("SEFAZ", "ICMS"),
    ("ISSQN", "ISS"),
    ("IPVA", "IPVA"),
    ("IPTU", "IPTU"),
]

_COLUNAS = {
    "data": ("data", "date", "dt", "data lancamento", "data do lancamento"),
    "valor": ("valor", "value", "amount", "valor (r$)", "valor r$"),
    "memo": ("memo", "descricao", "historico", "lancamento", "description"),
    "nome": ("nome", "name"),
    "contraparte": ("contraparte", "favorecido", "beneficiario", "counterpart", "cpf/cnpj"),
}


class _PontoEVirgula(csv.excel):
    delimiter = ";"


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower().strip()) if not unicodedata.combining(c))


def _valor(bruto: str) -> float:
    """"1.234,56", "-150,00", "R$ 10,00" ou "1234.56"."""
    t = bruto.strip().replace("R$", "").replace(" ", "")
    negativo = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    v = float(t)
    return -v if negativo else v


def _data(bruto: str) -> date:
    t = bruto.strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data que não entendi: {bruto!r}")


def ler_csv(dados: bytes) -> list[Lancamento]:
    """CSV de extrato/razão: separador ; ou , ou tab, UTF-8 (com ou sem BOM) ou Windows-1252, vírgula decimal."""
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252")
    amostra = texto[:4096]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
    except csv.Error:
        dialeto = _PontoEVirgula
    leitor = csv.reader(io.StringIO(texto), dialeto)
    cabecalho = [_sem_acento(c) for c in next(leitor, [])]
    indice = {}
    for campo, nomes in _COLUNAS.items():
        indice[campo] = next((i for i, c in enumerate(cabecalho) if c in nomes), None)
    if indice["data"] is None or indice["valor"] is None:
        raise ValueError("o CSV precisa das colunas data e valor (cabeçalho na primeira linha)")

    def campo(linha: list[str], nome: str) -> str:
        i = indice[nome]
        return linha[i].strip() if i is not None and i < len(linha) else ""

    saida = []
    for n, linha in enumerate(leitor, start=2):
        if not any(c.strip() for c in linha):
            continue
        if len(saida) >= MAX_LINHAS:
            raise ValueError(f"o CSV passa de {MAX_LINHAS} lançamentos")
        try:
            saida.append(Lancamento(data=_data(campo(linha, "data")), valor=_valor(campo(linha, "valor")),
                                    memo=campo(linha, "memo")[:500], nome=campo(linha, "nome")[:200],
                                    contraparte=campo(linha, "contraparte")[:200]))
        except ValueError as e:
            raise ValueError(f"linha {n} do CSV: {e}") from e
    return saida


def regras_com_extras(extras: list[Regra] | None = None) -> list[tuple[str, str]]:
    return [*REGRAS_PADRAO, *REGRAS_FISCAIS, *((r.palavra, r.categoria) for r in extras or [])]


def categoria(lanc: Lancamento, regras: list[tuple[str, str]]) -> str:
    # o original classifica memo + " " + nome; os espaços nas pontas só servem às regras de palavra inteira
    return classificar(f" {lanc.memo} {lanc.nome} ", regras)


def analisar(lancamentos: list[Lancamento], extras: list[Regra] | None = None, salt: str = "") -> dict:
    """Classificação, índice de risco com cada fator e grupos de fracionamento, com PII mascarada."""
    regras = regras_com_extras(extras)
    nomes = sorted({n for x in lancamentos for n in (x.nome, x.contraparte) if n.strip() and not re.fullmatch(
        r"[\d./-]+", n.strip())}, key=len, reverse=True)

    def mascarar(t: str) -> str:
        return sanitizar(t, nomes, salt)

    categorias = [categoria(x, regras) for x in lancamentos]
    linhas = [{"Data": x.data, "Valor": x.valor, "Contraparte": x.contraparte, "Categoria": c}
              for x, c in zip(lancamentos, categorias, strict=True)]
    fatores = fatores_risco(linhas)

    por_cat: dict[str, list[float]] = defaultdict(list)
    for x, c in zip(lancamentos, categorias, strict=True):
        por_cat[c].append(x.valor)
    exemplos: dict[tuple, list[str]] = defaultdict(list)
    for x in lancamentos:
        if len(exemplos[(x.data, x.valor)]) < 3:
            exemplos[(x.data, x.valor)].append(mascarar(x.memo)[:80])
    grupos = [{"data": g["data"].isoformat(), "valor": round(g["valor"], 2), "qtd": g["qtd"],
               "exemplos": exemplos[(g["data"], g["valor"])]} for g in fatores["fracionamento"]["grupos"]]
    contrapartes = defaultdict(float)
    for x in lancamentos:
        if x.contraparte.strip():
            contrapartes[pseudonimizar_nome(x.contraparte.strip(), salt)] += abs(x.valor)

    return {
        "total_lancamentos": len(lancamentos),
        "periodo": {"inicio": min(x.data for x in lancamentos).isoformat(),
                    "fim": max(x.data for x in lancamentos).isoformat()} if lancamentos else None,
        "entradas": round(sum(x.valor for x in lancamentos if x.valor > 0), 2),
        "saidas": round(sum(x.valor for x in lancamentos if x.valor < 0), 2),
        "categorias": sorted(({"categoria": c, "qtd": len(v), "total": round(sum(v), 2)} for c, v in por_cat.items()),
                             key=lambda d: -abs(d["total"])),
        "risco": {
            "indice": round(fatores["indice"], 2),
            "natureza": "índice heurístico (5 a 99), fórmula do MiniSaaS; não é probabilidade estatística calibrada",
            "fatores": {
                "base": fatores["base"],
                "sem_contraparte": {k: round(v, 2) for k, v in fatores["sem_contraparte"].items()},
                "fracionamento": {"pct": round(fatores["fracionamento"]["pct"], 2),
                                  "pontos": round(fatores["fracionamento"]["pontos"], 2)},
                "nao_classificados": {k: round(v, 2) for k, v in fatores["nao_classificados"].items()},
            },
        },
        "grupos_fracionamento": grupos[:MAX_GRUPOS],
        "maiores_contrapartes": [{"contraparte": k, "total_abs": round(v, 2)}
                                 for k, v in sorted(contrapartes.items(), key=lambda kv: -kv[1])[:5]],
    }
