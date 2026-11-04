"""Trilhum: planos de estudo para concurso e OAB (projeto em D:\\01_Projetos_Ativos\\Geladeira\\edtech-ai-platform\\trilhum), só leitura.

A agenda (o que estudar em cada dia) vem do próprio app: agenda_trilhum.mjs abre o trilha.html num navegador
simulado, como os testes do Trilhum fazem, e devolve as semanas que ele monta. Copiar a lógica do calendário
(fases, data-alvo, fase extra, reta final, rodízio de tópicos, sábados) para Python divergiria do app.

O cadastro (início, data-alvo, dias e horários) e o progresso do usuário ficam no navegador dele, com
sincronização opcional pela conta do Trilhum (Firestore). Com a sincronização configurada (sincronizacao.py), a
agenda é montada com o cadastro dele e os blocos feitos são marcados; sem ela, valem os padrões do plano. Nada é gravado na
Trilha.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 — só roda o Node com argumentos fixos (ver _executar_node)
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

PLANO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")   # o mesmo formato de id que o app aceita
SCRIPT = Path(__file__).with_name("agenda_trilhum.mjs")
TIMEOUT_S = 60.0  # abrir o app no jsdom leva de 4 a 6 s nesta máquina


class TrilhumErro(Exception):
    """Plano inexistente, pasta ausente, Node ausente ou o app mudou: mensagem para o usuário."""


class Bloco(BaseModel):
    id: str = ""              # o mesmo id do app ("5-0t"): é por ele que o progresso marca o bloco como feito
    tipo: str = ""            # rótulo do plano: "Lei seca", "Questões", "Exame", "Prova"...
    tipo_bloco: str = ""      # t (teoria), l (leitura), q (questões), a (áudio), x (extra) e outros do app
    disciplina: str = ""
    assunto: str = ""
    minutos: int = 0
    inicio: str | None = None  # HH:MM; None quando o plano não fixa horário (sábados, prova)
    questoes: int = 0


class Dia(BaseModel):
    data: date
    feriado: str = ""
    depois_da_prova: bool = False
    blocos: list[Bloco] = Field(default_factory=list)


class Semana(BaseModel):
    n: int
    segunda: date
    fase: str = ""
    titulo: str = ""
    dias: list[Dia] = Field(default_factory=list)


class Fase(BaseModel):
    nome: str
    descricao: str = ""
    saida: str = ""
    inicio: date | None = None
    fim: date | None = None


class Agenda(BaseModel):
    total: int
    semanas: list[Semana]
    fases: list[Fase] = Field(default_factory=list)

    def dia(self, d: date) -> tuple[Semana, Dia] | None:
        for s in self.semanas:
            for x in s.dias:
                if x.data == d:
                    return s, x
        return None


class PlanoInfo(BaseModel):
    id: str
    sigla: str = ""
    titulo: str
    inicio: date | None = None
    alvo: date | None = None
    versao: str = ""
    origem: str = "pasta"   # "pasta" (planos\*.json) ou "app" (salvo no app e sincronizado)

    @classmethod
    def de(cls, plano_id: str, d: dict, origem: str = "pasta") -> PlanoInfo:
        return cls(id=plano_id, sigla=str(d.get("sigla") or ""), titulo=str(d.get("titulo") or d.get("nome") or plano_id),
                   inicio=_data(d.get("inicio")), alvo=_data(d.get("alvo")), versao=str(d.get("versao") or ""),
                   origem=origem)

    @property
    def teste(self) -> bool:
        """Plano de teste do Trilhum (plano-teste-dados): listado, mas nunca escolhido sem ser pedido."""
        return "teste" in self.id or self.versao.lower().startswith("teste")

    def em_andamento(self, hoje: date) -> bool:
        return bool(self.inicio and self.inicio <= hoje <= (self.alvo or date.max))


def _data(v) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


Executor = Callable[[list[str], float, str | None], str]  # (argv, timeout, entrada) -> stdout


def _executar_node(argv: list[str], timeout_s: float, entrada: str | None = None) -> str:
    try:
        # argv = [node, agenda_trilhum.mjs, trilha.html, node_modules]: montados aqui, sem shell; o plano e o
        # cadastro do usuário vão pela entrada padrão, não pela linha de comando
        r = subprocess.run(argv, input=entrada, capture_output=True, text=True, encoding="utf-8",  # nosec B603
                           timeout=timeout_s, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise TrilhumErro(f"o app do Trilhum não montou a agenda em {timeout_s:.0f} s") from e
    except OSError as e:
        raise TrilhumErro(f"não consegui rodar o Node: {e}") from e
    if r.returncode != 0:
        linhas = (r.stderr or "").strip().splitlines() or ["sem detalhe"]
        raise TrilhumErro(f"o app do Trilhum falhou ao montar a agenda: {linhas[-1][:300]}")
    return r.stdout


class Trilhum:
    def __init__(self, pasta: Path, plano_padrao: str = "", node: str | None = None, modulos: Path | None = None,
                 timeout_s: float = TIMEOUT_S, executar: Executor = _executar_node, sync: Any = None):
        self.pasta = pasta
        self.sync = sync   # SincronizacaoTrilhum (progresso e cadastro do usuário); None = só os padrões do plano
        self.plano_padrao = plano_padrao.strip().lower()
        self.node = node or shutil.which("node")
        self.modulos = modulos or pasta / "testes" / "node_modules"   # o jsdom que os testes do Trilhum já usam
        self.timeout_s = timeout_s
        self._executar = executar
        self._cache: dict[str, tuple[tuple, Agenda]] = {}   # plano → ((hash do plano e cadastro, mtime do app), agenda)
        self._trava = threading.Lock()

    @property
    def html(self) -> Path:
        return self.pasta / "trilha.html"

    def _catalogo(self) -> dict[str, dict]:
        """Planos salvos no app (sincronização); vazio se ela não estiver configurada ou falhar."""
        if self.sync is None or not self.sync.configurada:
            return {}
        try:
            return self.sync.catalogo()
        except TrilhumErro:
            return {}

    def planos(self) -> list[PlanoInfo]:
        """Os planos da pasta planos\\ e os salvos no app (estes valem quando o id é o mesmo: é a versão que o
        usuário usa), do que começa antes ao que começa depois."""
        pasta = self.pasta / "planos"
        if not pasta.is_dir():
            raise TrilhumErro(f"a pasta de planos do Trilhum não existe: {pasta}")
        out: dict[str, PlanoInfo] = {}
        for f in pasta.glob("*.json"):
            if not PLANO_ID.match(f.stem):
                continue
            try:
                out[f.stem] = PlanoInfo.de(f.stem, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # arquivo ilegível não derruba a lista
        for pid, d in self._catalogo().items():
            out[pid] = PlanoInfo.de(pid, d, origem="app")
        return sorted(out.values(), key=lambda p: (p.inicio or date.max, p.id))

    def escolher(self, plano_id: str | None, hoje: date) -> PlanoInfo:
        """O plano pedido; senão JARVIS_TRILHUM_PLANO; senão, fora os de teste e preferindo os salvos no app, o em
        andamento que começou por último, o próximo a começar ou o último."""
        planos = self.planos()
        if not planos:
            raise TrilhumErro(f"não há planos em {self.pasta / 'planos'}")
        pedido = (plano_id or self.plano_padrao or "").strip().lower()
        if pedido:
            achado = next((p for p in planos if pedido in (p.id.lower(), p.sigla.lower())), None)
            if achado is None:
                raise TrilhumErro(f"plano {pedido!r} não encontrado; os planos são: {', '.join(p.id for p in planos)}")
            return achado
        planos = [p for p in planos if not p.teste] or planos
        planos = [p for p in planos if p.origem == "app"] or planos   # o que o usuário usa no app vem antes
        andamento = [p for p in planos if p.em_andamento(hoje)]
        if andamento:
            return max(andamento, key=lambda p: p.inicio)
        futuros = [p for p in planos if p.inicio and p.inicio > hoje]
        return min(futuros, key=lambda p: p.inicio) if futuros else planos[-1]

    def arquivo(self, plano_id: str) -> Path:
        if not PLANO_ID.match(plano_id):
            raise TrilhumErro(f"nome de plano inválido: {plano_id!r}")
        f = self.pasta / "planos" / f"{plano_id}.json"
        if not f.is_file():
            raise TrilhumErro(f"plano não encontrado: {f}")
        return f

    def plano(self, plano_id: str) -> dict:
        """O conteúdo do plano: a versão salva no app, se houver; senão o arquivo da pasta."""
        if not PLANO_ID.match(plano_id):
            raise TrilhumErro(f"nome de plano inválido: {plano_id!r}")
        if (d := self._catalogo().get(plano_id)) is not None:
            return d
        try:
            return json.loads(self.arquivo(plano_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise TrilhumErro(f"não consegui ler o plano {plano_id}: {e}") from e

    def progresso(self, plano_id: str):
        """Progresso e cadastro do usuário pela sincronização do app (Progresso), ou None se o plano ainda não foi
        sincronizado. TrilhumErro se a sincronização não estiver configurada ou falhar."""
        from .sincronizacao import plano_sync

        if self.sync is None:
            raise TrilhumErro("a sincronização do Trilhum não está ligada neste JARVIS")
        return self.sync.ler(plano_sync(self.plano(plano_id), plano_id))

    def agenda(self, plano_id: str, cfg: dict | None = None) -> Agenda:
        """As semanas montadas pelo app, com o cadastro do usuário (cfg) se houver. Fica em cache até o plano, o
        trilha.html ou o cadastro mudarem."""
        plano = dict(self.plano(plano_id))
        plano.setdefault("id", plano_id)
        if not self.html.is_file():
            raise TrilhumErro(f"o app do Trilhum não foi encontrado: {self.html}")
        if not self.node:
            raise TrilhumErro("o Node não está instalado (ou não está no PATH); a agenda usa o próprio app do Trilhum")
        if not (self.modulos / "jsdom").is_dir():
            raise TrilhumErro(f"o jsdom não está em {self.modulos} (rode npm install em {self.pasta / 'testes'})")
        entrada = json.dumps({"plano": plano, "cfg": cfg or None}, ensure_ascii=False, sort_keys=True)
        chave = (hashlib.sha256(entrada.encode()).hexdigest(), self.html.stat().st_mtime_ns)
        argv = [self.node, str(SCRIPT), str(self.html), str(self.modulos)]
        with self._trava:
            if (c := self._cache.get(plano_id)) and c[0] == chave:
                return c[1]
            saida = self._executar(argv, self.timeout_s, entrada)
            try:
                agenda = Agenda.model_validate_json(saida)
            except ValueError as e:
                raise TrilhumErro(f"o app do Trilhum devolveu uma agenda que não entendi: {str(e)[:200]}") from e
            self._cache[plano_id] = (chave, agenda)
            return agenda
