"""O número de WhatsApp e o consentimento do aluno, lidos do Firestore do Trilhum (assinantes/{uid}), só leitura.

O Trilhum grava esses campos pela função "api" quando o aluno ativa os avisos: whatsapp ("55" + DDD + número) e
whatsappConsentimento (ISO); "Parar avisos" apaga os dois. As regras do Firestore negam o acesso direto, então a
leitura usa o Admin SDK (assinante_trilhum.mjs, com o firebase-admin de Trilha\\functions\\node_modules) e a conta de
serviço (JARVIS_FIREBASE_CREDENCIAIS, arquivo fora do Git). No modo teste, o emulador do Firebase
(JARVIS_FIRESTORE_EMULADOR, projeto demo-trilhum).

Fecha na dúvida (LGPD): leitura que falha, registro sem consentimento ou assinatura que não é mais ULTRA = nenhum
aviso. O número não aparece em log nem em erro, e nunca vai ao Claude. Releitura a cada TTL_S, para que "Parar
avisos" valha em minutos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 — só roda o Node com argumentos fixos (ver _executar_node)
import threading
import time
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from .avisos import Destinatario
from .trilhum import TrilhumErro

SCRIPT = Path(__file__).with_name("assinante_trilhum.mjs")
UID = re.compile(r"^[A-Za-z0-9]{1,128}$")            # uid do Firebase Auth
PROJETO = re.compile(r"^[a-z0-9-]{4,30}$")           # id de projeto do Google Cloud
EMULADOR = re.compile(r"^(127\.0\.0\.1|localhost):\d{2,5}$")
TTL_S = 300.0
TIMEOUT_S = 30.0

Executor = Callable[[list[str], float, str, dict], str]   # (argv, timeout, entrada, ambiente) -> stdout


def _executar_node(argv: list[str], timeout_s: float, entrada: str, ambiente: dict) -> str:
    try:
        # argv = [node, assinante_trilhum.mjs, node_modules]: montados aqui, sem shell; uid e projeto pela entrada
        r = subprocess.run(argv, input=entrada, capture_output=True, text=True, encoding="utf-8",  # nosec B603
                           timeout=timeout_s, check=False, env=ambiente,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise TrilhumErro(f"o Firestore do Trilhum não respondeu em {timeout_s:.0f} s") from e
    except OSError as e:
        raise TrilhumErro(f"não consegui rodar o Node: {e}") from e
    if r.returncode != 0:
        linhas = (r.stderr or "").strip().splitlines() or ["sem detalhe"]
        raise TrilhumErro(f"não li o assinante no Firestore: {linhas[-1][:200]}")
    return r.stdout


class LeitorAssinante:
    def __init__(self, uid: str, projeto: str, modulos: Path, credenciais: str = "", emulador: str = "",
                 node: str | None = None, executar: Executor = _executar_node, ttl_s: float = TTL_S,
                 relogio: Callable[[], float] = time.monotonic):
        self.uid, self.projeto, self.modulos = uid.strip(), projeto.strip(), modulos
        self.credenciais, self.emulador = credenciais.strip(), emulador.strip()
        self.node = node or shutil.which("node")
        self._executar, self.ttl_s, self.relogio = executar, ttl_s, relogio
        self._cache: tuple[float, Destinatario | None] | None = None
        self._trava = threading.Lock()

    def problema(self) -> str | None:
        """Por que não dá para ler (sem citar o uid nem o caminho da credencial); None se está tudo certo."""
        if not UID.match(self.uid):
            return "JARVIS_TRILHUM_UID não parece um uid do Firebase (letras e números)"
        if not PROJETO.match(self.projeto):
            return "JARVIS_FIREBASE_PROJETO não parece um id de projeto do Firebase"
        if self.emulador:
            if not EMULADOR.match(self.emulador):
                return "JARVIS_FIRESTORE_EMULADOR precisa ser local (127.0.0.1:porta)"
        elif not self.credenciais or not Path(self.credenciais).is_file():
            return "JARVIS_FIREBASE_CREDENCIAIS precisa apontar para o arquivo da conta de serviço do Firebase"
        if not self.node:
            return "o Node não está instalado (ou não está no PATH)"
        if not (self.modulos / "firebase-admin").is_dir():
            return f"o firebase-admin não está em {self.modulos} (rode npm install em Trilha\\functions)"
        return None

    def _ambiente(self) -> dict:
        amb = {k: v for k, v in os.environ.items()
               if k not in ("GOOGLE_APPLICATION_CREDENTIALS", "FIRESTORE_EMULATOR_HOST")}
        if self.emulador:
            amb["FIRESTORE_EMULATOR_HOST"] = self.emulador
        else:
            amb["GOOGLE_APPLICATION_CREDENTIALS"] = self.credenciais
        return amb

    def ler(self) -> Destinatario | None:
        """O destinatário dos avisos, ou None (sem ULTRA, sem número, sem consentimento). TrilhumErro se a leitura
        falhar. Guardado por TTL_S."""
        if erro := self.problema():
            raise TrilhumErro(erro)
        with self._trava:
            agora = self.relogio()
            if self._cache and agora - self._cache[0] < self.ttl_s:
                return self._cache[1]
            saida = self._executar([self.node, str(SCRIPT), str(self.modulos)], TIMEOUT_S,
                                   json.dumps({"uid": self.uid, "projeto": self.projeto}), self._ambiente())
            try:
                d = json.loads(saida)
            except ValueError as e:
                raise TrilhumErro("o leitor do Firestore devolveu algo que não é JSON") from e
            destino = None
            if isinstance(d, dict) and d.get("existe") and d.get("plano") == "ultra":
                destino = Destinatario.da_config(str(d.get("whatsapp") or ""), str(d.get("whatsappConsentimento") or ""))
            self._cache = (agora, destino)
            return destino

    def __call__(self) -> Destinatario | None:
        """Para o agendador: fecha na dúvida (falha na leitura = nenhum aviso)."""
        try:
            return self.ler()
        except TrilhumErro as e:
            logger.warning(f"avisos WhatsApp: {e}; nenhum aviso sai até a leitura voltar")
            return None
