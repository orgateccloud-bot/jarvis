"""Coleta periódica das fontes oficiais, com o último dado válido de cada uma guardado no SQLite.

Uma fonte que falha não apaga nada: os itens anteriores dela continuam valendo, o estado vira erro (com a mensagem) e
o erro vai para o log. Uma fonte nunca derruba as outras nem o painel.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from .contratos import ItemFiscal, StatusFonte
from .fontes import FonteConfig, coletor
from .fontes.base import Coletor
from .http import Fetch, buscar

ESQUEMA = 1


class ArmazemPainel:
    """painel_fontes: estado de cada fonte; painel_itens: os itens da última coleta com sucesso de cada fonte."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS painel_schema (modulo TEXT PRIMARY KEY, versao INTEGER NOT NULL)")
            c.execute("""CREATE TABLE IF NOT EXISTS painel_fontes (
                id TEXT PRIMARY KEY, nome TEXT NOT NULL, url TEXT, ligada INTEGER NOT NULL, ok INTEGER,
                ultima_coleta TEXT, ultimo_sucesso TEXT, erro TEXT, itens INTEGER DEFAULT 0, nota TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS painel_itens (
                fonte_id TEXT PRIMARY KEY, coletado_em TEXT NOT NULL, itens_json TEXT NOT NULL)""")
            c.execute("INSERT OR IGNORE INTO painel_schema VALUES ('painel', ?)", (ESQUEMA,))

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def registrar(self, cfg: FonteConfig) -> None:
        """Cria ou atualiza o cadastro da fonte (nome, endereço, ligada, nota) sem mexer no histórico."""
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO painel_fontes (id, nome, url, ligada, nota) VALUES (?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, url=excluded.url,
                         ligada=excluded.ligada, nota=excluded.nota""",
                      (cfg.id, cfg.nome, cfg.url, int(cfg.ligada), cfg.nota))

    def sucesso(self, fonte_id: str, itens: list[ItemFiscal], quando: datetime) -> None:
        iso = quando.isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO painel_itens VALUES (?,?,?)",
                      (fonte_id, iso, json.dumps([i.model_dump(mode="json") for i in itens], ensure_ascii=False)))
            c.execute("UPDATE painel_fontes SET ok=1, ultima_coleta=?, ultimo_sucesso=?, erro=NULL, itens=? "
                      "WHERE id=?", (iso, iso, len(itens), fonte_id))

    def falha(self, fonte_id: str, erro: str, quando: datetime) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE painel_fontes SET ok=0, ultima_coleta=?, erro=? WHERE id=?",
                      (quando.isoformat(timespec="seconds"), erro[:500], fonte_id))

    def itens(self, ids: set[str] | None = None) -> list[ItemFiscal]:
        with self._conn() as c:
            rows = c.execute("SELECT fonte_id, itens_json FROM painel_itens").fetchall()
        return [ItemFiscal.model_validate(i) for fid, js in rows if ids is None or fid in ids for i in json.loads(js)]

    def status(self) -> list[StatusFonte]:
        with self._conn() as c:
            rows = c.execute("SELECT id, nome, url, ligada, ok, ultima_coleta, ultimo_sucesso, erro, itens, nota "
                             "FROM painel_fontes ORDER BY rowid").fetchall()
        return [StatusFonte(id=r[0], nome=r[1], url=r[2], ligada=bool(r[3]), ok=None if r[4] is None else bool(r[4]),
                            ultima_coleta=r[5], ultimo_sucesso=r[6], erro=r[7], itens=r[8] or 0, nota=r[9])
                for r in rows]


class ServicoColeta:
    def __init__(self, armazem: ArmazemPainel, fontes: list[FonteConfig], fetch: Fetch = buscar,
                 relogio: Callable[[], datetime] = datetime.now):
        self.armazem = armazem
        self.fontes = fontes
        self.fetch = fetch
        self.relogio = relogio
        self._coletores: dict[str, Coletor] = {}   # um por fonte, para os caches internos (ex.: datas do CONFAZ)
        self._lock = threading.Lock()                # uma coleta por vez (agendada ou pedida pelo usuário)
        self.ids_ativos = {f.id for f in fontes}
        for cfg in fontes:
            armazem.registrar(cfg)

    def _coletor(self, cfg: FonteConfig) -> Coletor:
        if cfg.id not in self._coletores:
            self._coletores[cfg.id] = coletor(cfg)
        return self._coletores[cfg.id]

    def coletar(self, so: set[str] | None = None) -> list[StatusFonte]:
        """Coleta cada fonte ligada, isoladamente. Devolve o estado de todas."""
        with self._lock:
            for cfg in self.fontes:
                if not cfg.ligada or (so and cfg.id not in so):
                    continue
                agora = self.relogio()
                try:
                    itens = self._coletor(cfg).coletar(self.fetch, agora.date())
                except Exception as e:  # noqa: BLE001 — fonte com problema não derruba as outras
                    msg = f"{type(e).__name__}: {e}"
                    logger.warning("painel: fonte {} falhou, mantidos os últimos dados válidos ({})", cfg.id, msg)
                    self.armazem.falha(cfg.id, msg, agora)
                    continue
                self.armazem.sucesso(cfg.id, itens, agora)
                logger.info("painel: fonte {} coletada ({} itens)", cfg.id, len(itens))
        return self.status()

    def itens(self) -> list[ItemFiscal]:
        return self.armazem.itens(self.ids_ativos)

    def status(self) -> list[StatusFonte]:
        return [s for s in self.armazem.status() if s.id in self.ids_ativos]

    def hoje(self) -> date:
        return self.relogio().date()


async def repetir(tarefa: Callable[[], object], intervalo_s: float, nome: str, espera_inicial_s: float = 20.0) -> None:
    """Laço agendado: a primeira execução sai logo depois da subida da API; depois, a cada intervalo. Nunca morre."""
    await asyncio.sleep(espera_inicial_s)
    while True:
        try:
            await asyncio.to_thread(tarefa)
        except Exception:  # noqa: BLE001 — o laço agendado nunca pode morrer
            logger.exception("painel: {} (execução agendada)", nome)
        await asyncio.sleep(intervalo_s)


async def run_coleta(servico: ServicoColeta, intervalo_s: float, espera_inicial_s: float = 20.0) -> None:
    await repetir(servico.coletar, intervalo_s, "coleta das fontes fiscais", espera_inicial_s)
