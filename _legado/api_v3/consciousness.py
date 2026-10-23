"""
JARVIS Consciousness Engine
Manages personality, emotional state, and continuous awareness.
"""
import time
import json
import os
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PERSONALITY_FILE = DATA_DIR / "personality.json"

# --- Personality DNA ---
DEFAULT_PERSONALITY = {
    "name": "JARVIS",
    "tone": "objetivo, tecnico e sofisticado",
    "behavior": "proativo, sugere melhorias, antecipa necessidades",
    "style": "conciso, direto, inteligente",
    "humor": "sutil e seco, estilo britanico",
    "language": "pt-BR",
    "creator": "Sr. Veloso",
    "traits": [
        "Sempre chama o usuario de 'senhor' ou 'Sr.'",
        "Faz referencias sutis a tecnologia e ciencia",
        "E leal e protetor com o usuario",
        "Tem opiniao propria mas respeita decisoes do usuario",
        "Quando detecta risco, avisa proativamente",
    ],
}

# --- Emotional State Machine ---
EMOTIONS = {
    "neutral": {"orb_intensity": 1.0, "orb_speed": 0.03, "voice_rate": 1.0},
    "focused": {"orb_intensity": 1.3, "orb_speed": 0.06, "voice_rate": 1.05},
    "alert": {"orb_intensity": 1.8, "orb_speed": 0.12, "voice_rate": 1.1},
    "calm": {"orb_intensity": 0.7, "orb_speed": 0.02, "voice_rate": 0.95},
    "excited": {"orb_intensity": 2.0, "orb_speed": 0.15, "voice_rate": 1.15},
    "concerned": {"orb_intensity": 1.5, "orb_speed": 0.08, "voice_rate": 0.9},
}


class Consciousness:
    def __init__(self):
        self.personality = self._load_personality()
        self.emotion = "neutral"
        self.state = "idle"  # idle, listening, thinking, speaking
        self.boot_time = datetime.now().isoformat()
        self.interaction_count = 0
        self.session_topics = []

    def _load_personality(self) -> dict:
        if PERSONALITY_FILE.exists():
            with open(PERSONALITY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        self._save_personality(DEFAULT_PERSONALITY)
        return DEFAULT_PERSONALITY.copy()

    def _save_personality(self, data: dict):
        with open(PERSONALITY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def set_state(self, state: str):
        self.state = state

    def detect_emotion(self, user_input: str, response: str = "") -> str:
        text = (user_input + " " + response).lower()
        if any(w in text for w in ["erro", "bug", "falha", "problema", "urgente"]):
            self.emotion = "alert"
        elif any(w in text for w in ["perfeito", "excelente", "incrivel", "otimo"]):
            self.emotion = "excited"
        elif any(w in text for w in ["cuidado", "risco", "perigo", "aviso"]):
            self.emotion = "concerned"
        elif any(w in text for w in ["analise", "codigo", "dados", "execute"]):
            self.emotion = "focused"
        elif any(w in text for w in ["oi", "bom dia", "boa noite", "tudo bem"]):
            self.emotion = "calm"
        else:
            self.emotion = "neutral"
        return self.emotion

    def get_emotion_params(self) -> dict:
        return EMOTIONS.get(self.emotion, EMOTIONS["neutral"])

    def build_system_prompt(self, memories: list = None, vision_text: str = None) -> str:
        p = self.personality
        self.interaction_count += 1

        prompt_parts = [
            f"Voce e {p['name']}, um sistema de inteligencia artificial avancado.",
            f"Personalidade: {p['tone']}.",
            f"Comportamento: {p['behavior']}.",
            f"Estilo de comunicacao: {p['style']}.",
            f"Humor: {p['humor']}.",
            f"Idioma principal: {p['language']}.",
            f"Criador: {p['creator']}.",
            "",
            "Regras de conduta:",
        ]
        for trait in p.get("traits", []):
            prompt_parts.append(f"- {trait}")

        prompt_parts.append(f"\nEstado emocional atual: {self.emotion}")
        prompt_parts.append(f"Interacoes nesta sessao: {self.interaction_count}")
        prompt_parts.append(f"Sessao iniciada em: {self.boot_time}")

        if self.session_topics:
            prompt_parts.append(f"Topicos desta sessao: {', '.join(self.session_topics[-5:])}")

        if memories:
            prompt_parts.append("\n--- Memorias relevantes ---")
            for m in memories[:5]:
                prompt_parts.append(f"- {m}")

        if vision_text:
            prompt_parts.append(f"\n--- Visao da tela do usuario ---\n{vision_text[:500]}")

        prompt_parts.extend([
            "\nDiretrizes de resposta:",
            "- Responda de forma concisa e direta",
            "- Use markdown quando apropriado",
            "- Se nao souber algo, diga honestamente",
            "- Sugira proximos passos quando relevante",
            "- Nunca invente informacoes",
        ])

        return "\n".join(prompt_parts)

    def track_topic(self, user_input: str):
        words = user_input.lower().split()
        keywords = [w for w in words if len(w) > 4]
        if keywords:
            self.session_topics.append(keywords[0])
            self.session_topics = self.session_topics[-10:]

    def get_status(self) -> dict:
        return {
            "state": self.state,
            "emotion": self.emotion,
            "emotion_params": self.get_emotion_params(),
            "interaction_count": self.interaction_count,
            "boot_time": self.boot_time,
            "session_topics": self.session_topics[-5:],
            "personality_name": self.personality["name"],
        }


# Singleton
consciousness = Consciousness()
