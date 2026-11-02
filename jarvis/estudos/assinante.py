"""O número de WhatsApp e o consentimento do aluno, lidos do Firestore do Trilhum (assinantes/{uid}), só leitura.

O Trilhum grava esses campos pela função "api" quando o aluno ativa os avisos: whatsapp ("55" + DDD + número) e
whatsappConsentimento (ISO); "Parar avisos" apaga os dois. A leitura usa o Admin SDK (assinante_trilhum.mjs; ver
firestore.py para a credencial e o emulador do modo teste).

Fecha na dúvida (LGPD): leitura que falha, registro sem consentimento ou assinatura que não é mais ULTRA = nenhum
aviso. O número não aparece em log nem em erro, e nunca vai ao Claude. Releitura a cada TTL_S, para que "Parar
avisos" valha em minutos.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from .avisos import Destinatario
from .firestore import Executor, LeitorFirestore, _executar_node
from .trilhum import TrilhumErro

SCRIPT = Path(__file__).with_name("assinante_trilhum.mjs")
TTL_S = 300.0


class LeitorAssinante(LeitorFirestore):
    def __init__(self, uid: str, projeto: str, modulos: Path, credenciais: str = "", emulador: str = "",
                 node: str | None = None, executar: Executor = _executar_node, ttl_s: float = TTL_S,
                 relogio: Callable[[], float] = time.monotonic):
        super().__init__(uid, projeto, modulos, credenciais, emulador, node, executar)
        self.ttl_s, self.relogio = ttl_s, relogio
        self._cache: tuple[float, Destinatario | None] | None = None
        self._trava = threading.Lock()

    def ler(self) -> Destinatario | None:
        """O destinatário dos avisos, ou None (sem ULTRA, sem número, sem consentimento). TrilhumErro se a leitura
        falhar. Guardado por TTL_S."""
        if erro := self.problema():
            raise TrilhumErro(erro)
        with self._trava:
            agora = self.relogio()
            if self._cache and agora - self._cache[0] < self.ttl_s:
                return self._cache[1]
            d = self._rodar(SCRIPT)
            destino = None
            if d.get("existe") and d.get("plano") == "ultra":
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
