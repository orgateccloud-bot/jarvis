"""Planilha de clientes: CSV ou XLSX local (JARVIS_CLIENTES_PLANILHA) ou Google Sheets publicado como CSV
(JARVIS_CLIENTES_SHEETS_URL, link de exportação https; sem credencial).

Uma linha por cliente; o cabeçalho é flexível (sem acento e sem caixa). Listas (obrigações, UFs, CNAEs) vêm separadas
por "|" ou ",". Colunas reconhecidas: documento/cnpj/cpf, razao social/nome, regime, cnae, cnaes secundarios,
atividades, ufs/estados, obrigacoes, contato, email, telefone, honorario, vencimento, certidao, certidao situacao,
certidao validade.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..fontes.base import data_br, norm
from ..http import Fetch, FonteIndisponivel, buscar
from .base import FonteCliente, documento

COLUNAS = {
    "documento": ("documento", "cnpj", "cpf", "cnpj/cpf", "cpf/cnpj"),
    "razao_social": ("razao social", "razao_social", "nome", "cliente"),
    "regime_tributario": ("regime", "regime tributario", "regime_tributario"),
    "cnae_principal": ("cnae", "cnae principal", "cnae_principal"),
    "cnaes_secundarios": ("cnaes secundarios", "cnaes_secundarios"),
    "atividades": ("atividades", "atividade"),
    "ufs_operacao": ("ufs", "estados", "ufs operacao", "ufs_operacao", "estados de operacao"),
    "obrigacoes": ("obrigacoes", "obrigacoes acessorias"),
    "contato_nome": ("contato", "contato nome", "responsavel"),
    "contato_email": ("email", "e-mail", "contato email"),
    "contato_telefone": ("telefone", "contato telefone"),
    "honorario_mensal": ("honorario", "honorarios", "honorario mensal"),
    "vencimento_dia": ("vencimento", "dia vencimento", "vencimento honorario"),
    "certidao_tipo": ("certidao",),
    "certidao_situacao": ("certidao situacao",),
    "certidao_validade": ("certidao validade", "validade certidao"),
}
REGIMES = {"simples nacional": "simples", "simples": "simples", "mei": "mei", "lucro presumido": "lucro_presumido",
           "presumido": "lucro_presumido", "lucro real": "lucro_real", "real": "lucro_real",
           "produtor rural": "produtor_rural", "pessoa fisica": "pessoa_fisica"}
SITUACOES = {"negativa": "negativa", "positiva com efeito de negativa": "positiva_efeito_negativa",
             "positiva": "positiva", "irregular": "irregular"}


def _lista(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[|,]", v) if x.strip()]


def _numero(v: str) -> float | None:
    t = v.replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def linha_para_campos(lin: dict[str, str]) -> dict[str, Any]:
    def g(k: str) -> str:
        return (lin.get(k) or "").strip()

    campos: dict[str, Any] = {"razao_social": g("razao_social") or None, "cnae_principal": g("cnae_principal") or None,
                              "atividades": g("atividades") or None}
    if r := g("regime_tributario"):
        campos["regime_tributario"] = REGIMES.get(norm(r), r)
    for lista in ("cnaes_secundarios", "ufs_operacao", "obrigacoes"):
        if v := g(lista):
            campos[lista] = [x.upper() if lista == "ufs_operacao" else x for x in _lista(v)]
    contato = {k: g(f"contato_{k}") for k in ("nome", "email", "telefone") if g(f"contato_{k}")}
    if contato:
        campos["contato"] = contato
    if (hon := _numero(g("honorario_mensal"))) is not None:
        dia = int(g("vencimento_dia")) if g("vencimento_dia").isdigit() else None
        campos["contratos"] = [{"descricao": "Honorários (planilha)", "honorario_mensal": hon, "vencimento_dia": dia}]
    if tipo := g("certidao_tipo"):
        validade = data_br(g("certidao_validade"))
        campos["certidoes"] = [{"tipo": tipo, "situacao": SITUACOES.get(norm(g("certidao_situacao")), "desconhecida"),
                                "validade": validade.isoformat() if isinstance(validade, date) else None}]
    return {k: v for k, v in campos.items() if v not in (None, "", [], {})}


class PlanilhaClientes(FonteCliente):
    id = "planilha"

    def __init__(self, caminho: Path | None = None, url: str | None = None, fetch: Fetch = buscar):
        if not caminho and not url:
            raise ValueError("planilha sem caminho e sem URL")
        self.caminho, self.url, self.fetch = caminho, url, fetch
        self.nome = f"planilha {caminho.name}" if caminho else "Google Sheets"

    def _linhas(self) -> list[dict[str, str]]:
        if self.caminho and self.caminho.suffix.lower() == ".xlsx":
            bruto = self._xlsx()
        else:
            if self.caminho:
                if not self.caminho.exists():
                    raise FonteIndisponivel(f"planilha não encontrada: {self.caminho.name}")
                dados = self.caminho.read_bytes()
                try:
                    texto = dados.decode("utf-8-sig")
                except UnicodeDecodeError:
                    texto = dados.decode("cp1252")
            else:
                texto = self.fetch(self.url)
            try:
                dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t")
            except csv.Error:
                dialeto = csv.excel
            bruto = list(csv.reader(io.StringIO(texto), dialeto))
        if not bruto:
            return []
        cab = [norm(c).strip() for c in bruto[0]]
        idx = {campo: next((i for i, c in enumerate(cab) if c in nomes), None) for campo, nomes in COLUNAS.items()}
        if idx["documento"] is None:
            raise FonteIndisponivel("a planilha precisa de uma coluna documento, cnpj ou cpf")
        return [{campo: (lin[i] if i is not None and i < len(lin) else "") for campo, i in idx.items()}
                for lin in bruto[1:] if any(str(c).strip() for c in lin)]

    def _xlsx(self) -> list[list[str]]:
        try:
            import openpyxl
        except ImportError as e:
            raise FonteIndisponivel("para ler .xlsx, instale o extra do painel: pip install -e .[painel]") from e
        if not self.caminho.exists():
            raise FonteIndisponivel(f"planilha não encontrada: {self.caminho.name}")
        aba = openpyxl.load_workbook(self.caminho, read_only=True, data_only=True).active
        return [["" if v is None else str(v) for v in linha] for linha in aba.iter_rows(values_only=True)]

    def listar(self) -> list[dict[str, Any]]:
        return [{"documento": documento(lin["documento"]), "razao_social": lin["razao_social"] or documento(lin["documento"])}
                for lin in self._linhas() if documento(lin["documento"])]

    def buscar(self, doc: str) -> dict[str, Any] | None:
        alvo = documento(doc)
        for lin in self._linhas():
            if documento(lin["documento"]) == alvo:
                return linha_para_campos(lin)
        return None
