"""Adaptadores de coleta: cada um transforma uma fonte do catálogo em texto (corpo do arquivo da base).

Assinatura: (fonte, ctx) → (corpo, url_final, itens). Itens de listas/tabelas viram blocos "### rótulo" com
"Situação:", "Data:", "URL:" (o corte sumula/ementa lê esses metadados). Se um site mudar de layout, o ajuste é aqui
(código), não no catálogo.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

from ..core.privacy import sanitizar
from .catalogo import FonteCatalogo
from .coleta import Contexto, FalhaColeta, RecusaColeta
from .documento import decodificar, html_para_texto, ler_cabecalho, ler_documento, pdf_para_texto

TEXTOS = (".txt", ".md", ".html", ".htm", ".pdf", ".csv")
EXECUTAVEIS = (".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jse", ".msi", ".jar",
               ".sh", ".py", ".lnk", ".reg", ".hta", ".wsf", ".cpl")
LIMITE_ZIP = 200 * 2**20
MIN_ARTIGOS = 10


class AguardandoArquivo(Exception):
    """Fonte manual (ou recusada pelo site) sem arquivo em _entrada/: o Senhor salva a página pelo navegador."""


def recortar(texto: str, fonte: FonteCatalogo, avisos: list[str]) -> str:
    if fonte.inicio:
        if fonte.inicio in texto:
            texto = texto.split(fonte.inicio, 1)[1]
        else:
            avisos.append(f"marcador de início não encontrado ({fonte.inicio!r}); texto inteiro mantido")
    if fonte.fim:
        marcas = [fonte.fim] if isinstance(fonte.fim, str) else fonte.fim
        if posicoes := [texto.find(m) for m in marcas if m in texto]:
            texto = texto[:min(posicoes)]
        else:
            avisos.append(f"marcador de fim não encontrado ({fonte.fim!r})")
    return texto.strip()


def _conferir_lei(texto: str, fonte: FonteCatalogo, url: str) -> None:
    if fonte.corte == "artigo" and texto.count("Art.") < MIN_ARTIGOS:
        raise FalhaColeta(f"{url}: o texto não parece uma lei ({len(texto)} caracteres, poucos 'Art.')")


def sem_zeros(rotulo: str) -> str:
    """"Tema 0008" → "Tema 8": a pergunta diz "tema 8", e o índice compara números como palavras."""
    return re.sub(r"\b0+(\d)", r"\1", rotulo)


def marcar_itens(texto: str, padrao: str) -> tuple[str, int]:
    """Documento corrido (PDF de súmulas, página única): cada linha que casa com `padrao` abre um bloco "### "."""
    rx = re.compile(padrao, re.MULTILINE)
    tem_situacao = "situacao" in rx.groupindex

    def bloco(m: re.Match) -> str:
        g = m.groupdict()
        sit = (g.get("situacao") or "vigente").strip() if tem_situacao else ""
        return f"\n### {sem_zeros((g.get('nome') or m.group(0)).strip())}\n" + (f"Situação: {sit}\n" if sit else "")

    texto, n = rx.subn(bloco, texto)
    return texto, n


def _preparar(texto: str, fonte: FonteCatalogo, url: str, avisos: list[str]) -> tuple[str, int]:
    texto = recortar(texto, fonte, avisos)
    itens = 0
    if fonte.padrao_item:
        texto, itens = marcar_itens(texto, fonte.padrao_item)
        if not itens:
            raise FalhaColeta(f"{url}: nenhum item casou com padrao_item (o formato mudou?)")
    _conferir_lei(texto, fonte, url)
    return texto, itens


def _entrada(fonte: FonteCatalogo, ctx: Contexto) -> Path | None:
    """Arquivo que o Senhor salvou em _entrada/<fonte-id>.* (o mais recente)."""
    pasta = ctx.root / "_entrada"
    achados = [p for p in pasta.glob(f"{fonte.id}.*") if p.suffix.lower() in TEXTOS] if pasta.is_dir() else []
    return max(achados, key=lambda p: p.stat().st_mtime) if achados else None


def _texto_da_entrada(fonte: FonteCatalogo, arquivo: Path, ctx: Contexto) -> tuple[str, str, int]:
    texto, itens = _preparar(ler_documento(arquivo), fonte, arquivo.name, ctx.avisos)
    ctx.avisos.append(f"texto lido de _entrada/{arquivo.name} (salvo pelo Senhor)")
    return texto, fonte.url, itens


def _com_entrada_reserva(coletar):
    """Se o site recusar ou falhar, usa _entrada/<fonte-id>.* quando existir (decisão 1 do plano)."""
    def envolto(fonte: FonteCatalogo, ctx: Contexto):
        try:
            return coletar(fonte, ctx)
        except (FalhaColeta, RecusaColeta) as e:
            if (arquivo := _entrada(fonte, ctx)) is None:
                raise type(e)(f"{e}. Para seguir sem o coletor: salve a página pelo navegador em "
                              f"_entrada/{fonte.id}.htm (ou .pdf) e rode de novo") from e
            ctx.avisos.append(f"site falhou ({e})")
            return _texto_da_entrada(fonte, arquivo, ctx)
    return envolto


@_com_entrada_reserva
def html_simples(fonte: FonteCatalogo, ctx: Contexto):
    r = ctx.http.baixar(fonte.url, ctx.dominios)
    if r.tipo == "application/pdf" or r.conteudo[:5] == b"%PDF-":
        texto = pdf_para_texto(r.conteudo)
    else:
        texto = html_para_texto(decodificar(r.conteudo, r.charset))
    texto, itens = _preparar(texto, fonte, r.url, ctx.avisos)
    return texto, r.url, itens


@_com_entrada_reserva
def pdf(fonte: FonteCatalogo, ctx: Contexto):
    r = ctx.http.baixar(fonte.url, ctx.dominios)
    if r.conteudo[:5] != b"%PDF-":
        raise FalhaColeta(f"{r.url}: não é PDF ({r.tipo})")
    texto, itens = _preparar(pdf_para_texto(r.conteudo), fonte, r.url, ctx.avisos)
    return texto, r.url, itens


def manual(fonte: FonteCatalogo, ctx: Contexto):
    if (arquivo := _entrada(fonte, ctx)) is None:
        raise AguardandoArquivo(f"salve o arquivo em _entrada/{fonte.id}.htm (ou .pdf, .txt, .md)")
    return _texto_da_entrada(fonte, arquivo, ctx)


# ── listas (página índice + uma página por item) ─────────────
class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._atual: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._atual = dict(attrs).get("href") or "", []

    def handle_data(self, data):
        if self._atual is not None:
            self._atual.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._atual is not None:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._atual)).replace("\u200b", "").strip()))
            self._atual = None


def _blocos(texto: str) -> dict[str, str]:
    """Blocos "### rótulo" de uma captura anterior (reserva quando um item falha agora)."""
    partes = re.split(r"^### ", texto, flags=re.MULTILINE)
    return {p.split("\n", 1)[0].strip(): "### " + p.rstrip() + "\n" for p in partes[1:]}


def _bloco(rotulo: str, texto: str, situacao: str = "", data: str = "", url: str = "") -> str:
    meta = "".join(f"{k}: {v}\n" for k, v in (("Situação", situacao), ("Data", data), ("URL", url)) if v)
    return f"### {rotulo}\n{meta}{texto.strip()}\n"


def lista_links(fonte: FonteCatalogo, ctx: Contexto):
    indice = ctx.http.baixar(fonte.url, ctx.dominios)
    leitor = _Links()
    leitor.feed(decodificar(indice.conteudo, indice.charset))
    itens, vistos = [], set()
    for href, texto in leitor.links:
        url = urljoin(indice.url, href)
        if url in vistos or not re.search(fonte.padrao_links, url):
            continue
        situacao, rotulo = "", texto
        if fonte.padrao_rotulo:
            m = re.search(fonte.padrao_rotulo, texto)
            if not m:
                continue
            grupos = m.groupdict()
            rotulo = sem_zeros((grupos.get("nome") or texto).strip())
            situacao = (grupos.get("situacao") or "vigente").strip() if "situacao" in grupos else ""
        vistos.add(url)
        itens.append((rotulo, situacao, url))
    if not itens:
        raise FalhaColeta(f"{indice.url}: nenhum link casou com padrao_links (o site mudou de layout?)")
    if ctx.seco:
        return None, indice.url, len(itens)
    anterior = _blocos(ler_cabecalho(ler_documento(ctx.destino))[1]) if ctx.destino and ctx.destino.exists() else {}
    blocos, falhas, sem_marcador = [], [], []
    for rotulo, situacao, url in itens:
        try:
            r = ctx.http.baixar(url, ctx.dominios)
            texto = recortar(html_para_texto(decodificar(r.conteudo, r.charset)), fonte, sem_marcador)
            blocos.append(_bloco(rotulo, texto, situacao, url=url))
        except (FalhaColeta, RecusaColeta) as e:
            falhas.append(f"{rotulo}: {e}")
            if rotulo in anterior:                     # mantém a captura anterior do item
                blocos.append(anterior[rotulo])
    if falhas:
        ctx.avisos.append(f"{len(falhas)} item(ns) falharam (mantida a captura anterior quando havia): "
                          + "; ".join(falhas[:5]))
    if sem_marcador:
        ctx.avisos.append(f"{len(sem_marcador)} página(s) sem o marcador de recorte: {sem_marcador[0]}")
    return "\n".join(blocos), indice.url, len(itens)


# ── tabelas (CSV de dados abertos ou tabela HTML) ────────────
class _Tabela(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.linhas: list[list[str]] = []
        self._celula: list[str] | None = None
        self._linha: list[str] | None = None
        self._profundidade = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._profundidade += 1
        elif tag == "tr" and self._profundidade == 1:
            self._linha = []
        elif tag in ("td", "th") and self._linha is not None and self._profundidade == 1:
            self._celula = []
        elif tag in ("br", "p", "div") and self._celula is not None:
            self._celula.append(" ")

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._celula is not None:
            self._linha.append(re.sub(r"\s+", " ", "".join(self._celula)).strip())
            self._celula = None
        elif tag == "tr" and self._linha is not None and self._profundidade == 1:
            if self._linha:
                self.linhas.append(self._linha)
            self._linha = None
        elif tag == "table":
            self._profundidade -= 1


class _Linha(dict):
    def __missing__(self, chave):
        return ""


def _linhas_csv(texto: str) -> list[dict[str, str]]:
    """Só o delimitador é adivinhado; o resto é o padrão (aspas duplicadas = aspas). O Sniffer chegou a errar o
    doublequote no CSV do STJ e quebrou 31 linhas."""
    csv.field_size_limit(16 * 2**20)
    try:
        delimitador = csv.Sniffer().sniff(texto[:8192], delimiters=",;\t").delimiter
    except csv.Error:
        delimitador = ","
    return list(csv.DictReader(io.StringIO(texto), delimiter=delimitador))


def _linhas_html(texto: str) -> list[dict[str, str]]:
    leitor = _Tabela()
    leitor.feed(texto)
    if len(leitor.linhas) < 2:
        return []
    cab = leitor.linhas[0]
    return [dict(zip(cab, ln, strict=False)) for ln in leitor.linhas[1:]]


def tabela(fonte: FonteCatalogo, ctx: Contexto):
    r = ctx.http.baixar(fonte.url, ctx.dominios)
    texto = decodificar(r.conteudo, r.charset).lstrip("﻿")
    formato = fonte.formato or ("csv" if r.tipo in ("text/csv", "application/csv") or r.url.lower().endswith(".csv")
                                else "html")
    linhas = _linhas_csv(texto) if formato == "csv" else _linhas_html(texto)
    for coluna, aceitos in fonte.filtro.items():
        linhas = [ln for ln in linhas if (ln.get(coluna) or "").strip() in aceitos]
    if not linhas:
        raise FalhaColeta(f"{r.url}: tabela vazia depois do filtro (o formato mudou?)")
    col = fonte.colunas
    blocos = []
    for ln in linhas:
        dados = _Linha({k: (v or "").strip() for k, v in ln.items() if k})
        corpo = []
        for entrada in col.texto:
            rotulo, _, nome = entrada.rpartition("=")
            if valor := dados.get(nome, ""):
                corpo.append(f"{rotulo or nome}: {valor}")
        rotulo_item = sem_zeros(col.rotulo.format_map(dados).strip())
        blocos.append(_bloco(rotulo_item, "\n".join(corpo), dados.get(col.situacao, ""), dados.get(col.data, ""),
                             col.url.format_map(dados) if col.url else ""))
    return "\n".join(blocos), r.url, len(blocos)


# ── zip e pasta local ────────────────────────────────────────
def zip_(fonte: FonteCatalogo, ctx: Contexto):
    r = ctx.http.baixar(fonte.url, ctx.dominios)
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(r.conteudo))
    except zipfile.BadZipFile as e:
        raise FalhaColeta(f"{r.url}: ZIP inválido") from e
    membros = arquivo.infolist()
    for m in membros:
        nome = m.filename.replace("\\", "/")
        if nome.startswith("/") or re.match(r"^[A-Za-z]:", nome) or ".." in PurePosixPath(nome).parts:
            raise RecusaColeta(f"ZIP com caminho perigoso: {m.filename}")
        if PurePosixPath(nome).suffix.lower() in EXECUTAVEIS:
            raise RecusaColeta(f"ZIP com executável: {m.filename}")
    if sum(m.file_size for m in membros) > LIMITE_ZIP:
        raise RecusaColeta(f"ZIP descompactado passaria de {LIMITE_ZIP // 2**20} MB")
    partes, lidos = [], 0
    for m in sorted(membros, key=lambda m: m.filename):
        sufixo = PurePosixPath(m.filename).suffix.lower()
        if m.is_dir() or sufixo not in TEXTOS:
            continue
        with arquivo.open(m) as f:
            dados = f.read(LIMITE_ZIP - lidos + 1)      # tamanho declarado pode mentir (bomba de ZIP)
        lidos += len(dados)
        if lidos > LIMITE_ZIP:
            raise RecusaColeta(f"ZIP descompactado passaria de {LIMITE_ZIP // 2**20} MB")
        if sufixo == ".pdf":
            texto = pdf_para_texto(dados)
        elif sufixo in (".html", ".htm"):
            texto = html_para_texto(decodificar(dados, None))
        else:
            texto = decodificar(dados, None)
        partes.append(f"## {m.filename}\n{texto.strip()}\n")
    if not partes:
        raise FalhaColeta(f"{r.url}: ZIP sem arquivo de texto")
    return recortar("\n".join(partes), fonte, ctx.avisos), r.url, len(partes)


def _nomes_pii(ctx: Contexto) -> list[str]:
    lista = ctx.root / "_catalogo" / "pii_nomes.txt"
    return [ln.strip() for ln in lista.read_text(encoding="utf-8").splitlines() if ln.strip()] \
        if lista.is_file() else []


def pasta_local(fonte: FonteCatalogo, ctx: Contexto):
    pasta = Path(fonte.pasta or "")
    if not pasta.is_dir():
        raise FalhaColeta(f"pasta não encontrada: {pasta}")
    partes = []
    for p in sorted(x for x in pasta.rglob("*") if x.is_file() and x.suffix.lower() in TEXTOS):
        partes.append(f"## {p.relative_to(pasta).as_posix()}\n{ler_documento(p).strip()}\n")
    if not partes:
        raise FalhaColeta(f"{pasta}: nenhum arquivo de texto")
    texto = recortar("\n".join(partes), fonte, ctx.avisos)
    if fonte.esfera == "interno":   # biblioteca interna: CPF/CNPJ e nomes da lista mascarados antes de indexar
        texto = sanitizar(texto, _nomes_pii(ctx), ctx.salt)
    return texto, str(pasta), len(partes)


ADAPTADORES = {"html_simples": html_simples, "pdf": pdf, "manual": manual, "lista_links": lista_links,
               "tabela": tabela, "zip": zip_, "pasta_local": pasta_local}
