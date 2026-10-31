"""Núcleo fiscal copiado do MiniSaaS (d:\\01_Projetos_Ativos\\Mini\\saas\\core\\financeiro.py).

Proveniência: REGRAS_PADRAO e classificar() são cópia literal (só a anotação List/Tuple virou list/tuple);
calcular_risco_autuacao() é o mesmo cálculo portado de pandas para Python puro (mesmos limiares, pesos e teto de 99),
para o JARVIS não depender de pandas.
ORIGEM_SHA256 é o sha256 do código-fonte desses três símbolos no original (segmentos do ast, LF, separados por uma
linha em branco). Se o Mini mudar, `pytest -m mini` acusa a deriva e compara os resultados com o original.

Extensão (não muda o original): fatores_risco() devolve cada parcela do índice e os grupos de fracionamento.
"""

from __future__ import annotations

from collections import Counter

ORIGEM = "Mini/saas/core/financeiro.py"
ORIGEM_SHA256 = "f1e6ae84579920c0ad4af35840f7f8c3d27924066b9bbc5f3a2e30d149778943"

# ── cópia literal ─────────────────────────────────────────────
# Regras de categorização padrão semeadas para cada novo tenant.
REGRAS_PADRAO: list[tuple[str, str]] = [
    ("TRANSF", "Transferências"),
    ("PIX EMITIDO", "Pagamentos PIX"),
    ("PIX RECEBIDO", "Recebimentos PIX"),
    ("CRD.TED", "Recebimentos TED"),
    ("DB.TIT.COMPE", "Pagamento de Títulos"),
    ("BOLETO", "Pagamento de Boletos"),
    ("TARIFA", "Tarifas Bancárias"),
    ("LIBERAO TD", "Liberação de Crédito (TD)"),
    ("PAGAMENTO TD", "Amortização de Crédito (TD)"),
    ("JUROS", "Juros e Encargos"),
    ("IOF", "Impostos (IOF)"),
    ("MESMA TIT", "Transf. Mesma Titularidade"),
    ("OFICINA", "Manutenção - Oficina"),
    ("PNEU", "Manutenção - Pneus"),
    ("POSTO", "Combustível"),
    ("COMBUSTIVEL", "Combustível"),
]


def classificar(texto: str, regras: list[tuple[str, str]]) -> str:
    """Classifica um texto (memo + nome) na categoria da última regra que casar."""
    txt = str(texto).upper()
    cat = "Outros"
    for kw, c in regras:
        if kw.upper() in txt:
            cat = c
    return cat


# ── porte para Python puro ────────────────────────────────────
def fatores_risco(linhas: list[dict]) -> dict:
    """Parcelas do índice de risco de autuação. Cada linha tem Data, Valor, Contraparte e Categoria (as colunas do
    DataFrame do original). É um índice heurístico de 5 a 99, não uma probabilidade estatística calibrada."""
    n = len(linhas)
    if n == 0:
        return {"base": 0.0, "sem_contraparte": {"pct": 0.0, "pontos": 0.0},
                "fracionamento": {"pct": 0.0, "pontos": 0.0, "grupos": []},
                "nao_classificados": {"pct": 0.0, "pontos": 0.0}, "total_bruto": 0.0, "indice": 0.0}

    # 1. Falta de contrapartes identificadas ("" ou ausente; um espaço conta como preenchida, como no original)
    pct_sem_cp = sum(1 for x in linhas if x.get("Contraparte") is None or x.get("Contraparte") == "") / n * 100
    pts_cp = (pct_sem_cp - 20) * 0.4 if pct_sem_cp > 20 else 0.0

    # 2. Fracionamento (smurfing): grupos de 3 ou mais com a mesma data e o mesmo valor
    grupos = Counter((x["Data"], x["Valor"]) for x in linhas if x["Data"] is not None and x["Valor"] is not None)
    suspeitos = {k: q for k, q in grupos.items() if q > 2}
    pct_smurfing = sum(suspeitos.values()) / n * 100
    pts_smurfing = pct_smurfing * 1.5

    # 3. Lançamentos não classificados
    pct_outros = sum(1 for x in linhas if x["Categoria"] == "Outros") / n * 100
    pts_outros = (pct_outros - 30) * 0.2 if pct_outros > 30 else 0.0

    total = 5.0 + pts_cp + pts_smurfing + pts_outros
    return {
        "base": 5.0,
        "sem_contraparte": {"pct": pct_sem_cp, "pontos": pts_cp},
        "fracionamento": {"pct": pct_smurfing, "pontos": pts_smurfing,
                          "grupos": [{"data": d, "valor": v, "qtd": q} for (d, v), q in sorted(
                              suspeitos.items(), key=lambda kv: (-kv[1], str(kv[0][0]), kv[0][1]))]},
        "nao_classificados": {"pct": pct_outros, "pontos": pts_outros},
        "total_bruto": total,
        "indice": min(float(total), 99.0),
    }


def calcular_risco_autuacao(linhas: list[dict]) -> float:
    """Índice de risco de autuação (%), igual ao do original para as mesmas linhas."""
    return fatores_risco(linhas)["indice"]
