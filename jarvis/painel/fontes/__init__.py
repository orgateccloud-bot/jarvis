"""Fontes oficiais do card tributário, configuradas em config/fontes_fiscais.json (uma entrada por fonte)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...config import ROOT
from .base import Coletor
from .cgibs import ResolucoesCgibs
from .confaz import ConveniosConfaz
from .marcos import MarcosReforma
from .receita_agenda import AgendaReceita
from .rss import FeedRSS
from .sefaz_to import NoticiasSefazTO

CONFIG_PADRAO = ROOT / "config" / "fontes_fiscais.json"


class FonteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    tipo: Literal["agenda_receita", "rss", "confaz", "cgibs_resolucoes", "sefaz_to", "marcos", "planalto"]
    nome: str
    url: str | None = None
    ligada: bool = True
    palavras: list[str] = Field(default_factory=list)
    maximo: int = Field(default=15, ge=1, le=100)
    dias: int = Field(default=45, ge=1, le=120)
    arquivo: str | None = None
    nota: str | None = None


def carregar(caminho: Path = CONFIG_PADRAO) -> list[FonteConfig]:
    return [FonteConfig.model_validate(f) for f in json.loads(caminho.read_text(encoding="utf-8"))["fontes"]]


def coletor(cfg: FonteConfig) -> Coletor:
    """O coletor da fonte. "planalto" não tem coletor: o portal recusa coleta automática (conferido em 31/10/2026)."""
    comum = {"id": cfg.id, "nome": cfg.nome, "url": cfg.url or "", "palavras": cfg.palavras, "maximo": cfg.maximo}
    match cfg.tipo:
        case "agenda_receita":
            return AgendaReceita(**comum, dias=cfg.dias)
        case "rss":
            return FeedRSS(**comum)
        case "confaz":
            return ConveniosConfaz(**comum)
        case "cgibs_resolucoes":
            return ResolucoesCgibs(**comum)
        case "sefaz_to":
            return NoticiasSefazTO(**comum)
        case "marcos":
            return MarcosReforma(**comum, arquivo=ROOT / (cfg.arquivo or "config/marcos_reforma.json"))
    raise ValueError(f"a fonte {cfg.id} ({cfg.tipo}) não tem coletor: {cfg.nota or 'tipo sem implementação'}")
