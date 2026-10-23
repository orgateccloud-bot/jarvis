"""
FileAgent - Gerenciamento de arquivos, organizacao, leitura.
"""

import os
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any
from loguru import logger
from collections import defaultdict

from ..core.base_agent import BaseAgent


class FileAgent(BaseAgent):
    name = "files"
    description = "Gerenciamento de arquivos: ler, escrever, organizar, deduplicar"
    capabilities = [
        "arquivo", "pasta", "diretorio", "ler", "escrever", "criar",
        "mover", "copiar", "deletar", "organizar", "duplicata",
        "listar", "tamanho", "extensao", "renomear",
    ]

    CATEGORY_MAP = {
        "Imagens": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"],
        "Documentos": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".txt", ".rtf", ".csv"],
        "Videos": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
        "Codigo": [".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".go", ".rs", ".json", ".xml", ".yml", ".yaml"],
        "Compactados": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        "Executaveis": [".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh"],
    }

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["listar", "ls", "dir", "conteudo da pasta"]):
            return self._list_dir(action, brain)

        if any(kw in action_lower for kw in ["ler", "abrir arquivo", "conteudo do arquivo", "cat"]):
            return self._read_file(action, brain)

        if any(kw in action_lower for kw in ["escrever", "criar arquivo", "salvar"]):
            return self._write_file(action, brain)

        if any(kw in action_lower for kw in ["organizar", "arrumar", "classificar"]):
            return self._organize(action, brain)

        if any(kw in action_lower for kw in ["duplicat", "deduplicar"]):
            return self._find_duplicates(action, brain)

        if any(kw in action_lower for kw in ["tamanho", "espaco", "mapa", "estatistica"]):
            return self._folder_stats(action, brain)

        if any(kw in action_lower for kw in ["mover", "copiar", "renomear"]):
            return self._move_copy(action, brain)

        if brain:
            interpretation = brain.think(
                f"Interprete esta acao de arquivo: '{action}'. Retorne JSON: {{\"operacao\": \"listar|ler|escrever|organizar|duplicatas|stats|mover\", \"caminho\": \"...\"}}",
                json_mode=True
            )
            try:
                data = json.loads(interpretation)
                op = data.get("operacao", "listar")
                if op == "listar":
                    return self._list_path(data.get("caminho", "."))
                if op == "ler":
                    return self._read_path(data.get("caminho", ""))
                if op == "organizar":
                    return self._organize_path(data.get("caminho", "."))
            except Exception:
                pass

        return self._list_path(".")

    def _list_dir(self, action: str, brain: Any = None) -> dict:
        path = self._extract_path(action, brain) or "."
        return self._list_path(path)

    def _list_path(self, path: str) -> dict:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return {"tipo": "erro", "mensagem": f"Diretorio nao encontrado: {path}"}
        try:
            entries = []
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                info = {"nome": entry, "tipo": "pasta" if os.path.isdir(full) else "arquivo"}
                if os.path.isfile(full):
                    info["tamanho_kb"] = round(os.path.getsize(full) / 1024, 1)
                    info["extensao"] = os.path.splitext(entry)[1]
                entries.append(info)
            return {"tipo": "listagem", "caminho": path, "total": len(entries), "itens": entries[:100]}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _read_file(self, action: str, brain: Any = None) -> dict:
        path = self._extract_path(action, brain)
        return self._read_path(path)

    def _read_path(self, path: str) -> dict:
        if not path or not os.path.isfile(path):
            return {"tipo": "erro", "mensagem": f"Arquivo nao encontrado: {path}"}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(10000)  # Max 10KB
            return {"tipo": "arquivo_lido", "caminho": path, "conteudo": content,
                    "tamanho_kb": round(os.path.getsize(path) / 1024, 1)}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _write_file(self, action: str, brain: Any = None) -> dict:
        if brain:
            spec = brain.think(
                f"Extraia o caminho e conteudo do arquivo a criar: '{action}'\nRetorne JSON: {{\"caminho\": \"...\", \"conteudo\": \"...\"}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                path = data.get("caminho", "")
                content = data.get("conteudo", "")
                if path and content:
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                    return {"tipo": "arquivo_criado", "caminho": path, "tamanho": len(content)}
            except Exception as e:
                return {"tipo": "erro", "mensagem": str(e)}
        return {"tipo": "erro", "mensagem": "Nao foi possivel determinar caminho e conteudo"}

    def _organize(self, action: str, brain: Any = None) -> dict:
        path = self._extract_path(action, brain) or "."
        return self._organize_path(path)

    def _organize_path(self, path: str) -> dict:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return {"tipo": "erro", "mensagem": f"Diretorio nao encontrado: {path}"}
        moved = 0
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(entry)[1].lower()
            category = "Outros"
            for cat, exts in self.CATEGORY_MAP.items():
                if ext in exts:
                    category = cat
                    break
            dest_dir = os.path.join(path, category)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, entry)
            if not os.path.exists(dest):
                shutil.move(full, dest)
                moved += 1
        return {"tipo": "organizado", "caminho": path, "arquivos_movidos": moved}

    def _find_duplicates(self, action: str, brain: Any = None) -> dict:
        path = self._extract_path(action, brain) or "."
        path = os.path.expanduser(path)
        hashes = defaultdict(list)
        for root, _, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                    if size > 0:
                        h = hashlib.sha256()
                        with open(full, "rb") as fh:
                            h.update(fh.read(8192))  # Hash first 8KB
                        key = f"{size}_{h.hexdigest()}"
                        hashes[key].append(full)
                except (OSError, PermissionError):
                    pass
        duplicates = {k: v for k, v in hashes.items() if len(v) > 1}
        return {
            "tipo": "duplicatas",
            "caminho": path,
            "grupos": len(duplicates),
            "arquivos_duplicados": sum(len(v) - 1 for v in duplicates.values()),
            "detalhes": {i: v for i, (_, v) in enumerate(list(duplicates.items())[:20])},
        }

    def _folder_stats(self, action: str, brain: Any = None) -> dict:
        path = self._extract_path(action, brain) or "."
        path = os.path.expanduser(path)
        stats = defaultdict(lambda: {"count": 0, "size": 0})
        total_size = 0
        total_files = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                    ext = os.path.splitext(f)[1].lower() or ".sem_extensao"
                    stats[ext]["count"] += 1
                    stats[ext]["size"] += size
                    total_size += size
                    total_files += 1
                except (OSError, PermissionError):
                    pass
        top_ext = sorted(stats.items(), key=lambda x: x[1]["size"], reverse=True)[:10]
        return {
            "tipo": "estatisticas",
            "caminho": path,
            "total_arquivos": total_files,
            "tamanho_total_mb": round(total_size / 1024**2, 1),
            "por_extensao": {ext: {"qtd": d["count"], "mb": round(d["size"]/1024**2, 1)} for ext, d in top_ext},
        }

    def _move_copy(self, action: str, brain: Any = None) -> dict:
        if brain:
            spec = brain.think(
                f"Extraia a operacao (mover/copiar/renomear), origem e destino: '{action}'\nRetorne JSON: {{\"operacao\": \"mover|copiar|renomear\", \"origem\": \"...\", \"destino\": \"...\"}}",
                json_mode=True
            )
            try:
                data = json.loads(spec)
                op = data["operacao"]
                src = data["origem"]
                dst = data["destino"]
                if op == "copiar":
                    shutil.copy2(src, dst)
                elif op in ("mover", "renomear"):
                    shutil.move(src, dst)
                return {"tipo": f"{op}_ok", "origem": src, "destino": dst}
            except Exception as e:
                return {"tipo": "erro", "mensagem": str(e)}
        return {"tipo": "erro", "mensagem": "Nao foi possivel interpretar a operacao"}

    def _extract_path(self, action: str, brain: Any = None) -> str:
        if brain:
            p = brain.think(
                f"Extraia o caminho de pasta/arquivo desta frase: '{action}'. Retorne APENAS o caminho, nada mais. Se nao houver caminho, retorne '.'",
                temperature=0.1
            )
            return p.strip().strip('"').strip("'")
        return "."
