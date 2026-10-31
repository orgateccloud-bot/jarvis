"""Catálogo de fontes (R1): um TOML por biblioteca em <base>/_catalogo. Só dados; o motor não muda quando ele muda.

Situação: proposto (sugerido) | aprovado (só o Senhor libera; só estes são baixados) | suspenso.
Um catálogo ou uma fonte com erro vira mensagem clara (arquivo e fonte) e fica de fora; o resto da base continua.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Situacao = Literal["proposto", "aprovado", "suspenso"]
Adaptador = Literal["html_simples", "pdf", "lista_links", "zip", "pasta_local", "manual", "tabela"]
Corte = Literal["artigo", "anexo", "sumula", "ementa", "secao", "pagina"]
Esfera = Literal["federal", "estadual", "municipal", "profissional", "interno", "tecnico"]
Frequencia = Literal["diaria", "semanal", "quinzenal", "mensal", "trimestral", "semestral", "anual", "manual"]
SEM_REDE = ("pasta_local", "manual")      # adaptadores que não usam url
DIAS_FREQUENCIA = {"diaria": 1, "semanal": 7, "quinzenal": 15, "mensal": 31, "trimestral": 92, "semestral": 183,
                   "anual": 366}

_ID = r"^[a-z0-9][a-z0-9_-]*$"


class Colunas(BaseModel):
    """Adaptador tabela: como cada linha (CSV ou tabela HTML) vira um item. Modelos usam {coluna}."""

    model_config = ConfigDict(extra="forbid")
    rotulo: str = Field(min_length=1)              # ex.: "{tipoPrecedente} {numeroPrecedente}"
    texto: list[str] = Field(min_length=1)         # colunas do corpo, na ordem
    situacao: str = ""
    data: str = ""
    url: str = ""                                  # modelo do link do item (só citado, não baixado)


class FonteCatalogo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=_ID, max_length=60)
    titulo: str = Field(min_length=1)
    tipo: str = Field(pattern=r"^[a-z_]+$")
    esfera: Esfera
    uf: str = Field(pattern=r"^[A-Z]{2}$")
    url: str = ""
    adaptador: Adaptador
    situacao: Situacao
    prioridade: int = Field(ge=1, le=9)
    frequencia: Frequencia
    corte: Corte
    obs: str = ""
    # opcionais (motor v2)
    area: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")   # sobrepõe a área da biblioteca
    transversal: bool = False                      # entra em qualquer filtro de área (precedentes do art. 927)
    arquivo: str | None = None                     # caminho na base; padrão <area>/<id>.md
    apelidos: list[str] = []                       # a pergunta que cita um apelido favorece esta fonte
    padrao_links: str | None = None                # lista_links: regex no endereço dos links do índice
    padrao_rotulo: str | None = None               # lista_links: regex no texto do link (grupos nome, situacao)
    padrao_item: str | None = None                 # html/pdf: regex da linha que abre cada item (grupos nome, situacao)
    inicio: str | None = None                      # recorta o texto a partir deste marcador...
    fim: str | list[str] | None = None             # ...até este (lista: vale o primeiro que aparecer)
    formato: Literal["csv", "html"] | None = None  # tabela
    colunas: Colunas | None = None                 # tabela
    filtro: dict[str, list[str]] = {}              # tabela: só linhas com estes valores
    pasta: str | None = None                       # pasta_local

    @field_validator("padrao_links", "padrao_rotulo", "padrao_item")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v

    @field_validator("arquivo")
    @classmethod
    def _relativo(cls, v: str | None) -> str | None:
        if v is not None:
            p = PurePosixPath(v.replace("\\", "/"))
            if p.is_absolute() or ":" in v or ".." in p.parts or p.parts[0].startswith(("_", ".")):
                raise ValueError("arquivo deve ser um caminho relativo dentro da base (sem '..' nem pasta '_')")
        return v

    @model_validator(mode="after")
    def _aprovado_completo(self) -> FonteCatalogo:
        if self.situacao != "aprovado":
            return self
        if self.adaptador not in SEM_REDE and urlparse(self.url).scheme != "https":
            raise ValueError("fonte aprovada precisa de url https")
        if self.adaptador == "pasta_local" and not self.pasta:
            raise ValueError("fonte aprovada com adaptador pasta_local precisa de 'pasta'")
        if self.adaptador == "lista_links" and not self.padrao_links:
            raise ValueError("fonte aprovada com adaptador lista_links precisa de 'padrao_links'")
        if self.adaptador == "tabela" and not self.colunas:
            raise ValueError("fonte aprovada com adaptador tabela precisa de 'colunas'")
        return self


class Biblioteca(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=_ID)
    nome: str = Field(min_length=1)
    area: str = Field(pattern=r"^[a-z0-9_]+$")
    descricao: str = ""
    versao_catalogo: int = Field(ge=1)
    atualizado_em: date


class Seguranca(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dominios: list[str] = []


@dataclass
class Catalogo:
    arquivo: Path
    biblioteca: Biblioteca
    seguranca: Seguranca
    fontes: list[FonteCatalogo]


@dataclass
class Carga:
    """Todos os catálogos válidos da pasta, mais os erros (um por fonte ou arquivo recusado)."""

    catalogos: list[Catalogo] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._fontes = {f.id: (f, c) for c in self.catalogos for f in c.fontes}

    def fontes(self) -> list[FonteCatalogo]:
        return [f for f, _ in self._fontes.values()]

    def fonte(self, fid: str) -> FonteCatalogo | None:
        return self._fontes.get(fid, (None, None))[0]

    def catalogo_de(self, fid: str) -> Catalogo | None:
        return self._fontes.get(fid, (None, None))[1]

    def area_de(self, fid: str) -> str | None:
        f, c = self._fontes.get(fid, (None, None))
        return (f.area or c.biblioteca.area) if f else None

    def arquivo_de(self, fid: str) -> str:
        f = self.fonte(fid)
        return f.arquivo.replace("\\", "/") if f and f.arquivo else f"{self.area_de(fid)}/{fid}.md"

    def fonte_do_arquivo(self, rel: str) -> FonteCatalogo | None:
        """Qual fonte grava neste caminho (para arquivos antigos, sem Fonte-id no cabeçalho)."""
        return next((f for f in self.fontes() if self.arquivo_de(f.id) == rel), None)

    def areas(self) -> list[str]:
        return sorted({c.biblioteca.area for c in self.catalogos} | {f.area for f in self.fontes() if f.area})


def _mensagens(erro: ValidationError) -> str:
    partes = []
    for e in erro.errors():
        msg = e["msg"].removeprefix("Value error, ")
        partes.append(f"{'.'.join(str(p) for p in e['loc'])}: {msg}" if e["loc"] else msg)
    return "; ".join(partes)


def carregar_catalogos(pasta: Path) -> Carga:
    catalogos, erros, vistos = [], [], {}
    for arq in sorted(pasta.glob("*.toml")) if pasta.is_dir() else []:
        try:
            bruto = tomllib.loads(arq.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as e:
            erros.append(f"{arq.name}: TOML inválido ({e}); catálogo ignorado")
            continue
        sobra = set(bruto) - {"biblioteca", "seguranca", "fonte"}
        try:
            if sobra:
                raise ValueError(f"seções desconhecidas: {', '.join(sorted(sobra))}")
            bib = Biblioteca.model_validate(bruto.get("biblioteca"))
            seg = Seguranca.model_validate(bruto.get("seguranca", {}))
        except ValidationError as e:
            erros.append(f"{arq.name}: [biblioteca]/[seguranca] inválido ({_mensagens(e)}); catálogo ignorado")
            continue
        except ValueError as e:
            erros.append(f"{arq.name}: {e}; catálogo ignorado")
            continue
        fontes = []
        for i, item in enumerate(bruto.get("fonte", []), 1):
            nome = item.get("id", f"#{i}") if isinstance(item, dict) else f"#{i}"
            try:
                f = FonteCatalogo.model_validate(item)
            except ValidationError as e:
                erros.append(f"{arq.name}: fonte '{nome}': {_mensagens(e)}; fonte ignorada")
                continue
            if f.id in vistos:
                erros.append(f"{arq.name}: fonte '{f.id}': id repetido (já existe em {vistos[f.id]}); fonte ignorada")
                continue
            vistos[f.id] = arq.name
            fontes.append(f)
        catalogos.append(Catalogo(arq, bib, seg, fontes))
    return Carga(catalogos, erros)


def dominio_permitido(url: str, dominios: list[str]) -> bool:
    """https e host na lista do catálogo: "gov.br" vale para subdomínios; curingas ("*.sefaz.*.gov.br") via fnmatch."""
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not host:
        return False
    for d in (d.lower() for d in dominios):
        if any(c in d for c in "*?[") and fnmatch.fnmatchcase(host, d):
            return True
        if host == d or host.endswith("." + d):
            return True
    return False
