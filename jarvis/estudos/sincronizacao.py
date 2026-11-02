"""Progresso do Trilhum lido pela sincronização do app (Supabase da Trilha), só leitura.

O app guarda um JSON por plano no Supabase próprio da Trilha, atrás de um token de sincronização (o banco guarda só
o hash). Aqui só se chama trilha_sync_get, com a chave publishable, como o app faz; trilha_sync_put nunca. O token
dá acesso de leitura e gravação aos dados do usuário: vem do .env (JARVIS_TRILHUM_SYNC_TOKEN), não aparece em log,
mensagem de erro ou resposta.

Do JSON só fica o necessário para falar de progresso. perfil (nome) e perguntas (texto livre) são descartados na
leitura: nada pessoal segue para o Claude.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import date

import httpx
from pydantic import BaseModel, Field

from .trilhum import TrilhumErro

SUPABASE = re.compile(r"^https://[a-z0-9-]+\.supabase\.co/?$", re.IGNORECASE)   # o mesmo teste do app
TTL_S = 60.0      # o app aceita 3.000 leituras por hora por endereço; o JARVIS não precisa de mais que uma por minuto
CFG_CHAVES = {"start", "exam", "hora", "dias", "blocos", "hDia", "hSab", "hDom", "nq", "pomodoro"}


class Acerto(BaseModel):
    ok: float = 0
    tot: float = 0


class Nota(BaseModel):
    d: date
    t: str = "obj"   # "obj" (objetiva) ou "disc" (discursiva)
    n: float


class Progresso(BaseModel):
    cfg: dict = Field(default_factory=dict)            # cadastro: início, data-alvo, dias e horários
    feito: set[str] = Field(default_factory=set)       # ids dos blocos marcados como feitos
    acertos: dict[str, Acerto] = Field(default_factory=dict)
    notas: list[Nota] = Field(default_factory=list)
    revisoes: dict[str, int] = Field(default_factory=dict)   # semana → itens da revisão de sábado marcados (de 6)

    @classmethod
    def do_app(cls, d: dict) -> Progresso:
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
        )


class SincronizacaoTrilhum:
    def __init__(self, url: str | None = None, chave: str | None = None, token: str | None = None,
                 ttl_s: float = TTL_S, cliente: httpx.Client | None = None,
                 relogio: Callable[[], float] = time.monotonic):
        self.url, self.chave, self.token = (url or "").strip(), (chave or "").strip(), (token or "").strip()
        self.ttl_s, self.relogio = ttl_s, relogio
        self._cliente = cliente
        self._cache: dict[str, tuple[float, Progresso | None]] = {}
        self._trava = threading.Lock()

    @property
    def configurada(self) -> bool:
        return bool(self.url and self.chave and self.token)

    def problema(self) -> str | None:
        """Por que não dá para ler (sem citar o token nem a chave); None se está tudo certo."""
        if not self.configurada:
            return ("a sincronização do Trilhum não está configurada: faltam JARVIS_TRILHUM_SYNC_URL, "
                    "JARVIS_TRILHUM_SYNC_CHAVE e JARVIS_TRILHUM_SYNC_TOKEN no .env do JARVIS-TRILHUM")
        if not SUPABASE.match(self.url):
            return "JARVIS_TRILHUM_SYNC_URL precisa ser o endereço do Supabase da Trilha (https://….supabase.co)"
        if not 32 <= len(self.token) <= 200:
            return "JARVIS_TRILHUM_SYNC_TOKEN não parece um token de sincronização do Trilhum (32 a 200 caracteres)"
        return None

    def ler(self, plano_sync: str) -> Progresso | None:
        """O progresso do plano (None se o plano ainda não foi sincronizado). Guardado por TTL_S."""
        if erro := self.problema():
            raise TrilhumErro(erro)
        with self._trava:
            agora = self.relogio()
            if (c := self._cache.get(plano_sync)) and agora - c[0] < self.ttl_s:
                return c[1]
            cliente = self._cliente or httpx.Client(timeout=10.0, trust_env=False)
            try:
                r = cliente.post(self.url.rstrip("/") + "/rest/v1/rpc/trilha_sync_get",
                                 headers={"apikey": self.chave, "Content-Type": "application/json"},
                                 json={"p_token": self.token, "p_plano": plano_sync})
            except httpx.HTTPError as e:
                raise TrilhumErro(f"não consegui falar com a sincronização do Trilhum ({type(e).__name__})") from e
            finally:
                if self._cliente is None:
                    cliente.close()
            if r.status_code != 200:
                raise TrilhumErro(f"a sincronização do Trilhum recusou a leitura (HTTP {r.status_code}); confira a "
                                  "chave e o token no .env")
            try:
                bruto = r.json()
            except ValueError as e:
                raise TrilhumErro("a sincronização do Trilhum devolveu algo que não é JSON") from e
            progresso = Progresso.do_app(bruto) if isinstance(bruto, dict) else None
            self._cache[plano_sync] = (agora, progresso)
            return progresso


def plano_sync(plano: dict, plano_id: str) -> str:
    """O nome do plano na sincronização: o id de dentro do JSON, limpo como o app faz (planoSync)."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(plano.get("id") or plano_id))[:80]
