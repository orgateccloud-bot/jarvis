"""Trilhum (estudos para concurso e OAB): planos, agenda, andamento e resumo de um plano. Só leitura.

O serviço (jarvis.estudos) lê os planos, roda o próprio app para montar a agenda e lê o progresso pela sincronização
do Trilhum; aqui só se valida a entrada e se escreve a resposta. Sem a sincronização configurada, a agenda usa os
horários padrão do plano e o andamento não está disponível.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field

from ..estudos.andamento import calcular
from ..estudos.sincronizacao import Progresso
from ..estudos.trilhum import PLANO_ID, Agenda, Bloco, PlanoInfo, Trilhum, TrilhumErro
from . import Tool, ToolContext, ToolError

DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
SEM_SYNC = ("Horários padrão do plano (o seu cadastro no Trilhum pode ter outros); sem a sincronização configurada "
            "não vejo o que já foi feito.")
COM_SYNC = "Horários do seu cadastro no Trilhum; ✓ = marcado como feito (pela sincronização)."
PLANO_CAMPO = Field(default=None, pattern=PLANO_ID.pattern,
                    description="Id do plano (ex.: rota40-oab-48). Vazio = o plano em andamento")


def _br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "sem data"


def _servico(ctx: ToolContext) -> Trilhum:
    if ctx.trilhum is None:
        raise ToolError("o Trilhum não está configurado neste JARVIS (JARVIS_TRILHUM_DIR)")
    return ctx.trilhum


def _progresso(t: Trilhum, info: PlanoInfo) -> tuple[Progresso | None, str]:
    """(progresso, aviso). Falha na sincronização não derruba a agenda: vira aviso e valem os padrões do plano."""
    if t.sync is None or not t.sync.configurada:
        return None, SEM_SYNC
    try:
        prog = t.progresso(info.id)
    except TrilhumErro as e:
        return None, f"Não li o progresso ({e}); horários padrão do plano."
    if prog is None:
        return None, "Este plano ainda não foi sincronizado no Trilhum; horários padrão do plano."
    return prog, COM_SYNC


def _bloco(b: Bloco, prog: Progresso | None) -> str:
    quando = f"{b.inicio} · " if b.inicio else ""
    duracao = f", {b.minutos} min" if b.minutos else ""
    assunto = f": {b.assunto}" if b.assunto else ""
    marca = ""
    if prog is not None:
        marca = "✓ " if b.id in prog.feito else "· "
        if (ac := prog.acertos.get(b.id)) and b.tipo_bloco == "q":
            assunto += f" ({ac.ok:g} de {ac.tot or b.questoes:g} acertos)"
    return f"- {marca}{quando}{b.tipo}{duracao} · {b.disciplina}{assunto}"


def _periodo(p: PlanoInfo) -> str:
    return f"{_br(p.inicio)} a {_br(p.alvo)}" if p.alvo else f"desde {_br(p.inicio)}"


def _pct(a: float, b: float) -> str:
    return f"{round(100 * a / b)}%" if b else "—"


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
        prog, aviso = _progresso(t, info)
        agenda = t.agenda(info.id, prog.cfg if prog and prog.cfg else None)
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
            partes.append(cab + "\n" + "\n".join(_bloco(b, prog) for b in dia.blocos))
    try:
        outros = [x.id for x in t.planos() if x.id != info.id and not x.teste and x.em_andamento(inicio)]
    except TrilhumErro:
        outros = []
    if outros and not p.plano:
        partes.append(f"Também em andamento: {', '.join(outros)} (peça pelo nome).")
    partes.append(aviso)
    return "\n\n".join(partes)


# ── andamento ────────────────────────────────────────────────
class ProgressoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str | None = PLANO_CAMPO


def trilhum_progresso(p: ProgressoParams, ctx: ToolContext) -> str:
    t, hoje = _servico(ctx), date.today()
    try:
        info = t.escolher(p.plano, hoje)
        if t.sync is None or (problema := t.sync.problema()):
            raise ToolError(problema if t.sync is not None else "a sincronização do Trilhum não está ligada")
        prog = t.progresso(info.id)
        if prog is None:
            return f"{info.titulo} ({info.id}) ainda não foi sincronizado no Trilhum: não há progresso para ler."
        agenda = t.agenda(info.id, prog.cfg or None)
        dados = t.plano(info.id)
    except TrilhumErro as e:
        raise ToolError(str(e)) from e
    a = calcular(agenda, prog, hoje)
    linhas = [f"{info.titulo} ({info.id}), {_periodo(info)}: progresso pela sincronização do Trilhum."]
    linhas.append(f"Até ontem: {a.passados_feitos} de {a.passados_previstos} blocos feitos "
                  f"({_pct(a.passados_feitos, a.passados_previstos)}). Hoje: {a.hoje_feitos} de {a.hoje_previstos}.")
    if a.semana:
        linhas.append(f"Semana {a.semana.n} de {agenda.total} ({a.semana.titulo}): {a.semana_feitos} de "
                      f"{a.semana_previstos} blocos feitos.")
    if a.pendentes_semana:
        linhas.append("Pendentes desta semana:")
        linhas += [f"- {DIAS_SEMANA[x.data.weekday()]} {x.data:%d/%m}: {x.bloco.tipo} · {x.bloco.disciplina}"
                   + (f" ({x.bloco.assunto[:80]})" if x.bloco.assunto else "") for x in a.pendentes_semana]
    if a.pendentes_antes:
        linhas.append(f"Das semanas anteriores, {a.pendentes_antes} bloco(s) ficaram sem marcar.")
    com_blocos = [x for x in a.disciplinas if x.previstos][:10]
    if com_blocos:
        linhas.append("Por disciplina, até ontem:")
        for x in com_blocos:
            q = (f"; questões {x.acertos_ok:g} de {x.acertos_tot:g} ({_pct(x.acertos_ok, x.acertos_tot)})"
                 if x.acertos_tot else "")
            linhas.append(f"- {x.disciplina}: {x.feitos} de {x.previstos} blocos{q}")
    if a.notas:
        maximo, unidade = dados.get("notaMax"), dados.get("unidadeNota") or ""
        sufixo = f" de {maximo}" + (f" {unidade}" if unidade else "") if maximo else ""
        tipo = {"obj": "objetiva", "disc": "discursiva"}
        linhas.append("Últimas notas: " + "; ".join(f"{n.d:%d/%m} {tipo.get(n.t, n.t)} {n.n:g}{sufixo}"
                                                  for n in a.notas) + ".")
    if a.revisoes:
        feitas = [f"{k} ({v}/6)" for k, v in sorted(a.revisoes.items(), key=lambda kv: int(kv[0])) if v]
        if feitas:
            linhas.append("Revisões de sábado: semana " + ", ".join(feitas) + ".")
    return "\n".join(linhas)


# ── resumo do plano ──────────────────────────────────────────
class PlanoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str | None = PLANO_CAMPO


def trilhum_plano(p: PlanoParams, ctx: ToolContext) -> str:
    t = _servico(ctx)
    try:
        info = t.escolher(p.plano, date.today())
        dados = t.plano(info.id)
        prog, _ = _progresso(t, info)
        agenda: Agenda | None = t.agenda(info.id, prog.cfg if prog and prog.cfg else None)
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
                    "disciplina e assunto, montados pelo próprio app, e o que já foi feito. Sem plano, usa o que "
                    "está em andamento.",
        params=AgendaParams, run=trilhum_agenda,
        summary=lambda p: f"consultou a agenda do Trilhum ({p.data or 'hoje'}, {p.dias} dia(s))",
    ),
    Tool(
        name="trilhum_progresso",
        description="Andamento no Trilhum: blocos feitos até ontem, hoje e na semana, pendências, desempenho por "
                    "disciplina, acertos em questões e notas dos exames.",
        params=ProgressoParams, run=trilhum_progresso,
        summary=lambda p: f"consultou o progresso no Trilhum ({p.plano or 'plano em andamento'})",
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
