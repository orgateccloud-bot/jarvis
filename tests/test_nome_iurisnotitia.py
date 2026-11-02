"""O JARVIS-IurisNotitia se apresenta pelo nome: no prompt do Claude e na saudação falada (02/11/2026, quarto JARVIS
do projeto, voltado ao conhecimento jurídico)."""

from types import SimpleNamespace

from jarvis.config import Settings
from jarvis.core.llm import ClaudeBrain
from jarvis.proactive.monitors import Monitor


def test_nome_padrao_e_o_do_iurisnotitia(monkeypatch):
    monkeypatch.delenv("JARVIS_ASSISTENTE", raising=False)
    assert Settings().assistente == "JARVIS-IurisNotitia"


def test_nome_no_prompt_e_na_saudacao():
    cerebro = ClaudeBrain(1024, "Senhor", client=object(), assistente="JARVIS-IurisNotitia")
    assert cerebro.system.startswith("Você é o JARVIS-IurisNotitia, assistente pessoal de Senhor")
    monitor = Monitor(SimpleNamespace(state=lambda: None), SimpleNamespace(pending=list), "Senhor",
                      sampler=lambda: {"disk": 10.0, "ram": 10.0}, assistente="JARVIS-IurisNotitia")
    assert "Senhor. JARVIS-IurisNotitia online." in monitor.greeting().texto
