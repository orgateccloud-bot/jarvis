"""O que fazer com uma fala transcrita depois do disparo (Decisão B, aprovada em 30/10).

- "Ok Jarvis" isolado (só essas duas palavras, fala curta) → nova conversa;
- "Jarvis" sozinho → "Pois não?";
- "Jarvis, pare" → interrompe;
- "Jarvis, X" e "Ok Jarvis, X" → pergunta X (o "Ok" na frente de um pedido NÃO zera a conversa);
- sem o vocativo no começo → nada: a fala não era para o JARVIS.

Com o Whisper como ativação (31/10), toda fala curta passa por aqui; por isso o vocativo precisa ser a 1ª palavra,
ou vir logo depois de um chamamento ("ok", "ei", "oi", "olá", "e aí"). Na voz do usuário, aceitar "Jarvis" até a
3ª palavra trazia "O Jarvis já chegou?" (ouvido no lugar de "O Jarbas já chegou?") como pergunta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jarvis.voz.texto import corrigir_termos, depois_do_vocativo, e_comando_de_parar, palavras, sem_acento

NOVA_CONVERSA = {"ok", "okay", "oquei", "okei"}
MAX_NOVA_S = 2.0           # "Ok Jarvis" dito como comando é curto; mais que isso é outra coisa
LIMIAR_SEM_FALA = 0.6      # no_speech_prob do Whisper acima disso = o trecho não tinha fala (SUPOSIÇÃO, ver 2b)
CHAMAMENTOS = [("ok",), ("okay",), ("oquei",), ("okei",), ("ei",), ("hey",), ("oi",), ("ola",), ("e", "ai")]

Tipo = Literal["nova_conversa", "so_jarvis", "parar", "pergunta", "nada"]


@dataclass(frozen=True)
class Comando:
    tipo: Tipo
    texto: str = ""             # o pedido, sem o vocativo (só em "pergunta")
    negar_aprovacao: bool = False  # "Ok Jarvis" com aprovação pendente: nega antes de zerar (nunca aprova)


def classificar(transcricao: str, duracao_fala_s: float, no_speech_prob: float = 0.0,
                aprovacao_pendente: bool = False) -> Comando:
    texto = corrigir_termos((transcricao or "").strip())
    pal = palavras(texto)
    if not pal or no_speech_prob >= LIMIAR_SEM_FALA:
        return Comando("nada")
    if len(pal) == 2 and pal[0] in NOVA_CONVERSA and pal[1] == "jarvis" and duracao_fala_s <= MAX_NOVA_S:
        return Comando("nova_conversa", negar_aprovacao=aprovacao_pendente)
    if not comeca_pelo_vocativo(pal):
        return Comando("nada")
    # sem acento: o Whisper escreve "Jarvis, parê!" (medido na voz do usuário); o HUD não precisa disso
    if e_comando_de_parar(sem_acento(depois_do_prefixo(texto))):
        return Comando("parar")
    resto = depois_do_vocativo(texto) or ""
    if len(resto) <= 2:
        return Comando("so_jarvis")
    return Comando("pergunta", resto)


def comeca_pelo_vocativo(pal: list[str]) -> bool:
    if pal[:1] == ["jarvis"]:
        return True
    return any(tuple(pal[:len(c)]) == c and pal[len(c):len(c) + 1] == ["jarvis"] for c in CHAMAMENTOS)


def depois_do_prefixo(texto: str) -> str:
    """Tira o que veio antes do vocativo ("e aí, Jarvis, pare" → "Jarvis, pare"), para o teste de parada."""
    i = texto.lower().find("jarvis")
    return texto[i:] if i >= 0 else texto
