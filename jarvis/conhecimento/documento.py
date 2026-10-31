"""Documento da base: leitura (txt, md, html, pdf), HTML → texto e cabeçalho v2 (R3).

Cabeçalho v2 (uma linha "Chave: valor" por campo, depois "---"):
Título / Fonte (URL) / Baixado em / Biblioteca / Fonte-id / Tipo / Esfera / UF / Vigência (início a fim) /
Situação (vigente, revogado, histórico) / Hash (sha256 do texto). Arquivos antigos (só Título/Fonte/Baixado em)
continuam válidos; campo ausente = vazio.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

SEPARADOR = "\n---\n"
QUEBRA_PAGINA = "\n\f\n"


# ── HTML → texto ─────────────────────────────────────────────
class _Texto(HTMLParser):
    """Extrai o texto; descarta script/style e, se pedido, trechos riscados (redação revogada no texto compilado)."""

    _BLOCO = frozenset({"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"})
    _VAZIAS = frozenset({"br", "img", "meta", "hr", "input", "link", "col", "area", "base", "wbr"})

    def __init__(self, remover_tachado: bool = True):
        super().__init__(convert_charrefs=True)
        self.remover_tachado = remover_tachado
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
        tachado = tag in ("strike", "s", "del") or "line-through" in estilo
        self.pilha.append((tag, tag in ("script", "style") or (tachado and self.remover_tachado)))

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


def html_para_texto(html: str, remover_tachado: bool = True) -> str:
    p = _Texto(remover_tachado)
    p.feed(html)
    texto = "".join(p.partes).replace("\xa0", " ").replace("\u200b", "")
    linhas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


def decodificar(raw: bytes, charset: str | None) -> str:
    for enc in filter(None, (charset, "utf-8", "cp1252")):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("cp1252", errors="replace")


def pdf_para_texto(dados: bytes | Path) -> str:
    """Uma página por bloco, separadas por form feed (o corte "pagina" usa essa marca)."""
    from io import BytesIO

    from pypdf import PdfReader

    leitor = PdfReader(dados if isinstance(dados, Path) else BytesIO(dados))
    return QUEBRA_PAGINA.join((p.extract_text() or "").strip() for p in leitor.pages)


def ler_documento(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".html", ".htm"):
        return html_para_texto(decodificar(path.read_bytes(), None))
    if suf == ".pdf":
        try:
            return pdf_para_texto(path)
        except ImportError:
            logger.warning(f"pypdf não instalado: {path.name} fica fora da base")
            return ""
    return decodificar(path.read_bytes(), None).replace("\r\n", "\n")


# ── cabeçalho v2 ─────────────────────────────────────────────
CAMPOS = {"titulo": "Título", "fonte": "Fonte", "baixado_em": "Baixado em", "biblioteca": "Biblioteca",
          "fonte_id": "Fonte-id", "tipo": "Tipo", "esfera": "Esfera", "uf": "UF", "vigencia": "Vigência",
          "situacao": "Situação", "hash": "Hash"}
_CHAVES = {v: k for k, v in CAMPOS.items()}


def data_br(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def ler_data(texto: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto.strip(), fmt).date()
        except ValueError:
            continue
    return None


class Cabecalho(BaseModel):
    titulo: str = ""
    fonte: str = ""           # URL de origem
    baixado_em: str = ""      # dd/mm/aaaa (última captura que conferiu o texto)
    biblioteca: str = ""
    fonte_id: str = ""
    tipo: str = ""
    esfera: str = ""
    uf: str = ""
    vigencia: str = ""        # "dd/mm/aaaa a dd/mm/aaaa" (fim vazio = em vigor)
    situacao: str = ""
    hash: str = ""

    def baixado(self) -> date | None:
        return ler_data(self.baixado_em) if self.baixado_em else None

    def periodo(self) -> tuple[date | None, date | None]:
        """Vigência (início, fim). Sem o campo, o início é a data da captura (o que se sabe de fato)."""
        if not self.vigencia:
            return self.baixado(), None
        m = re.fullmatch(r"\s*(\S*)\s*(?:a\s*(\S*))?\s*", self.vigencia)
        ini, fim = (m.group(1), m.group(2) or "") if m else ("", "")
        return ler_data(ini) if ini else None, ler_data(fim) if fim else None


def ler_cabecalho(texto: str) -> tuple[Cabecalho, str]:
    """Separa cabeçalho e corpo. Só vale como cabeçalho se a 1ª linha for um campo conhecido ("Título: ...")."""
    topo, sep, _ = texto[:4000].partition(SEPARADOR)
    if not sep or topo.split(": ", 1)[0] not in _CHAVES:
        return Cabecalho(), texto
    campos = {}
    for ln in topo.splitlines():
        chave, _, valor = ln.partition(": ")
        if chave in _CHAVES:
            campos[_CHAVES[chave]] = valor.strip()
    return Cabecalho(**campos), texto[len(topo) + len(SEPARADOR):]


def escrever_cabecalho(cab: Cabecalho) -> str:
    linhas = [f"{rotulo}: {getattr(cab, campo)}" for campo, rotulo in CAMPOS.items()
              if getattr(cab, campo) or campo == "titulo"]
    return "\n".join(linhas) + SEPARADOR


def normalizar(corpo: str) -> str:
    return corpo.replace("\r\n", "\n").strip() + "\n"


def hash_texto(corpo: str) -> str:
    return hashlib.sha256(normalizar(corpo).encode("utf-8")).hexdigest()
