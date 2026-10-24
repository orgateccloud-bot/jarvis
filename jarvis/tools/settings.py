"""Abrir telas de configuração do Windows (lista fixa). O JARVIS abre; quem altera é o usuário."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import Tool, ToolContext, ToolError

TELAS = {
    "armazenamento": "ms-settings:storagesense",
    "sensor de armazenamento": "ms-settings:storagepolicies",
    "apps instalados": "ms-settings:appsfeatures",
    "inicializacao": "ms-settings:startupapps",
    "energia": "ms-settings:powersleep",
    "windows update": "ms-settings:windowsupdate",
    "som": "ms-settings:sound",
    "tela": "ms-settings:display",
    "rede": "ms-settings:network-status",
    "bluetooth": "ms-settings:bluetooth",
    "privacidade do microfone": "ms-settings:privacy-microphone",
    "limpeza de disco": "cleanmgr.exe",
}


class TelaParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tela: Literal[tuple(TELAS)] = Field(description="Tela de configuração da lista permitida")  # type: ignore[valid-type]


def abrir_configuracao(p: TelaParams, ctx: ToolContext) -> str:
    if not hasattr(os, "startfile"):
        raise ToolError("abrir configurações só é suportado no Windows")
    try:
        # alvo vem só da lista fixa TELAS (validada pelo Literal), sem shell
        os.startfile(TELAS[p.tela])  # nosec B606
    except OSError as e:
        raise ToolError(f"não consegui abrir {p.tela}: {e.strerror or e}") from e
    return f"Tela de {p.tela} aberta."


SETTINGS_TOOLS = [
    Tool(
        name="abrir_configuracao",
        description="Abre uma tela de configuração do Windows (armazenamento, sensor de armazenamento, apps "
                    "instalados, inicialização, energia, Windows Update, som, tela, rede, bluetooth, privacidade do "
                    "microfone) ou a Limpeza de Disco. Abrir é seguro: não precisa de confirmação.",
        params=TelaParams, run=abrir_configuracao, summary=lambda p: f"abriu {p.tela}",
    ),
]
