"""Avisos pelo WhatsApp 30 minutos antes de cada bloco do dia, com a agenda que trilhum_agenda monta.

Regras, as mesmas dos alarmes (.ics) do próprio Trilhum: bloco já feito não é avisado, bloco sem duração (a prova)
também não, e o horário é o do bloco ou, sem ele (sábado, domingo), o horário padrão do cadastro. Os horários são
de São Paulo, qualquer que seja o fuso do PC. Feriado: o app mantém os blocos e o aviso sai com o nome do feriado;
JARVIS_WHATSAPP_FERIADO=0 não avisa nos feriados. Depois da data-alvo, nada.

O envio é trocável (Envio): Meta Cloud API oficial, com mensagem utilitária de modelo aprovado (fora da janela de 24 h
a Meta só aceita modelo), ou dry-run, que só registra no log. Sem token e id do número da Meta, é sempre dry-run.

O número e o consentimento (LGPD) ficam no Firestore do Trilhum, em assinantes/{uid}.whatsapp e
whatsappConsentimento; por enquanto chegam pela configuração local (JARVIS_WHATSAPP_NUMERO e
JARVIS_WHATSAPP_CONSENTIMENTO). O número só vai para a Meta: a mensagem é montada aqui, sem o Claude, e o log mostra
o número mascarado. Sem consentimento, nada sai.

    python -m jarvis.estudos.avisos --listar            # os avisos de hoje (sem enviar)
    python -m jarvis.estudos.avisos --dry-run           # roda o agendador só registrando no log
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from .trilhum import Agenda, Bloco, Trilhum, TrilhumErro

ANTECEDENCIA = timedelta(minutes=30)
INTERVALO_S = 60.0
META_VERSAO = "v23.0"
MODELO_PADRAO = "aviso_bloco_estudo"   # modelo utilitário aprovado na Meta, corpo com {{1}} hora, {{2}} bloco, {{3}} assunto


def _fuso_sp() -> timezone | ZoneInfo:
    try:
        return ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:   # Windows sem o pacote tzdata: o Brasil não tem horário de verão desde 2019
        return timezone(timedelta(hours=-3), "BRT")


FUSO_SP = _fuso_sp()


class AvisoErro(Exception):
    """Falha no envio (rede, recusa da Meta): mensagem sem token nem número."""


def normalizar_whats(v) -> str | None:
    """55 + DDD + número, como o Trilhum grava (normalizarWhats, functions/nucleo.mjs); None se inválido."""
    d = re.sub(r"\D", "", str(v or ""))
    n = "55" + d if len(d) in (10, 11) else d
    return n if re.fullmatch(r"55\d{10,11}", n) else None


def mascarar_numero(numero: str) -> str:
    return numero[:4] + "*" * max(len(numero) - 8, 0) + numero[-4:] if len(numero) > 8 else "****"


class Destinatario(BaseModel):
    """O aluno que recebe os avisos. Os nomes dos campos são os do Firestore (assinantes/{uid})."""

    whatsapp: str = Field(repr=False)
    whatsappConsentimento: datetime   # o nome do campo no Firestore do Trilhum

    @classmethod
    def da_config(cls, numero: str, consentimento: str) -> Destinatario | None:
        """None sem número válido ou sem a data do consentimento (sem autorização, nenhum aviso sai)."""
        n = normalizar_whats(numero)
        try:
            quando = datetime.fromisoformat(consentimento.strip()) if consentimento.strip() else None
        except ValueError:
            quando = None
        return cls(whatsapp=n, whatsappConsentimento=quando) if n and quando else None


class Aviso(BaseModel):
    chave: str            # plano:data:bloco: um aviso por bloco, nunca dois
    quando: datetime      # hora do envio (São Paulo)
    inicio: datetime      # início do bloco (São Paulo)
    feriado: str = ""
    bloco: Bloco

    def parametros(self) -> list[str]:
        """Os três parâmetros do corpo do modelo: hora, bloco e assunto (sem quebra de linha, como a Meta exige)."""
        def limpo(t: str, n: int) -> str:
            return re.sub(r"\s+", " ", t).strip()[:n] or "-"

        b = self.bloco
        assunto = b.assunto + (f" (feriado: {self.feriado})" if self.feriado else "")
        return [f"{self.inicio:%H:%M}", limpo(f"{b.tipo} · {b.disciplina}", 120), limpo(assunto, 200)]

    def texto(self) -> str:
        hora, bloco, assunto = self.parametros()
        return f"Em {(self.inicio - self.quando).seconds // 60} minutos, às {hora}: {bloco}. {assunto}"


def avisos_do_dia(agenda: Agenda, dia: date, feito: set[str], plano_id: str, hora_padrao: str | None = None,
                  antecedencia: timedelta = ANTECEDENCIA, avisar_feriado: bool = True) -> list[Aviso]:
    """Os avisos de um dia, em ordem. Regras dos alarmes do Trilhum (icsTexto): pula feito e bloco sem duração."""
    achado = agenda.dia(dia)
    if achado is None:
        return []
    _, d = achado
    if d.depois_da_prova or (d.feriado and not avisar_feriado):
        return []
    out = []
    for b in d.blocos:
        hhmm = b.inicio or hora_padrao
        if b.id in feito or not b.minutos or not hhmm or not re.fullmatch(r"\d{2}:\d{2}", hhmm):
            continue
        inicio = datetime.combine(dia, time.fromisoformat(hhmm), tzinfo=FUSO_SP)
        out.append(Aviso(chave=f"{plano_id}:{dia.isoformat()}:{b.id}", quando=inicio - antecedencia, inicio=inicio,
                         feriado=d.feriado, bloco=b))
    return sorted(out, key=lambda a: a.inicio)


# ── envio ────────────────────────────────────────────────────
class Envio(Protocol):
    dry_run: bool

    def enviar(self, numero: str, aviso: Aviso) -> str:
        """Manda o aviso; devolve o id da mensagem. AvisoErro se falhar."""
        ...


class EnvioDryRun:
    """Só registra no log (número mascarado). É o envio enquanto a conta da Meta não existe."""

    dry_run = True

    def __init__(self):
        self.enviados: list[tuple[str, Aviso]] = []

    def enviar(self, numero: str, aviso: Aviso) -> str:
        self.enviados.append((numero, aviso))
        logger.info(f"[dry-run] aviso WhatsApp para {mascarar_numero(numero)}: {aviso.texto()}")
        return "dry-run"


class EnvioMetaCloud:
    """Meta Cloud API oficial (graph.facebook.com): mensagem de modelo utilitário aprovado, em pt_BR."""

    dry_run = False

    def __init__(self, token: str, numero_id: str, modelo: str = MODELO_PADRAO, idioma: str = "pt_BR",
                 versao: str = META_VERSAO, cliente: httpx.Client | None = None):
        if not re.fullmatch(r"\d{5,20}", numero_id or ""):
            raise ValueError("JARVIS_META_NUMERO_ID precisa ser o id numérico do número na Meta")
        if not re.fullmatch(r"v\d{1,2}\.\d", versao):
            raise ValueError("JARVIS_META_VERSAO precisa ser uma versão da Graph API (ex.: v23.0)")
        self.token, self.numero_id, self.modelo, self.idioma, self.versao = token, numero_id, modelo, idioma, versao
        self._cliente = cliente

    def corpo(self, numero: str, aviso: Aviso) -> dict:
        return {
            "messaging_product": "whatsapp", "to": numero, "type": "template",
            "template": {"name": self.modelo, "language": {"code": self.idioma}, "components": [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in aviso.parametros()]}]},
        }

    def enviar(self, numero: str, aviso: Aviso) -> str:
        cliente = self._cliente or httpx.Client(timeout=15.0)
        try:
            r = cliente.post(f"https://graph.facebook.com/{self.versao}/{self.numero_id}/messages",
                             headers={"Authorization": f"Bearer {self.token}"}, json=self.corpo(numero, aviso))
        except httpx.HTTPError as e:
            raise AvisoErro(f"não consegui falar com a Meta ({type(e).__name__})") from e
        finally:
            if self._cliente is None:
                cliente.close()
        if r.status_code != 200:
            try:
                detalhe = str(r.json().get("error", {}).get("message", ""))[:200]
            except ValueError:
                detalhe = ""
            raise AvisoErro(f"a Meta recusou o aviso (HTTP {r.status_code}) {detalhe}".strip())
        try:
            return str(r.json()["messages"][0]["id"])
        except (ValueError, KeyError, IndexError, TypeError):
            return "?"


# ── registro (um aviso por bloco, mesmo reiniciando) ─────────
class RegistroAvisos:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._trava = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS avisos_whatsapp (chave TEXT PRIMARY KEY, em TEXT NOT NULL, "
                      "modo TEXT NOT NULL, mensagem TEXT)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def reservar(self, chave: str, modo: str) -> bool:
        """True se o aviso ainda não saiu (e fica reservado); False se já saiu."""
        with self._trava, self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO avisos_whatsapp (chave, em, modo) VALUES (?,?,?)",
                            (chave, datetime.now(FUSO_SP).isoformat(timespec="seconds"), modo))
            return cur.rowcount == 1

    def confirmar(self, chave: str, mensagem: str) -> None:
        with self._trava, self._conn() as c:
            c.execute("UPDATE avisos_whatsapp SET mensagem = ? WHERE chave = ?", (mensagem, chave))

    def liberar(self, chave: str) -> None:
        """O envio falhou: a próxima verificação tenta de novo (até o bloco começar)."""
        with self._trava, self._conn() as c:
            c.execute("DELETE FROM avisos_whatsapp WHERE chave = ?", (chave,))


# ── agendador ────────────────────────────────────────────────
class AgendadorAvisos:
    def __init__(self, trilhum: Trilhum, envio: Envio, destinatario: Destinatario | None, registro: RegistroAvisos,
                 plano: str | None = None, antecedencia: timedelta = ANTECEDENCIA, avisar_feriado: bool = True,
                 relogio: Callable[[], datetime] = lambda: datetime.now(FUSO_SP)):
        self.trilhum, self.envio, self.registro = trilhum, envio, registro
        # destino fixo (configuração local) ou lido na hora (LeitorAssinante, do Firestore do Trilhum)
        self.destino: Callable[[], Destinatario | None] = (
            destinatario if callable(destinatario) else lambda: destinatario)
        self.plano, self.antecedencia, self.avisar_feriado, self.relogio = plano, antecedencia, avisar_feriado, relogio
        self._sem_destino_avisado = False

    def agora(self) -> datetime:
        agora = self.relogio()
        return (agora if agora.tzinfo else agora.replace(tzinfo=FUSO_SP)).astimezone(FUSO_SP)

    def avisos(self, dia: date) -> list[Aviso]:
        """Os avisos do dia com o cadastro e o progresso do aluno (feito relido a cada verificação, cache de 60 s)."""
        info = self.trilhum.escolher(self.plano, dia)
        prog = None
        if self.trilhum.sync is not None and self.trilhum.sync.configurada:
            prog = self.trilhum.progresso(info.id)
        cfg = prog.cfg if prog and prog.cfg else None
        agenda = self.trilhum.agenda(info.id, cfg)
        hora = (cfg or {}).get("hora") or self.trilhum.plano(info.id).get("hora")
        return avisos_do_dia(agenda, dia, prog.feito if prog else set(), info.id, str(hora) if hora else None,
                             self.antecedencia, self.avisar_feriado)

    def verificar(self) -> list[Aviso]:
        """Manda os avisos que venceram e cujo bloco ainda não começou. Devolve os enviados. O destino (número e
        consentimento) só é lido quando há aviso a mandar, e é relido a cada vez: o aluno pode ter parado os avisos."""
        agora = self.agora()
        try:
            pendentes = [a for a in self.avisos(agora.date()) if a.quando <= agora < a.inicio]
        except TrilhumErro as e:
            logger.warning(f"avisos WhatsApp: não li a agenda ({e})")
            return []
        if not pendentes:
            return []
        destino = self.destino()
        if destino is None:
            if not self._sem_destino_avisado:
                logger.warning("avisos WhatsApp: sem número válido, sem consentimento ou sem a ULTRA; nenhum aviso sai")
                self._sem_destino_avisado = True
            return []
        self._sem_destino_avisado = False
        modo = "dry-run" if self.envio.dry_run else "meta"
        enviados = []
        for a in pendentes:
            if not self.registro.reservar(a.chave, modo):
                continue
            try:
                self.registro.confirmar(a.chave, self.envio.enviar(destino.whatsapp, a))
            except AvisoErro as e:
                self.registro.liberar(a.chave)
                logger.warning(f"aviso WhatsApp {a.chave} não saiu: {e}")
                continue
            enviados.append(a)
        return enviados


async def run_avisos(agendador: AgendadorAvisos, intervalo_s: float = INTERVALO_S) -> None:
    """Laço do agendador (no lifespan da API ou pela linha de comando): nunca morre por um erro."""
    while True:
        try:
            await asyncio.to_thread(agendador.verificar)
        except Exception:  # noqa: BLE001 — o laço de avisos nunca pode morrer
            logger.exception("agendador de avisos WhatsApp")
        await asyncio.sleep(intervalo_s)


def destino(settings, trilhum: Trilhum):
    """Com JARVIS_TRILHUM_UID, o Firestore do Trilhum (assinantes/{uid}) é a fonte: vale o que o aluno ativou ou parou
    no app, e a configuração local é ignorada. Sem o uid, a configuração local (piloto)."""
    uid, projeto, credenciais, emulador = settings.firebase()
    if uid:
        from .assinante import LeitorAssinante

        return LeitorAssinante(uid, projeto, trilhum.pasta / "functions" / "node_modules", credenciais, emulador)
    return Destinatario.da_config(*settings.whatsapp_destino())


def montar(settings, trilhum: Trilhum, dry_run: bool = False) -> AgendadorAvisos:
    """O agendador com a configuração local. Sem token e id do número da Meta, o envio é dry-run."""
    token, numero_id, modelo, idioma, versao = settings.meta_whatsapp()
    if dry_run or settings.whatsapp_dry_run() or not (token and numero_id):
        envio: Envio = EnvioDryRun()
    else:
        envio = EnvioMetaCloud(token, numero_id, modelo or MODELO_PADRAO, idioma or "pt_BR", versao or META_VERSAO)
    return AgendadorAvisos(trilhum, envio, destino(settings, trilhum), RegistroAvisos(settings.db_path), plano=settings.trilhum_plano() or None,
                           antecedencia=timedelta(minutes=settings.whatsapp_antecedencia_min()),
                           avisar_feriado=settings.whatsapp_feriado())


def main(argv: list[str] | None = None) -> int:
    from ..config import get_settings
    from .sincronizacao import SincronizacaoTrilhum

    ap = argparse.ArgumentParser(prog="python -m jarvis.estudos.avisos", description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="só registra no log, não manda nada")
    ap.add_argument("--listar", action="store_true", help="mostra os avisos do dia e sai (não manda nada)")
    ap.add_argument("--data", type=date.fromisoformat, help="dia para --listar (AAAA-MM-DD); padrão: hoje")
    a = ap.parse_args(argv)
    s = get_settings()
    trilhum = Trilhum(s.trilhum_dir(), s.trilhum_plano(), sync=SincronizacaoTrilhum(*s.trilhum_sync(), salt=s.salt()))
    ag = montar(s, trilhum, dry_run=a.dry_run or a.listar)
    if a.listar:
        try:
            avisos = ag.avisos(a.data or ag.agora().date())
        except TrilhumErro as e:
            print(f"erro: {e}")
            return 1
        if hasattr(sys.stdout, "reconfigure"):   # redirecionado no Windows, a saída seria cp1252
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print("\n".join(f"{x.quando:%d/%m %H:%M} - {x.texto()}" for x in avisos) or "Nenhum aviso para o dia.")
        return 0
    logger.info(f"agendador de avisos WhatsApp ({'dry-run' if ag.envio.dry_run else 'Meta Cloud API'})")
    asyncio.run(run_avisos(ag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
