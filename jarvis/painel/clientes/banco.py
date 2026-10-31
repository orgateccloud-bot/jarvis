"""Banco próprio do JARVIS (fonte principal e padrão): cadastro do cliente no jarvis.db, editável pela API.

clientes_indice é a identidade de todos os clientes, venham de onde vierem (banco, planilha, ERP); as outras tabelas
guardam o que o escritório cadastrou aqui. cliente_snapshot e clientes_fontes guardam o último dado válido e o estado
das outras fontes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..contratos import ClienteEntrada
from .base import FonteCliente, documento

ESQUEMA = 1


class BancoClientes(FonteCliente):
    id, nome = "banco", "banco do JARVIS"

    def __init__(self, db_path: Path, relogio=datetime.now):
        self.db_path = db_path
        self.relogio = relogio
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS clientes_schema (modulo TEXT PRIMARY KEY, versao INTEGER NOT NULL)")
            c.execute("""CREATE TABLE IF NOT EXISTS clientes_indice (
                id INTEGER PRIMARY KEY AUTOINCREMENT, documento TEXT UNIQUE NOT NULL, nome TEXT NOT NULL,
                origem TEXT NOT NULL, criado_em TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS clientes (
                documento TEXT PRIMARY KEY, razao_social TEXT NOT NULL, regime_tributario TEXT,
                cnae_principal TEXT, cnaes_secundarios TEXT, atividades TEXT, ufs_operacao TEXT, obrigacoes TEXT,
                contato TEXT, atualizado_em TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cliente_certidoes (
                documento TEXT NOT NULL, tipo TEXT NOT NULL, situacao TEXT NOT NULL, validade TEXT, observacao TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cliente_contratos (
                documento TEXT NOT NULL, descricao TEXT NOT NULL, honorario_mensal REAL, vencimento_dia INTEGER,
                inicio TEXT, fim TEXT, reajuste TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cliente_pendencias (
                documento TEXT NOT NULL, descricao TEXT NOT NULL, prazo TEXT, status TEXT NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS cliente_snapshot (
                documento TEXT NOT NULL, fonte_id TEXT NOT NULL, quando TEXT NOT NULL, dados_json TEXT NOT NULL,
                PRIMARY KEY (documento, fonte_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS clientes_fontes (
                fonte_id TEXT PRIMARY KEY, nome TEXT NOT NULL, ok INTEGER, ultima_coleta TEXT,
                ultimo_sucesso TEXT, erro TEXT)""")
            c.execute("INSERT OR IGNORE INTO clientes_schema VALUES ('clientes', ?)", (ESQUEMA,))

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _agora(self) -> str:
        return self.relogio().isoformat(timespec="seconds")

    # ---------- índice (identidade dos clientes de todas as fontes) ----------
    def garantir(self, doc: str, nome: str, origem: str) -> int:
        doc = documento(doc)
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO clientes_indice (documento, nome, origem, criado_em) VALUES (?,?,?,?)",
                      (doc, nome, origem, self._agora()))
            return c.execute("SELECT id FROM clientes_indice WHERE documento = ?", (doc,)).fetchone()[0]

    def indice(self) -> list[tuple[int, str, str]]:
        with self._conn() as c:
            return c.execute("SELECT id, documento, nome FROM clientes_indice ORDER BY nome").fetchall()

    def documento_de(self, cliente_id: int) -> tuple[str, str] | None:
        with self._conn() as c:
            row = c.execute("SELECT documento, nome FROM clientes_indice WHERE id = ?", (cliente_id,)).fetchone()
        return (row[0], row[1]) if row else None

    # ---------- cadastro do escritório ----------
    def salvar(self, e: ClienteEntrada) -> int:
        doc = documento(e.documento)
        cliente_id = self.garantir(doc, e.razao_social, "banco")
        contato = {k: v for k, v in {"nome": e.contato_nome, "email": e.contato_email,
                                     "telefone": e.contato_telefone}.items() if v}
        with self._lock, self._conn() as c:
            c.execute("UPDATE clientes_indice SET nome = ? WHERE documento = ?", (e.razao_social, doc))
            c.execute("INSERT OR REPLACE INTO clientes VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (doc, e.razao_social, e.regime_tributario, e.cnae_principal, json.dumps(e.cnaes_secundarios),
                       e.atividades, json.dumps(e.ufs_operacao), json.dumps(e.obrigacoes),
                       json.dumps(contato, ensure_ascii=False), self._agora()))
            for tabela in ("cliente_certidoes", "cliente_contratos", "cliente_pendencias"):
                c.execute(f"DELETE FROM {tabela} WHERE documento = ?", (doc,))  # nosec B608 — nome de tabela fixo
            c.executemany("INSERT INTO cliente_certidoes VALUES (?,?,?,?,?)",
                          [(doc, x.tipo, x.situacao, x.validade and x.validade.isoformat(), x.observacao)
                           for x in e.certidoes])
            c.executemany("INSERT INTO cliente_contratos VALUES (?,?,?,?,?,?,?)",
                          [(doc, x.descricao, x.honorario_mensal, x.vencimento_dia, x.inicio and x.inicio.isoformat(),
                            x.fim and x.fim.isoformat(), x.reajuste) for x in e.contratos])
            c.executemany("INSERT INTO cliente_pendencias VALUES (?,?,?,?)",
                          [(doc, x.descricao, x.prazo and x.prazo.isoformat(), x.status) for x in e.pendencias])
        return cliente_id

    def listar(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT documento, razao_social FROM clientes").fetchall()
        return [{"documento": d, "razao_social": r} for d, r in rows]

    def buscar(self, doc: str) -> dict[str, Any] | None:
        doc = documento(doc)
        with self._conn() as c:
            row = c.execute("SELECT razao_social, regime_tributario, cnae_principal, cnaes_secundarios, atividades, "
                            "ufs_operacao, obrigacoes, contato, atualizado_em FROM clientes WHERE documento = ?",
                            (doc,)).fetchone()
            if row is None:
                return None
            certidoes = c.execute("SELECT tipo, situacao, validade, observacao FROM cliente_certidoes "
                                  "WHERE documento = ?", (doc,)).fetchall()
            contratos = c.execute("SELECT descricao, honorario_mensal, vencimento_dia, inicio, fim, reajuste "
                                  "FROM cliente_contratos WHERE documento = ?", (doc,)).fetchall()
            pendencias = c.execute("SELECT descricao, prazo, status FROM cliente_pendencias WHERE documento = ?",
                                   (doc,)).fetchall()
        return {
            "razao_social": row[0], "regime_tributario": row[1], "cnae_principal": row[2],
            "cnaes_secundarios": json.loads(row[3] or "[]"), "atividades": row[4],
            "ufs_operacao": json.loads(row[5] or "[]"), "obrigacoes": json.loads(row[6] or "[]"),
            "contato": json.loads(row[7] or "{}"),
            "certidoes": [dict(zip(("tipo", "situacao", "validade", "observacao"), r, strict=True)) for r in certidoes],
            "contratos": [dict(zip(("descricao", "honorario_mensal", "vencimento_dia", "inicio", "fim", "reajuste"), r,
                                   strict=True)) for r in contratos],
            "pendencias": [dict(zip(("descricao", "prazo", "status"), r, strict=True)) for r in pendencias],
            "_atualizado_em": row[8],
        }

    # ---------- último dado válido e estado das outras fontes ----------
    def guardar_snapshot(self, doc: str, fonte_id: str, dados: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO cliente_snapshot VALUES (?,?,?,?)",
                      (documento(doc), fonte_id, self._agora(), json.dumps(dados, ensure_ascii=False, default=str)))

    def snapshot(self, doc: str, fonte_id: str) -> tuple[dict[str, Any], str] | None:
        with self._conn() as c:
            row = c.execute("SELECT dados_json, quando FROM cliente_snapshot WHERE documento = ? AND fonte_id = ?",
                            (documento(doc), fonte_id)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def estado_fonte(self, fonte_id: str, nome: str, ok: bool, erro: str | None = None) -> None:
        agora = self._agora()
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO clientes_fontes (fonte_id, nome, ok, ultima_coleta, ultimo_sucesso, erro)
                         VALUES (?,?,?,?,?,?) ON CONFLICT(fonte_id) DO UPDATE SET nome=excluded.nome, ok=excluded.ok,
                         ultima_coleta=excluded.ultima_coleta, erro=excluded.erro,
                         ultimo_sucesso=COALESCE(excluded.ultimo_sucesso, clientes_fontes.ultimo_sucesso)""",
                      (fonte_id, nome, int(ok), agora, agora if ok else None, None if ok else (erro or "")[:500]))

    def estados(self) -> dict[str, tuple]:
        with self._conn() as c:
            rows = c.execute("SELECT fonte_id, nome, ok, ultima_coleta, ultimo_sucesso, erro FROM clientes_fontes")
            return {r[0]: r for r in rows.fetchall()}
