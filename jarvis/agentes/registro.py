"""Registro dos agentes (SQLite, no mesmo jarvis.db): agentes, configuração versionada e execuções.

Configuração append-only: atualizar ou reverter cria uma versão nova, nada é apagado. O esquema tem a própria tabela
de versão (agentes_schema): o PRAGMA user_version do banco é do ledger de custos.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .contratos import ConfigAgente, ExecucaoResumo, Ordem, ResultadoTarefa, VersaoConfig

ESQUEMA = 1


class OrdemRepetida(Exception):
    """Uma ordem com este id já foi registrada: não roda de novo."""


class Registro:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS agentes_schema (modulo TEXT PRIMARY KEY, versao INTEGER NOT NULL)")
            c.execute(
                """CREATE TABLE IF NOT EXISTS agentes (
                    id TEXT PRIMARY KEY, tipo TEXT NOT NULL, criado_em TEXT NOT NULL,
                    pausado INTEGER NOT NULL DEFAULT 0)"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS agente_config (
                    agente_id TEXT NOT NULL, versao INTEGER NOT NULL, at TEXT NOT NULL, origem TEXT NOT NULL,
                    motivo TEXT NOT NULL, config_json TEXT NOT NULL, PRIMARY KEY (agente_id, versao))"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS agente_execucoes (
                    tarefa_id TEXT PRIMARY KEY, agente_id TEXT NOT NULL, tarefa TEXT NOT NULL,
                    origem TEXT NOT NULL, estado TEXT NOT NULL, versao_config INTEGER NOT NULL,
                    inicio TEXT NOT NULL, fim TEXT, custo_usd REAL DEFAULT 0, resultado_json TEXT)"""
            )
            c.execute("INSERT OR IGNORE INTO agentes_schema VALUES ('agentes', ?)", (ESQUEMA,))

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ---------- agentes ----------
    def criar(self, agente_id: str, tipo: str, config: ConfigAgente) -> bool:
        """Registra o agente com a configuração v1. False se ele já existia (nada muda)."""
        agora = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            if c.execute("SELECT 1 FROM agentes WHERE id = ?", (agente_id,)).fetchone():
                return False
            c.execute("INSERT INTO agentes (id, tipo, criado_em) VALUES (?,?,?)", (agente_id, tipo, agora))
            c.execute("INSERT INTO agente_config VALUES (?,?,?,?,?,?)",
                      (agente_id, 1, agora, "criacao", "configuração inicial", config.model_dump_json()))
        return True

    def agentes(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, tipo, pausado FROM agentes ORDER BY id").fetchall()
        return [{"id": r[0], "tipo": r[1], "pausado": bool(r[2])} for r in rows]

    def pausado(self, agente_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT pausado FROM agentes WHERE id = ?", (agente_id,)).fetchone()
        return bool(row and row[0])

    def pausar(self, agente_id: str, pausado: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE agentes SET pausado = ? WHERE id = ?", (int(pausado), agente_id))

    # ---------- configuração versionada ----------
    def config(self, agente_id: str) -> tuple[int, ConfigAgente]:
        with self._conn() as c:
            row = c.execute("SELECT versao, config_json FROM agente_config WHERE agente_id = ? "
                            "ORDER BY versao DESC LIMIT 1", (agente_id,)).fetchone()
        if row is None:
            raise KeyError(agente_id)
        return row[0], ConfigAgente.model_validate_json(row[1])

    def versoes(self, agente_id: str) -> list[VersaoConfig]:
        with self._conn() as c:
            rows = c.execute("SELECT versao, config_json, at, origem, motivo FROM agente_config "
                             "WHERE agente_id = ? ORDER BY versao", (agente_id,)).fetchall()
        return [VersaoConfig(versao=r[0], config=ConfigAgente.model_validate_json(r[1]), at=r[2], origem=r[3],
                             motivo=r[4]) for r in rows]

    def nova_versao(self, agente_id: str, config: ConfigAgente, origem: str, motivo: str) -> int:
        with self._lock, self._conn() as c:
            atual = c.execute("SELECT COALESCE(MAX(versao), 0) FROM agente_config WHERE agente_id = ?",
                              (agente_id,)).fetchone()[0]
            if not atual:
                raise KeyError(agente_id)
            c.execute("INSERT INTO agente_config VALUES (?,?,?,?,?,?)",
                      (agente_id, atual + 1, datetime.now().isoformat(timespec="seconds"), origem, motivo,
                       config.model_dump_json()))
        return atual + 1

    def reverter(self, agente_id: str, versao: int, origem: str, motivo: str) -> int:
        """Volta à configuração de uma versão antiga criando uma versão nova igual a ela."""
        antiga = next((v for v in self.versoes(agente_id) if v.versao == versao), None)
        if antiga is None:
            raise KeyError(f"{agente_id} v{versao}")
        return self.nova_versao(agente_id, antiga.config, origem, f"reverte para v{versao}: {motivo}")

    # ---------- execuções ----------
    def iniciar(self, ordem: Ordem, versao_config: int) -> None:
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO agente_execucoes (tarefa_id, agente_id, tarefa, origem, estado, versao_config, "
                    "inicio) VALUES (?,?,?,?,?,?,?)",
                    (ordem.id, ordem.agente_id, ordem.pedido.tarefa, ordem.origem, "em_andamento", versao_config,
                     datetime.now().isoformat()),
                )
        except sqlite3.IntegrityError as e:
            raise OrdemRepetida(ordem.id) from e

    def concluir(self, r: ResultadoTarefa) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE agente_execucoes SET estado = ?, fim = ?, custo_usd = ?, resultado_json = ? "
                      "WHERE tarefa_id = ?",
                      (r.estado, r.fim.isoformat() if r.fim else None, r.custo_usd, r.model_dump_json(), r.tarefa_id))

    def execucao(self, tarefa_id: str) -> ResultadoTarefa | None:
        """O resultado gravado; None se não existe. Em andamento, sem resultado ainda, volta só o cabeçalho."""
        with self._conn() as c:
            row = c.execute("SELECT agente_id, tarefa, origem, estado, versao_config, inicio, resultado_json "
                            "FROM agente_execucoes WHERE tarefa_id = ?", (tarefa_id,)).fetchone()
        if row is None:
            return None
        if row[6]:
            return ResultadoTarefa.model_validate_json(row[6])
        return ResultadoTarefa(tarefa_id=tarefa_id, agente_id=row[0], tarefa=row[1], origem=row[2], estado=row[3],
                               versao_config=row[4], versao_codigo="", inicio=row[5])

    def ultima(self, agente_id: str | None = None) -> str | None:
        """Id da execução mais recente (de um agente ou de todos)."""
        with self._conn() as c:
            row = c.execute("SELECT tarefa_id FROM agente_execucoes WHERE ? IS NULL OR agente_id = ? "
                            "ORDER BY inicio DESC LIMIT 1", (agente_id, agente_id)).fetchone()
        return row[0] if row else None

    def ultimas(self, agente_id: str, n: int = 5) -> list[ExecucaoResumo]:
        with self._conn() as c:
            rows = c.execute("SELECT tarefa_id, tarefa, estado, origem, inicio, fim, custo_usd, resultado_json "
                             "FROM agente_execucoes WHERE agente_id = ? ORDER BY inicio DESC LIMIT ?",
                             (agente_id, n)).fetchall()
        return [ExecucaoResumo(tarefa_id=r[0], tarefa=r[1], estado=r[2], origem=r[3], inicio=r[4], fim=r[5],
                               custo_usd=r[6] or 0.0,
                               resumo=json.loads(r[7]).get("resumo", "")[:200] if r[7] else "") for r in rows]

    def mes(self, agente_id: str, now: datetime | None = None) -> tuple[int, int, float]:
        """(execuções, falhas, custo em US$) do agente no mês."""
        prefixo = (now or datetime.now()).strftime("%Y-%m") + "%"
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(estado = 'falhou'), 0), COALESCE(SUM(custo_usd), 0) "
                "FROM agente_execucoes WHERE agente_id = ? AND inicio LIKE ?", (agente_id, prefixo),
            ).fetchone()
        return int(row[0]), int(row[1]), float(row[2])

    def marcar_interrompidas(self) -> int:
        """No boot: o que ficou "em_andamento" morreu com o processo anterior."""
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE agente_execucoes SET estado = 'interrompida', fim = ? "
                            "WHERE estado = 'em_andamento'", (datetime.now().isoformat(),))
        return cur.rowcount
