"""Portais oficiais via integração: Consulta CNPJ do SERPRO (Receita) pelo cliente que já existe em D:\\integracoes.

Premissas (credenciais não informadas):
- CNPJ: o módulo serpro_client.py é carregado do caminho em JARVIS_SERPRO_CLIENTE; as credenciais ficam nas variáveis
  que ele já usa (SERPRO_CONSUMER_KEY, SERPRO_CONSUMER_SECRET, SERPRO_AUDIT_SALT), nunca no código. Precisa do pacote
  requests. A própria integração avisa que o mapeamento do JSON v2 do CNPJ ainda não foi conferido no Swagger do
  contrato. A consulta é paga: o serviço só consulta no agendamento diário ou a pedido, nunca a cada atualização da tela.
- CPF: não é consultado (LGPD; não é preciso para o card).
- Certidões e e-CAC (situação fiscal, CND): exigem contrato do Integra Contador e e-CNPJ ou procuração. A interface está
  aqui, mas responde "não configurado"; nenhum endpoint é inventado.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from ..http import FonteIndisponivel
from .base import FonteCliente, documento


def carregar_serpro(caminho: Path) -> Any:
    """Importa serpro_client.py de fora do repositório (sem copiar o código de segurança dele)."""
    if not caminho.exists():
        raise FonteIndisponivel(f"cliente SERPRO não encontrado em {caminho}")
    spec = importlib.util.spec_from_file_location("serpro_client_jarvis", caminho)
    modulo = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(modulo)
    except ImportError as e:
        raise FonteIndisponivel(f"o cliente SERPRO precisa de um pacote ausente: {e.name}") from e
    return modulo


class PortaisClientes(FonteCliente):
    id, nome = "portais", "SERPRO · Consulta CNPJ (Receita)"

    def __init__(self, modulo: Any, env: dict[str, str] | None = None):
        self.modulo = modulo
        self.env = os.environ if env is None else env

    def _cliente(self):
        try:
            return self.modulo.SerproClient(consumer_key=self.env.get("SERPRO_CONSUMER_KEY"),
                                            consumer_secret=self.env.get("SERPRO_CONSUMER_SECRET"),
                                            audit_salt=self.env.get("SERPRO_AUDIT_SALT"))
        except self.modulo.SerproError as e:   # SerproConfigError: credencial ausente
            raise FonteIndisponivel(f"SERPRO sem credencial: {type(e).__name__}") from e

    def buscar(self, doc: str) -> dict[str, Any] | None:
        doc = documento(doc)
        if len(doc) != 14:
            return None                        # CPF: não consulta
        try:
            with self._cliente() as serpro:
                r = serpro.consultar_cnpj(doc)
        except self.modulo.SerproNaoEncontrado:
            return None
        except self.modulo.SerproError as e:   # rede, autenticação, limite: a mensagem não traz o documento
            raise FonteIndisponivel(f"SERPRO: {type(e).__name__}") from e
        d = r.dados
        campos = {"razao_social": d.get("razao_social"), "nome_fantasia": d.get("nome_fantasia"),
                  "situacao_cadastral": d.get("situacao_descricao"), "cnae_principal": d.get("cnae_principal"),
                  "uf_sede": (d.get("endereco") or {}).get("uf")}
        return {k: v for k, v in campos.items() if v}

    @staticmethod
    def certidoes(doc: str) -> list[dict[str, Any]]:
        raise FonteIndisponivel("certidões e e-CAC: não configurado (exige contrato Integra Contador e e-CNPJ)")
