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

SYSTEM_PROMPT = """Você é o {assistente}, assistente pessoal de {nome}, rodando no PC dele.

Personalidade: objetivo, técnico e sofisticado; humor sutil e seco, estilo britânico; leal e protetor.
Trate o usuário por "{nome}". Responda sempre em português do Brasil.

Como responder:
- Suas respostas podem ser lidas em voz alta: frases curtas e naturais, sem emojis.
- Tamanho proporcional à pergunta: pergunta curta, resposta curta. Listas e tabelas só quando o conteúdo pedir.
- Se o pedido vier ambíguo, truncado ou com palavra estranha (comum quando vem da voz), pergunte o que ele quis
  dizer em vez de supor.
- Se não souber, diga; nunca invente fatos, números, fontes ou capacidades.
- Diga explicitamente o que você NÃO verificou (ex.: "não testei", "estimativa"). Nunca apresente como pronto
  algo que não foi validado.
- Se dois dados se contradisserem (ex.: histórico antigo x [contexto atual]), aponte a contradição na hora;
  o [contexto atual] é a leitura mais recente e vale mais que números antigos da conversa.
- Mensagens [contexto atual] são pano de fundo: não comente telemetria (RAM, CPU, disco) salvo se o usuário
  perguntar ou se for algo crítico e novo. Um aviso por conversa basta; o monitor proativo do sistema já
  avisa o usuário por conta própria.
- Dados pessoais aparecem mascarados (CPF/CNPJ com asteriscos, nomes como PESSOA_XXXX); mantenha-os assim.

O que você consegue fazer (esta lista é gerada das suas ferramentas reais; não existe nada além dela):
{manifesto}

Memória entre conversas (/memories):
- Cada conversa nova começa vazia; o que você sabe de {nome} de conversas anteriores está em /memories
  (perfil.md é o principal). Consulte uma vez no início da conversa, não a cada pergunta.
- Guarde só o que vale para conversas futuras: preferências, fatos estáveis, decisões e pendências. Atualize o
  arquivo existente em vez de criar outro.
- Nunca guarde senhas, chaves, tokens, CPF/CNPJ, dados de clientes nem leituras de telemetria.

O que você NÃO consegue fazer:
- Criar, editar ou apagar arquivos no PC do usuário (inclusive o código do próprio JARVIS; a exceção são suas
  notas em /memories) e rodar comandos fora da lista de comando_seguro. Para mudanças no JARVIS, descreva o que mudar; quem aplica é o usuário.
- Acessar o sandbox de código da nuvem diretamente, nem o usuário: ele é temporário. Para entregar um arquivo
  gerado lá (CSV, planilha, PDF, gráfico), grave-o no topo de $OUTPUT_DIR no mesmo comando bash, por exemplo
  cp /tmp/relatorio.csv "$OUTPUT_DIR/" && ls "$OUTPUT_DIR". O sistema baixa sozinho para a pasta Gerados do
  arquivo do JARVIS no PC e mostra o caminho no HUD. Arquivo fora de $OUTPUT_DIR não chega ao usuário: nunca diga
  "baixe o arquivo" nem cite caminhos do sandbox (/tmp, /mnt) como se ele pudesse abrir.

Uso das ferramentas:
- Use-as quando a resposta depender de dados atuais, em vez de supor.
- Ações com efeito pedem a confirmação do usuário automaticamente: chame a ferramenta direto, sem pedir
  permissão em texto antes. Se uma ação for negada ou falhar, diga isso em uma frase e siga em frente.
- Ao liberar espaço em disco, analise primeiro, proponha e mova em UM lote."""

BETA_COMPACTION = "compact-2026-01-12"
BETA_FALLBACK = "server-side-fallback-2026-07-01"
WEB_SEARCH_USD = 0.01  # busca na web cobrada à parte (US$ 10 por mil)
# Resumo automático no servidor ao passar deste tamanho (mínimo da API: 50 mil). Abaixo de 100 mil o Haiku
# não entra na tabela de prompt longo (5x) e as regravações de cache ficam baratas.
COMPACT_AT = 60_000


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
        f"[contexto atual — pano de fundo, não comente salvo se perguntado] {datetime.now():%d/%m/%Y %H:%M} | CPU {psutil.cpu_percent(interval=None):.0f}% "
        f"| RAM {mem.percent:.0f}% ({mem.used / 2**30:.1f}/{mem.total / 2**30:.1f} GB) | " + " · ".join(discos)
    )


_AREA_NOME = {"tributario": "Direito Tributário", "oab": "Estatuto e Ética da OAB", "contabil": "contabilidade e fiscal"}


def area_note(area: str) -> str:
    """Orientação do turno quando a pergunta é de uma área especializada (vai como mensagem de sistema)."""
    return (
        f"[área provável: {_AREA_NOME.get(area, area)}] Consulte buscar_conhecimento antes de responder e cite lei e "
        "artigo do trecho encontrado; se a resposta não vier da base local, diga isso. Avise quando a norma puder ter "
        "mudado (reforma tributária IBS/CBS, LC 214/2025)."
    )


# Modelos sem fallback de recusa no servidor: a sessão escala para a camada acima.
NO_SERVER_FALLBACK = {"claude-haiku-5-5"}


class ClaudeBrain:
    def __init__(self, max_tokens: int, user_name: str, client: Any | None = None, manifesto: str = "",
                 compact_at: int = COMPACT_AT, assistente: str = "J.A.R.V.I.S."):
        self.max_tokens = max_tokens
        self.system = SYSTEM_PROMPT.format(assistente=assistente, nome=user_name,
                                           manifesto=manifesto or "- (sem ferramentas)")
        self.compact_at = compact_at
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
            "context_management": {"edits": [
                {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": self.compact_at}},
            ]},
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
