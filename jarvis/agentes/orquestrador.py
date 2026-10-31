"""Orquestrador: o JARVIS como cérebro dos agentes (service; a API e as ferramentas do cérebro só o chamam).

Só ele guarda as referências dos agentes, emite ordens, registra execuções, sela resultados na cadeia de auditoria do
JARVIS e publica os eventos para o HUD. Cada tarefa roda numa asyncio.Task própria, uma por agente por vez: quem
comanda espera um tempo limitado e, se a tarefa passar disso, recebe "em andamento" e a trava da sessão fica livre.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ..core.audit import AuditChain
from ..core.contracts import AgentResult, BudgetState, Route
from ..core.costs import CostLedger
from ..proactive.bus import ProactiveEvent
from .base import Agente
from .contratos import (
    AtualizacaoAgente,
    ConfigInvalida,
    EstadoAgente,
    Ordem,
    Origem,
    PedidoTarefa,
    ResultadoTarefa,
    SaidaTarefa,
    TarefaRecusada,
)
from .recursos import ConsultaConhecimento, GatewayClaude, Recursos, rota_do_modelo
from .registro import Registro

ESPERA_S = 20.0


class AgenteDesconhecido(KeyError):
    """Não há agente ativo com este id."""


def catalogo_padrao() -> dict[str, type[Agente]]:
    from .tributario.agente import AgenteTributario

    return {AgenteTributario.tipo: AgenteTributario}


def sha256_canonico(r: ResultadoTarefa) -> str:
    """sha256 do resultado sem os próprios selos (o que a verificação recalcula)."""
    canon = json.dumps(r.model_dump(mode="json", exclude={"conteudo_sha256", "audit_hash"}), sort_keys=True,
                       ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


class Orquestrador:
    def __init__(self, registro: Registro, audit: AuditChain, ledger: CostLedger, *, client: Any, salt: str,
                 pasta: Path, conhecimento: Any = None, catalogo: dict[str, type[Agente]] | None = None,
                 ativos: Iterable[str] = ("tributario",), espera_s: float = ESPERA_S):
        self.registro = registro
        self.audit = audit
        self.ledger = ledger
        self.espera_s = espera_s
        self.publicar: Callable[[ProactiveEvent], None] = lambda _ev: None   # o servidor liga ao EventBus
        self._catalogo = catalogo if catalogo is not None else catalogo_padrao()
        self._agentes: dict[str, Agente] = {}
        self._gateways: dict[str, GatewayClaude] = {}
        self._semaforos: dict[str, asyncio.Semaphore] = {}
        self._ocupado: dict[str, str] = {}      # agente → tarefa em execução
        self._fora_do_turno: set[str] = set()   # tarefas que terminam depois de quem comandou parar de esperar
        self._tarefas: set[asyncio.Task] = set()
        self._iniciar(list(ativos), client, salt, pasta, ConsultaConhecimento(conhecimento))

    # ---------- criar e restaurar ----------
    def _iniciar(self, ativos: list[str], client: Any, salt: str, pasta: Path, conhecimento) -> None:
        if n := self.registro.marcar_interrompidas():
            logger.warning(f"agentes: {n} execução(ões) interrompida(s) pelo encerramento anterior")
        for tipo in ativos:
            cls = self._catalogo.get(tipo)
            if cls is None:
                logger.warning(f"agentes: tipo desconhecido em JARVIS_AGENTES: {tipo}")
                continue
            if self.registro.criar(tipo, tipo, cls.config_padrao()):
                logger.info(f"agentes: {tipo} criado (configuração v1)")
            _, config = self.registro.config(tipo)
            if not cls.aceita_modelo(config.modelo):   # configuração de antes da regra de modelos do agente
                padrao = cls.config_padrao().modelo
                versao = self.registro.nova_versao(
                    tipo, config.model_copy(update={"modelo": padrao}), "sistema",
                    f"o {cls.nome} roda só em {', '.join(cls.modelos)}: {config.modelo} trocado por {padrao}")
                logger.info(f"agentes: {tipo} migrado para {padrao} (v{versao})")
            gateway = GatewayClaude(client, self.ledger, tipo, salt,
                                    lambda agente_id=tipo: self.registro.config(agente_id)[1].teto_mensal_usd)
            recursos = Recursos(claude=gateway if client is not None else None, conhecimento=conhecimento,
                                pasta=pasta / tipo, salt=salt)
            self._agentes[tipo] = cls(tipo, recursos)
            self._gateways[tipo] = gateway

    def ids(self) -> list[str]:
        return sorted(self._agentes)

    def _agente(self, agente_id: str) -> Agente:
        if agente_id not in self._agentes:
            raise AgenteDesconhecido(agente_id)
        return self._agentes[agente_id]

    def catalogo(self) -> dict[str, dict]:
        """agente → nome e tarefas (o manifesto das ferramentas do cérebro vem daqui)."""
        return {i: {"nome": a.nome, "tarefas": dict(a.tarefas)} for i, a in sorted(self._agentes.items())}

    # ---------- comandar ----------
    async def comandar(self, agente_id: str, pedido: PedidoTarefa, origem: Origem,
                       espera_s: float | None = None) -> ResultadoTarefa:
        """Emite a ordem e espera até `espera_s`; se passar, devolve a execução "em_andamento"."""
        agente = self._agente(agente_id)
        ordem = Ordem(agente_id=agente_id, pedido=pedido, origem=origem)
        versao, config = self.registro.config(agente_id)
        self.registro.iniciar(ordem, versao)
        task = asyncio.create_task(self._executar(agente, ordem, versao, config), name=f"agente-{ordem.id}")
        self._tarefas.add(task)
        task.add_done_callback(self._tarefas.discard)
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.espera_s if espera_s is None else espera_s)
        except TimeoutError:
            self._fora_do_turno.add(ordem.id)
            return self.registro.execucao(ordem.id)
        except asyncio.CancelledError:
            self._fora_do_turno.add(ordem.id)   # o cliente caiu: a tarefa segue, custo e selo não se perdem
            raise

    async def _executar(self, agente: Agente, ordem: Ordem, versao: int, config) -> ResultadoTarefa:
        inicio = datetime.now()
        semaforo = self._semaforos.setdefault(agente.id, asyncio.Semaphore(1))
        gateway = self._gateways[agente.id]
        saida, erro = None, None
        async with semaforo:
            self._ocupado[agente.id] = ordem.id
            gateway.zerar()
            try:
                if self.registro.pausado(agente.id):
                    raise TarefaRecusada(f"o {agente.nome} está pausado")
                saida = await agente.executar(ordem.pedido, config)
                estado = "concluida"
            except TarefaRecusada as e:
                estado, erro = "recusada", str(e)
            except Exception as e:  # noqa: BLE001 — falha de agente vira execução "falhou", nunca derruba o JARVIS
                logger.exception(f"agente {agente.id}: tarefa {ordem.pedido.tarefa}")
                estado, erro = "falhou", f"{type(e).__name__}: {e}"[:300]
            finally:
                self._ocupado.pop(agente.id, None)
        saida = saida or SaidaTarefa(resumo="")
        resultado = ResultadoTarefa(
            tarefa_id=ordem.id, agente_id=agente.id, tarefa=ordem.pedido.tarefa, origem=ordem.origem, estado=estado,
            versao_config=versao, versao_codigo=agente.versao_codigo, resumo=saida.resumo,
            resumo_voz=saida.resumo_voz, saida=saida.saida, modelo=gateway.modelo, custo_usd=round(gateway.custo, 6),
            inicio=inicio, fim=datetime.now(), arquivo=saida.arquivo, erro=erro,
        )
        self._selar(resultado)
        self.registro.concluir(resultado)
        self._avisar_fim(agente, resultado)
        return resultado

    def _selar(self, r: ResultadoTarefa) -> None:
        r.conteudo_sha256 = sha256_canonico(r)
        selo = self.audit.seal(AgentResult(
            session_id=f"agente-{r.agente_id}",
            route=Route.LOCAL if r.modelo == "regras" else rota_do_modelo(r.modelo), model=r.modelo,
            text=f"tarefa {r.tarefa_id} {r.tarefa} {r.estado} sha256={r.conteudo_sha256}",
            cost_usd=r.custo_usd, stop_reason=r.estado,
        ))
        r.audit_hash = selo.audit_hash

    def _avisar_fim(self, agente: Agente, r: ResultadoTarefa) -> None:
        """Eventos terminais, com texto montado pelo código (nunca pelo modelo): podem ser falados."""
        fora = r.tarefa_id in self._fora_do_turno
        self._fora_do_turno.discard(r.tarefa_id)
        tarefa = r.tarefa.replace("_", " ")
        if r.estado == "concluida":
            if not fora:
                return   # quem comandou ainda está no turno e conta o resultado
            texto = f"O {agente.nome} concluiu: {tarefa}. {r.resumo_voz or 'O resultado está pronto.'}"
            ev = ProactiveEvent(kind="agente", nivel="info", titulo=agente.nome, texto=texto, falar=True)
        elif r.estado == "recusada":
            ev = ProactiveEvent(kind="agente", nivel="aviso", titulo=agente.nome, falar=fora,
                                texto=f"O {agente.nome} recusou {tarefa}: {r.erro}.")
        else:
            ev = ProactiveEvent(kind="agente", nivel="aviso", titulo=agente.nome, falar=fora,
                                texto=f"O {agente.nome} não conseguiu concluir {tarefa}. Detalhes em /agentes.")
        self.publicar(ev)

    async def encerrar(self) -> None:
        """Desligamento: cancela o que está rodando (o próximo boot marca como interrompida)."""
        for task in list(self._tarefas):
            task.cancel()
        await asyncio.gather(*self._tarefas, return_exceptions=True)

    # ---------- observar ----------
    def observar(self, agente_id: str) -> EstadoAgente:
        agente = self._agente(agente_id)
        versao, config = self.registro.config(agente_id)
        execucoes, falhas, _ = self.registro.mes(agente_id)
        custo = self.ledger.month_total(sessao=f"agente-{agente_id}")
        ultimas = self.registro.ultimas(agente_id, 5)
        if self.registro.pausado(agente_id):
            estado = "pausado"
        elif agente_id in self._ocupado:
            estado = "trabalhando"
        elif self.ledger.state() is BudgetState.CAP_REACHED or custo >= config.teto_mensal_usd:
            estado = "sem_orcamento"
        else:
            estado = "ocioso"
        degradado = bool(ultimas) and sum(e.estado == "falhou" for e in ultimas) / len(ultimas) > 0.5
        return EstadoAgente(
            id=agente_id, tipo=agente.tipo, nome=agente.nome, descricao=agente.descricao,
            versao_codigo=agente.versao_codigo, versao_config=versao, estado=estado,
            saude="degradado" if degradado else "ok", tarefas=dict(agente.tarefas), config=config,
            execucoes_mes=execucoes, falhas_mes=falhas, custo_mes_usd=round(custo, 4), ultimas=ultimas,
        )

    def observar_todos(self) -> list[EstadoAgente]:
        return [self.observar(i) for i in self.ids()]

    def resultado(self, tarefa_id: str) -> ResultadoTarefa | None:
        return self.registro.execucao(tarefa_id)

    def ultima(self, agente_id: str | None = None) -> ResultadoTarefa | None:
        tarefa_id = self.registro.ultima(agente_id)
        return self.registro.execucao(tarefa_id) if tarefa_id else None

    def verificar(self, tarefa_id: str) -> dict:
        """Recalcula o sha256 do resultado gravado e confere o selo na cadeia de auditoria."""
        r = self.registro.execucao(tarefa_id)
        if r is None or not r.conteudo_sha256:
            raise KeyError(tarefa_id)
        sha = sha256_canonico(r)
        selo = self.audit.encontrar(r.audit_hash) if r.audit_hash else None
        return {
            "tarefa_id": tarefa_id,
            "conteudo_ok": sha == r.conteudo_sha256,
            "na_cadeia": bool(selo) and f"sha256={sha}" in selo.get("text", ""),
            "cadeia_integra": self.audit.verify(),
        }

    # ---------- atualizar ----------
    def atualizar(self, agente_id: str, mudanca: AtualizacaoAgente, origem: str) -> dict:
        """Nova versão da configuração (append-only). Sem mudança de fato, nada é gravado."""
        agente = self._agente(agente_id)
        versao, atual = self.registro.config(agente_id)
        self._conferir_modelo(agente, mudanca.aplicar(atual).modelo)
        diff = mudanca.diff(atual)
        if diff:
            versao = self.registro.nova_versao(agente_id, mudanca.aplicar(atual), origem, mudanca.motivo)
            self.publicar(ProactiveEvent(kind="agente", titulo=agente.nome, falar=False,
                                         texto=f"Configuração do {agente.nome} atualizada para a v{versao}: "
                                               f"{', '.join(diff)}."))
        return {"agente": agente_id, "versao": versao, "mudou": diff}

    @staticmethod
    def _conferir_modelo(agente: Agente, modelo: str) -> None:
        if not agente.aceita_modelo(modelo):
            raise ConfigInvalida(f"o {agente.nome} só roda em {', '.join(agente.modelos)}; {modelo} não é aceito")

    def reverter(self, agente_id: str, versao: int, origem: str, motivo: str) -> dict:
        agente = self._agente(agente_id)
        alvo = next((v for v in self.registro.versoes(agente_id) if v.versao == versao), None)
        if alvo is not None:
            self._conferir_modelo(agente, alvo.config.modelo)
        nova = self.registro.reverter(agente_id, versao, origem, motivo)
        self.publicar(ProactiveEvent(kind="agente", titulo=agente.nome, falar=False,
                                     texto=f"Configuração do {agente.nome} revertida para a da v{versao} (v{nova})."))
        return {"agente": agente_id, "versao": nova, "revertida_para": versao}

    def pausar(self, agente_id: str, pausado: bool) -> dict:
        agente = self._agente(agente_id)
        self.registro.pausar(agente_id, pausado)
        self.publicar(ProactiveEvent(kind="agente", titulo=agente.nome, falar=False,
                                     texto=f"O {agente.nome} foi {'pausado' if pausado else 'retomado'}."))
        return {"agente": agente_id, "pausado": pausado}
