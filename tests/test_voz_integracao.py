"""Fase 2c de ponta a ponta, sem Claude e sem hardware: a API de verdade (uvicorn, com o Claude falso) e o serviço de
voz completo (Escuta com o Whisper, Conversa, Cliente HTTP, batimento). O microfone é o WAV sintético "Jarvis, que
horas são?" e a voz local é um gravador do que seria falado.

Precisa do extra [voz], do faster-whisper e dos modelos (senão é pulado).
"""

import json
import socket
import threading
import time
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("faster_whisper")
uvicorn = pytest.importorskip("uvicorn")

from jarvis.api.server import build_conversation, create_app
from jarvis.voz.baixar import verificar, verificar_whisper
from jarvis.voz.config import MODELOS_ATIVACAO, QUADRO, TAXA, WHISPER, pastas
from tests.conftest import FakeAnthropic, text_turn

FIXTURES = Path(__file__).parent / "fixtures" / "voz"
pytestmark = [
    pytest.mark.voz_modelos,
    pytest.mark.skipif(bool(verificar(pastas(), list(MODELOS_ATIVACAO)) + verificar_whisper(pastas(), WHISPER)),
                       reason="modelos de voz não baixados"),
]


class MicrofoneDeWav:
    """Entrega os quadros de um WAV e depois silêncio, no ritmo que o serviço pedir (sem esperar o tempo real)."""

    nome = "WAV de teste"

    def __init__(self, audio):
        self.audio, self.i, self.mudo, self.perdidos, self._aberto = audio, 0, False, 0, False

    @property
    def aberto(self):
        return self._aberto

    def abrir(self):
        self._aberto = True

    def fechar(self):
        self._aberto = False

    def quadros(self, timeout=1.0):
        while self._aberto:
            if self.i + QUADRO <= len(self.audio):
                q = self.audio[self.i:self.i + QUADRO]
                self.i += QUADRO
                yield None if self.mudo else q
            else:
                time.sleep(0.01)
                yield np.zeros(QUADRO, dtype=np.int16)


class VozGravada:
    def __init__(self):
        self.falados, self.falando, self.mudo, self.conversa = [], False, False, None

    def falar(self, texto):
        self.falados.append(texto)
        self.conversa.na_frase(texto)
        self.conversa.fala_terminou()

    def cancelar(self):
        pass

    def encerrar(self):
        pass


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rodar(settings, wav: str, claude: FakeAnthropic):
    """Sobe a API (Claude falso) e o serviço de voz com o WAV no lugar do microfone; devolve o que seria falado."""
    from jarvis.voz.ativacao import Ativacao
    from jarvis.voz.cliente import Cliente
    from jarvis.voz.escuta import Escuta
    from jarvis.voz.servico import Servico
    from jarvis.voz.transcricao import criar_transcritor

    s = settings.model_copy(update={"voz_local": True})
    app = create_app(s, conversation=build_conversation(s, claude_client=claude), proactive=False, iniciar_voz=False)
    porta = _porta_livre()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True).start()
    while not servidor.started:
        time.sleep(0.05)

    with wave.open(str(FIXTURES / f"{wav}.wav"), "rb") as w:
        fala = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(TAXA, dtype=np.int16)
    p = pastas()
    voz = VozGravada()
    srv = Servico(Escuta(Ativacao(p.ativacao), criar_transcritor(p.whisper(WHISPER))),
                  Cliente(f"http://127.0.0.1:{porta}", "token-de-teste"), MicrofoneDeWav(np.concatenate([pad, fala, pad])),
                  voz=voz)
    voz.conversa = srv.conversa
    t = threading.Thread(target=srv.rodar, daemon=True)
    t.start()
    try:
        for _ in range(300):
            if voz.falados and not srv.conversa.ocupado:
                break
            time.sleep(0.1)
    finally:
        srv.parar.set()
        t.join(timeout=10)
        servidor.should_exit = True
    return voz.falados, app


def test_que_horas_sao_responde_pela_regra_local_sem_claude(settings):
    claude = FakeAnthropic(script=[text_turn("não deveria ser chamado")])
    falados, app = _rodar(settings, "jarvis_que_horas_daniel", claude)
    # "que horas são" a API responde pela regra local, como faz para o HUD: custo zero, o Claude nem é chamado
    assert len(falados) == 1 and falados[0].startswith("São ") and ":" in falados[0], falados
    assert claude.calls == []
    assert app.state.voz.estado in ("ouvindo", "falando", "processando", "repouso")   # o batimento chegou


def test_pergunta_vai_ao_claude_e_a_resposta_e_falada_frase_a_frase(settings):
    claude = FakeAnthropic(script=[text_turn("A capital da França é Paris, Senhor. Quer saber mais alguma coisa?")])
    falados, _ = _rodar(settings, "jarvis_capital_daniel", claude)
    assert falados == ["A capital da França é Paris, Senhor. Quer saber mais alguma coisa?"]
    enviado = json.dumps(claude.calls[0]["messages"], ensure_ascii=False)
    assert "qual é a capital da França?" in enviado and "Jarvis, qual" not in enviado   # o pedido, sem o vocativo
