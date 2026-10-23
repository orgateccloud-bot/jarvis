"""
SystemAgent - Controle total do PC.
Processos, hardware, apps, comandos shell, monitoramento.
"""

import os
import subprocess
import psutil
from datetime import datetime
from typing import Any
from loguru import logger

from ..core.base_agent import BaseAgent


class SystemAgent(BaseAgent):
    name = "system"
    description = "Controle do PC: processos, hardware, apps, comandos"
    capabilities = [
        "cpu", "ram", "memoria", "disco", "processo", "hardware",
        "status", "sistema", "abrir", "programa", "executar", "comando",
        "matar", "fechar", "reiniciar", "desligar", "monitor",
    ]

    BLOCKED_COMMANDS = [
        "rm -rf /", "format c:", "del /f /s /q c:\\",
        ":(){ :|:& };:", "mkfs", "> /dev/sda",
    ]

    PROGRAMS = {
        "chrome": "chrome", "edge": "msedge", "notepad": "notepad",
        "calculadora": "calc", "explorer": "explorer", "word": "winword",
        "excel": "excel", "powerpoint": "powerpnt", "vscode": "code",
        "terminal": "wt", "cmd": "cmd", "paint": "mspaint",
        "task manager": "taskmgr", "gerenciador": "taskmgr",
    }

    def execute(self, action: str, brain: Any = None, **kwargs) -> dict:
        action_lower = action.lower()

        if any(kw in action_lower for kw in ["status", "cpu", "ram", "disco", "hardware", "sistema"]):
            return self._system_status()

        if any(kw in action_lower for kw in ["processo", "processos", "top"]):
            return self._top_processes()

        if any(kw in action_lower for kw in ["abrir", "iniciar", "executar programa", "abra"]):
            return self._open_program(action, brain)

        if any(kw in action_lower for kw in ["matar", "fechar", "encerrar processo", "kill"]):
            return self._kill_process(action, brain)

        if any(kw in action_lower for kw in ["executar", "comando", "rodar", "shell", "cmd"]):
            return self._execute_command(action, brain)

        # Fallback: usa Brain para interpretar
        if brain:
            interpretation = brain.think(
                f"O usuario pediu: {action}\nExtraia a intencao: status_sistema, abrir_programa, executar_comando, listar_processos ou matar_processo?\nRetorne JSON: {{\"intencao\": \"...\", \"parametro\": \"...\"}}",
                json_mode=True
            )
            try:
                import json
                data = json.loads(interpretation)
                intent = data.get("intencao", "")
                param = data.get("parametro", "")
                if "status" in intent:
                    return self._system_status()
                if "abrir" in intent:
                    return self._open_specific(param)
                if "comando" in intent or "executar" in intent:
                    return self._run_shell(param)
                if "processo" in intent or "matar" in intent:
                    return self._kill_by_name(param)
            except Exception:
                pass

        return self._system_status()

    def _system_status(self) -> dict:
        disk = psutil.disk_usage("/") if os.name != "nt" else psutil.disk_usage("C:\\")
        net = psutil.net_io_counters()
        return {
            "tipo": "status_sistema",
            "cpu_percent": psutil.cpu_percent(interval=1),
            "cpu_cores": psutil.cpu_count(),
            "ram_percent": psutil.virtual_memory().percent,
            "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 1),
            "ram_usada_gb": round(psutil.virtual_memory().used / 1024**3, 1),
            "disco_total_gb": round(disk.total / 1024**3, 1),
            "disco_livre_gb": round(disk.free / 1024**3, 1),
            "disco_percent": round(disk.percent, 1),
            "rede_enviado_mb": round(net.bytes_sent / 1024**2, 1),
            "rede_recebido_mb": round(net.bytes_recv / 1024**2, 1),
            "processos_ativos": len(psutil.pids()),
            "hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).strftime("%d/%m/%Y %H:%M"),
        }

    def _top_processes(self, top: int = 10) -> dict:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
        return {"tipo": "processos", "top": procs[:top]}

    def _open_program(self, action: str, brain: Any = None) -> dict:
        action_lower = action.lower()
        for name, cmd in self.PROGRAMS.items():
            if name in action_lower:
                return self._open_specific(cmd)

        if brain:
            result = brain.think(
                f"Extraia o nome do programa desta frase: '{action}'. Retorne APENAS o nome do executavel.",
                temperature=0.1
            )
            return self._open_specific(result.strip())

        return {"tipo": "erro", "mensagem": "Programa nao identificado"}

    def _open_specific(self, program: str) -> dict:
        cmd = self.PROGRAMS.get(program.lower(), program)
        try:
            subprocess.Popen(cmd, shell=True)
            return {"tipo": "programa_aberto", "programa": cmd, "sucesso": True}
        except Exception as e:
            return {"tipo": "erro", "mensagem": f"Falha ao abrir {cmd}: {e}"}

    def _execute_command(self, action: str, brain: Any = None) -> dict:
        if brain:
            cmd = brain.think(
                f"Extraia APENAS o comando shell desta frase: '{action}'. Retorne somente o comando, nada mais.",
                temperature=0.1
            )
        else:
            cmd = action
        return self._run_shell(cmd.strip())

    def _run_shell(self, cmd: str) -> dict:
        if any(b in cmd.lower() for b in self.BLOCKED_COMMANDS):
            return {"tipo": "bloqueado", "mensagem": f"Comando bloqueado por seguranca: {cmd}"}
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {
                "tipo": "comando_executado",
                "comando": cmd,
                "stdout": r.stdout[:2000] if r.stdout else "",
                "stderr": r.stderr[:500] if r.stderr else "",
                "exit_code": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"tipo": "timeout", "mensagem": f"Comando excedeu 30s: {cmd}"}
        except Exception as e:
            return {"tipo": "erro", "mensagem": str(e)}

    def _kill_process(self, action: str, brain: Any = None) -> dict:
        if brain:
            name = brain.think(
                f"Extraia o nome do processo a matar desta frase: '{action}'. Retorne APENAS o nome.",
                temperature=0.1
            )
        else:
            name = action
        return self._kill_by_name(name.strip())

    def _kill_by_name(self, name: str) -> dict:
        killed = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if name.lower() in proc.info["name"].lower():
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"tipo": "processo_morto", "nome": name, "total_mortos": killed}
