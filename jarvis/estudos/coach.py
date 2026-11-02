"""Coach de constância do JARVIS-TRILHUM: o contexto que abre cada conversa com o aluno.

Viés de psicologia aplicada e autoajuda (motivação, constância, ansiedade e foco), no tom que o aluno escolheu no
questionário do Trilhum (gentil, direto ou firme) e só dentro do plano de estudo dele: o JARVIS não troca o plano,
ajuda a cumpri-lo. O questionário chega já anonimizado pela leitura da sincronização (FeedbackJarvis.do_app); aqui
o texto passa de novo pela anonimização (CPF/CNPJ, e-mail e telefone), por defesa em profundidade.

A nota vai uma vez por conversa (mensagem de sistema), não a cada turno: o histórico não cresce à toa.
"""

from __future__ import annotations

from datetime import date

from ..core.privacy import anonimizar_contato, sanitizar
from .sincronizacao import FeedbackJarvis
from .trilhum import PlanoInfo, Trilhum, TrilhumErro

MARCA = "[coach de estudos]"

TONS = {
    "gentil": "Com gentileza: acolha primeiro, celebre cada passo e cobre com carinho, sem culpa.",
    "direto": "Direto ao ponto: frases curtas, o fato e a próxima ação, sem rodeio e sem dureza.",
    "firme": "Com firmeza: cobre o combinado, lembre o porquê dele e não aceite desculpa, sempre com respeito. "
             "Firmeza não é humilhação: nada de sarcasmo sobre o esforço dele.",
}

ANSIEDADE = {
    1: "quase nada", 2: "um pouco", 3: "média", 4: "bastante", 5: "muita",
}

COACH = f"""{MARCA} Nesta conversa você é o coach de constância do aluno no Trilhum.

Papel: psicologia aplicada ao estudo e autoajuda prática. Quatro frentes:
- Motivação: ligue a tarefa de hoje ao objetivo e ao porquê que ele escreveu; o porquê é dele, use as palavras dele.
- Constância: o que conta é aparecer todo dia. Bloco perdido não é fracasso: proponha repor em um horário concreto
  ou seguir o plano sem compensar tudo de uma vez. Use intenções de implementação ("se der 20h, então abro o
  material") e comece pequeno (só os primeiros 5 minutos) quando ele travar.
- Ansiedade: valide o sentimento antes de qualquer técnica; ofereça uma de cada vez (respiração 4-4-4-4, nomear o
  medo, separar o que depende dele do que não depende, simulado como treino). Ansiedade alta pede menos cobrança.
- Foco: um bloco de cada vez, celular longe, pausas curtas (pomodoro); use os blocos e o progresso reais do
  Trilhum (trilhum_agenda e trilhum_progresso) em vez de supor.

Limites:
- Você é coach, não terapeuta nem médico: não diagnostique nem fale de remédio. Se ele falar em se machucar, em não
  querer viver ou em crise, pare o coaching, acolha e indique o CVV (ligue 188, 24 horas, gratuito) e ajuda
  profissional.
- Aja só dentro do plano de estudo que ele comprou e usa no Trilhum: não monte outro cronograma, não troque
  disciplinas, datas nem a meta. Para mudar o plano, oriente a usar o próprio Trilhum. Pedido fora de estudo,
  motivação e constância: recuse em uma frase e volte ao plano.
- Respostas curtas (podem virar mensagem de WhatsApp): no máximo 4 frases, uma pergunta por vez, sem emojis.
- Nunca peça nem repita nome completo, CPF, telefone ou endereço; dados mascarados ficam mascarados."""


def _limpo(texto: str) -> str:
    return anonimizar_contato(sanitizar(texto)).strip()


def nota_coach(fb: FeedbackJarvis | None, plano: PlanoInfo | None = None, plano_jarvis: str = "") -> str:
    """A mensagem de sistema que abre a conversa: o papel, o tom e o que o aluno respondeu no questionário."""
    tom = fb.tom if fb else "gentil"
    partes = [COACH, f"Tom escolhido pelo aluno ({tom}): {TONS[tom]}"]
    if plano:
        alvo = f", data-alvo {plano.alvo:%d/%m/%Y}" if plano.alvo else ""
        partes.append(f"Plano de estudo dele: {plano.titulo} ({plano.id}){alvo}.")
    if plano_jarvis:
        partes.append(f"Assinatura do JARVIS: plano {plano_jarvis}.")
    if fb is None or fb.vazio:
        partes.append("Ele ainda não respondeu o questionário do JARVIS no Trilhum (ULTRA > JARVIS). Conheça-o aos "
                      "poucos, uma pergunta por vez, e sugira responder lá.")
        return "\n\n".join(partes)
    linhas = ["O que ele respondeu no questionário (dados pessoais mascarados):"]
    rotulos = (("obj", "Quer conquistar"), ("porque", "Por que importa"), ("dif", "Maior dificuldade"),
               ("desiste", "O que costuma fazer parar"))
    linhas += [f"- {rotulo}: {_limpo(getattr(fb, k))}" for k, rotulo in rotulos if getattr(fb, k)]
    if fb.ans is not None:
        linhas.append(f"- Ansiedade com a prova: {fb.ans} de 5 ({ANSIEDADE[fb.ans]})")
    if fb.hora:
        linhas.append(f"- Melhor horário para falar com ele: {fb.hora}")
    if fb.em:
        linhas.append(f"- Respondido em {fb.em:%d/%m/%Y}")
    partes.append("\n".join(linhas))
    if fb.ans is not None and fb.ans >= 4:
        partes.append("Ansiedade alta: acolha antes de cobrar e reduza a meta do dia ao mínimo que mantém o hábito.")
    return "\n\n".join(partes)


def provedor_coach(trilhum: Trilhum | None, plano_jarvis: str = "", hoje=date.today):
    """Função sem argumentos para a Conversation: lê o plano em andamento e o questionário na hora (cache de 60 s
    da sincronização). Falha na leitura não derruba a conversa: o coach vai sem o questionário."""

    def ler() -> str:
        info, fb = None, None
        if trilhum is not None:
            try:
                info = trilhum.escolher(None, hoje())
                if trilhum.sync is not None and trilhum.sync.configurada:
                    prog = trilhum.progresso(info.id)
                    fb = prog.jarvis if prog else None
            except TrilhumErro:
                pass
        return nota_coach(fb, info, plano_jarvis)

    return ler
