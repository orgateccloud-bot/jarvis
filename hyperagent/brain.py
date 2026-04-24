from openai import OpenAI
client = OpenAI()

NOME = os.getenv("JARVIS_NOME", "Senhor".
Responda sempre em português do Brasil, de forma clara, direta e inteligente.
Você pode controlar sistemas, sugerir ações e executar tarefas."""

def chatgpt(prompt: str, contexto: str = "") -> str:
    msg = f"{contexto}\n\n{prompt}" if contexto else prompt

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # rápido e barato
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": msg}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content.strip()