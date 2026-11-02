"""Leitura do Firestore do Trilhum (projeto trilha-estudos-2026), só leitura, pelo Admin SDK.

As regras do Firestore negam o acesso direto: só a conta de serviço lê, como a função "api" do Trilhum. Os scripts
.mjs desta pasta usam o firebase-admin já instalado em Trilha\\functions\\node_modules (nada é instalado no JARVIS) e
a conta de serviço (JARVIS_FIREBASE_CREDENCIAIS, arquivo fora do Git). No modo teste, o emulador do Firebase
(JARVIS_FIRESTORE_EMULADOR, projeto demo-trilhum). O uid e o projeto vão pela entrada, nunca pela linha de comando,
e não aparecem em log nem em erro.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 — só roda o Node com argumentos fixos (ver _executar_node)
from collections.abc import Callable
from pathlib import Path

from .trilhum import TrilhumErro

UID = re.compile(r"^[A-Za-z0-9]{1,128}$")            # uid do Firebase Auth
PROJETO = re.compile(r"^[a-z0-9-]{4,30}$")           # id de projeto do Google Cloud
EMULADOR = re.compile(r"^(127\.0\.0\.1|localhost):\d{2,5}$")
TIMEOUT_S = 30.0

Executor = Callable[[list[str], float, str, dict], str]   # (argv, timeout, entrada, ambiente) -> stdout


def _executar_node(argv: list[str], timeout_s: float, entrada: str, ambiente: dict) -> str:
    try:
        # argv = [node, <script>.mjs, node_modules]: montados aqui, sem shell; uid e projeto pela entrada
        r = subprocess.run(argv, input=entrada, capture_output=True, text=True, encoding="utf-8",  # nosec B603
                           timeout=timeout_s, check=False, env=ambiente,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise TrilhumErro(f"o Firestore do Trilhum não respondeu em {timeout_s:.0f} s") from e
    except OSError as e:
        raise TrilhumErro(f"não consegui rodar o Node: {e}") from e
    if r.returncode != 0:
        linhas = (r.stderr or "").strip().splitlines() or ["sem detalhe"]
        raise TrilhumErro(f"não li o Firestore do Trilhum: {linhas[-1][:200]}")
    return r.stdout


class LeitorFirestore:
    """O que a leitura do assinante e a da sincronização têm em comum: configuração, ambiente e a chamada ao Node."""

    def __init__(self, uid: str, projeto: str, modulos: Path, credenciais: str = "", emulador: str = "",
                 node: str | None = None, executar: Executor = _executar_node):
        self.uid, self.projeto, self.modulos = (uid or "").strip(), (projeto or "").strip(), modulos
        self.credenciais, self.emulador = (credenciais or "").strip(), (emulador or "").strip()
        self.node = node or shutil.which("node")
        self._executar = executar

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

    def _rodar(self, script: Path, **entrada) -> dict:
        """Roda o script com {uid, projeto, **entrada} pela entrada padrão e devolve o JSON que ele imprime."""
        if erro := self.problema():
            raise TrilhumErro(erro)
        saida = self._executar([self.node, str(script), str(self.modulos)], TIMEOUT_S,
                               json.dumps({"uid": self.uid, "projeto": self.projeto, **entrada}), self._ambiente())
        try:
            d = json.loads(saida)
        except ValueError as e:
            raise TrilhumErro("o leitor do Firestore devolveu algo que não é JSON") from e
        if not isinstance(d, dict):
            raise TrilhumErro("o leitor do Firestore devolveu algo que não é um objeto")
        return d
