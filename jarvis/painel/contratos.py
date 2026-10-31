"""Contratos (Pydantic V2) do painel fiscal: itens com origem verificável, estado das fontes e dados do cliente."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Grupo = Literal["prazos", "legislacao", "situacao", "interno"]
TipoData = Literal["vencimento", "publicacao", "vigencia", "competencia", "ato"]
Severidade = Literal["info", "atencao", "critico"]


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemFiscal(_Contrato):
    """Um alerta ou informação do card tributário. Sem fonte e data, não entra: dado sem origem não é fato."""

    id: str = ""
    grupo: Grupo
    titulo: str = Field(min_length=1, max_length=300)
    detalhe: str = Field(default="", max_length=1000)
    data: date
    tipo_data: TipoData
    fonte_id: str
    fonte_nome: str
    fonte_url: str | None = None          # oficial: obrigatório; interno: None (vale a fonte_nome)
    origem: Literal["oficial", "interna"] = "oficial"
    severidade: Severidade = "info"
    etiquetas: list[str] = Field(default_factory=list)   # para filtrar pelo cliente (ex.: "EFD-Contribuições")

    @model_validator(mode="after")
    def _origem_verificavel(self) -> ItemFiscal:
        if self.origem == "oficial" and not (self.fonte_url or "").startswith("https://"):
            raise ValueError("item oficial precisa do link https da fonte")
        if not self.id:
            chave = f"{self.fonte_id}|{self.fonte_url}|{self.titulo}|{self.data.isoformat()}"
            self.id = hashlib.sha256(chave.encode()).hexdigest()[:16]
        return self


class StatusFonte(_Contrato):
    id: str
    nome: str
    url: str | None = None
    ligada: bool = True
    ok: bool | None = None                 # None: ainda não coletou
    ultima_coleta: datetime | None = None
    ultimo_sucesso: datetime | None = None
    erro: str | None = None
    itens: int = 0
    nota: str | None = None                # ex.: por que está desligada


class PainelTributario(_Contrato):
    grupos: dict[Grupo, list[ItemFiscal]]
    atualizado_em: datetime | None          # última coleta com sucesso de alguma fonte
    gerado_em: datetime
    fontes: list[StatusFonte]
    cliente_id: int | None = None


# ── dados do cliente ─────────────────────────────────────────
class CampoComFonte(_Contrato):
    valor: Any
    fonte: str                             # id da fonte que venceu a precedência
    fonte_nome: str
    atualizado_em: datetime | None = None
    antigo: bool = False                   # veio do último dado válido porque a fonte falhou agora


class Conflito(_Contrato):
    campo: str
    valores: dict[str, Any]                # fonte → valor


class ClienteResumo(_Contrato):
    id: int
    nome: str
    documento_mascarado: str


class ClienteConsolidado(_Contrato):
    id: int
    campos: dict[str, CampoComFonte]
    conflitos: list[Conflito] = Field(default_factory=list)
    fontes: list[StatusFonte] = Field(default_factory=list)
    gerado_em: datetime


class ClienteEntrada(_Contrato):
    """Cadastro no banco do JARVIS (fonte principal). Listas e objetos simples, sem dado sensível além do necessário."""

    id: int | None = None
    documento: str = Field(min_length=11, max_length=18, description="CNPJ ou CPF, com ou sem pontuação")
    razao_social: str = Field(min_length=2, max_length=200)
    regime_tributario: Literal["simples", "mei", "lucro_presumido", "lucro_real", "pessoa_fisica",
                               "produtor_rural"] | None = None
    cnae_principal: str | None = Field(default=None, max_length=12)
    cnaes_secundarios: list[str] = Field(default_factory=list, max_length=99)
    atividades: str | None = Field(default=None, max_length=500)
    ufs_operacao: list[str] = Field(default_factory=list, max_length=27)
    obrigacoes: list[str] = Field(default_factory=list, max_length=60,
                                  description="Obrigações acessórias, ex.: EFD-Contribuições, DCTFWeb, ECD, LCDPR")
    contato_nome: str | None = Field(default=None, max_length=120)
    contato_email: str | None = Field(default=None, max_length=160)
    contato_telefone: str | None = Field(default=None, max_length=40)
    certidoes: list[Certidao] = Field(default_factory=list, max_length=20)
    contratos: list[Contrato] = Field(default_factory=list, max_length=20)
    pendencias: list[Pendencia] = Field(default_factory=list, max_length=100)


class Certidao(_Contrato):
    tipo: str = Field(min_length=2, max_length=80)        # ex.: "CND federal (RFB/PGFN)", "CND estadual GO"
    situacao: Literal["negativa", "positiva_efeito_negativa", "positiva", "irregular", "desconhecida"]
    validade: date | None = None
    observacao: str | None = Field(default=None, max_length=300)


class Contrato(_Contrato):
    descricao: str = Field(min_length=2, max_length=200)
    honorario_mensal: float | None = Field(default=None, ge=0)
    vencimento_dia: int | None = Field(default=None, ge=1, le=31)
    inicio: date | None = None
    fim: date | None = None
    reajuste: str | None = Field(default=None, max_length=120)


class Pendencia(_Contrato):
    descricao: str = Field(min_length=2, max_length=300)
    prazo: date | None = None
    status: Literal["aberta", "concluida"] = "aberta"


ClienteEntrada.model_rebuild()
