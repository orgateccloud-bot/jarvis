"""Índice da base (R6): SQLite FTS5 em <base>/_indice/base.db, incremental por arquivo; BM25 em memória como reserva.

Os dois motores indexam a mesma sequência de termos (tokens(): minúsculas, sem acento, sem stopwords, plural
reduzido), então o ranking do FTS5 fica próximo do BM25 antigo. No FTS5 o índice mora em disco: a RAM do JARVIS
não cresce com a base (só o cache do SQLite, limitado a 8 MB).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

VERSAO = "3"          # muda quando tokens() ou o esquema mudam: o índice é refeito do zero
CACHE_KB = 8000
_BLOCO = 20           # rowid do trecho = id do documento << _BLOCO | posição (apagar um documento é um intervalo)

_STOP_TXT = (
    "a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para com sem sob "
    "que se e ou ao aos à às é ser sao foi como mais menos qual quais quando onde sobre entre ate este esta "
    "esse essa isso isto aquele aquela seu sua seus suas lhe lhes nao sim ja tambem me te nos voce diz fala "
    "art artigo lei"
)
_STOP = frozenset(_STOP_TXT.split())
# termos da pergunta → palavras que a lei usa (ex.: o art. 173 do CTN não usa a palavra "decadência")
SINONIMOS = {
    "decadencia": "direito constituir credito tributario extingue cinco anos lancamento",
    "prescricao": "acao cobranca credito tributario prescreve cinco anos constituicao definitiva",
    "mei": "microempreendedor individual",
    "simples": "simples nacional microempresa pequeno porte",
    "imunidade": "vedado instituir impostos",
    "isencao": "isencao exclusao credito tributario",
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _radical(tok: str) -> str:
    if len(tok) > 5:
        for suf, troca in (("coes", "cao"), ("oes", "ao"), ("ais", "al"), ("eis", "el")):
            if tok.endswith(suf):
                return tok[: -len(suf)] + troca
    return tok[:-1] if len(tok) > 4 and tok.endswith("s") else tok


def tokens(texto: str) -> list[str]:
    return [_radical(t) for t in re.findall(r"[a-z0-9]+", norm(texto)) if len(t) > 1 and t not in _STOP]


def termos_da_consulta(consulta: str) -> list[str]:
    q = norm(consulta)
    termos = tokens(consulta)
    for chave, extra in SINONIMOS.items():
        if chave in q:
            termos += tokens(extra)
    return list(dict.fromkeys(termos))


def chave_rotulo(rotulo: str) -> str:
    """ "Súmula Vinculante 8 (parte 2)" → "sumula vinculante 8"; "Art. 174-A" → "art 174 a"; "SÚMULA 603" → "sumula 603"."""
    return re.sub(r"[^a-z0-9]+", " ", norm(rotulo.split(" (")[0])).strip()


# item citado pelo número na pergunta ("art. 173", "súmula vinculante 8", "tema repetitivo 1001", "IAC 5"); o número
# de um dígito não vira termo de busca, então o item é achado pela chave do rótulo
_CITACOES = (
    (re.compile(r"\bart(?:igo)?\.?\s*(\d+)"), "art {}"),
    (re.compile(r"\bsumula\s+(vinculante\s+)?(?:n[.o]?\s*)?(\d+)"), "sumula {}{}"),
    (re.compile(r"\btema\s+(repetitivo\s+)?(?:n[.o]?\s*)?(\d+)"), "tema {}{}"),
    (re.compile(r"\biac\s+(?:n[.o]?\s*)?(\d+)"), "iac {}"),
)


def chaves_citadas(consulta: str) -> list[str]:
    q = re.sub(r"[º°]", "o", norm(consulta))
    chaves = []
    for rx, modelo in _CITACOES:
        for m in rx.finditer(q):
            grupos = [g.strip() + " " if g and not g.isdigit() else (g or "") for g in m.groups()]
            chave = re.sub(r"\s+", " ", modelo.format(*grupos)).strip()
            chaves.append(chave)
            if chave.startswith("tema ") and "repetitivo" not in chave:   # "tema 1001 do STJ" = tema repetitivo
                chaves.append(chave.replace("tema ", "tema repetitivo ", 1))
    return list(dict.fromkeys(chaves))


@dataclass(frozen=True)
class Trecho:
    fonte: str        # título do documento
    rotulo: str       # "Art. 173", "Anexo I", "Súmula Vinculante 8", "parágrafo 3"
    arquivo: str      # caminho relativo à base
    area: str
    texto: str
    url: str = ""
    baixado_em: str = ""
    situacao: str = ""
    vigencia: str = ""
    uf: str = ""
    tipo: str = ""
    esfera: str = ""
    fonte_id: str = ""
    atual: bool = True
    aviso: str = ""


@dataclass
class Documento:
    """O que o índice guarda de um arquivo: metadados (cabeçalho + catálogo) e os trechos já cortados."""

    caminho: str
    hash: str
    titulo: str
    area: str
    fonte_id: str = ""
    url: str = ""
    baixado_em: str = ""
    tipo: str = ""
    esfera: str = ""
    uf: str = ""
    situacao: str = ""
    vig_ini: str = ""        # ISO; vazio = sem data
    vig_fim: str = ""
    atual: bool = True
    trechos: list[tuple[str, str, str, str]] = field(default_factory=list)   # (rótulo, texto, situação, url)


_META = ("caminho", "hash", "titulo", "area", "fonte_id", "url", "baixado_em", "tipo", "esfera", "uf", "situacao",
         "vig_ini", "vig_fim", "atual")
# candidato da busca: (pontos, caminho, rótulo, texto, situação do item, url do item)
Candidato = tuple[float, str, str, str, str, str]

# SQL montado só com nomes de coluna constantes (_META); os valores vão sempre como parâmetros
_COLUNAS = ", ".join(_META)
_MARCAS = ", ".join("?" * len(_META))
_SQL_ATUALIZAR = f"UPDATE documentos SET mtime=?, tamanho=?, {'=?, '.join(_META)}=? WHERE id=?"  # nosec B608
_SQL_INSERIR = f"INSERT INTO documentos(mtime, tamanho, {_COLUNAS}) VALUES (?, ?, {_MARCAS})"  # nosec B608
_SQL_DOCUMENTOS = f"SELECT {_COLUNAS} FROM documentos"  # nosec B608
_DOCS = "(rowid >> ?) IN (SELECT value FROM json_each(?))"
_SQL_MATCH = f"SELECT rowid, -bm25(trechos), rotulo, texto, situacao, url FROM trechos WHERE trechos MATCH ? AND {_DOCS} ORDER BY bm25(trechos) LIMIT ?"  # nosec B608
_SQL_CHAVES = f"SELECT rowid, rotulo, texto, situacao, url FROM trechos WHERE chave IN (SELECT value FROM json_each(?)) AND {_DOCS}"  # nosec B608


def fts5_disponivel() -> bool:
    try:
        with sqlite3.connect(":memory:") as con:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61 remove_diacritics 2')")
        return True
    except sqlite3.OperationalError:
        return False


class IndiceFTS:
    """Índice persistente: documentos (metadados) + trechos (FTS5 sobre os termos já normalizados)."""

    nome = "fts5"

    def __init__(self, caminho_db: Path):
        caminho_db.parent.mkdir(parents=True, exist_ok=True)
        self.caminho_db = caminho_db
        self._trava = threading.Lock()
        try:
            self._con = self._abrir()
        except sqlite3.DatabaseError:
            # índice é dado derivado: o arquivo ruim é guardado ao lado (não apagado) e o índice é refeito
            reserva = caminho_db.with_name(f"{caminho_db.name}.corrompido-{time.strftime('%Y%m%d-%H%M%S')}")
            logger.exception(f"base de conhecimento: índice ilegível, guardado em {reserva.name}; refazendo")
            caminho_db.replace(reserva)
            self._con = self._abrir()

    def _abrir(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho_db, timeout=15, check_same_thread=False, isolation_level=None)
        try:
            return self._preparar(con)
        except sqlite3.DatabaseError:
            con.close()              # no Windows o arquivo aberto não pode ser renomeado
            raise

    @staticmethod
    def _preparar(con: sqlite3.Connection) -> sqlite3.Connection:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute(f"PRAGMA cache_size=-{CACHE_KB}")
        con.execute("CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT)")
        versao = con.execute("SELECT valor FROM meta WHERE chave='versao'").fetchone()
        if not versao or versao[0] != VERSAO:
            con.executescript("DROP TABLE IF EXISTS trechos; DROP TABLE IF EXISTS documentos; DELETE FROM meta;")
        con.executescript(f"""
            CREATE TABLE IF NOT EXISTS documentos(
                id INTEGER PRIMARY KEY, caminho TEXT UNIQUE NOT NULL, mtime INTEGER, tamanho INTEGER,
                {", ".join(f"{c} TEXT" for c in _META[1:-1])}, atual INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS trechos USING fts5(
                termos, rotulo UNINDEXED, texto UNINDEXED, situacao UNINDEXED, url UNINDEXED, chave UNINDEXED,
                tokenize='unicode61 remove_diacritics 2');
            INSERT OR REPLACE INTO meta VALUES ('versao', '{VERSAO}');
        """)
        return con

    def ler_meta(self, chave: str) -> str | None:
        with self._trava:
            linha = self._con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return linha[0] if linha else None

    def gravar_meta(self, chave: str, valor: str) -> None:
        with self._trava:
            self._con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (chave, valor))

    def estado(self) -> dict[str, tuple[int, int, str]]:
        with self._trava:
            return {c: (m, t, h) for c, m, t, h in
                    self._con.execute("SELECT caminho, mtime, tamanho, hash FROM documentos")}

    def gravar(self, doc: Documento, mtime: int, tamanho: int) -> None:
        valores = [getattr(doc, c) for c in _META[:-1]] + [int(doc.atual)]
        with self._trava, self._con:
            self._con.execute("BEGIN")
            antigo = self._con.execute("SELECT id FROM documentos WHERE caminho=?", (doc.caminho,)).fetchone()
            if antigo:
                self._apagar_trechos(antigo[0])
                self._con.execute(_SQL_ATUALIZAR, [mtime, tamanho, *valores, antigo[0]])
                did = antigo[0]
            else:
                did = self._con.execute(_SQL_INSERIR, [mtime, tamanho, *valores]).lastrowid
            self._con.executemany(
                "INSERT INTO trechos(rowid, termos, rotulo, texto, situacao, url, chave) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [((did << _BLOCO) | i, " ".join(tokens(f"{rot} {txt}")), rot, txt, sit, url, chave_rotulo(rot))
                 for i, (rot, txt, sit, url) in enumerate(doc.trechos)])

    def tocar(self, caminho: str, mtime: int, tamanho: int) -> None:
        with self._trava:
            self._con.execute("UPDATE documentos SET mtime=?, tamanho=? WHERE caminho=?", (mtime, tamanho, caminho))

    def _apagar_trechos(self, did: int) -> None:
        self._con.execute("DELETE FROM trechos WHERE rowid BETWEEN ? AND ?",
                          (did << _BLOCO, ((did + 1) << _BLOCO) - 1))

    def remover(self, caminho: str) -> None:
        with self._trava, self._con:
            self._con.execute("BEGIN")
            antigo = self._con.execute("SELECT id FROM documentos WHERE caminho=?", (caminho,)).fetchone()
            if antigo:
                self._apagar_trechos(antigo[0])
                self._con.execute("DELETE FROM documentos WHERE id=?", (antigo[0],))

    def documentos(self) -> list[Documento]:
        with self._trava:
            linhas = self._con.execute(_SQL_DOCUMENTOS).fetchall()
        return [Documento(**dict(zip(_META, (*ln[:-1], bool(ln[-1])), strict=True))) for ln in linhas]

    def contar(self) -> tuple[int, int]:
        with self._trava:
            docs = self._con.execute("SELECT count(*) FROM documentos").fetchone()[0]
            trechos = self._con.execute("SELECT count(*) FROM trechos").fetchone()[0]
        return docs, trechos

    def buscar(self, termos: list[str], permitidos: set[str], limite: int,
               chaves: list[str] | None = None) -> list[Candidato]:
        if not permitidos:
            return []
        with self._trava:
            ids = {did: cam for did, cam in self._con.execute("SELECT id, caminho FROM documentos")
                   if cam in permitidos}
            lista = json.dumps(list(ids))
            achados = []
            if termos:
                consulta = " OR ".join(f'"{t}"' for t in termos)      # termos só têm [a-z0-9]
                achados = self._con.execute(_SQL_MATCH, (consulta, _BLOCO, lista, limite)).fetchall()
            if chaves:   # "art. 173", "súmula vinculante 8": o item entra mesmo sem termo em comum
                vistos = {r[0] for r in achados}
                achados += [(r[0], 0.0, *r[1:]) for r in self._con.execute(
                    _SQL_CHAVES, (json.dumps(chaves), _BLOCO, lista)) if r[0] not in vistos]
        return [(s, ids[rid >> _BLOCO], rot, txt, sit, url) for rid, s, rot, txt, sit, url in achados]


class IndiceMemoria:
    """Reserva quando o sqlite3 do Python não tem FTS5: o BM25 de antes, em memória (refeito a cada execução)."""

    nome = "memória"
    K1, B = 1.5, 0.75

    def __init__(self):
        self._docs: dict[str, tuple[Documento, int, int, list[Counter]]] = {}
        self._meta: dict[str, str] = {}

    def ler_meta(self, chave: str) -> str | None:
        return self._meta.get(chave)

    def gravar_meta(self, chave: str, valor: str) -> None:
        self._meta[chave] = valor

    def estado(self) -> dict[str, tuple[int, int, str]]:
        return {c: (m, t, d.hash) for c, (d, m, t, _) in self._docs.items()}

    def gravar(self, doc: Documento, mtime: int, tamanho: int) -> None:
        self._docs[doc.caminho] = (doc, mtime, tamanho, [Counter(tokens(f"{r} {t}")) for r, t, _, _ in doc.trechos])

    def tocar(self, caminho: str, mtime: int, tamanho: int) -> None:
        d, _, _, tfs = self._docs[caminho]
        self._docs[caminho] = (d, mtime, tamanho, tfs)

    def remover(self, caminho: str) -> None:
        self._docs.pop(caminho, None)

    def documentos(self) -> list[Documento]:
        return [d for d, *_ in self._docs.values()]

    def contar(self) -> tuple[int, int]:
        return len(self._docs), sum(len(d.trechos) for d, *_ in self._docs.values())

    def buscar(self, termos: list[str], permitidos: set[str], limite: int,
               chaves: list[str] | None = None) -> list[Candidato]:
        tfs = [tf for d, _, _, lista in self._docs.values() for tf in lista]
        n = len(tfs)
        df = Counter(term for tf in tfs for term in tf)
        media = sum(sum(tf.values()) for tf in tfs) / max(n, 1)
        pontos, extra = [], []
        for cam, (d, _, _, lista) in self._docs.items():
            if cam not in permitidos:
                continue
            for (rot, txt, sit, url), tf in zip(d.trechos, lista, strict=True):
                tam = sum(tf.values()) or 1
                s = 0.0
                for term in termos:
                    f = tf.get(term)
                    if f:
                        idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                        s += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * tam / media))
                if s > 0:
                    pontos.append((s, cam, rot, txt, sit, url))
                elif chaves and chave_rotulo(rot) in chaves:
                    extra.append((0.0, cam, rot, txt, sit, url))
        pontos.sort(key=lambda c: c[0], reverse=True)
        return pontos[:limite] + extra
