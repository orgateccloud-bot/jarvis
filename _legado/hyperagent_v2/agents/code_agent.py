"""
CodeAgent - Gerar, analisar, executar e depurar codigo.
"""

import os
import json
import subprocess
import tempfile
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    description = "Gerar, analisar, executar e depurar codigo"
    capabilities = [
        "codigo", "code", "python", "javascript", "script",
        "programar", "funcao", "classe", "bug", "erro",
        "executar codigo", "rodar script", "gerar", "refatorar",
        "explicar codigo", "depurar", "debug",
    ]

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["executar", "rodar", "run"]):
            return self._execute_code(action, brain)

        if any(kw in action_lower for kw in ["gerar", "criar", "escrever", "programar", "faca um"]):
            return self._generate_code(action, brain)

        if any(kw in action_lower for kw in ["explicar", "analisar", "o que faz"]):
            return self._explain_code(action, brain)

        if any(kw in action_lower for kw in ["bug", "erro", "depurar", "debug", "consertar", "fix"]):
            return self._debug_code(action, brain)

        # Default: gerar
        return self._generate_code(action, brain)

    def _generate_code(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario para gerar codigo"}

        code = brain.think(
            f"""Gere codigo Python para: {action}

REGRAS:
- Codigo limpo, funcional e bem comentado
- Use type hints
- Inclua docstring
- Se for um script completo, inclua if __name__ == '__main__'
- Retorne APENAS o codigo, sem markdown, sem ```""",
            system_override="Voce e um programador Python expert. Gere codigo limpo, eficiente e funcional."
        )
        # Remove markdown code blocks se houver
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return {"tipo": "codigo_gerado", "linguagem": "python", "codigo": code}

    def _execute_code(self, action: str, brain: Any = None) -> dict:
        # Extrai ou gera o codigo
        code = None
        if brain:
            spec = brain.think(
                f"Extraia o codigo a executar desta instrucao: '{action}'\nSe nao houver codigo explicito, gere o codigo Python para cumprir a tarefa.\nRetorne APENAS o codigo Python.",
                system_override="Voce e um programador Python. Retorne APENAS codigo executavel."
            )
            code = spec.strip()
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        if not code:
            return {"tipo": "erro", "mensagem": "Nenhum codigo para executar"}

        # Executa em arquivo temporario por seguranca
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name

            result = subprocess.run(
                ["python", tmp_path],
                capture_output=True, text=True, timeout=30,
                cwd=tempfile.gettempdir()
            )
            return {
                "tipo": "codigo_executado",
                "codigo": code[:1000],
                "stdout": result.stdout[:2000] if result.stdout else "",
                "stderr": result.stderr[:1000] if result.stderr else "",
                "exit_code": result.returncode,
                "sucesso": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"tipo": "timeout", "mensagem": "Codigo excedeu 30 segundos"}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _explain_code(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario"}
        explanation = brain.think(
            f"Explique este codigo/conceito de forma clara e didatica:\n{action}",
            system_override="Voce e um professor de programacao. Explique de forma clara, com exemplos."
        )
        return {"tipo": "explicacao", "conteudo": explanation}

    def _debug_code(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario"}
        fix = brain.think(
            f"""Analise este codigo/erro e forneca a correcao:

{action}

Retorne JSON:
{{
  "problema": "descricao do problema",
  "causa": "causa raiz",
  "solucao": "codigo corrigido",
  "explicacao": "porque isso corrige"
}}""",
            json_mode=True,
            system_override="Voce e um debugger expert. Identifique bugs e forneca correcoes."
        )
        try:
            return {"tipo": "debug", **json.loads(fix)}
        except json.JSONDecodeError:
            return {"tipo": "debug", "analise": fix}
