"""
WebAgent - Pesquisa, scraping e APIs externas.
"""

import re
import json
import requests
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent


class WebAgent(BaseAgent):
    name = "web"
    description = "Pesquisa na internet, scraping, chamadas a APIs"
    capabilities = [
        "pesquisar", "buscar", "google", "internet", "web",
        "site", "url", "api", "http", "download", "scraping",
        "noticias", "clima", "cotacao", "dolar",
    ]

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["pesquisar", "buscar", "procurar", "google", "search"]):
            query = self._extract_query(action, brain)
            results = self._search(query)
            analysis = ""
            if brain and results.get("resultados"):
                analysis = brain.think(
                    f"Resuma os resultados de busca por '{query}' de forma clara:\n{json.dumps(results['resultados'], ensure_ascii=False)}"
                )
            results["analise"] = analysis
            return results

        if any(kw in action_lower for kw in ["clima", "tempo", "temperatura", "previsao"]):
            return self._weather(action, brain)

        if any(kw in action_lower for kw in ["cotacao", "dolar", "euro", "bitcoin", "cambio"]):
            return self._exchange_rates()

        if any(kw in action_lower for kw in ["http", "api", "get", "post", "url", "fetch"]):
            return self._api_call(action, brain)

        # Default: pesquisa
        return self._search(action)

    def _extract_query(self, action: str, brain: Any = None) -> str:
        if brain:
            q = brain.think(
                f"Extraia a query de busca desta frase: '{action}'. Retorne APENAS a query.",
                temperature=0.1
            )
            return q.strip().strip('"').strip("'")
        # Remove palavras-chave comuns
        for kw in ["pesquisar", "buscar", "procurar", "pesquise", "busque"]:
            action = re.sub(rf'\b{kw}\b', '', action, flags=re.IGNORECASE)
        return action.strip()

    def _search(self, query: str) -> dict:
        try:
            url = f"https://duckduckgo.com/html/?q={requests.utils.quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, headers=headers, timeout=15)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            results = []
            for i, (title, snippet) in enumerate(zip(titles[:5], snippets[:5])):
                results.append({
                    "posicao": i + 1,
                    "titulo": re.sub(r'<[^>]+>', '', title).strip(),
                    "resumo": re.sub(r'<[^>]+>', '', snippet).strip(),
                })
            return {"tipo": "pesquisa", "query": query, "resultados": results, "total": len(results)}
        except Exception as e:
            return {"tipo": "erro", "mensagem": f"Falha na pesquisa: {e}"}

    def _weather(self, action: str, brain: Any = None) -> dict:
        try:
            city = "Sao Paulo"
            if brain:
                city = brain.think(
                    f"Extraia o nome da cidade desta frase: '{action}'. Se nao houver cidade, retorne 'Sao Paulo'. APENAS o nome.",
                    temperature=0.1
                ).strip().strip('"')

            url = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
            r = requests.get(url, timeout=10)
            data = r.json()
            current = data.get("current_condition", [{}])[0]
            return {
                "tipo": "clima",
                "cidade": city,
                "temperatura_c": current.get("temp_C"),
                "sensacao_c": current.get("FeelsLikeC"),
                "umidade": current.get("humidity"),
                "descricao": current.get("weatherDesc", [{}])[0].get("value", ""),
                "vento_kmh": current.get("windspeedKmph"),
            }
        except Exception as e:
            return {"tipo": "erro", "mensagem": f"Falha ao buscar clima: {e}"}

    def _exchange_rates(self) -> dict:
        try:
            r = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL", timeout=10)
            data = r.json()
            rates = {}
            for key, val in data.items():
                rates[val["name"]] = {
                    "compra": val.get("bid"),
                    "venda": val.get("ask"),
                    "variacao": val.get("pctChange"),
                }
            return {"tipo": "cotacoes", "moedas": rates}
        except Exception as e:
            return {"tipo": "erro", "mensagem": f"Falha nas cotacoes: {e}"}

    def _api_call(self, action: str, brain: Any = None) -> dict:
        if brain:
            spec = brain.think(
                f"Extraia da frase o metodo HTTP, URL e body (se houver): '{action}'\nRetorne JSON: {{\"method\": \"GET\", \"url\": \"...\", \"body\": null}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                method = data.get("method", "GET").upper()
                url = data.get("url", "")
                body = data.get("body")
                if not url:
                    return {"tipo": "erro", "mensagem": "URL nao identificada"}

                if method == "GET":
                    r = requests.get(url, timeout=15)
                elif method == "POST":
                    r = requests.post(url, json=body, timeout=15)
                else:
                    r = requests.request(method, url, json=body, timeout=15)

                return {
                    "tipo": "api_response",
                    "status_code": r.status_code,
                    "body": r.text[:2000],
                }
            except json.JSONDecodeError:
                pass
        return {"tipo": "erro", "mensagem": "Nao foi possivel interpretar a chamada API"}
