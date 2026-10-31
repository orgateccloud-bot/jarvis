"""Conversa por voz do serviço local: o que fazer com cada fala transcrita e quando o microfone fica aberto.

Segue o useConversation.js e o route.js do HUD:
- repouso: só fala que começa por "Jarvis" vale (a ativação é o Whisper, Escuta);
- ativa: depois de cada resposta, 12 s em que qualquer fala vira pergunta, sem precisar do "Jarvis";
- half-duplex: microfone mudo enquanto o JARVIS fala e por mais 1,5 s (no modo fone, JARVIS_VOZ_INTERROMPER=1,
  fica aberto e só "Jarvis, pare" interrompe; o filtro de eco descarta a própria voz);
- confirmação: "Confirma: ...? Diga sim ou não." e a resposta por voz. "Ok Jarvis" com confirmação pendente nega
  e abre nova conversa (Decisão B): nunca aprova.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from jarvis.voz.cliente import ApiIndisponivel
from jarvis.voz.comando import LIMIAR_SEM_FALA
from jarvis.voz.eco import FiltroDeEco
from jarvis.voz.texto import NAO, SIM, DivisorDeFrases, corrigir_termos, e_comando_de_parar, sem_acento

if TYPE_CHECKING:  # a escuta puxa numpy e onnxruntime; a lógica da conversa roda sem eles (CI sem o extra [voz])
    from jarvis.voz.escuta import Evento

JANELA_S = 12.0   # useConversation.js:8 (SILENCE_MS)
CAUDA_S = 1.5     # webspeech.js:12 (TAIL_MS): o reconhecimento entrega o fim da frase com atraso; o eco assenta


def _em_thread(trabalho: Callable[[], None]) -> None:
    threading.Thread(target=trabalho, name="voz-pergunta", daemon=True).start()


class Conversa:
    def __init__(self, cliente, voz, eco: FiltroDeEco | None = None, interromper: bool = False,
                 relogio: Callable[[], float] = time.monotonic, executar: Callable = _em_thread):
        self.cliente, self.voz = cliente, voz
        self.eco = eco or FiltroDeEco()
        self.interromper = interromper
        self.relogio = relogio
        self._executar = executar
        self._trava = threading.RLock()
        self.modo = "repouso"
        self.ocupado = False
        self.aprovacao: dict | None = None
        self._ativa_ate = 0.0
        self._cauda_ate = 0.0

    # ---------- callbacks da voz local ----------
    def na_frase(self, texto: str) -> None:
        self.eco.lembrar(texto)

    def fala_terminou(self) -> None:
        with self._trava:
            self.eco.terminou()
            agora = self.relogio()
            self._cauda_ate = agora + CAUDA_S
            if self.modo == "ativa":  # a janela de 12 s conta a partir do fim da fala (armSilence)
                self._ativa_ate = agora + CAUDA_S + JANELA_S

    # ---------- estado ----------
    def mic_fechado(self) -> bool:
        """Half-duplex: mudo enquanto fala e na cauda. No modo fone o microfone nunca fecha."""
        if self.interromper:
            return False
        return self.voz.falando or self.relogio() < self._cauda_ate

    def estado(self) -> str:
        if self.voz.falando:
            return "falando"
        if self.ocupado:
            return "processando"
        return "ouvindo" if self.modo == "ativa" else "repouso"

    def tick(self) -> None:
        """Encerra a conversa ativa depois de 12 s sem fala (se ninguém estiver falando nem esperando)."""
        with self._trava:
            if (self.modo == "ativa" and self.relogio() > self._ativa_ate and not self.ocupado
                    and not self.voz.falando and not self.aprovacao):
                self.modo = "repouso"

    # ---------- o que fazer com cada fala ----------
    def ouvido(self, ev: Evento) -> str:
        """Decide e executa. Devolve o nome da ação (para o log e os testes)."""
        with self._trava:
            return self._ouvido(ev)

    def _ouvido(self, ev: Evento) -> str:
        texto = corrigir_termos(ev.transcricao.texto.strip())
        c = ev.comando
        if not texto:
            return "vazio"
        resposta = bool(self.aprovacao) and bool(SIM.match(texto) or NAO.match(texto))
        parar = c.tipo == "parar" or e_comando_de_parar(sem_acento(texto))
        if not parar and self.eco.e_eco(texto, resposta=resposta):
            return "eco"
        if self.voz.falando:  # só acontece no modo fone: o resto é eco do alto-falante ou conversa paralela
            if parar:
                self.voz.cancelar()
                return "parou"
            return "ignorado"
        if self.aprovacao:
            if c.tipo == "nova_conversa":
                self._decidir(False)
                self._nova_conversa()
                return "negou_e_nova_conversa"
            if resposta:
                ok = bool(SIM.match(texto)) and not NAO.match(texto)
                self._decidir(ok)
                return "aprovou" if ok else "negou"
            return "ignorado"
        if c.tipo == "nova_conversa":
            self._nova_conversa()
            return "nova_conversa"
        if parar or self.ocupado:
            return "ignorado"  # "pare" com nada falando não vira pergunta; e uma pergunta por vez
        if c.tipo == "so_jarvis":
            self._ativar()
            self.voz.falar("Pois não?")
            return "pois_nao"
        if c.tipo == "pergunta":
            self._perguntar(c.texto)
            return "pergunta"
        if (self.modo == "ativa" and self.relogio() <= self._ativa_ate
                and ev.transcricao.no_speech_prob < LIMIAR_SEM_FALA):
            self._perguntar(texto)  # conversa aberta: não precisa do "Jarvis"
            return "pergunta"
        return "ignorado"

    # ---------- comandos do HUD e avisos proativos ----------
    def comando(self, acao: str) -> None:
        with self._trava:
            if acao == "ouvir":
                self._ativar()
            elif acao == "parar":
                self.voz.cancelar()
                self.modo = "repouso"
            elif acao in ("mudo", "som"):
                self.voz.mudo = acao == "mudo"
                if self.voz.mudo:
                    self.voz.cancelar()

    def proativo(self, ev: dict) -> None:
        if ev.get("falar") and ev.get("texto"):
            self.voz.falar(ev["texto"])

    # ---------- ações ----------
    def _ativar(self) -> None:
        self.modo = "ativa"
        self._ativa_ate = self.relogio() + JANELA_S

    def _decidir(self, ok: bool) -> None:
        ap, self.aprovacao = self.aprovacao, None
        try:
            self.cliente.aprovar(ap["id"], ok)
        except ApiIndisponivel as e:
            logger.warning("voz: aprovação não enviada ({})", e)

    def _nova_conversa(self) -> None:
        self.voz.cancelar()
        self.eco.limpar()
        try:
            self.cliente.nova_conversa()
            self.voz.falar("Nova conversa.")
        except Exception as e:  # noqa: BLE001 — a API pode estar fora ou sem a rota; a voz não pode cair
            logger.warning("voz: nova conversa falhou ({})", e)
            self.voz.falar("Não consegui abrir uma nova conversa.")
        self._ativar()

    def _perguntar(self, texto: str) -> None:
        self.ocupado = True
        self._ativar()

        def trabalho() -> None:
            divisor = DivisorDeFrases(self.voz.falar)
            try:
                for ev in self.cliente.perguntar(texto):
                    tipo = ev.get("type")
                    if tipo == "approval" and isinstance(ev.get("data"), dict):
                        divisor.flush()
                        with self._trava:
                            self.aprovacao = ev["data"]
                        self.voz.falar(f"Confirma: {ev['data'].get('resumo', 'a ação')}? Diga sim ou não.")
                        continue
                    if self.aprovacao and tipo in ("text", "tool"):  # decidida pelo HUD ou vencida
                        with self._trava:
                            self.aprovacao = None
                    if tipo == "text" and isinstance(ev.get("data"), str):
                        divisor.push(ev["data"])
                    elif tipo == "done":
                        break
                divisor.flush()
            except ApiIndisponivel as e:
                logger.warning("voz: API indisponível ({})", e)
                self.voz.falar("Não consegui falar com o núcleo do JARVIS.")
            finally:
                with self._trava:
                    self.ocupado = False
                    self.aprovacao = None
                    self._ativa_ate = max(self._ativa_ate, self.relogio() + JANELA_S)

        self._executar(trabalho)
