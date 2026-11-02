"""Progresso do Trilhum lido da sincronização do app (Firestore do Trilhum), só leitura.

O app grava um JSON por plano em sync/{uid}/planos/{plano} (campo json, a string {app, plano, ts, data, em}, e
campo em), pela função "api"; o catálogo dos planos salvos fica no plano "_planos". Aqui só se lê, pelo Admin SDK
(sync_trilhum.mjs; ver firestore.py para a credencial e o emulador do modo teste); nada é gravado. O uid é o
código que o aluno copia no app ("Copiar código para o JARVIS"), em JARVIS_TRILHUM_UID; não aparece em log nem em
mensagem de erro.

Do JSON só fica o necessário para falar de progresso e para o coach. perfil (nome) e perguntas (texto livre) são
descartados na leitura. O questionário do JARVIS (chave jarvis, campo exclusivo da ULTRA) fica, mas já anonimizado:
CPF/CNPJ, e-mail e telefone mascarados e o nome do perfil pseudonimizado (PESSOA_XXXX), antes de sair da leitura.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.privacy import anonimizar_contato, sanitizar
from .firestore import Executor, LeitorFirestore, _executar_node
from .trilhum import TrilhumErro

SCRIPT = Path(__file__).with_name("sync_trilhum.mjs")
PLANO_APP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")                   # ids de plano que o app aceita
TTL_S = 60.0      # cada leitura roda o Node; o JARVIS não precisa de mais que uma por minuto por plano
CFG_CHAVES = {"start", "exam", "hora", "dias", "blocos", "hDia", "hSab", "hDom", "nq", "pomodoro"}
JARVIS_TEXTOS = ("obj", "porque", "dif", "desiste")   # respostas livres do questionário (até 300 caracteres no app)
HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TONS = ("gentil", "direto", "firme")


class Acerto(BaseModel):
    ok: float = 0
    tot: float = 0


class Nota(BaseModel):
    d: date
    t: str = "obj"   # "obj" (objetiva) ou "disc" (discursiva)
    n: float


class FeedbackJarvis(BaseModel):
    """O questionário inicial do campo JARVIS (Trilhum ULTRA), já anonimizado."""

    obj: str = ""       # o que quer conquistar
    porque: str = ""    # por que importa
    dif: str = ""       # maior dificuldade hoje
    desiste: str = ""   # o que costuma fazer parar
    ans: int | None = Field(default=None, ge=1, le=5)   # quanto a ansiedade com a prova pesa (1 a 5)
    hora: str | None = None                            # melhor horário para falar com ele (HH:MM)
    tom: Literal["gentil", "direto", "firme"] = "gentil"
    em: datetime | None = None                         # quando respondeu (o app grava Date.now(), em ms)

    @property
    def vazio(self) -> bool:
        return not any(getattr(self, k) for k in JARVIS_TEXTOS) and self.ans is None

    @classmethod
    def do_app(cls, d, nomes: list[str] | None = None, salt: str = "") -> FeedbackJarvis | None:
        """Do registro jarvis do app; None se não veio. Texto anonimizado aqui, antes de ir a qualquer lugar."""
        if not isinstance(d, dict):
            return None

        def limpo(v) -> str:
            texto = sanitizar(str(v)[:300], nomes=nomes, salt=salt, inteiras=True)
            return anonimizar_contato(texto).strip()

        ans = d.get("ans")
        em = d.get("em")
        hora = str(d.get("hora") or "")
        return cls(
            **{k: limpo(d[k]) for k in JARVIS_TEXTOS if isinstance(d.get(k), str)},
            ans=int(ans) if isinstance(ans, int | float) and not isinstance(ans, bool) and 1 <= ans <= 5 else None,
            hora=hora if HORA.match(hora) else None,
            tom=d.get("tom") if d.get("tom") in TONS else "gentil",
            em=datetime.fromtimestamp(em / 1000, tz=UTC) if isinstance(em, int | float) and em > 0 else None,
        )


def _nomes_do_perfil(d: dict) -> list[str]:
    """Nome completo e primeiro nome do perfil, só para pseudonimizar o questionário (o perfil não é guardado)."""
    perfil = d.get("perfil") if isinstance(d.get("perfil"), dict) else {}
    nome = str(perfil.get("nome") or "").strip()
    if not nome:
        return []
    primeiro = nome.split()[0]
    return [nome] + ([primeiro] if len(primeiro) >= 3 and primeiro != nome else [])


class Progresso(BaseModel):
    cfg: dict = Field(default_factory=dict)            # cadastro: início, data-alvo, dias e horários
    feito: set[str] = Field(default_factory=set)       # ids dos blocos marcados como feitos
    acertos: dict[str, Acerto] = Field(default_factory=dict)
    notas: list[Nota] = Field(default_factory=list)
    revisoes: dict[str, int] = Field(default_factory=dict)   # semana → itens da revisão de sábado marcados (de 6)
    jarvis: FeedbackJarvis | None = None                     # questionário do JARVIS (ULTRA), anonimizado

    @classmethod
    def do_app(cls, d: dict, salt: str = "") -> Progresso:
        """Do JSON do app (dadosLocais), tolerante a campos estranhos; perfil e perguntas ficam de fora."""
        d = d if isinstance(d, dict) else {}
        cfg = d.get("cfg") if isinstance(d.get("cfg"), dict) else {}
        feito = d.get("feito") if isinstance(d.get("feito"), dict) else {}
        acertos = d.get("acertos") if isinstance(d.get("acertos"), dict) else {}
        notas = d.get("notas") if isinstance(d.get("notas"), list) else []
        check = d.get("check") if isinstance(d.get("check"), dict) else {}
        boas_notas = []
        for n in notas:
            try:
                boas_notas.append(Nota.model_validate({k: n[k] for k in ("d", "t", "n") if k in n}))
            except (TypeError, ValueError):
                continue
        return cls(
            cfg={k: v for k, v in cfg.items() if k in CFG_CHAVES},
            feito={str(k) for k, v in feito.items() if v and len(str(k)) <= 60},
            acertos={str(k): Acerto(ok=float(v.get("ok") or 0), tot=float(v.get("tot") or 0))
                     for k, v in acertos.items() if isinstance(v, dict) and len(str(k)) <= 60},
            notas=sorted(boas_notas, key=lambda n: n.d),
            revisoes={str(k): sum(1 for x in v if x) for k, v in check.items() if isinstance(v, list)},
            jarvis=FeedbackJarvis.do_app(d.get("jarvis"), _nomes_do_perfil(d), salt),
        )


class SincronizacaoTrilhum(LeitorFirestore):
    def __init__(self, uid: str = "", projeto: str = "", modulos: Path | None = None, credenciais: str = "",
                 emulador: str = "", node: str | None = None, executar: Executor = _executar_node,
                 ttl_s: float = TTL_S, relogio: Callable[[], float] = time.monotonic, salt: str = ""):
        super().__init__(uid, projeto, modulos or Path("node_modules"), credenciais, emulador, node, executar)
        self.ttl_s, self.relogio = ttl_s, relogio
        self.salt = salt   # pseudonimização do nome no questionário do JARVIS (o mesmo salt do resto do JARVIS)
        self._cache: dict[str, tuple[float, object]] = {}   # registro → (quando, JSON cru)
        self._trava = threading.Lock()

    @classmethod
    def da_config(cls, settings, salt: str = "") -> SincronizacaoTrilhum:
        """Com o uid, o projeto e a credencial do Firebase do .env e o firebase-admin de Trilha\\functions."""
        uid, projeto, credenciais, emulador = settings.firebase()
        return cls(uid, projeto, settings.trilhum_dir() / "functions" / "node_modules", credenciais, emulador,
                   salt=salt)

    @property
    def configurada(self) -> bool:
        return bool(self.uid)

    def problema(self) -> str | None:
        """Por que não dá para ler (sem citar o uid nem a credencial); None se está tudo certo."""
        if not self.configurada:
            return ("a sincronização do Trilhum não está configurada: falta JARVIS_TRILHUM_UID (o código de "
                    "\"Copiar código para o JARVIS\" no app) no .env do JARVIS-TRILHUM")
        return super().problema()

    def ler(self, plano_sync: str) -> Progresso | None:
        """O progresso do plano (None se o plano ainda não foi sincronizado). Guardado por TTL_S."""
        bruto = self._ler(plano_sync)
        if isinstance(bruto, dict) and isinstance(bruto.get("data"), dict):   # o envelope {app, plano, ts, data, em}
            bruto = bruto["data"]
        return Progresso.do_app(bruto, self.salt) if isinstance(bruto, dict) else None

    def catalogo(self) -> dict[str, dict]:
        """Os planos salvos no app ({id: plano}), que viajam na conta no registro "_planos". São as versões que o
        usuário de fato usa, e podem não existir na pasta planos\\ (ex.: um plano gerado ou importado no app)."""
        bruto = self._ler("_planos")
        if not isinstance(bruto, dict):
            return {}
        itens = bruto.get("itens")
        if isinstance(itens, dict):   # formato atual: {id: {em, plano}}; plano None = removido
            pares = ((k, v.get("plano")) for k, v in itens.items() if isinstance(v, dict))
        else:                         # formato antigo: {planos: {id: plano}}
            pares = (bruto.get("planos") or {}).items() if isinstance(bruto.get("planos"), dict) else ()
        return {str(k): v for k, v in pares if isinstance(v, dict) and PLANO_APP.match(str(k))}

    def _ler(self, nome: str):
        """O JSON cru de um registro da sincronização (None se não existe). Guardado por TTL_S."""
        if erro := self.problema():
            raise TrilhumErro(erro)
        with self._trava:
            agora = self.relogio()
            if (c := self._cache.get(nome)) and agora - c[0] < self.ttl_s:
                return c[1]
            d = self._rodar(SCRIPT, plano=nome)
            bruto = None
            if d.get("existe") and isinstance(d.get("json"), str):
                try:
                    bruto = json.loads(d["json"])
                except ValueError as e:
                    raise TrilhumErro("a sincronização do Trilhum guardou algo que não é JSON") from e
            self._cache[nome] = (agora, bruto)
            return bruto


def plano_sync(plano: dict, plano_id: str) -> str:
    """O nome do plano na sincronização: o id de dentro do JSON, limpo como o app faz (planoSync)."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(plano.get("id") or plano_id))[:80]
