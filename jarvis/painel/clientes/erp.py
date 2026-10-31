"""API do sistema contábil/ERP: REST genérico, desligado até ser configurado.

Premissa: o ERP do escritório não foi informado. A integração fica isolada: endereço em JARVIS_ERP_URL (https), token
em JARVIS_ERP_TOKEN (vai no cabeçalho Authorization: Bearer, nunca no código nem no log) e o formato em
config/clientes_fontes.json ("erp": caminhos de busca e de lista e o mapa campo canônico → caminho no JSON do ERP).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from ..http import Fetch, FonteIndisponivel
from .base import FonteCliente, documento


def _pegar(obj: Any, caminho: str) -> Any:
    """"contato.email" → obj["contato"]["email"]; None se faltar algum nível."""
    for parte in caminho.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(parte)
    return obj


class ErpClientes(FonteCliente):
    id, nome = "erp", "ERP (API)"

    def __init__(self, url: str, token: str, formato: dict[str, Any], fetch: Fetch):
        if not url.startswith("https://"):
            raise ValueError("JARVIS_ERP_URL precisa ser https")
        self.url, self.formato = url.rstrip("/"), formato
        self._fetch = fetch
        self._cabecalho = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.nome = formato.get("nome", self.nome)

    def _json(self, caminho: str) -> Any:
        try:
            return json.loads(self._fetch(self.url + caminho, headers=self._cabecalho))
        except json.JSONDecodeError as e:
            raise FonteIndisponivel("o ERP não respondeu JSON") from e

    def _mapear(self, bruto: dict[str, Any]) -> dict[str, Any]:
        campos = {canon: _pegar(bruto, origem) for canon, origem in self.formato.get("campos", {}).items()}
        return {k: v for k, v in campos.items() if v not in (None, "", [], {})}

    def listar(self) -> list[dict[str, Any]]:
        caminho = self.formato.get("caminho_lista")
        if not caminho:
            return []
        dados = self._json(caminho)
        lista = _pegar(dados, self.formato["lista_chave"]) if self.formato.get("lista_chave") else dados
        doc_campo = self.formato.get("campo_documento", "documento")
        return [{"documento": documento(_pegar(x, doc_campo) or ""),
                 "razao_social": _pegar(x, self.formato.get("campos", {}).get("razao_social", "razao_social")) or ""}
                for x in (lista or []) if isinstance(x, dict) and _pegar(x, doc_campo)]

    def buscar(self, doc: str) -> dict[str, Any] | None:
        dados = self._json(self.formato.get("caminho_busca", "/clientes/{documento}").format(
            documento=quote(documento(doc))))
        if isinstance(dados, list):
            dados = dados[0] if dados else None
        return self._mapear(dados) if isinstance(dados, dict) else None
