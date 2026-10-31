"""Serviço de clientes: junta as fontes por precedência, registra a fonte de cada campo e guarda o último dado válido.

O banco do JARVIS é lido na hora; planilha, ERP e portais são lidos no agendamento (ou a pedido) e ficam guardados,
porque são lentos e, no caso do SERPRO, pagos. Se uma fonte falha, valem os últimos dados dela, marcados como antigos,
e o card mostra o aviso. Nenhum documento em claro vai para o log.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from loguru import logger

from ..contratos import CampoComFonte, ClienteConsolidado, ClienteResumo, Conflito, StatusFonte
from ..fontes.base import norm
from ..http import FonteIndisponivel
from .banco import BancoClientes
from .base import CAMPOS, GRUPOS, PRECEDENCIA, FonteCliente, documento, mascarado, para_log

GRUPO_DO_CAMPO = {campo: grupo for grupo, campos in GRUPOS.items() for campo in campos}


def _comparavel(v: Any) -> str:
    if isinstance(v, list | dict):
        return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
    return norm(str(v)).strip()


class ServicoClientes:
    def __init__(self, banco: BancoClientes, outras: list[FonteCliente], salt: str = "",
                 relogio: Callable[[], datetime] = datetime.now):
        self.banco = banco
        self.outras = outras          # planilha, ERP, portais: as que estiverem configuradas
        self.salt = salt
        self.relogio = relogio

    @property
    def fontes(self) -> list[FonteCliente]:
        return [self.banco, *self.outras]

    def listar(self) -> list[ClienteResumo]:
        return [ClienteResumo(id=i, nome=nome, documento_mascarado=mascarado(doc)) for i, doc, nome in self.banco.indice()]

    def atualizar(self) -> list[StatusFonte]:
        """Agendamento: traz para o índice os clientes que só existem na planilha ou no ERP e guarda o que cada fonte
        sabe de cada cliente. Uma fonte que falha fica com os dados anteriores e com o estado de erro."""
        for fonte in self.fontes:
            try:
                for c in fonte.listar():
                    if documento(c["documento"]):
                        self.banco.garantir(c["documento"], c.get("razao_social") or c["documento"], fonte.id)
            except Exception as e:  # noqa: BLE001 — uma fonte nunca derruba as outras
                self._falhou(fonte, e)
        docs = [doc for _, doc, _ in self.banco.indice()]
        for fonte in self.outras:
            try:
                for doc in docs:
                    dados = fonte.buscar(doc)
                    if dados:
                        self.banco.guardar_snapshot(doc, fonte.id, dados)
            except Exception as e:  # noqa: BLE001
                self._falhou(fonte, e, doc)
                continue
            self.banco.estado_fonte(fonte.id, fonte.nome, ok=True)
        return self.status()

    def _falhou(self, fonte: FonteCliente, e: Exception, doc: str | None = None) -> None:
        msg = f"{type(e).__name__}: {e}" if isinstance(e, FonteIndisponivel | ValueError) else type(e).__name__
        onde = f" (cliente {para_log(doc, self.salt)})" if doc else ""
        logger.warning("clientes: fonte {} falhou{}; valem os últimos dados válidos ({})", fonte.id, onde, msg)
        self.banco.estado_fonte(fonte.id, fonte.nome, ok=False, erro=msg)

    def status(self) -> list[StatusFonte]:
        estados = self.banco.estados()
        saida = []
        for f in self.outras:
            e = estados.get(f.id)
            saida.append(StatusFonte(id=f"cliente_{f.id}", nome=f.nome, ok=None if e is None else bool(e[2]),
                                     ultima_coleta=e and e[3], ultimo_sucesso=e and e[4], erro=e and e[5]))
        return saida

    def consolidar(self, cliente_id: int) -> ClienteConsolidado | None:
        achado = self.banco.documento_de(cliente_id)
        if achado is None:
            return None
        doc, nome_indice = achado
        estados = self.banco.estados()
        por_fonte: dict[str, tuple[dict[str, Any], datetime | None, bool, str]] = {}
        try:
            if dados := self.banco.buscar(doc):
                quando = dados.pop("_atualizado_em", None)
                por_fonte["banco"] = (dados, quando and datetime.fromisoformat(quando), False, self.banco.nome)
        except Exception as e:  # noqa: BLE001 — banco ilegível: o card mostra o resto e o aviso
            self._falhou(self.banco, e, doc)
        for f in self.outras:
            if snap := self.banco.snapshot(doc, f.id):
                dados, quando = snap
                estado = estados.get(f.id)
                antigo = bool(estado) and not estado[2]       # a última tentativa falhou
                por_fonte[f.id] = (dados, datetime.fromisoformat(quando), antigo, f.nome)

        campos: dict[str, CampoComFonte] = {
            "documento": CampoComFonte(valor=doc, fonte="indice", fonte_nome="cadastro do cliente")}
        conflitos: list[Conflito] = []
        for campo in CAMPOS:
            candidatos = [(fid, por_fonte[fid]) for fid in PRECEDENCIA[GRUPO_DO_CAMPO[campo]]
                          if fid in por_fonte and por_fonte[fid][0].get(campo) not in (None, "", [], {})]
            if not candidatos:
                continue
            fid, (dados, quando, antigo, nome) = candidatos[0]
            campos[campo] = CampoComFonte(valor=dados[campo], fonte=fid, fonte_nome=nome, atualizado_em=quando,
                                          antigo=antigo)
            valores = {f: d[campo] for f, (d, *_resto) in candidatos}
            if len({_comparavel(v) for v in valores.values()}) > 1:
                conflitos.append(Conflito(campo=campo, valores=valores))
        if "razao_social" not in campos:
            campos["razao_social"] = CampoComFonte(valor=nome_indice, fonte="indice", fonte_nome="cadastro do cliente")
        return ClienteConsolidado(id=cliente_id, campos=campos, conflitos=conflitos, fontes=self.status(),
                                  gerado_em=self.relogio())
