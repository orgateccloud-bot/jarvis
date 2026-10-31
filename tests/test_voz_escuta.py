"""Fase 2b, de ponta a ponta com WAVs sintéticos: recorte da fala (VAD) → Whisper local (que também é a ativação)
→ comando. "Ok Jarvis" × "Jarvis, ..." (Decisão B), eco, silêncio, ruído e pedido no meio de conversa.

Sem API e sem rede: a trava de rede fica ligada e nenhuma tentativa pode ser contada. Precisa do extra [voz], do
faster-whisper e dos modelos (senão é pulado).
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


def _comandos(eventos):
    """Só o que vira ação: "nada" é fala transcrita que não começava pelo vocativo."""
    return [(e.comando.tipo, e.comando.texto) for e in eventos if e.comando.tipo != "nada"]


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
    ("jarvis_que_horas_maria", "pergunta", "que horas são?"),      # o modelo pronto perde (0,108); o Whisper não
    ("jarvis_daniel", "so_jarvis", ""),
    ("hey_jarvis_maria", "so_jarvis", ""),
])
def test_ok_jarvis_e_jarvis_com_pedido(escuta, nome, tipo, pedido):
    assert _comandos(escuta.processar_clip(_clip(nome))) == [(tipo, pedido)]


@pytest.mark.parametrize("nome", ["eco_disco_daniel", "eco_lembrete_daniel", "eco_custo_maria"])
def test_eco_da_propria_voz_nao_vira_comando(escuta, nome):
    eventos = escuta.processar_clip(_clip(nome))
    assert eventos and _comandos(eventos) == []   # foi transcrita (fala curta), mas não começa por "Jarvis"


def test_silencio_e_ruido_nao_viram_comando(escuta):
    rng = np.random.default_rng(1)
    assert escuta.processar_clip(np.zeros(TAXA * 5, dtype=np.int16)) == []
    assert escuta.processar_clip(rng.normal(0, 3000, TAXA * 5).clip(-32768, 32767).astype(np.int16)) == []


def _aparado(nome: str):
    """O WAV sem o silêncio que o SAPI deixa nas pontas: as pausas montadas no teste ficam exatas."""
    with wave.open(str(FIXTURES / f"{nome}.wav"), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    som = np.flatnonzero(np.abs(x) > 300)
    return x[som[0]:som[-1] + 1]


def test_pedido_emendado_na_conversa_ao_redor_e_ouvido(escuta):
    """31/10: com gente conversando perto, o "Jarvis, que horas são?" emendou na fala dos outros sem a pausa de
    560 ms, o trecho passou de 8 s e era descartado sem transcrever. Agora vai ao Whisper, e só a frase do pedido
    segue (a conversa dos outros não vai para a API)."""
    pausa, pad = np.zeros(int(TAXA * 0.2), dtype=np.int16), np.zeros(TAXA, dtype=np.int16)
    clip = np.concatenate([pad, _aparado("eco_disco_daniel"), pausa, _aparado("jarvis_que_horas_daniel"), pausa,
                           _aparado("eco_custo_maria"), pad])   # outra voz continua falando logo depois
    antes = escuta.contagem.longas
    eventos = escuta.processar_clip(clip)
    assert len(eventos) == 1 and eventos[0].duracao_fala_s > 8          # um trecho só, longo
    assert escuta.contagem.longas == antes + 1
    assert _comandos(eventos) == [("pergunta", "que horas são?")], eventos[0].transcricao.texto


def test_transcricao_adiantada_e_aproveitada_e_pausa_curta_a_descarta(escuta):
    antes = (escuta.contagem.adiantadas, escuta.contagem.descartadas)
    ev = escuta.processar_clip(_clip("jarvis_que_horas_daniel"))[0]
    assert ev.adiantada and escuta.contagem.adiantadas == antes[0] + 1        # começou no silêncio e valeu

    # "Jarvis." + pausa de 400 ms (mais que o adiantamento, menos que o fim) + "Jarvis, que horas são?"
    pausa, pad = np.zeros(int(TAXA * 0.4), dtype=np.int16), np.zeros(TAXA, dtype=np.int16)

    eventos = escuta.processar_clip(np.concatenate([pad, _aparado("jarvis_daniel"), pausa, _aparado("jarvis_que_horas_daniel"), pad]))
    assert escuta.contagem.descartadas > antes[1]                             # o texto adiantado ficou velho
    assert len(eventos) == 1 and "que horas" in eventos[0].transcricao.texto  # uma fala só, inteira


def test_latencia_ate_o_texto_na_gpu(escuta):
    if ":cuda:" not in escuta.transcritor.config:
        pytest.skip("Whisper na CPU: a meta de latência é para a GPU")
    clip = _clip("jarvis_que_horas_daniel")
    lat = sorted(escuta.processar_clip(clip)[0].latencia_s for _ in range(5))
    # meta da Etapa 2: < 1,5 s do fim da fala ao início da resposta; a voz local (fase 2c) leva ~0,1 s.
    # Mediana de 5: com a GPU dividida (o cosmos do HUD, por exemplo) uma transcrição isolada já levou 0,65 s.
    assert lat[2] < 1.3, lat
