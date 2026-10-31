"""O que fazer com uma fala transcrita depois do disparo (Decisão B, aprovada em 30/10).

- "Ok Jarvis" isolado (só essas duas palavras, fala curta) → nova conversa;
- "Jarvis" sozinho → "Pois não?";
- "Jarvis, pare" → interrompe;
- "Jarvis, X" e "Ok Jarvis, X" → pergunta X (o "Ok" na frente de um pedido NÃO zera a conversa);
- sem o vocativo abrindo uma frase → nada: a fala não era para o JARVIS.

Com o Whisper como ativação (31/10), toda fala curta passa por aqui; por isso o vocativo precisa ser a 1ª palavra,
ou vir logo depois de um chamamento ("ok", "ei", "oi", "olá", "e aí"). Na voz do usuário, aceitar "Jarvis" até a
3ª palavra trazia "O Jarvis já chegou?" (ouvido no lugar de "O Jarbas já chegou?") como pergunta.

Conversa ao redor (31/10): o pedido do usuário emendava na fala dos outros sem a pausa de 560 ms, o trecho passava
de 8 s e era jogado fora sem transcrever. Agora toda fala é transcrita e o vocativo pode abrir QUALQUER frase do
trecho; nesse caso só a frase dele segue, porque o resto é a conversa dos outros e não deve ir para a API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from jarvis.voz.texto import corrigir_termos, depois_do_vocativo, e_comando_de_parar, palavras, sem_acento

NOVA_CONVERSA = {"ok", "okay", "oquei", "okei"}
MAX_NOVA_S = 2.0           # "Ok Jarvis" dito como comando é curto; mais que isso é outra coisa
LIMIAR_SEM_FALA = 0.6      # no_speech_prob do Whisper acima disso = o trecho não tinha fala (SUPOSIÇÃO, ver 2b)
CHAMAMENTOS = [("ok",), ("okay",), ("oquei",), ("okei",), ("ei",), ("hey",), ("oi",), ("ola",), ("e", "ai")]
FALA_CURTA_S = 8.0         # mais longa que isso, quase sempre é conversa ao redor emendada no pedido
FIM_DE_FRASE = re.compile(r"(?<=[.!?…])\s+")

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
    texto = recortar_pedido(texto, longa=duracao_fala_s > FALA_CURTA_S)
    if texto is None:
        return Comando("nada")
    # sem acento: o Whisper escreve "Jarvis, parê!" (medido na voz do usuário); o HUD não precisa disso
    if e_comando_de_parar(sem_acento(depois_do_prefixo(texto))):
        return Comando("parar")
    resto = depois_do_vocativo(texto) or ""
    if len(resto) <= 2:
        return Comando("so_jarvis")
    return Comando("pergunta", resto)


def recortar_pedido(texto: str, longa: bool = False) -> str | None:
    """A parte da transcrição que é para o JARVIS, ou None. Fala curta aberta pelo vocativo: ela inteira (um pedido
    pode ter várias frases). Senão, a primeira frase aberta pelo vocativo, sozinha: o que veio antes e depois dela é
    a fala de outra pessoa emendada sem pausa."""
    if not longa and comeca_pelo_vocativo(palavras(texto)):
        return texto
    return next((f for f in FIM_DE_FRASE.split(texto) if comeca_pelo_vocativo(palavras(f))), None)


def comeca_pelo_vocativo(pal: list[str]) -> bool:
    if pal[:1] == ["jarvis"]:
        return True
    return any(tuple(pal[:len(c)]) == c and pal[len(c):len(c) + 1] == ["jarvis"] for c in CHAMAMENTOS)


def depois_do_prefixo(texto: str) -> str:
    """Tira o que veio antes do vocativo ("e aí, Jarvis, pare" → "Jarvis, pare"), para o teste de parada."""
    i = texto.lower().find("jarvis")
    return texto[i:] if i >= 0 else texto
