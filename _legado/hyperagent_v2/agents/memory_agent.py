"""
MemoryAgent - Historico, preferencias, aprendizado persistente.
"""

import os
import json
from datetime import datetime
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "dados", "memory")


class MemoryAgent(BaseAgent):
    name = "memory"
    description = "Historico de conversas, preferencias, aprendizado"
    capabilities = [
        "lembrar", "memoria", "historico", "preferencia",
        "aprender", "salvar", "recordar", "contexto",
        "esquecer", "nota", "anotacao", "lembrete",
    ]

    def __init__(self):
        super().__init__()
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self.preferences = self._load("preferences.json", {})
        self.notes = self._load("notes.json", [])
        self.learned = self._load("learned.json", [])
        self.conversations = self._load("conversations.json", [])

    def _path(self, filename: str) -> str:
        return os.path.join(MEMORY_DIR, filename)

    def _load(self, filename: str, default: Any) -> Any:
        path = self._path(filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def _save(self, filename: str, data: Any):
        with open(self._path(filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["salvar nota", "anotar", "anota", "guardar"]):
            return self._save_note(action, brain)

        if any(kw in action_lower for kw in ["notas", "anotacoes", "listar notas"]):
            return self._list_notes()

        if any(kw in action_lower for kw in ["preferencia", "prefiro", "gosto", "configurar"]):
            return self._set_preference(action, brain)

        if any(kw in action_lower for kw in ["lembrar", "recordar", "recall", "buscar memoria"]):
            return self._recall(action, brain)

        if any(kw in action_lower for kw in ["aprender", "aprenda", "saiba que"]):
            return self._learn(action, brain)

        if any(kw in action_lower for kw in ["esquecer", "apagar", "limpar"]):
            return self._forget(action, brain)

        if any(kw in action_lower for kw in ["historico", "conversas"]):
            return self._get_history()

        # Salvar conversa por padrao
        self._log_conversation(action)
        return self._recall(action, brain)

    def _save_note(self, action: str, brain: Any = None) -> dict:
        content = action
        if brain:
            content = brain.think(
                f"Extraia apenas o conteudo da nota desta frase: '{action}'. Retorne APENAS a nota.",
                temperature=0.1
            ).strip()

        note = {
            "id": len(self.notes) + 1,
            "conteudo": content,
            "criado_em": datetime.now().isoformat(),
        }
        self.notes.append(note)
        self._save("notes.json", self.notes)
        return {"tipo": "nota_salva", "nota": note}

    def _list_notes(self) -> dict:
        return {"tipo": "notas", "total": len(self.notes), "notas": self.notes[-20:]}

    def _set_preference(self, action: str, brain: Any = None) -> dict:
        if brain:
            spec = brain.think(
                f"Extraia chave e valor da preferencia: '{action}'\nRetorne JSON: {{\"chave\": \"...\", \"valor\": \"...\"}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                key = data["chave"]
                value = data["valor"]
                self.preferences[key] = value
                self._save("preferences.json", self.preferences)
                return {"tipo": "preferencia_salva", "chave": key, "valor": value}
            except Exception:
                pass
        return {"tipo": "preferencias", "todas": self.preferences}

    def _recall(self, action: str, brain: Any = None) -> dict:
        """Busca na memoria por informacoes relevantes."""
        results = {
            "notas_relevantes": [],
            "aprendizados_relevantes": [],
            "preferencias": self.preferences,
        }

        search_terms = action.lower().split()

        for note in self.notes:
            if any(term in note["conteudo"].lower() for term in search_terms):
                results["notas_relevantes"].append(note)

        for item in self.learned:
            if any(term in item.get("conteudo", "").lower() for term in search_terms):
                results["aprendizados_relevantes"].append(item)

        return {"tipo": "memoria", **results}

    def _learn(self, action: str, brain: Any = None) -> dict:
        content = action
        if brain:
            content = brain.think(
                f"Extraia o fato/informacao a aprender: '{action}'. Retorne APENAS o fato.",
                temperature=0.1
            ).strip()

        item = {
            "id": len(self.learned) + 1,
            "conteudo": content,
            "aprendido_em": datetime.now().isoformat(),
        }
        self.learned.append(item)
        self._save("learned.json", self.learned)
        return {"tipo": "aprendido", "item": item}

    def _forget(self, action: str, brain: Any = None) -> dict:
        # Limpa notas ou aprendizados
        if "tudo" in action.lower() or "todas" in action.lower():
            self.notes = []
            self.learned = []
            self._save("notes.json", [])
            self._save("learned.json", [])
            return {"tipo": "esquecido", "mensagem": "Toda a memoria foi limpa"}
        return {"tipo": "info", "mensagem": "Especifique o que deseja esquecer ou diga 'esquecer tudo'"}

    def _log_conversation(self, message: str):
        self.conversations.append({
            "mensagem": message[:500],
            "timestamp": datetime.now().isoformat(),
        })
        if len(self.conversations) > 200:
            self.conversations = self.conversations[-200:]
        self._save("conversations.json", self.conversations)

    def _get_history(self) -> dict:
        return {"tipo": "historico", "total": len(self.conversations),
                "ultimas": self.conversations[-20:]}

    def get_context(self) -> str:
        """Retorna contexto persistente para o Brain usar."""
        parts = []
        if self.preferences:
            parts.append(f"Preferencias do usuario: {json.dumps(self.preferences, ensure_ascii=False)}")
        if self.learned:
            recent = self.learned[-5:]
            parts.append(f"Aprendizados recentes: {json.dumps(recent, ensure_ascii=False)}")
        return "\n".join(parts)
