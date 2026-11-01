"""O JARVIS Tributário se apresenta pelo nome: no prompt do Claude e na saudação falada (31/10/2026, quando o
projeto foi separado em dois JARVIS)."""

from types import SimpleNamespace

from jarvis.config import Settings
from jarvis.core.llm import ClaudeBrain
from jarvis.proactive.monitors import Monitor


def test_nome_padrao_e_o_do_tributario(monkeypatch):
    monkeypatch.delenv("JARVIS_ASSISTENTE", raising=False)
    assert Settings().assistente == "JARVIS Tributário"


def test_nome_no_prompt_e_na_saudacao():
    cerebro = ClaudeBrain(1024, "Senhor", client=object(), assistente="JARVIS Tributário")
    assert cerebro.system.startswith("Você é o JARVIS Tributário, assistente pessoal de Senhor")
    monitor = Monitor(SimpleNamespace(state=lambda: None), SimpleNamespace(pending=list), "Senhor",
                      sampler=lambda: {"disk": 10.0, "ram": 10.0}, assistente="JARVIS Tributário")
    assert "Senhor. JARVIS Tributário online." in monitor.greeting().texto
