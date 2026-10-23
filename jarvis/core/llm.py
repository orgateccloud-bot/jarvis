"""Cérebros: Claude (nuvem, com cache/compaction/fallback) e Local (determinístico + Ollama)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic
import psutil
from loguru import logger

from .contracts import Route, StreamEvent
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
- Dados pessoais aparecem mascarados (CPF/CNPJ com asteriscos, nomes como PESSOA_XXXX); mantenha-os assim."""

BETAS = ["compact-2026-01-12", "server-side-fallback-2026-07-01"]


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
    cost_usd: float = 0.0


class BrainUnavailable(Exception):
    """O provedor não respondeu (rede, sobrecarga, credencial); a sessão cai para o modo local."""


def telemetry_note() -> str:
    mem = psutil.virtual_memory()
    return (
        f"[contexto] {datetime.now():%d/%m/%Y %H:%M} | CPU {psutil.cpu_percent(interval=None):.0f}% "
        f"| RAM {mem.percent:.0f}% ({mem.used / 2**30:.1f}/{mem.total / 2**30:.1f} GB)"
    )


class ClaudeBrain:
    def __init__(self, model: str, max_tokens: int, user_name: str, client: Any | None = None):
        self.model = model
        self.max_tokens = max_tokens
        self.system = SYSTEM_PROMPT.format(nome=user_name)
        self.client = client or anthropic.AsyncAnthropic()

    async def stream(self, messages: list[dict], effort: str) -> AsyncIterator[StreamEvent | TurnOutcome]:
        try:
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                messages=messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
                context_management={"edits": [{"type": "compact_20260112"}]},
                fallbacks="default",
                betas=BETAS,
            ) as stream:
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
        except TypeError as e:
            # o SDK levanta TypeError quando não há nenhuma credencial configurada
            if "authentication method" in str(e):
                raise BrainUnavailable("credencial da Anthropic ausente (ANTHROPIC_API_KEY)") from e
            raise

        text = "".join(b.text for b in final.content if b.type == "text")
        if final.stop_reason == "refusal":
            category = getattr(getattr(final, "stop_details", None), "category", None)
            logger.warning(f"Recusa do modelo (categoria={category})")
            if not text:
                text = "Não posso ajudar com isso, Senhor."
                yield StreamEvent(type="text", data=text)

        u = final.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        served_by = final.model or self.model
        yield TurnOutcome(
            text=text,
            model=served_by,
            content=[b.to_dict() for b in final.content],
            stop_reason=final.stop_reason,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=price_usage(served_by, u.input_tokens, u.output_tokens, cache_read, cache_write),
        )


def _plain(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


class LocalBrain:
    """Custo zero: respostas determinísticas para o trivial e Ollama para o resto."""

    def __init__(self, host: str, model: str, user_name: str):
        self.host = host
        self.model = model
        self.user_name = user_name

    def quick_answer(self, text: str) -> str | None:
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

    async def stream(self, messages: list[dict], system: str) -> AsyncIterator[StreamEvent | TurnOutcome]:
        last_user = next((_plain(m["content"]) for m in reversed(messages) if m["role"] == "user"), "")
        quick = self.quick_answer(last_user)
        if quick:
            yield StreamEvent(type="text", data=quick)
            yield TurnOutcome(text=quick, model="local", content=[{"type": "text", "text": quick}])
            return

        import ollama

        chat = [{"role": "system", "content": system}]
        chat += [{"role": m["role"], "content": _plain(m["content"])} for m in messages[-12:] if m["role"] != "system"]
        parts: list[str] = []
        try:
            client = ollama.AsyncClient(host=self.host)
            async for chunk in await client.chat(model=self.model, messages=chat, stream=True):
                piece = chunk["message"]["content"]
                if piece:
                    parts.append(piece)
                    yield StreamEvent(type="text", data=piece)
        except Exception as e:  # noqa: BLE001 — Ollama fora do ar ou modelo ausente: degrada com aviso
            logger.error(f"Ollama indisponível: {e}")
            msg = f"Modelo local indisponível no momento, {self.user_name}. Verifique o Ollama ({self.model})."
            parts = [msg]
            yield StreamEvent(type="text", data=msg)
        text = "".join(parts)
        yield TurnOutcome(text=text, model=f"ollama:{self.model}", content=[{"type": "text", "text": text}])


def route_label(route: Route, effort: str | None) -> str:
    return route.value if route is Route.LOCAL else f"{route.value}:{effort}"
