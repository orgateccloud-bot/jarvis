"""Fase 2b, de ponta a ponta com WAVs sintéticos: ativação → recorte da fala (VAD) → Whisper local → comando.

"Ok Jarvis" × "Jarvis, ..." (Decisão B), eco, silêncio e ruído. Sem API e sem rede: a trava de rede fica ligada e
nenhuma tentativa pode ser contada. Precisa do extra [voz], do faster-whisper e dos modelos (senão é pulado).
"""

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
pytest.importorskip("faster_whisper")

from jarvis.voz import offline
from jarvis.voz.baixar import verificar, verificar_whisper
from jarvis.voz.config import MODELOS_ATIVACAO, TAXA, WHISPER, pastas

FIXTURES = Path(__file__).parent / "fixtures" / "voz"
pytestmark = [
    pytest.mark.voz_modelos,
    pytest.mark.skipif(bool(verificar(pastas(), list(MODELOS_ATIVACAO)) + verificar_whisper(pastas(), WHISPER)),
                       reason="modelos de voz não baixados"),
]


@pytest.fixture(scope="module")
def escuta():
    from jarvis.voz.ativacao import Ativacao
    from jarvis.voz.escuta import Escuta
    from jarvis.voz.transcricao import criar_transcritor

    offline.ativar()
    antes = offline.bloqueadas()
    p = pastas()
    e = Escuta(Ativacao(p.ativacao), criar_transcritor(p.whisper(WHISPER)))
    e.transcritor.transcrever(np.zeros(TAXA, dtype=np.int16))  # aquecimento
    yield e
    assert offline.bloqueadas() == antes  # nada tentou sair do PC
    offline.desativar()


def _clip(nome: str):
    with wave.open(str(FIXTURES / f"{nome}.wav"), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(TAXA, dtype=np.int16)
    return np.concatenate([pad, audio, pad])


@pytest.mark.parametrize(("nome", "tipo", "pedido"), [
    ("ok_jarvis_daniel", "nova_conversa", ""),
    ("ok_jarvis_maria", "nova_conversa", ""),
    ("ok_jarvis_que_horas_daniel", "pergunta", "que horas são?"),   # "Ok" + pedido não zera a conversa
    ("jarvis_que_horas_daniel", "pergunta", "que horas são?"),
    ("jarvis_daniel", "so_jarvis", ""),
    ("hey_jarvis_maria", "so_jarvis", ""),
])
def test_ok_jarvis_e_jarvis_com_pedido(escuta, nome, tipo, pedido):
    eventos = escuta.processar_clip(_clip(nome))
    assert len(eventos) == 1
    assert (eventos[0].comando.tipo, eventos[0].comando.texto) == (tipo, pedido)


@pytest.mark.parametrize("nome", ["eco_disco_daniel", "eco_lembrete_daniel", "eco_custo_maria"])
def test_eco_da_propria_voz_nao_vira_comando(escuta, nome):
    assert escuta.processar_clip(_clip(nome)) == []


def test_silencio_e_ruido_nao_viram_comando(escuta):
    rng = np.random.default_rng(1)
    assert escuta.processar_clip(np.zeros(TAXA * 5, dtype=np.int16)) == []
    assert escuta.processar_clip(rng.normal(0, 3000, TAXA * 5).clip(-32768, 32767).astype(np.int16)) == []


def test_latencia_ate_o_texto_na_gpu(escuta):
    if ":cuda:" not in escuta.transcritor.config:
        pytest.skip("Whisper na CPU: a meta de latência é para a GPU")
    clip = _clip("jarvis_que_horas_daniel")
    lat = sorted(escuta.processar_clip(clip)[0].latencia_s for _ in range(5))
    # meta da Etapa 2: < 1,5 s do fim da fala ao início da resposta; a voz local (fase 2c) leva ~0,1 s.
    # Mediana de 5: com a GPU dividida (o cosmos do HUD, por exemplo) uma transcrição isolada já levou 0,65 s.
    assert lat[2] < 1.3, lat
