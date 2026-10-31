"""Contratos (Pydantic V2) entre o JARVIS e os agentes subordinados."""

from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ID_AGENTE = r"^[a-z][a-z0-9_]{1,31}$"
Origem = Literal["usuario_api", "jarvis_conversa"]
EstadoExecucao = Literal["em_andamento", "concluida", "falhou", "recusada", "interrompida"]
Effort = Literal["low", "medium", "high", "xhigh"]


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lancamento(_Contrato):
    """Uma linha de extrato ou razão. Fica no PC: só agregados e grupos mascarados vão ao Claude."""

    data: date
    valor: float
    memo: str = Field(default="", max_length=500)
    nome: str = Field(default="", max_length=200)
    contraparte: str = Field(default="", max_length=200)


class ParametrosCenario(_Contrato):
    """Entrada da calculadora atual × pós-Reforma. Alíquotas ausentes usam os padrões declarados nas premissas."""

    faturamento_anual: float = Field(gt=0, le=1e12, description="Faturamento bruto anual, em R$")
    regime: Literal["lucro_presumido", "lucro_real", "simples"]
    atividade: Literal["comercio", "industria", "servicos"]
    ano: int = Field(ge=2026, le=2040, description="Ano do cenário pós-Reforma")
    aliquota_icms: float | None = Field(default=None, ge=0, le=0.4)
    aliquota_iss: float | None = Field(default=None, ge=0, le=0.05)
    aliquota_ipi: float | None = Field(default=None, ge=0, le=1)
    aliquota_referencia: float | None = Field(default=None, ge=0.1, le=0.4,
                                              description="IBS + CBS somados; o padrão é uma estimativa")
    compras_creditaveis_pct: float = Field(default=0.0, ge=0, le=1,
                                           description="Fração do faturamento em compras que geram crédito")


class PedidoTarefa(_Contrato):
    tarefa: str = Field(pattern=r"^[a-z_]{3,40}$", description="Uma das tarefas do catálogo do agente")
    pedido: str = Field(default="", max_length=4000)
    lancamentos: list[Lancamento] | None = Field(default=None, max_length=50_000)
    cenario: ParametrosCenario | None = None


class Ordem(_Contrato):
    """Só o orquestrador emite ordens; o id é único no registro (a mesma ordem nunca roda duas vezes)."""

    id: str = Field(default_factory=lambda: secrets.token_hex(8), pattern=r"^[a-f0-9]{16}$")
    agente_id: str = Field(pattern=ID_AGENTE)
    pedido: PedidoTarefa
    origem: Origem
    emitida_em: datetime = Field(default_factory=datetime.now)


class SaidaTarefa(_Contrato):
    """O que o agente devolve ao orquestrador; o orquestrador completa com ids, versões, horários e selo."""

    resumo: str
    resumo_voz: str = ""
    saida: dict[str, Any] = Field(default_factory=dict)
    modelo: str = "regras"
    custo_usd: float = 0.0
    arquivo: str | None = None


class ResultadoTarefa(_Contrato):
    tarefa_id: str
    agente_id: str
    tarefa: str
    origem: Origem
    estado: EstadoExecucao
    versao_config: int
    versao_codigo: str
    resumo: str = ""
    resumo_voz: str = ""
    saida: dict[str, Any] = Field(default_factory=dict)
    modelo: str = "regras"
    custo_usd: float = 0.0
    inicio: datetime
    fim: datetime | None = None
    arquivo: str | None = None
    erro: str | None = None
    conteudo_sha256: str = ""
    audit_hash: str = ""

    @property
    def ok(self) -> bool:
        return self.estado == "concluida"


class Regra(_Contrato):
    """Regra extra de classificação: a palavra no memo/nome leva à categoria (a última que casar vence)."""

    palavra: str = Field(min_length=2, max_length=60)
    categoria: str = Field(min_length=2, max_length=60)


class ConfigAgente(_Contrato):
    modelo: str = Field(default="claude-sonnet-5-5", pattern=r"^claude-[a-z0-9-]{3,40}$")
    effort: Effort | None = Field(default=None, description="Vazio: o padrão de cada tarefa")
    teto_mensal_usd: float = Field(default=30.0, ge=0, le=1000)
    instrucoes_extras: str = Field(default="", max_length=4000)
    regras_extras: list[Regra] = Field(default_factory=list, max_length=200)


class AtualizacaoAgente(_Contrato):
    """Mudança parcial da configuração; cada uma vira uma versão nova (nada é sobrescrito)."""

    modelo: str | None = Field(default=None, pattern=r"^claude-[a-z0-9-]{3,40}$")
    effort: Effort | None = None
    teto_mensal_usd: float | None = Field(default=None, ge=0, le=1000)
    instrucoes_extras: str | None = Field(default=None, max_length=4000)
    regras_extras: list[Regra] | None = Field(default=None, max_length=200)
    motivo: str = Field(min_length=3, max_length=300)

    def aplicar(self, atual: ConfigAgente) -> ConfigAgente:
        mudancas = self.model_dump(exclude={"motivo"}, exclude_none=True)
        return ConfigAgente.model_validate({**atual.model_dump(), **mudancas})

    def diff(self, atual: ConfigAgente) -> dict[str, dict[str, Any]]:
        """Campo → {de, para}, só o que muda de fato (vai para o cartão de aprovação)."""
        nova = self.aplicar(atual).model_dump(mode="json")
        antiga = atual.model_dump(mode="json")
        return {k: {"de": antiga[k], "para": v} for k, v in nova.items() if antiga[k] != v}


class VersaoConfig(_Contrato):
    versao: int
    config: ConfigAgente
    at: datetime
    origem: str
    motivo: str


class ExecucaoResumo(_Contrato):
    tarefa_id: str
    tarefa: str
    estado: EstadoExecucao
    origem: Origem
    inicio: datetime
    fim: datetime | None = None
    custo_usd: float = 0.0
    resumo: str = ""


class EstadoAgente(_Contrato):
    """O que o JARVIS observa de cada agente."""

    id: str
    tipo: str
    nome: str
    descricao: str
    versao_codigo: str
    versao_config: int
    estado: Literal["ocioso", "trabalhando", "pausado", "sem_orcamento"]
    saude: Literal["ok", "degradado"]
    tarefas: dict[str, str]
    config: ConfigAgente
    execucoes_mes: int = 0
    falhas_mes: int = 0
    custo_mes_usd: float = 0.0
    ultimas: list[ExecucaoResumo] = Field(default_factory=list)
