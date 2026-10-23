"""
JARVIS HyperAgent - Brain (LLM Interface)
Motor de IA que alimenta todas as decisoes do orquestrador.
Suporta Ollama (local) e Anthropic Claude (cloud) com fallback automatico.
"""

import os
import json
import time
from typing import Optional
from loguru import logger

# Tenta importar os providers
try:
    import ollama as ollama_client
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class Brain:
    """Motor de IA do JARVIS - abstrai o provider LLM."""

    SYSTEM_PROMPT = """Voce e JARVIS, um HyperAgent — orquestrador central de inteligencia artificial.
Voce COMANDA sub-agentes especializados para executar tarefas complexas.
Voce DECOMPOE tarefas em passos, DELEGA para o agente certo e COORDENA a execucao.

Sub-agentes disponiveis:
- system: controle do PC (processos, hardware, apps, comandos)
- web: pesquisa na internet, scraping, chamadas a APIs externas
- files: gerenciamento de arquivos, organizacao, deduplicacao, leitura
- code: gerar, analisar, executar e depurar codigo
- memory: historico de conversas, preferencias do usuario, aprendizado
- data: analise de dados, relatorios, graficos, BI
- plugin: integracoes externas (n8n, WhatsApp, webhooks)

REGRAS:
1. Sempre responda em portugues do Brasil
2. Seja direto, inteligente e proativo
3. Ao receber uma tarefa complexa, decomponha em etapas e delegue
4. Retorne SEMPRE JSON valido quando solicitado
5. Quando nao souber algo, diga honestamente e sugira alternativas"""

    def __init__(self):
        self.provider = self._detect_provider()
        self.model = self._detect_model()
        self.history: list[dict] = []
        self.max_history = 20
        logger.info(f"Brain inicializado: provider={self.provider}, model={self.model}")

    def _detect_provider(self) -> str:
        if os.getenv("ANTHROPIC_API_KEY") and HAS_ANTHROPIC:
            return "anthropic"
        if HAS_OLLAMA:
            try:
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                # Quick check if Ollama is running
                import requests
                requests.get(f"{ollama_host}/api/tags", timeout=10)
                return "ollama"
            except Exception:
                pass
        if HAS_ANTHROPIC and os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "none"

    def _detect_model(self) -> str:
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        if self.provider == "ollama":
            # Detecta melhor modelo disponivel no Ollama
            preferred = os.getenv("OLLAMA_MODEL", "")
            if preferred:
                return preferred
            try:
                import requests as _req
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                tags = _req.get(f"{ollama_host}/api/tags", timeout=5).json()
                models = [m["name"] for m in tags.get("models", [])]
                # Prefere gemma3 do menor ao maior (cabe na RAM)
                for candidate in ["gemma3:4b", "gemma3:12b", "gemma3:27b"]:
                    if candidate in models:
                        return candidate
                return models[0] if models else "gemma3:12b"
            except Exception:
                return "gemma3:12b"
        return "none"

    def think(self, prompt: str, context: str = "", json_mode: bool = False,
              system_override: Optional[str] = None, temperature: float = 0.3) -> str:
        """Envia prompt para o LLM e retorna resposta."""
        system = system_override or self.SYSTEM_PROMPT
        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        if json_mode:
            full_prompt += "\n\nRETORNE APENAS JSON VALIDO, sem markdown, sem explicacao."

        self.history.append({"role": "user", "content": full_prompt})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history:]

        for attempt in range(3):
            try:
                if self.provider == "anthropic":
                    result = self._call_anthropic(system, temperature)
                elif self.provider == "ollama":
                    result = self._call_ollama(system, temperature)
                else:
                    result = "Erro: Nenhum provider de IA configurado. Configure ANTHROPIC_API_KEY ou instale Ollama."

                self.history.append({"role": "assistant", "content": result})
                return result

            except Exception as e:
                logger.warning(f"Brain tentativa {attempt+1} falhou: {e}")
                if "429" in str(e) or "rate" in str(e).lower():
                    time.sleep(5 * (attempt + 1))
                elif attempt == 2:
                    raise
                else:
                    time.sleep(1)

        return "Erro: Todas as tentativas falharam."

    def _call_anthropic(self, system: str, temperature: float) -> str:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        messages = [{"role": m["role"], "content": m["content"]} for m in self.history]
        resp = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            temperature=temperature,
            messages=messages,
        )
        return resp.content[0].text.strip()

    def _call_ollama(self, system: str, temperature: float) -> str:
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history)
        resp = ollama_client.chat(
            model=self.model,
            messages=messages,
            options={"temperature": temperature},
        )
        return resp["message"]["content"].strip()

    def plan(self, task: str, available_agents: list[str]) -> list[dict]:
        """Decompoe uma tarefa em passos delegados a sub-agentes."""
        prompt = f"""Decomponha esta tarefa em passos executaveis:

TAREFA: {task}

AGENTES DISPONIVEIS: {', '.join(available_agents)}

Retorne JSON com esta estrutura:
{{
  "plano": [
    {{"passo": 1, "agente": "nome_agente", "acao": "descricao da acao", "depende_de": []}},
    {{"passo": 2, "agente": "nome_agente", "acao": "descricao", "depende_de": [1]}}
  ],
  "explicacao": "resumo do plano"
}}"""
        result = self.think(prompt, json_mode=True)
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # Tenta extrair JSON de dentro de markdown
            import re
            match = re.search(r'\{[\s\S]*\}', result)
            if match:
                return json.loads(match.group())
            return {"plano": [{"passo": 1, "agente": "system", "acao": task, "depende_de": []}],
                    "explicacao": "Execucao direta (falha no planejamento)"}

    def route(self, task: str, available_agents: list[str]) -> str:
        """Decide rapidamente qual agente deve atender uma tarefa simples."""
        prompt = f"""Qual agente deve executar esta tarefa?

TAREFA: {task}
AGENTES: {', '.join(available_agents)}

Retorne APENAS o nome do agente (uma palavra), nada mais."""
        result = self.think(prompt, temperature=0.1)
        agent = result.strip().lower().replace('"', '').replace("'", "")
        if agent in available_agents:
            return agent
        # Fallback: tenta encontrar no texto
        for a in available_agents:
            if a in result.lower():
                return a
        return available_agents[0]
