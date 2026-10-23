"""
DataAgent - Analise de dados, relatorios, BI.
"""

import os
import json
import csv
from datetime import datetime
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent


class DataAgent(BaseAgent):
    name = "data"
    description = "Analise de dados, relatorios, graficos, BI"
    capabilities = [
        "dado", "dados", "analise", "relatorio", "csv",
        "excel", "grafico", "estatistica", "media", "soma",
        "tabela", "dashboard", "bi", "kpi", "metrica",
    ]

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["csv", "excel", "planilha"]):
            return self._analyze_file(action, brain)

        if any(kw in action_lower for kw in ["relatorio", "report"]):
            return self._generate_report(action, brain)

        if any(kw in action_lower for kw in ["json", "analisar dados"]):
            return self._analyze_json(action, brain)

        # Default: analise com IA
        return self._ai_analysis(action, brain)

    def _analyze_file(self, action: str, brain: Any = None) -> dict:
        """Analisa arquivo CSV/dados."""
        if brain:
            path = brain.think(
                f"Extraia o caminho do arquivo desta frase: '{action}'. APENAS o caminho.",
                temperature=0.1
            ).strip().strip('"')
        else:
            return {"tipo": "erro", "mensagem": "Caminho do arquivo nao especificado"}

        if not os.path.isfile(path):
            return {"tipo": "erro", "mensagem": f"Arquivo nao encontrado: {path}"}

        try:
            ext = os.path.splitext(path)[1].lower()

            if ext == ".csv":
                return self._analyze_csv(path, brain)
            elif ext == ".json":
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._analyze_data(data, path, brain)
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(5000)
                return self._ai_analysis(f"Analise estes dados do arquivo {path}:\n{content}", brain)

        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _analyze_csv(self, path: str, brain: Any = None) -> dict:
        rows = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for i, row in enumerate(reader):
                rows.append(row)
                if i >= 999:
                    break

        stats = {
            "arquivo": path,
            "colunas": headers,
            "total_linhas": len(rows),
            "amostra": rows[:5],
        }

        # Estatisticas numericas basicas
        for col in headers:
            values = []
            for row in rows:
                try:
                    values.append(float(row.get(col, "").replace(",", ".")))
                except (ValueError, AttributeError):
                    pass
            if values:
                stats[f"_{col}_stats"] = {
                    "min": min(values),
                    "max": max(values),
                    "media": round(sum(values) / len(values), 2),
                    "soma": round(sum(values), 2),
                    "count": len(values),
                }

        if brain:
            analysis = brain.think(
                f"Analise estes dados CSV e forneca insights:\n{json.dumps(stats, ensure_ascii=False, default=str)[:3000]}",
                system_override="Voce e um analista de dados. Forneca insights claros e acionaveis."
            )
            stats["analise_ia"] = analysis

        return {"tipo": "analise_csv", **stats}

    def _analyze_data(self, data: Any, source: str, brain: Any = None) -> dict:
        summary = {
            "fonte": source,
            "tipo_dados": type(data).__name__,
        }
        if isinstance(data, list):
            summary["total_registros"] = len(data)
            if data and isinstance(data[0], dict):
                summary["campos"] = list(data[0].keys())
                summary["amostra"] = data[:3]
        elif isinstance(data, dict):
            summary["chaves"] = list(data.keys())[:20]

        if brain:
            analysis = brain.think(
                f"Analise estes dados JSON:\n{json.dumps(summary, ensure_ascii=False, default=str)[:3000]}",
                system_override="Voce e um analista de dados. Forneca insights claros."
            )
            summary["analise_ia"] = analysis

        return {"tipo": "analise_json", **summary}

    def _analyze_json(self, action: str, brain: Any = None) -> dict:
        return self._analyze_file(action, brain)

    def _generate_report(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario para gerar relatorios"}

        report = brain.think(
            f"Gere um relatorio completo e profissional sobre: {action}",
            system_override="""Voce e um analista de negocios senior. Gere relatorios completos com:
- Titulo
- Sumario executivo
- Dados e metricas
- Analise
- Recomendacoes
- Conclusao
Formate de forma profissional."""
        )
        return {"tipo": "relatorio", "conteudo": report, "gerado_em": datetime.now().isoformat()}

    def _ai_analysis(self, action: str, brain: Any = None) -> dict:
        if not brain:
            return {"tipo": "erro", "mensagem": "Brain necessario para analise"}

        analysis = brain.think(
            f"Faca uma analise detalhada: {action}",
            system_override="Voce e um analista de dados expert. Forneca analises profundas com metricas e insights acionaveis."
        )
        return {"tipo": "analise", "conteudo": analysis}
