"""Cérebro Claude (cache, compaction, fallback) e respostas por regra para o trivial."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic
import psutil
from loguru import logger

from .contracts import StreamEvent
from .costs import price_usage

SYSTEM_PROMPT = """Você é o J.A.R.V.I.S., assistente pessoal de {nome}, rodando no PC dele.

Personalidade: objetivo, técnico e sofisticado; humor sutil e seco, estilo britânico; leal e protetor.
Trate o usuário por "{nome}". Responda sempre em português do Brasil.

Como responder:
- Suas respostas podem ser lidas em voz alta: frases curtas e naturais, sem emojis.
- Use markdown (listas, tabelas, código) só quando o conteúdo pedir.
- Seja direto. Quando detectar risco ou algo que mereça atenção, avise proativamente.
- Se não souber, diga; nunca invente fatos, números ou fontes.
- Mensagens de sistema no meio da conversa trazem contexto atual (data, telemetria do PC); use quando relevante.
- Dados pessoais aparecem mascarados (CPF/CNPJ com asteriscos, nomes como PESSOA_XXXX); mantenha-os assim.

Ferramentas:
- Você tem ferramentas para consultar o PC, processos, arquivos (pastas permitidas), custos e lembretes, e em alguns
  modelos busca na web. Use-as quando a resposta depender de dados atuais em vez de supor.
- Você também gerencia o disco: analisar_espaco mostra o que ocupa espaço; mover_itens leva arquivos para o
  arquivo do JARVIS no D: (reversível, com desfazer_movimento); enviar_para_lixeira é recuperável; e
  abrir_configuracao abre telas do Windows. Ao liberar espaço, analise primeiro, proponha e mova em UM lote.
- Ações com efeito (abrir app, encerrar processo, lembretes, mover, desfazer, Lixeira) pedem a confirmação do
  usuário automaticamente: chame a ferramenta direto, sem pedir permissão em texto antes.
- Se uma ação for negada ou falhar, diga isso em uma frase e siga em frente."""

BETA_COMPACTION = "compact-2026-01-12"
BETA_FALLBACK = "server-side-fallback-2026-07-01"
WEB_SEARCH_USD = 0.01  # busca na web cobrada à parte (US$ 10 por mil)


@dataclass
class TurnOutcome:
    """Resultado final de um turno: o que anexar ao histórico e quanto custou."""

    text: str
    model: str
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    cost_usd: float = 0.0


class BrainUnavailable(Exception):
    """O Claude não respondeu (rede, sobrecarga, credencial); a sessão avisa o usuário."""


class ToolInputUnparseable(Exception):
    """Com eager_input_streaming o SDK levanta ValueError para JSON ilegível; a sessão reemite o pedido."""


def telemetry_note() -> str:
    """Contexto atual de cada turno: vale mais que números antigos do histórico."""
    mem = psutil.virtual_memory()
    discos = []
    for d in ("C:\\", "D:\\"):
        try:
            u = psutil.disk_usage(d)
            discos.append(f"{d[0]}: {u.free / 2**30:.1f} GB livres ({u.percent:.0f}%)")
        except OSError:
            continue
    return (
        f"[contexto atual] {datetime.now():%d/%m/%Y %H:%M} | CPU {psutil.cpu_percent(interval=None):.0f}% "
        f"| RAM {mem.percent:.0f}% ({mem.used / 2**30:.1f}/{mem.total / 2**30:.1f} GB) | " + " · ".join(discos)
    )


# Modelos sem fallback de recusa no servidor: a sessão escala para a camada acima.
NO_SERVER_FALLBACK = {"claude-haiku-5-5"}


class ClaudeBrain:
    def __init__(self, max_tokens: int, user_name: str, client: Any | None = None):
        self.max_tokens = max_tokens
        self.system = SYSTEM_PROMPT.format(nome=user_name)
        self.client = client or anthropic.AsyncAnthropic()

    def request(self, messages: list[dict], model: str, effort: str,
                tools: list[dict] | None = None, tool_choice: dict | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": effort},
            "cache_control": {"type": "ephemeral"},
            "context_management": {"edits": [{"type": "compact_20260112"}]},
            "betas": [BETA_COMPACTION],
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        if model not in NO_SERVER_FALLBACK:
            params["fallbacks"] = "default"
            params["betas"] = [BETA_COMPACTION, BETA_FALLBACK]
        return params

    async def stream(self, messages: list[dict], model: str, effort: str, tools: list[dict] | None = None,
                     tool_choice: dict | None = None) -> AsyncIterator[StreamEvent | TurnOutcome]:
        params = self.request(messages, model, effort, tools, tool_choice)
        try:
            async with self.client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "thinking_delta" and event.delta.thinking:
                            yield StreamEvent(type="thinking", data=event.delta.thinking)
                        elif event.delta.type == "text_delta":
                            yield StreamEvent(type="text", data=event.delta.text)
                final = await stream.get_final_message()
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
            raise BrainUnavailable(str(e)) from e
        except anthropic.AuthenticationError as e:
            raise BrainUnavailable("credencial da Anthropic inválida") from e
        except ValueError as e:
            # JSON de entrada de ferramenta ilegível (eager streaming): sem tool_use_id para responder
            raise ToolInputUnparseable(str(e)) from e
        except TypeError as e:
            # o SDK levanta TypeError quando não há nenhuma credencial configurada
            if "authentication method" in str(e):
                raise BrainUnavailable("credencial da Anthropic ausente (ANTHROPIC_API_KEY)") from e
            raise

        text = "".join(b.text for b in final.content if b.type == "text")
        if final.stop_reason == "refusal":
            category = getattr(getattr(final, "stop_details", None), "category", None)
            logger.warning(f"Recusa de {model} (categoria={category})")

        u = final.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        served_by = final.model or model
        searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        yield TurnOutcome(
            text=text,
            model=served_by,
            content=[b.to_dict() for b in final.content],
            stop_reason=final.stop_reason,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            web_searches=searches,
            cost_usd=round(price_usage(served_by, u.input_tokens, u.output_tokens, cache_read, cache_write)
                           + searches * WEB_SEARCH_USD, 6),
        )


class RuleResponder:
    """Respostas instantâneas por regra (sem IA, custo zero) para o trivial."""

    def __init__(self, user_name: str):
        self.user_name = user_name

    def answer(self, text: str) -> str | None:
        t = text.lower()
        now = datetime.now()
        if any(k in t for k in ("que horas", "horas são", "horas sao")):
            return f"São {now:%H:%M}, {self.user_name}."
        if any(k in t for k in ("que dia", "data de hoje")):
            return f"Hoje é {now:%d/%m/%Y}, {self.user_name}."
        if any(k in t for k in ("cpu", "ram", "memória", "memoria", "disco", "status do pc", "status do sistema")):
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")
            return (
                f"CPU em {psutil.cpu_percent(interval=0.3):.0f}%, RAM em {mem.percent:.0f}% "
                f"({mem.used / 2**30:.1f} de {mem.total / 2**30:.1f} GB) e disco C: em {disk.percent:.0f}%, "
                f"{self.user_name}."
            )
        if t.strip(" !.?,") in ("oi", "olá", "ola", "jarvis", "hey jarvis", "bom dia", "boa tarde", "boa noite"):
            return f"Às suas ordens, {self.user_name}."
        if t.strip(" !.?,") in ("obrigado", "obrigada", "valeu"):
            return f"Sempre um prazer, {self.user_name}."
        return None
