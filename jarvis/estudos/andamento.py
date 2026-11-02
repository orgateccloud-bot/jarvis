"""Andamento de um plano do Trilhum: o que foi feito até ontem, hoje e na semana, por disciplina e as notas.

Junta a agenda montada pelo app (com o cadastro do usuário) e o progresso da sincronização. Os blocos são casados
pelo id do app ("5-0t"), o mesmo que o app usa ao marcar "feito"; os acertos, pelo id dos blocos de questões.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from .sincronizacao import Nota, Progresso
from .trilhum import Agenda, Bloco, Semana

MAX_PENDENTES = 8
MAX_NOTAS = 5


class Pendente(BaseModel):
    data: date
    bloco: Bloco


class PorDisciplina(BaseModel):
    disciplina: str
    previstos: int = 0
    feitos: int = 0
    acertos_ok: float = 0
    acertos_tot: float = 0


class Andamento(BaseModel):
    passados_previstos: int = 0     # blocos dos dias antes de hoje
    passados_feitos: int = 0
    hoje_previstos: int = 0
    hoje_feitos: int = 0
    semana: Semana | None = None
    semana_previstos: int = 0
    semana_feitos: int = 0
    pendentes_semana: list[Pendente] = Field(default_factory=list)   # dias antes de hoje, nesta semana
    pendentes_antes: int = 0                                        # não feitos das semanas anteriores
    disciplinas: list[PorDisciplina] = Field(default_factory=list)
    notas: list[Nota] = Field(default_factory=list)
    revisoes: dict[str, int] = Field(default_factory=dict)


def calcular(agenda: Agenda, prog: Progresso, hoje: date) -> Andamento:
    a = Andamento(notas=prog.notas[-MAX_NOTAS:], revisoes=prog.revisoes)
    por_disc: dict[str, PorDisciplina] = {}
    a.semana = next((s for s in agenda.semanas if s.segunda <= hoje < s.segunda + timedelta(days=7)), None)
    for s in agenda.semanas:
        na_semana = a.semana is not None and s.n == a.semana.n
        for d in s.dias:
            for b in d.blocos:
                feito = b.id in prog.feito
                if na_semana:
                    a.semana_previstos += 1
                    a.semana_feitos += feito
                if d.data == hoje:
                    a.hoje_previstos += 1
                    a.hoje_feitos += feito
                if d.data >= hoje:
                    continue
                a.passados_previstos += 1
                a.passados_feitos += feito
                x = por_disc.setdefault(b.disciplina, PorDisciplina(disciplina=b.disciplina))
                x.previstos += 1
                x.feitos += feito
                if b.tipo_bloco == "q" and (ac := prog.acertos.get(b.id)):
                    x.acertos_ok += ac.ok
                    x.acertos_tot += ac.tot or b.questoes
                if not feito:
                    if na_semana:
                        a.pendentes_semana.append(Pendente(data=d.data, bloco=b))
                    else:
                        a.pendentes_antes += 1
    a.pendentes_semana = a.pendentes_semana[:MAX_PENDENTES]
    a.disciplinas = sorted(por_disc.values(), key=lambda x: (-x.previstos, x.disciplina))
    return a
