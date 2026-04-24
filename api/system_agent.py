"""
JARVIS System Agent
Controls the operating system: apps, processes, system metrics.
"""
import os
import subprocess
import psutil
from datetime import datetime

APPS = {
    "chrome": "start chrome",
    "edge": "start msedge",
    "firefox": "start firefox",
    "notepad": "notepad",
    "bloco de notas": "notepad",
    "calculadora": "calc",
    "calculator": "calc",
    "vscode": "code",
    "terminal": "start wt",
    "explorer": "explorer",
    "explorador": "explorer",
    "paint": "mspaint",
    "word": "start winword",
    "excel": "start excel",
    "powershell": "start powershell",
    "cmd": "start cmd",
    "spotify": "start spotify:",
    "discord": "start discord:",
}

BLOCKED_COMMANDS = [
    "rm -rf /", "format c:", "del /f /s /q c:\\",
    ":(){ :|:& };:", "mkfs", "> /dev/sda",
    "shutdown", "restart", "taskkill /f /im explorer",
]


def get_system_status() -> dict:
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        net = psutil.net_io_counters()
        boot = datetime.fromtimestamp(psutil.boot_time())
        return {
            "cpu_percent": cpu,
            "ram_total_gb": round(mem.total / (1024**3), 1),
            "ram_used_gb": round(mem.used / (1024**3), 1),
            "ram_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "disk_used_gb": round(disk.used / (1024**3), 1),
            "disk_percent": round(disk.percent, 1),
            "net_sent_mb": round(net.bytes_sent / (1024**2), 1),
            "net_recv_mb": round(net.bytes_recv / (1024**2), 1),
            "process_count": len(list(psutil.process_iter())),
            "boot_time": boot.isoformat(),
            "uptime_hours": round((datetime.now() - boot).total_seconds() / 3600, 1),
        }
    except Exception as e:
        return {"error": str(e)}


def get_top_processes(limit: int = 10) -> list:
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            info = p.info
            if info["cpu_percent"] is not None:
                procs.append(info)
        procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
        return procs[:limit]
    except Exception:
        return []


def open_app(name: str) -> str:
    name_lower = name.lower().strip()
    if name_lower in APPS:
        try:
            subprocess.Popen(APPS[name_lower], shell=True)
            return f"Abrindo {name}"
        except Exception as e:
            return f"Erro ao abrir {name}: {e}"
    return f"App '{name}' nao permitido. Disponiveis: {', '.join(sorted(APPS.keys()))}"


def execute_command(cmd: str) -> str:
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in cmd.lower():
            return f"Comando bloqueado por seguranca: {cmd}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout or result.stderr or "Comando executado sem saida"
        return output[:2000]
    except subprocess.TimeoutExpired:
        return "Comando excedeu o tempo limite (30s)"
    except Exception as e:
        return f"Erro: {e}"


def kill_process(name: str) -> str:
    killed = 0
    for p in psutil.process_iter(["name"]):
        try:
            if name.lower() in p.info["name"].lower():
                p.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        return f"{killed} processo(s) '{name}' finalizado(s)"
    return f"Nenhum processo '{name}' encontrado"


# Backward compatibility
def execute_action(action):
    action = action.lower()
    if "abrir chrome" in action:
        return open_app("chrome")
    if "abrir bloco de notas" in action:
        return open_app("notepad")
    return "Nenhuma acao de sistema executada."
