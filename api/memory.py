"""
JARVIS Memory System
Persistent vector memory using ChromaDB for long-term recall.
"""
import os
from datetime import datetime
from pathlib import Path

os.makedirs("data/db", exist_ok=True)

MEMORY_AVAILABLE = False
conversations = None
facts = None

try:
    import chromadb
    client = chromadb.PersistentClient(path="data/db")
    conversations = client.get_or_create_collection("conversations")
    facts = client.get_or_create_collection("facts")
    MEMORY_AVAILABLE = True
    print("[JARVIS] ChromaDB memory initialized")
except Exception as e:
    print(f"[JARVIS] ChromaDB unavailable: {e}. Running without persistent memory.")


def save_conversation(user_input: str, response: str):
    if not MEMORY_AVAILABLE:
        return
    try:
        ts = datetime.now().isoformat()
        doc = f"User: {user_input}\nJARVIS: {response}"
        conversations.add(
            documents=[doc],
            ids=[f"conv_{ts}"],
            metadatas=[{"timestamp": ts, "type": "conversation"}],
        )
    except Exception as e:
        print(f"[JARVIS] Memory save error: {e}")


def recall(query: str, n_results: int = 5) -> list:
    if not MEMORY_AVAILABLE:
        return []
    try:
        results = conversations.query(query_texts=[query], n_results=n_results)
        return results["documents"][0] if results["documents"] else []
    except Exception as e:
        print(f"[JARVIS] Memory recall error: {e}")
        return []


def save_fact(key: str, value: str):
    if not MEMORY_AVAILABLE:
        return
    try:
        facts.upsert(
            documents=[value],
            ids=[f"fact_{key}"],
            metadatas=[{"key": key, "timestamp": datetime.now().isoformat()}],
        )
    except Exception as e:
        print(f"[JARVIS] Fact save error: {e}")


def recall_facts(query: str, n_results: int = 3) -> list:
    if not MEMORY_AVAILABLE:
        return []
    try:
        results = facts.query(query_texts=[query], n_results=n_results)
        return results["documents"][0] if results["documents"] else []
    except Exception as e:
        print(f"[JARVIS] Fact recall error: {e}")
        return []


def get_memory_stats() -> dict:
    if not MEMORY_AVAILABLE:
        return {"available": False}
    try:
        return {
            "available": True,
            "conversations": conversations.count(),
            "facts": facts.count(),
        }
    except Exception:
        return {"available": False}


# Backward compatibility aliases
save_memory = save_conversation
recall_memory = recall
