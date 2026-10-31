"""Coleta (R8, R10): baixa as fontes APROVADAS do catálogo, converte em texto, guarda versões e escreve relatório.

Não usa a API do Claude. HTTP: só https, só domínios do [seguranca] do catálogo (também nos redirecionamentos),
User-Agent identificado, 1 requisição a cada 2 s por domínio, até 50 MB por arquivo, 3 tentativas.
Mudou o texto (hash) → a versão anterior vai para _versoes/<fonte-id>/<início da vigência>.md com a vigência fechada.
Relatório do dia em _relatorios/AAAA-MM-DD.md: novos, alterados, sem mudança, em dia, aguardando, falhas, recusas.
"""

from __future__ import annotations

import http.client
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from .catalogo import DIAS_FREQUENCIA, Carga, FonteCatalogo, dominio_permitido
from .documento import (
    Cabecalho,
    data_br,
    escrever_cabecalho,
    hash_texto,
    ler_cabecalho,
    ler_documento,
    normalizar,
)

UA = "JARVIS-conhecimento/1.0 (assistente pessoal; uso pessoal; 1 req/2 s por site)"
LIMITE_ARQUIVO = 50 * 2**20


class RecusaColeta(Exception):
    """Recusa por regra de segurança (domínio, esquema, tamanho, ZIP perigoso). Não tenta de novo."""


class FalhaColeta(Exception):
    """Falha de rede ou de conteúdo depois das tentativas."""


@dataclass
class Resposta:
    conteudo: bytes
    tipo: str
    charset: str | None
    url: str


class _Redirecionamento(urllib.request.HTTPRedirectHandler):
    def __init__(self, dominios: list[str]):
        self.dominios = dominios

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not dominio_permitido(newurl, self.dominios):
            raise RecusaColeta(f"redirecionamento para fora da lista do catálogo: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Http:
    def __init__(self, intervalo: float = 2.0, limite: int = LIMITE_ARQUIVO, tentativas: int = 3,
                 timeout: float = 60, ua: str = UA, abrir: Callable | None = None,
                 relogio: Callable[[], float] = time.monotonic, dormir: Callable[[float], None] = time.sleep):
        self.intervalo, self.limite, self.tentativas, self.timeout, self.ua = intervalo, limite, tentativas, timeout, ua
        self.abrir, self.relogio, self.dormir = abrir, relogio, dormir
        self._ultimo: dict[str, float] = {}
        self.requisicoes = 0

    def _esperar(self, host: str) -> None:
        if host in self._ultimo:
            falta = self.intervalo - (self.relogio() - self._ultimo[host])
            if falta > 0:
                self.dormir(falta)
        self._ultimo[host] = self.relogio()

    def baixar(self, url: str, dominios: list[str]) -> Resposta:
        if not dominio_permitido(url, dominios):
            raise RecusaColeta(f"domínio fora da lista do catálogo (ou sem https): {urlparse(url).hostname or url}")
        host = urlparse(url).hostname or ""
        erro = ""
        for tentativa in range(1, self.tentativas + 1):
            self._esperar(host)
            try:
                return self._uma(url, dominios)
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500 and e.code not in (408, 429):
                    raise FalhaColeta(f"HTTP {e.code} em {url}") from e
                erro = f"HTTP {e.code}"
            except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                if isinstance(getattr(e, "reason", None), RecusaColeta):
                    raise e.reason from e
                erro = f"{type(e).__name__}: {e}"
            if tentativa < self.tentativas:
                self.dormir(2.0 * tentativa)
        raise FalhaColeta(f"{erro} em {url} (após {self.tentativas} tentativas)")

    def _uma(self, url: str, dominios: list[str]) -> Resposta:
        self.requisicoes += 1
        req = urllib.request.Request(url, headers={"User-Agent": self.ua})
        abrir = self.abrir or urllib.request.build_opener(_Redirecionamento(dominios)).open
        # URL do catálogo (https, domínio da lista conferido acima e em cada redirecionamento); nada vem do modelo
        with abrir(req, timeout=self.timeout) as resp:  # nosec B310
            declarado = resp.headers.get("Content-Length")
            if declarado and declarado.isdigit() and int(declarado) > self.limite:
                raise RecusaColeta(f"arquivo maior que {self.limite // 2**20} MB: {url}")
            dados = resp.read(self.limite + 1)
            if len(dados) > self.limite:
                raise RecusaColeta(f"arquivo maior que {self.limite // 2**20} MB: {url}")
            final = resp.geturl() if hasattr(resp, "geturl") else url
            if not dominio_permitido(final, dominios):
                raise RecusaColeta(f"redirecionamento para fora da lista do catálogo: {final}")
            return Resposta(dados, resp.headers.get_content_type(), resp.headers.get_content_charset(), final)


@dataclass
class Contexto:
    root: Path
    http: Http
    dominios: list[str]
    seco: bool = False
    salt: str = ""
    destino: Path | None = None          # arquivo atual da fonte (captura anterior)
    avisos: list[str] = field(default_factory=list)


@dataclass
class Relatorio:
    novos: list[str] = field(default_factory=list)
    alterados: list[str] = field(default_factory=list)
    sem_mudanca: list[str] = field(default_factory=list)
    em_dia: list[str] = field(default_factory=list)
    aguardando: list[str] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    recusados: list[str] = field(default_factory=list)
    nao_aprovadas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    caminho: Path | None = None

    def markdown(self, titulo: str) -> str:
        secoes = [("Novos", self.novos), ("Alterados", self.alterados), ("Sem mudança", self.sem_mudanca),
                  ("Em dia (dentro da frequência)", self.em_dia), ("Aguardando arquivo manual", self.aguardando),
                  ("Falhas", self.falhas), ("Recusados (segurança)", self.recusados), ("Avisos", self.avisos)]
        linhas = [f"## {titulo}"]
        for nome, itens in secoes:
            linhas.append(f"- {nome} ({len(itens)})" + "".join(f"\n  - {i}" for i in itens))
        if self.nao_aprovadas:
            linhas.append(f"- Não aprovadas, nada baixado ({len(self.nao_aprovadas)})")
        return "\n".join(linhas) + "\n\n"


def _escrever(alvo: Path, texto: str) -> None:
    """Grava de uma vez (arquivo temporário + troca): o índice nunca lê um arquivo pela metade."""
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_name(f".{alvo.name}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, alvo)


def gravar(root: Path, carga: Carga, fonte: FonteCatalogo, corpo: str, url: str, hoje: date,
           seco: bool = False) -> tuple[str, str]:
    """Grava a captura com cabeçalho v2. Devolve (estado, detalhe): novo | alterado | sem mudança."""
    destino = root / carga.arquivo_de(fonte.id)
    corpo = normalizar(corpo)
    novo_hash = hash_texto(corpo)
    cat = carga.catalogo_de(fonte.id)
    base = {"titulo": fonte.titulo, "fonte": url or fonte.url, "biblioteca": cat.biblioteca.id if cat else "",
            "fonte_id": fonte.id, "tipo": fonte.tipo, "esfera": fonte.esfera, "uf": fonte.uf}
    estado, detalhe, inicio = "novo", carga.arquivo_de(fonte.id), hoje
    if destino.exists():
        cab_ant, corpo_ant = ler_cabecalho(ler_documento(destino))
        ini_ant = cab_ant.periodo()[0] or date.fromtimestamp(destino.stat().st_mtime)
        if hash_texto(corpo_ant) == novo_hash:
            estado, inicio = "sem mudança", ini_ant
        else:
            pasta = root / "_versoes" / fonte.id
            alvo_v = pasta / f"{ini_ant:%Y-%m-%d}.md"
            n = 2
            while alvo_v.exists():
                alvo_v = pasta / f"{ini_ant:%Y-%m-%d}-{n}.md"
                n += 1
            versao = Cabecalho(**{**base, "titulo": cab_ant.titulo or fonte.titulo, "fonte": cab_ant.fonte or fonte.url,
                                  "baixado_em": cab_ant.baixado_em, "vigencia": f"{data_br(ini_ant)} a {data_br(hoje)}",
                                  "situacao": "histórico", "hash": hash_texto(corpo_ant)})
            if not seco:
                _escrever(alvo_v, escrever_cabecalho(versao) + normalizar(corpo_ant))
            estado, detalhe = "alterado", f"versão anterior em {alvo_v.relative_to(root).as_posix()}"
    cab = Cabecalho(**base, baixado_em=data_br(hoje), vigencia=f"{data_br(inicio)} a", situacao="vigente",
                    hash=novo_hash)
    if not seco:
        _escrever(destino, escrever_cabecalho(cab) + corpo)
    return estado, detalhe


def _em_dia(root: Path, carga: Carga, fonte: FonteCatalogo, hoje: date) -> bool:
    destino = root / carga.arquivo_de(fonte.id)
    dias = DIAS_FREQUENCIA.get(fonte.frequencia)
    if not dias or not destino.exists():
        return False
    baixado = ler_cabecalho(destino.read_text(encoding="utf-8", errors="replace")[:4000])[0].baixado()
    return bool(baixado and (hoje - baixado).days < dias)


def atualizar(root: Path, carga: Carga, biblioteca: str | None = None, fonte: str | None = None, seco: bool = False,
              forcar: bool = False, http_cliente: Http | None = None, hoje: date | None = None,
              salt: str = "") -> Relatorio:
    from .adaptadores import ADAPTADORES, AguardandoArquivo

    hoje = hoje or date.today()
    http_cliente = http_cliente or Http()
    rel = Relatorio()
    escolhidas = [f for f in carga.fontes()
                  if (not biblioteca or carga.catalogo_de(f.id).biblioteca.id == biblioteca)
                  and (not fonte or f.id == fonte)]
    if fonte and not escolhidas:
        rel.falhas.append(f"{fonte}: fonte não existe no catálogo")
    for f in sorted(escolhidas, key=lambda f: (f.prioridade, f.id)):
        if f.situacao != "aprovado":
            rel.nao_aprovadas.append(f.id)
            if fonte:
                rel.avisos.append(f"{f.id}: situação '{f.situacao}'; só fonte aprovada é baixada (só o Senhor aprova)")
            continue
        if not forcar and not fonte and _em_dia(root, carga, f, hoje):
            rel.em_dia.append(f.id)
            continue
        ctx = Contexto(root, http_cliente, carga.catalogo_de(f.id).seguranca.dominios, seco, salt,
                       root / carga.arquivo_de(f.id))
        try:
            corpo, url, itens = ADAPTADORES[f.adaptador](f, ctx)
            if seco and corpo is None:
                rel.sem_mudanca.append(f"{f.id}: modo seco, {itens} itens no índice (nada baixado além dele)")
                continue
            estado, detalhe = gravar(root, carga, f, corpo, url, hoje, seco)
            linha = f"{f.id}: {detalhe}" + (f" ({itens} itens)" if itens else "")
            {"novo": rel.novos, "alterado": rel.alterados, "sem mudança": rel.sem_mudanca}[estado].append(linha)
        except AguardandoArquivo as e:
            rel.aguardando.append(f"{f.id}: {e}")
        except RecusaColeta as e:
            rel.recusados.append(f"{f.id}: {e}")
        except FalhaColeta as e:                     # esperada (rede, site recusou): sem rastro de pilha
            logger.warning(f"coleta: {f.id}: {e}")
            rel.falhas.append(f"{f.id}: {e}")
        except Exception as e:  # noqa: BLE001 — uma fonte ruim não para a coleta das outras
            logger.exception(f"coleta: {f.id}")
            rel.falhas.append(f"{f.id}: {e}")
        rel.avisos += [f"{f.id}: {a}" for a in ctx.avisos]
    titulo = f"Execução {datetime.now():%H:%M}" + (" (modo seco: nada gravado)" if seco else "") + \
        (f" — biblioteca {biblioteca}" if biblioteca else "") + (f" — fonte {fonte}" if fonte else "")
    rel.caminho = root / "_relatorios" / f"{hoje:%Y-%m-%d}.md"
    rel.caminho.parent.mkdir(parents=True, exist_ok=True)
    with rel.caminho.open("a", encoding="utf-8") as arq:
        arq.write(rel.markdown(titulo))
    logger.info(f"coleta: {len(rel.novos)} novos, {len(rel.alterados)} alterados, {len(rel.falhas)} falhas; "
                f"relatório em {rel.caminho}")
    return rel
