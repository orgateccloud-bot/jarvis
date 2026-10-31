"""Etapa 3: agentes subordinados ao JARVIS.

O JARVIS é o cérebro: o orquestrador cria, observa, atualiza e comanda cada agente. Um agente nunca recebe ordem de
outro lugar: só o orquestrador guarda a referência a ele (objeto-capacidade), e o orquestrador só é alcançado pela
API com token e pelas ferramentas do cérebro, que rodam dentro de um turno autenticado.
"""
