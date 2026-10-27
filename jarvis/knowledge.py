"""Base de conhecimento local do especialista: leis e documentos em texto, cortados por artigo, com busca BM25.

Tudo em Python puro e determinístico (sem outro modelo, sem custo). A pasta é JARVIS_CONHECIMENTO
(padrão D:\\JARVIS-Conhecimento); cada subpasta é uma área (tributario, oab, contabil...). Arquivos aceitos:
.txt, .md, .html/.htm e .pdf (este com pypdf). Pastas que começam com "_" ou "." ficam de fora do índice.

Uso: python -m jarvis.knowledge baixar      → baixa as leis do Planalto (texto compilado, sem trechos revogados)
     python -m jarvis.knowledge buscar "decadência do crédito tributário"
"""

from __future__ import annotations

import math
import re
import sys
import textwrap
import unicodedata
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from loguru import logger

AREAS = ("tributario", "oab", "contabil", "geral")


@dataclass(frozen=True)
class Fonte:
    arquivo: str      # caminho relativo à pasta da base (a subpasta é a área)
    titulo: str
    url: str
    apelidos: tuple[str, ...] = ()


FONTES = [
    Fonte("tributario/ctn-lei-5172-1966.txt", "Código Tributário Nacional (Lei 5.172/1966, compilada)",
          "https://www.planalto.gov.br/ccivil_03/leis/l5172compilado.htm", ("ctn", "codigo tributario", "5172")),
    Fonte("tributario/lc-123-2006-simples-nacional.txt", "Lei Complementar 123/2006 (Simples Nacional)",
          "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm", ("lc 123", "simples nacional", "mei")),
    Fonte("oab/estatuto-oab-lei-8906-1994.txt", "Estatuto da Advocacia e da OAB (Lei 8.906/1994)",
          "https://www.planalto.gov.br/ccivil_03/leis/l8906.htm", ("estatuto", "8906", "advocacia")),
]


# ── HTML → texto ─────────────────────────────────────────────
class _Texto(HTMLParser):
    """Extrai o texto; descarta script/style e trechos riscados (redação revogada no texto compilado)."""

    _BLOCO = frozenset({"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"})
    _VAZIAS = frozenset({"br", "img", "meta", "hr", "input", "link", "col", "area", "base", "wbr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.pilha: list[tuple[str, bool]] = []

    def _pulando(self) -> bool:
        return any(skip for _, skip in self.pilha)

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCO:
            self.partes.append("\n")
        if tag in self._VAZIAS:
            return
        estilo = (dict(attrs).get("style") or "").lower().replace(" ", "")
        skip = tag in ("script", "style", "strike", "s", "del") or "line-through" in estilo
        self.pilha.append((tag, skip))

    def handle_endtag(self, tag):
        if tag in self._BLOCO:
            self.partes.append("\n")
        for i in range(len(self.pilha) - 1, -1, -1):  # HTML antigo fecha tags fora de ordem
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                break

    def handle_data(self, data):
        if not self._pulando():
            self.partes.append(re.sub(r"\s+", " ", data))  # quebra de linha no fonte HTML é só espaço


def html_para_texto(html: str) -> str:
    p = _Texto()
    p.feed(html)
    texto = "".join(p.partes).replace("\xa0", " ")
    linhas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


def _decodificar(raw: bytes, charset: str | None) -> str:
    for enc in filter(None, (charset, "utf-8", "cp1252")):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("cp1252", errors="replace")


def baixar(destino: Path, fontes: list[Fonte] = FONTES) -> list[Path]:
    """Baixa cada fonte, converte para texto e grava com cabeçalho (título, fonte, data). A versão anterior
    vai para _versoes/ (nada é apagado)."""
    gravados = []
    for f in fontes:
        req = urllib.request.Request(f.url, headers={"User-Agent": "Mozilla/5.0 (JARVIS; uso pessoal)"})
        # URL fixa da lista FONTES (https, planalto.gov.br); nada vem do modelo
        with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
            texto = html_para_texto(_decodificar(resp.read(), resp.headers.get_content_charset()))
        if texto.count("Art.") < 10:
            raise RuntimeError(f"{f.url}: o texto baixado não parece uma lei ({len(texto)} caracteres)")
        alvo = destino / f.arquivo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if alvo.exists():
            versoes = destino / "_versoes"
            versoes.mkdir(exist_ok=True)
            alvo.replace(versoes / f"{alvo.stem}.{date.fromtimestamp(alvo.stat().st_mtime)}{alvo.suffix}")
        cabecalho = f"Título: {f.titulo}\nFonte: {f.url}\nBaixado em: {date.today():%d/%m/%Y}\n---\n"
        alvo.write_text(cabecalho + texto + "\n", encoding="utf-8")
        gravados.append(alvo)
        logger.info(f"base de conhecimento: {alvo} ({len(texto)} caracteres)")
    return gravados


# ── corte em trechos ─────────────────────────────────────────
_ARTIGO = re.compile(r"^Art\.?\s*(\d+)\s*[ºo°]?\s*(-\s*[A-Z]{1,2}\b)?", re.MULTILINE)
_ANEXO = re.compile(r"^ANEXO\s+([IVXL]+)\b", re.MULTILINE)
TAM_TRECHO = 1500


@dataclass(frozen=True)
class Trecho:
    fonte: str        # título do documento
    rotulo: str       # "Art. 173", "Anexo I", "parágrafo 3"
    arquivo: str      # caminho relativo à base
    area: str
    texto: str


def _cabecalho(texto: str) -> tuple[dict[str, str], str]:
    if "\n---\n" not in texto[:1000]:
        return {}, texto
    topo, corpo = texto.split("\n---\n", 1)
    meta = dict(ln.split(": ", 1) for ln in topo.splitlines() if ": " in ln)
    return meta, corpo


def _fatiar(texto: str, rotulo: str) -> list[tuple[str, str]]:
    """Divide trechos longos em partes de até TAM_TRECHO, quebrando em linha."""
    if len(texto) <= TAM_TRECHO:
        return [(rotulo, texto)]
    linhas = []
    for ln in texto.splitlines(keepends=True):  # linha única enorme (PDF, tabela): quebra nos espaços
        linhas += [w + "\n" for w in textwrap.wrap(ln, TAM_TRECHO)] if len(ln) > TAM_TRECHO else [ln]
    partes, atual = [], ""
    for ln in linhas:
        if atual and len(atual) + len(ln) > TAM_TRECHO:
            partes.append(atual)
            atual = ""
        atual += ln
    partes.append(atual)
    return [(rotulo if i == 0 else f"{rotulo} (parte {i + 1})", p) for i, p in enumerate(partes)]


def cortar(texto: str) -> list[tuple[str, str]]:
    """Lei → um trecho por artigo (e por anexo); outros textos → blocos de parágrafos."""
    marcas = sorted(
        [(m.start(), f"Art. {m.group(1)}{(m.group(2) or '').replace(' ', '')}") for m in _ARTIGO.finditer(texto)]
        + [(m.start(), f"Anexo {m.group(1)}") for m in _ANEXO.finditer(texto)]
    )
    if len(marcas) >= 3:
        pedacos = [(0, "Preâmbulo")] + marcas if marcas[0][0] > 0 else marcas
        out = []
        for i, (ini, rot) in enumerate(pedacos):
            fim = pedacos[i + 1][0] if i + 1 < len(pedacos) else len(texto)
            trecho = texto[ini:fim].strip()
            if trecho:
                out += _fatiar(trecho, rot)
        return out
    blocos, atual, n = [], "", 0
    for par in re.split(r"\n\s*\n", texto):
        if atual and len(atual) + len(par) > TAM_TRECHO:
            n += 1
            blocos.append((f"parágrafo {n}", atual.strip()))
            atual = ""
        atual += par + "\n\n"
    if atual.strip():
        blocos.append((f"parágrafo {n + 1}", atual.strip()))
    return [p for rot, t in blocos for p in _fatiar(t, rot)]


def ler_documento(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".html", ".htm"):
        return html_para_texto(_decodificar(path.read_bytes(), None))
    if suf == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning(f"pypdf não instalado: {path.name} fica fora da base")
            return ""
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    return _decodificar(path.read_bytes(), None).replace("\r\n", "\n")


# ── busca BM25 ───────────────────────────────────────────────
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


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _radical(tok: str) -> str:
    if len(tok) > 5:
        for suf, troca in (("coes", "cao"), ("oes", "ao"), ("ais", "al"), ("eis", "el")):
            if tok.endswith(suf):
                return tok[: -len(suf)] + troca
    return tok[:-1] if len(tok) > 4 and tok.endswith("s") else tok


def tokens(texto: str) -> list[str]:
    return [_radical(t) for t in re.findall(r"[a-z0-9]+", _norm(texto)) if len(t) > 1 and t not in _STOP]


class KnowledgeBase:
    """Índice em memória; refeito sozinho quando algum arquivo da pasta muda."""

    K1, B = 1.5, 0.75
    SUFIXOS = (".txt", ".md", ".html", ".htm", ".pdf")

    def __init__(self, root: Path):
        self.root = root
        self._assinatura: tuple | None = None
        self.trechos: list[Trecho] = []
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._media = 1.0
        self._apelidos = {f.arquivo: f.apelidos for f in FONTES}

    def _arquivos(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            p for p in self.root.rglob("*")
            if p.is_file() and p.suffix.lower() in self.SUFIXOS
            and not any(part.startswith(("_", ".")) for part in p.relative_to(self.root).parts)
        )

    def _atualizar(self) -> None:
        arquivos = self._arquivos()
        assinatura = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in arquivos)
        if assinatura == self._assinatura:
            return
        trechos = []
        for p in arquivos:
            rel = p.relative_to(self.root).as_posix()
            area = rel.split("/")[0] if "/" in rel and rel.split("/")[0] in AREAS else "geral"
            try:
                meta, corpo = _cabecalho(ler_documento(p))
            except Exception:  # noqa: BLE001 — um arquivo ruim não derruba a base inteira
                logger.exception(f"base de conhecimento: não consegui ler {rel}")
                continue
            titulo = meta.get("Título", p.stem)
            trechos += [Trecho(titulo, rot, rel, area, txt) for rot, txt in cortar(corpo)]
        self.trechos = trechos
        self._tf = [Counter(tokens(f"{t.rotulo} {t.texto}")) for t in trechos]
        self._df = Counter(term for tf in self._tf for term in tf)
        self._media = sum(sum(tf.values()) for tf in self._tf) / max(len(self._tf), 1)
        self._assinatura = assinatura
        logger.info(f"base de conhecimento: {len(arquivos)} arquivos, {len(trechos)} trechos")

    def buscar(self, consulta: str, area: str | None = None, k: int = 5) -> list[tuple[float, Trecho]]:
        self._atualizar()
        q = _norm(consulta)
        termos = tokens(consulta)
        for chave, extra in SINONIMOS.items():
            if chave in q:
                termos += tokens(extra)
        artigo = re.search(r"\bart(?:igo)?\.?\s*(\d+)", q)
        n = len(self.trechos)
        pontos = []
        for i, (t, tf) in enumerate(zip(self.trechos, self._tf, strict=True)):
            if area and area != "geral" and t.area != area:
                continue
            tam = sum(tf.values()) or 1
            s = 0.0
            for term in set(termos):
                f = tf.get(term)
                if f:
                    idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                    s += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * tam / self._media))
            if s and any(a in q for a in self._apelidos.get(t.arquivo, ())):
                s += 2.0  # a pergunta nomeia a lei
            if artigo and t.rotulo.split(" (")[0] in (f"Art. {artigo.group(1)}",):
                s += 10.0  # "art. 173" na pergunta: o próprio artigo vem primeiro
            if s > 0:
                pontos.append((s, i))
        pontos.sort(reverse=True)
        return [(round(s, 2), self.trechos[i]) for s, i in pontos[:k]]

    def resumo(self) -> dict:
        self._atualizar()
        return {"pasta": str(self.root), "arquivos": len({t.arquivo for t in self.trechos}),
                "trechos": len(self.trechos)}


def _main(argv: list[str]) -> int:
    from .config import get_settings

    root = get_settings().knowledge_dir()
    if argv[:1] == ["baixar"]:
        for p in baixar(root):
            print(p)
        return 0
    if argv[:1] == ["buscar"] and len(argv) > 1:
        for s, t in KnowledgeBase(root).buscar(" ".join(argv[1:])):
            print(f"{s:6.2f}  {t.fonte} — {t.rotulo}\n        {t.texto[:160]!r}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
