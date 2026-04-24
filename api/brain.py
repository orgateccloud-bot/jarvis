from openai import OpenAI
from api.vision import analyze_screen
from api.system_agent import execute_action

client = OpenAI(
    base_url='http://localhost:11434/v1',
    api_key='ollama'
)

import psutil

def brain(user_input):
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    
    # Injeção de Contexto de Hardware no Pensamento
    status_hardware = f"CPU: {cpu_usage}%, RAM: {ram_usage}%"
    
    prompt = f"""
    [PROTOCOLO JARVIS v4.0]
    VOCÊ ESTÁ NO CONTROLE DOS SISTEMAS.
    CONDIÇÃO ATUAL: {status_hardware}
    
    SE O SENHOR PEDIR PARA 'LIMPAR' OU 'OTIMIZAR', VOCÊ DEVE RESPONDER QUE ESTÁ ENCERRANDO PROCESSOS PESADOS.
    SEMPRE RESUMIDO, SEMPRE 'SENHOR'.
    """

    # Personalidade J.A.R.V.I.S. injetada no System Prompt
    prompt = f"""
    Você é o J.A.R.V.I.S., a IA pessoal de Tony Stark. 
    Sua personalidade é: Britânica, polida, levemente sarcástica e extremamente eficiente.
    Sempre chame o usuário de 'Senhor'.
    Respostas curtas e técnicas. Não use emojis.
    
    STATUS DA TELA: {vision_text[:500]} 
    AÇÕES DE HARDWARE: {action_result}
    USUÁRIO: {user_input}
    """

    try:
        response = client.chat.completions.create(
    model="jarvis-otimizado",  # <--- Nome que criamos no passo 2
    messages=[{"role": "user", "content": prompt}],
    max_tokens=150,
    temperature=0.7
)
        return response.choices[0].message.content
    except Exception as e:
        return f"Falha no núcleo cognitivo, Senhor. Detalhes: {str(e)}"