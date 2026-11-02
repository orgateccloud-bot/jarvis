"""Trilhum (estudos para concurso e OAB): planos, agenda do dia e resumo de um plano. Só leitura.

O serviço (jarvis.estudos.trilhum) lê os planos e roda o próprio app para montar a agenda; aqui só se valida a
entrada e se escreve a resposta. O progresso (o que já foi feito) fica no navegador do usuário e não é lido.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field

from ..estudos.trilhum import PLANO_ID, Agenda, Bloco, PlanoInfo, Trilhum, TrilhumErro
from . import Tool, ToolContext, ToolError

DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
AVISO = ("Horários padrão do plano (o seu cadastro no Trilhum pode ter outros). O que já foi feito não aparece aqui: "
         "o progresso fica no navegador.")
PLANO_CAMPO = Field(default=None, pattern=PLANO_ID.pattern,
                    description="Id do plano (ex.: rota40-oab-48). Vazio = o plano em andamento")


def _br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "sem data"


def _servico(ctx: ToolContext) -> Trilhum:
    if ctx.trilhum is None:
        raise ToolError("o Trilhum não está configurado neste JARVIS (JARVIS_TRILHUM_DIR)")
    return ctx.trilhum


def _bloco(b: Bloco) -> str:
    quando = f"{b.inicio} · " if b.inicio else ""
    duracao = f", {b.minutos} min" if b.minutos else ""
    assunto = f": {b.assunto}" if b.assunto else ""
    return f"- {quando}{b.tipo}{duracao} · {b.disciplina}{assunto}"


def _periodo(p: PlanoInfo) -> str:
    return f"{_br(p.inicio)} a {_br(p.alvo)}" if p.alvo else f"desde {_br(p.inicio)}"


# ── planos ───────────────────────────────────────────────────
class PlanosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def trilhum_planos(p: PlanosParams, ctx: ToolContext) -> str:
    t, hoje = _servico(ctx), date.today()
    try:
        planos = t.planos()
    except TrilhumErro as e:
        raise ToolError(str(e)) from e
    if not planos:
        return "Não há planos na pasta do Trilhum."
    linhas = []
    for x in planos:
        marca = " · plano de teste" if x.teste else " · em andamento" if x.em_andamento(hoje) else ""
        linhas.append(f"- {x.id}: {x.titulo} ({_periodo(x)}; versão {x.versao or '?'}){marca}")
    return "Planos do Trilhum:\n" + "\n".join(linhas)


# ── agenda ───────────────────────────────────────────────────
class AgendaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str | None = PLANO_CAMPO
    data: date | None = Field(default=None, description="Primeiro dia (AAAA-MM-DD). Vazio = hoje")
    dias: int = Field(default=1, ge=1, le=7, description="Quantos dias a partir da data (1 a 7)")


def trilhum_agenda(p: AgendaParams, ctx: ToolContext) -> str:
    t, hoje = _servico(ctx), date.today()
    inicio = p.data or hoje
    try:
        info = t.escolher(p.plano, inicio)
        agenda = t.agenda(info.id)
    except TrilhumErro as e:
        raise ToolError(str(e)) from e
    partes = [f"{info.titulo} ({info.id}), {_periodo(info)}."]
    for i in range(p.dias):
        d = inicio + timedelta(days=i)
        cab = f"{DIAS_SEMANA[d.weekday()]}, {_br(d)}"
        achado = agenda.dia(d)
        if achado is None:
            partes.append(f"{cab}: fora do plano.")
            continue
        semana, dia = achado
        cab += f" · semana {semana.n} de {agenda.total}, {semana.titulo} ({semana.fase})"
        if dia.feriado:
            cab += f" · feriado: {dia.feriado}"
        if dia.depois_da_prova:
            partes.append(f"{cab}: depois da data-alvo, sem estudo.")
        elif not dia.blocos:
            partes.append(f"{cab}: sem estudo marcado.")
        else:
            partes.append(cab + "\n" + "\n".join(_bloco(b) for b in dia.blocos))
    try:
        outros = [x.id for x in t.planos() if x.id != info.id and not x.teste and x.em_andamento(inicio)]
    except TrilhumErro:
        outros = []
    if outros and not p.plano:
        partes.append(f"Também em andamento: {', '.join(outros)} (peça pelo nome).")
    partes.append(AVISO)
    return "\n\n".join(partes)


# ── resumo do plano ──────────────────────────────────────────
class PlanoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str | None = PLANO_CAMPO


def trilhum_plano(p: PlanoParams, ctx: ToolContext) -> str:
    t = _servico(ctx)
    try:
        info = t.escolher(p.plano, date.today())
        dados = t.plano(info.id)
        agenda: Agenda | None = t.agenda(info.id)
    except TrilhumErro as e:
        if "Node" not in str(e) and "jsdom" not in str(e):
            raise ToolError(str(e)) from e
        agenda = None  # sem o motor, o resumo sai sem as datas das fases
    linhas = [f"{info.titulo} ({info.id}), versão {info.versao or '?'}: {_periodo(info)}."]
    if dados.get("lead"):
        linhas.append(str(dados["lead"]))
    if agenda:
        linhas.append(f"Fases ({agenda.total} semanas):")
        linhas += [f"- {f.nome}: {_br(f.inicio)} a {_br(f.fim)}" + (f". {f.saida}" if f.saida else "")
                   for f in agenda.fases]
    disciplinas = dados.get("disciplinas") or {}
    if isinstance(disciplinas, dict) and disciplinas:
        linhas.append("Disciplinas (prioridade A, B ou C):")
        for nome, d in disciplinas.items():
            d = d if isinstance(d, dict) else {}
            extra = "; ".join(str(d[k]) for k in ("obj", "retorno") if d.get(k))
            linhas.append(f"- {d.get('nome') or nome} [{d.get('pri', '?')}]" + (f": {extra}" if extra else ""))
    metas = dados.get("metas") or {}
    if isinstance(metas, dict) and metas.get("meta") is not None:
        linhas.append(f"Meta: {metas['meta']}" + (f" (base {metas['base']})" if metas.get("base") is not None else ""))
    return "\n".join(linhas)


TRILHUM_TOOLS = [
    Tool(
        name="trilhum_agenda",
        description="Agenda de estudos do Trilhum (concursos e OAB) num dia ou em até 7 dias: blocos com horário, "
                    "disciplina e assunto, montados pelo próprio app. Sem plano, usa o que está em andamento. Não "
                    "mostra o progresso.",
        params=AgendaParams, run=trilhum_agenda,
        summary=lambda p: f"consultou a agenda do Trilhum ({p.data or 'hoje'}, {p.dias} dia(s))",
    ),
    Tool(
        name="trilhum_planos",
        description="Lista os planos de estudo do Trilhum com período e versão, e indica os em andamento.",
        params=PlanosParams, run=trilhum_planos, summary=lambda p: "listou os planos do Trilhum",
    ),
    Tool(
        name="trilhum_plano",
        description="Resumo de um plano do Trilhum: período, fases com datas, disciplinas com prioridade e meta.",
        params=PlanoParams, run=trilhum_plano, summary=lambda p: f"resumiu o plano {p.plano or 'em andamento'}",
    ),
]
