import requests
import os

N8N_URL = os.getenv("N8N_WEBHOOK_URL")

def trigger_workflow(endpoint, payload=None):
    url = f"{N8N_URL}/webhook/{endpoint}"

    try:
        response = requests.post(url, json=payload or {})
        return response.json()
    except Exception as e:
        return {"error": str(e)}