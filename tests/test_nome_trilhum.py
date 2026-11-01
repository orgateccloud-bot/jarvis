"""O JARVIS-TRILHUM se apresenta pelo nome: no prompt do Claude e na saudação falada (01/11/2026, terceiro JARVIS
do projeto, voltado aos estudos do Trilhum)."""

from types import SimpleNamespace

from jarvis.config import Settings
from jarvis.core.llm import ClaudeBrain
from jarvis.proactive.monitors import Monitor


def test_nome_padrao_e_o_do_trilhum(monkeypatch):
    monkeypatch.delenv("JARVIS_ASSISTENTE", raising=False)
    assert Settings().assistente == "JARVIS-TRILHUM"


def test_nome_no_prompt_e_na_saudacao():
    cerebro = ClaudeBrain(1024, "Senhor", client=object(), assistente="JARVIS-TRILHUM")
    assert cerebro.system.startswith("Você é o JARVIS-TRILHUM, assistente pessoal de Senhor")
    monitor = Monitor(SimpleNamespace(state=lambda: None), SimpleNamespace(pending=list), "Senhor",
                      sampler=lambda: {"disk": 10.0, "ram": 10.0}, assistente="JARVIS-TRILHUM")
    assert "Senhor. JARVIS-TRILHUM online." in monitor.greeting().texto
