import os

# Cria a pasta api
os.makedirs("api", exist_ok=True)

# 1. memory.py
with open("api/memory.py", "w", encoding="utf-8") as f:
    f.write('''import os
import chromadb
from datetime import datetime

os.makedirs("data/db", exist_ok=True)
client = chromadb.PersistentClient(path="data/db")
collection = client.get_or_create_collection("jarvis_consciousness")

def save_memory(user_input, ai_response):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory_text = f"[{timestamp}] Usuário: {user_input} -> JARVIS: {ai_response}"
    collection.add(
        documents=[memory_text],
        ids=[str(datetime.now().timestamp())],
        metadatas=[{"time": timestamp}]
    )

def recall_memory(query):
    results = collection.query(query_texts=[query], n_results=5)
    if results["documents"] and results["documents"][0]:
        return "\\n".join(results["documents"][0])
    return "Nenhuma memória relevante."
''')

# 2. vision.py
with open("api/vision.py", "w", encoding="utf-8") as f:
    f.write('''import mss
import pytesseract
import numpy as np
import cv2

pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

def capture_screen():
    with mss.mss() as sct:
        screen = sct.grab(sct.monitors[1])
        img = np.array(screen)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

def analyze_screen():
    try:
        img = capture_screen()
        gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray_img, lang='por+eng')
        clean_text = text.strip()[:1500]
        return clean_text if clean_text else "O ecrã parece estar vazio."
    except Exception as e:
        return f"Erro na visão: {str(e)}"
''')

# 3. system_agent.py
with open("api/system_agent.py", "w", encoding="utf-8") as f:
    f.write('''import os

def execute_action(action):
    action = action.lower()
    if "abrir chrome" in action:
        os.system("start chrome")
        return "Chrome iniciado no Windows."
    if "abrir bloco de notas" in action:
        os.system("notepad")
        return "Bloco de notas aberto."
    return "Nenhuma ação de sistema executada."
''')

# 4. brain.py
with open("api/brain.py", "w", encoding="utf-8") as f:
    f.write('''import os
from openai import OpenAI
from api.memory import recall_memory, save_memory
from api.vision import analyze_screen
from api.system_agent import execute_action
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

def brain(user_input):
    memory = recall_memory(user_input)
    vision = analyze_screen()
    
    prompt = f"""
    Você é um assistente de IA avançado estilo JARVIS com consciência e visão.
    Personalidade: Objetivo, técnico, proativo e direto.

    Memórias Relevantes:
    {memory}

    Conteúdo Atual do Ecrã (OCR):
    {vision}

    Entrada do Usuário:
    {user_input}

    Responda ao utilizador. Se ele pedir para abrir um programa (ex: chrome, bloco de notas), diga que vai abrir.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        ai_response = response.choices[0].message.content
        
        save_memory(user_input, ai_response)
        
        if "abrir chrome" in user_input.lower():
            execute_action("abrir chrome")
        elif "bloco de notas" in user_input.lower():
            execute_action("abrir bloco de notas")

        return ai_response
    except Exception as e:
        return f"Erro no cérebro: {str(e)}"
''')

# 5. server.py
with open("api/server.py", "w", encoding="utf-8") as f:
    f.write('''from fastapi import FastAPI
from pydantic import BaseModel
from api.brain import brain
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class JarvisRequest(BaseModel):
    message: str

@app.post("/jarvis")
async def jarvis_endpoint(data: JarvisRequest):
    return {"response": brain(data.message)}
''')

# 6. .env
with open(".env", "w", encoding="utf-8") as f:
    f.write("OPENAI_API_KEY=sk-sua-chave-aqui-123456\\n")

print("\\n✅ Tudo gerado com sucesso!")
