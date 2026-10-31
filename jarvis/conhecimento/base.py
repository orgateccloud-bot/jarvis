"""KnowledgeBase: junta catálogo, arquivos da pasta e índice. É a porta única de leitura da base (buscar_conhecimento).

Pasta (JARVIS_CONHECIMENTO, padrão D:\\JARVIS-Conhecimento): cada subpasta é uma área; _catalogo (TOMLs), _indice
(SQLite), _relatorios e _entrada ficam fora do índice. _versoes/<fonte-id>/<data>.md são versões antigas: entram no
índice, mas só aparecem com vigente_em. O _versoes antigo (arquivos soltos, sem pasta da fonte) continua de fora.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from .catalogo import DIAS_FREQUENCIA, Carga, carregar_catalogos
from .corte import cortar, meta_do_item
from .documento import data_br, ler_cabecalho, ler_data, ler_documento
from .indice import (
    Documento,
    IndiceFTS,
    IndiceMemoria,
    Trecho,
    chave_rotulo,
    chaves_citadas,
    fts5_disponivel,
    norm,
    termos_da_consulta,
)

SUFIXOS = (".txt", ".md", ".html", ".htm", ".pdf")
NAO_VIGENTE = ("cancelad", "superad", "revogad", "historico", "revisad")
DIAS_SEM_CATALOGO = 60


@dataclass(frozen=True)
class Filtros:
    area: str | None = None
    uf: str | None = None
    tipo: str | None = None
    esfera: str | None = None
    vigente_em: date | None = None


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _br(iso: str) -> str:
    return data_br(date.fromisoformat(iso)) if iso else ""


def selecionar(docs: list[Documento], f: Filtros) -> dict[str, str]:
    """Documentos que entram na busca → aviso de vigência (vazio se nada a dizer). Padrão: só a versão atual."""
    ok = [d for d in docs
          if (not f.area or f.area == "geral" or d.area == f.area) and (not f.uf or d.uf.upper() == f.uf.upper())
          and (not f.tipo or d.tipo == f.tipo) and (not f.esfera or d.esfera == f.esfera)]
    if f.vigente_em is None:
        return {d.caminho: "" for d in ok if d.atual}
    alvo = f.vigente_em.isoformat()
    out, grupos = {}, {}
    for d in ok:
        if d.fonte_id:
            grupos.setdefault(d.fonte_id, []).append(d)
        elif d.atual:                       # sem fonte-id não há histórico: vale a versão que existe
            out[d.caminho] = ""
    for versoes in grupos.values():
        cobre = [d for d in versoes if (not d.vig_ini or d.vig_ini <= alvo) and (not d.vig_fim or alvo < d.vig_fim)]
        if cobre:
            out[max(cobre, key=lambda d: d.vig_ini).caminho] = ""
        else:
            velha = min(versoes, key=lambda d: d.vig_ini or "9999")
            out[velha.caminho] = (f"não há versão capturada vigente em {data_br(f.vigente_em)}; "
                                  f"este texto vale desde {_br(velha.vig_ini)}")
    return out


class KnowledgeBase:
    """Índice incremental: a cada busca confere a pasta e recorta só os arquivos novos ou alterados."""

    def __init__(self, root: Path, fts: bool | None = None):
        self.root = root
        self._fts = fts_disponivel_cache() if fts is None else fts
        self._motor: IndiceFTS | IndiceMemoria | None = None
        self._assinatura: tuple | None = None
        self._assinatura_cat: tuple | None = None
        self.carga = Carga()
        self._trava = threading.RLock()
        self.ultima_sincronizacao: dict[str, list[str]] = {"cortados": [], "removidos": []}

    # ── arquivos e catálogo ──────────────────────────────────
    def _arquivos(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        out = []
        for p in self.root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in SUFIXOS:
                continue
            partes = p.relative_to(self.root).parts
            versao = len(partes) == 3 and partes[0] == "_versoes" and not partes[1].startswith(("_", "."))
            if versao or not any(part.startswith(("_", ".")) for part in partes):
                out.append(p)
        return sorted(out)

    def _catalogo(self) -> None:
        pasta = self.root / "_catalogo"
        assinatura = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(pasta.glob("*.toml"))) \
            if pasta.is_dir() else ()
        if assinatura == self._assinatura_cat:
            return
        self.carga = carregar_catalogos(pasta)
        for erro in self.carga.erros:
            logger.warning(f"catálogo: {erro}")
        self._assinatura_cat = assinatura
        self._assinatura = None

    def _impressao_catalogo(self) -> str:
        """O que do catálogo muda o recorte/metadados de um arquivo. Aprovar ou mudar obs não reindexa nada."""
        dados = {f.id: [self.carga.area_de(f.id), self.carga.arquivo_de(f.id), f.titulo, f.tipo, f.esfera, f.uf,
                        f.url, f.corte] for f in self.carga.fontes()}
        return hashlib.sha256(json.dumps(dados, sort_keys=True).encode()).hexdigest()[:16]

    def _fonte_id(self, rel: str, cab_fonte_id: str) -> str:
        partes = rel.split("/")
        if cab_fonte_id:
            return cab_fonte_id
        if partes[0] == "_versoes":
            return partes[1]
        f = self.carga.fonte_do_arquivo(rel)
        return f.id if f else ""

    def _carregar(self, path: Path, rel: str, hash_: str) -> Documento:
        cab, corpo = ler_cabecalho(ler_documento(path))
        partes = rel.split("/")
        versao = partes[0] == "_versoes"
        fid = self._fonte_id(rel, cab.fonte_id)
        fonte = self.carga.fonte(fid) if fid else None
        if fonte:
            area = self.carga.area_de(fid)
        else:
            area = partes[0] if len(partes) > 1 and not versao else "geral"
        ini, fim = cab.periodo()
        doc = Documento(
            caminho=rel, hash=hash_, titulo=cab.titulo or (fonte.titulo if fonte else path.stem), area=area,
            fonte_id=fid, url=cab.fonte or (fonte.url if fonte else ""), baixado_em=cab.baixado_em,
            tipo=cab.tipo or (fonte.tipo if fonte else ""), esfera=cab.esfera or (fonte.esfera if fonte else ""),
            uf=cab.uf or (fonte.uf if fonte else ""), situacao=cab.situacao or ("histórico" if versao else ""),
            vig_ini=_iso(ini), vig_fim=_iso(fim), atual=not versao)
        corte = fonte.corte if fonte else None
        meta = {}
        for rot, txt in cortar(corpo, corte):
            if corte in ("sumula", "ementa"):
                if " (parte " not in rot:          # as partes seguintes herdam os metadados do item
                    meta = meta_do_item(txt)
                doc.trechos.append((rot, txt, meta.get("situacao", ""), meta.get("url", "")))
            else:
                doc.trechos.append((rot, txt, "", ""))
        return doc

    # ── sincronização ────────────────────────────────────────
    def _obter_motor(self) -> IndiceFTS | IndiceMemoria | None:
        if self._motor is None and self.root.is_dir():
            if self._fts:
                self._motor = IndiceFTS(self.root / "_indice" / "base.db")
            else:
                logger.warning("base de conhecimento: sqlite3 sem FTS5; usando o índice em memória (mais RAM)")
                self._motor = IndiceMemoria()
        return self._motor

    def sincronizar(self) -> IndiceFTS | IndiceMemoria | None:
        with self._trava:
            motor = self._obter_motor()
            if motor is None:
                return None
            self._catalogo()
            arquivos = self._arquivos()
            assinatura = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in arquivos)
            if assinatura == self._assinatura:
                return motor
            impressao = self._impressao_catalogo()
            catalogo_mudou = motor.ler_meta("catalogo") != impressao
            estado = motor.estado()
            cortados, presentes = [], set()
            for p, (_, mtime, tamanho) in zip(arquivos, assinatura, strict=True):
                rel = p.relative_to(self.root).as_posix()
                presentes.add(rel)
                antes = estado.get(rel)
                if antes and antes[:2] == (mtime, tamanho) and not catalogo_mudou:
                    continue
                hash_ = hashlib.sha256(p.read_bytes()).hexdigest() + ":" + impressao
                if antes and antes[2] == hash_:
                    motor.tocar(rel, mtime, tamanho)
                    continue
                try:
                    motor.gravar(self._carregar(p, rel, hash_), mtime, tamanho)
                    cortados.append(rel)
                except Exception:  # noqa: BLE001 — um arquivo ruim não derruba a base inteira
                    logger.exception(f"base de conhecimento: não consegui ler {rel}")
            removidos = [rel for rel in estado if rel not in presentes]
            for rel in removidos:
                motor.remover(rel)
            motor.gravar_meta("catalogo", impressao)
            self._assinatura = assinatura
            self.ultima_sincronizacao = {"cortados": cortados, "removidos": removidos}
            if cortados or removidos:
                docs, trechos = motor.contar()
                logger.info(f"base de conhecimento ({motor.nome}): {len(cortados)} arquivo(s) indexado(s), "
                            f"{len(removidos)} removido(s); total {docs} arquivos, {trechos} trechos")
            return motor

    # ── consulta ─────────────────────────────────────────────
    def areas(self) -> list[str]:
        with self._trava:
            self._catalogo()
        pastas = {p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))} \
            if self.root.is_dir() else set()
        return sorted(set(self.carga.areas()) | pastas | {"geral"})

    def _aviso(self, d: Documento, situacao: str, aviso_vigencia: str, hoje: date) -> str:
        avisos = [aviso_vigencia] if aviso_vigencia else []
        if any(s in norm(situacao) for s in NAO_VIGENTE):
            avisos.append(f"{situacao}: não use como norma vigente")
        baixado = ler_data(d.baixado_em) if d.baixado_em else None
        fonte = self.carga.fonte(d.fonte_id) if d.fonte_id else None
        dias = DIAS_FREQUENCIA.get(fonte.frequencia) if fonte else DIAS_SEM_CATALOGO
        if d.atual and baixado and dias and hoje - baixado > timedelta(days=dias * 1.5):
            avisos.append(f"capturado em {d.baixado_em}; pode estar desatualizado")
        return "; ".join(avisos)

    def buscar(self, consulta: str, area: str | None = None, k: int = 5, *, uf: str | None = None,
               tipo: str | None = None, esfera: str | None = None,
               vigente_em: date | None = None) -> list[tuple[float, Trecho]]:
        with self._trava:
            motor = self.sincronizar()
            if motor is None:
                return []
            docs = {d.caminho: d for d in motor.documentos()}
            permitidos = selecionar(list(docs.values()), Filtros(area, uf, tipo, esfera, vigente_em))
            q = norm(consulta)
            chaves = chaves_citadas(consulta)
            candidatos = motor.buscar(termos_da_consulta(consulta), set(permitidos), 60, chaves)
        hoje = date.today()
        pontos = []
        for s, cam, rot, txt, sit_item, url_item in candidatos:
            d = docs[cam]
            fonte = self.carga.fonte(d.fonte_id) if d.fonte_id else None
            if s and fonte and any(norm(a) in q for a in fonte.apelidos):
                s += 2.0  # a pergunta nomeia a lei
            if chaves and chave_rotulo(rot) in chaves:
                s += 10.0  # "art. 173", "súmula vinculante 8": o próprio item vem primeiro
                if " (parte " not in rot and not rot.startswith(("Art", "Anexo")):
                    s += 10.0  # na jurisprudência, a 1ª parte traz o enunciado/tese: vem antes dos precedentes
            if s > 0:
                pontos.append((s, cam, rot, txt, sit_item, url_item))
        pontos.sort(key=lambda c: c[0], reverse=True)
        out = []
        for s, cam, rot, txt, sit_item, url_item in pontos[:k]:
            d = docs[cam]
            situacao = sit_item or d.situacao
            vigencia = f"{_br(d.vig_ini)} a {_br(d.vig_fim)}".strip() if d.vig_ini or d.vig_fim else ""
            out.append((round(s, 2), Trecho(
                d.titulo, rot, cam, d.area, txt, url=url_item or d.url, baixado_em=d.baixado_em, situacao=situacao,
                vigencia=vigencia, uf=d.uf, tipo=d.tipo, esfera=d.esfera, fonte_id=d.fonte_id, atual=d.atual,
                aviso=self._aviso(d, situacao, permitidos[cam], hoje))))
        return out

    def resumo(self) -> dict:
        motor = self.sincronizar()
        docs, trechos = motor.contar() if motor else (0, 0)
        return {"pasta": str(self.root), "arquivos": docs, "trechos": trechos,
                "motor": motor.nome if motor else "", "erros_catalogo": len(self.carga.erros)}


_FTS: bool | None = None


def fts_disponivel_cache() -> bool:
    global _FTS
    if _FTS is None:
        _FTS = fts5_disponivel()
    return _FTS
