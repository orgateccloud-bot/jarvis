"""
PluginAgent - Integracoes externas: n8n, webhooks, WhatsApp, APIs de terceiros.
"""

import os
import json
import requests
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent


class PluginAgent(BaseAgent):
    name = "plugin"
    description = "Integracoes: n8n, WhatsApp, webhooks, servicos externos"
    capabilities = [
        "n8n", "webhook", "whatsapp", "integracao", "notificacao",
        "enviar", "mensagem", "workflow", "automacao", "telegram",
        "email", "slack", "api externa",
    ]

    def __init__(self):
        super().__init__()
        self.n8n_url = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678")
        self.n8n_user = os.getenv("N8N_USER", "admin")
        self.n8n_pass = os.getenv("N8N_PASSWORD", "")
        self.evolution_url = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
        self.evolution_key = os.getenv("EVOLUTION_API_KEY", "")

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["n8n", "workflow"]):
            return self._n8n_action(action, brain)

        if any(kw in action_lower for kw in ["whatsapp", "wpp", "zap"]):
            return self._whatsapp_action(action, brain)

        if any(kw in action_lower for kw in ["webhook", "notificacao", "notificar"]):
            return self._webhook(action, brain)

        if any(kw in action_lower for kw in ["email", "enviar email"]):
            return self._email_action(action, brain)

        return {"tipo": "plugins_disponiveis", "plugins": [
            "n8n (workflows)", "WhatsApp (Evolution API)",
            "Webhooks", "Email (via n8n)",
        ]}

    def _n8n_action(self, action: str, brain: Any = None) -> dict:
        action_lower = action.lower()

        if "status" in action_lower or "saude" in action_lower:
            return self._n8n_health()

        if "disparar" in action_lower or "trigger" in action_lower or "executar" in action_lower:
            return self._n8n_trigger(action, brain)

        if "listar" in action_lower or "workflows" in action_lower:
            return self._n8n_list_workflows()

        return self._n8n_health()

    def _n8n_health(self) -> dict:
        try:
            r = requests.get(f"{self.n8n_url}/healthz", timeout=5)
            return {"tipo": "n8n_status", "online": r.status_code == 200, "url": self.n8n_url}
        except Exception as e:
            return {"tipo": "n8n_status", "online": False, "erro": str(e)}

    def _n8n_list_workflows(self) -> dict:
        try:
            r = requests.get(
                f"{self.n8n_url}/api/v1/workflows",
                auth=(self.n8n_user, self.n8n_pass),
                timeout=10
            )
            if r.status_code == 200:
                workflows = r.json().get("data", [])
                return {
                    "tipo": "n8n_workflows",
                    "total": len(workflows),
                    "workflows": [{"id": w["id"], "nome": w["name"], "ativo": w.get("active", False)} for w in workflows],
                }
            return {"tipo": "erro", "status_code": r.status_code}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _n8n_trigger(self, action: str, brain: Any = None) -> dict:
        """Dispara um webhook no n8n."""
        payload = {"source": "jarvis_hyperagent", "action": action}
        if brain:
            spec = brain.think(
                f"Extraia o webhook path e payload desta frase: '{action}'\nRetorne JSON: {{\"path\": \"webhook-test\", \"payload\": {{}}}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                path = data.get("path", "webhook-test")
                payload.update(data.get("payload", {}))
            except Exception:
                path = "webhook-test"
        else:
            path = "webhook-test"

        try:
            r = requests.post(f"{self.n8n_url}/webhook/{path}", json=payload, timeout=10)
            return {"tipo": "n8n_trigger", "path": path, "status_code": r.status_code,
                    "resposta": r.text[:500]}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _whatsapp_action(self, action: str, brain: Any = None) -> dict:
        action_lower = action.lower()

        if "status" in action_lower:
            return self._whatsapp_status()

        if any(kw in action_lower for kw in ["enviar", "mandar", "send"]):
            return self._whatsapp_send(action, brain)

        return self._whatsapp_status()

    def _whatsapp_status(self) -> dict:
        try:
            r = requests.get(
                f"{self.evolution_url}/instance/fetchInstances",
                headers={"apikey": self.evolution_key},
                timeout=5
            )
            if r.status_code == 200:
                instances = r.json()
                return {"tipo": "whatsapp_status", "instancias": instances}
            return {"tipo": "whatsapp_status", "online": False, "status_code": r.status_code}
        except Exception as e:
            return {"tipo": "whatsapp_status", "online": False, "erro": str(e)}

    def _whatsapp_send(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario para extrair destinatario e mensagem"}

        spec = brain.think(
            f"Extraia numero e mensagem: '{action}'\nRetorne JSON: {{\"numero\": \"5511999999999\", \"mensagem\": \"...\"}}",
            json_mode=True
        )
        try:
            data = json.loads(spec)
            numero = data["numero"]
            mensagem = data["mensagem"]
            r = requests.post(
                f"{self.evolution_url}/message/sendText/ORGATEC",
                headers={"apikey": self.evolution_key, "Content-Type": "application/json"},
                json={"number": numero, "text": mensagem},
                timeout=10
            )
            return {"tipo": "whatsapp_enviado", "numero": numero, "status": r.status_code}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _webhook(self, action: str, brain: Any = None) -> dict:
        if brain:
            spec = brain.think(
                f"Extraia URL e payload do webhook: '{action}'\nRetorne JSON: {{\"url\": \"...\", \"payload\": {{}}}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                url = data["url"]
                payload = data.get("payload", {})
                r = requests.post(url, json=payload, timeout=10)
                return {"tipo": "webhook_enviado", "url": url, "status": r.status_code}
            except Exception as e:
                return {"tipo": "erro", "mensagem": str(e)}
        return {"tipo": "erro", "mensagem": "URL do webhook nao especificada"}

    def _email_action(self, action: str, brain: Any = None) -> dict:
        # Email via n8n workflow
        return self._n8n_trigger(f"enviar email: {action}", brain)
