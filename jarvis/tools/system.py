"""Ferramentas do sistema: telemetria, hardware, processos, abrir apps (lista permitida), encerrar processos e
comandos da lista fixa (sem shell)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import time
from datetime import datetime
from typing import Literal

import psutil
from pydantic import BaseModel, ConfigDict, Field

from . import Tool, ToolContext, ToolError


class _Vazio(BaseModel):
    model_config = ConfigDict(extra="forbid")


def status_sistema(_: _Vazio, ctx: ToolContext) -> str:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    net = psutil.net_io_counters()
    boot = datetime.fromtimestamp(psutil.boot_time())
    return json.dumps({
        "cpu_percent": psutil.cpu_percent(interval=0.4),
        "nucleos": psutil.cpu_count(),
        "ram_percent": mem.percent,
        "ram_usada_gb": round(mem.used / 2**30, 1),
        "ram_total_gb": round(mem.total / 2**30, 1),
        "disco_c_percent": disk.percent,
        "disco_c_livre_gb": round(disk.free / 2**30, 1),
        "rede_enviada_mb": round(net.bytes_sent / 2**20),
        "rede_recebida_mb": round(net.bytes_recv / 2**20),
        "ligado_ha_horas": round((datetime.now() - boot).total_seconds() / 3600, 1),
        "processos": len(psutil.pids()),
    }, ensure_ascii=False)


class ProcessosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top: int = Field(default=8, ge=1, le=25, description="Quantos processos listar")
    ordenar_por: Literal["memoria", "cpu"] = Field(default="memoria", description="Critério de ordenação")


def processos_pesados(p: ProcessosParams, ctx: ToolContext) -> str:
    procs = list(psutil.process_iter(["pid", "name", "memory_info"]))
    for pr in procs:  # 1ª leitura de CPU sempre vem 0: amostra em duas passadas
        try:
            pr.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.4)
    rows = []
    for pr in procs:
        try:
            mem = pr.info["memory_info"].rss if pr.info["memory_info"] else 0
            rows.append({
                "nome": pr.info["name"], "pid": pr.info["pid"],
                "cpu_percent": round(pr.cpu_percent(None) / max(psutil.cpu_count() or 1, 1), 1),
                "memoria_mb": round(mem / 2**20),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = "memoria_mb" if p.ordenar_por == "memoria" else "cpu_percent"
    rows.sort(key=lambda r: r[key], reverse=True)
    return json.dumps(rows[: p.top], ensure_ascii=False)


# Apps permitidos → alvo do ShellExecute (os.startfile). Nada fora desta lista é aberto.
APPS = {
    "chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe",
    "bloco de notas": "notepad.exe", "calculadora": "calc.exe", "paint": "mspaint.exe",
    "explorador de arquivos": "explorer.exe", "terminal": "wt.exe", "vscode": "code",
    "word": "winword.exe", "excel": "excel.exe", "gerenciador de tarefas": "taskmgr.exe",
    "spotify": "spotify:", "discord": "discord:",
}


class AbrirAppParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: Literal[tuple(APPS)] = Field(description="Aplicativo da lista permitida")  # type: ignore[valid-type]


def abrir_app(p: AbrirAppParams, ctx: ToolContext) -> str:
    if not hasattr(os, "startfile"):
        raise ToolError("abrir aplicativos só é suportado no Windows")
    try:
        # alvo vem só da lista fixa APPS (validada pelo Literal), sem shell
        os.startfile(APPS[p.nome])  # nosec B606
    except OSError as e:
        raise ToolError(f"não consegui abrir {p.nome}: {e.strerror or e}") from e
    return f"{p.nome} aberto."


# Processos que nunca podem ser encerrados (sistema, sessão e o próprio JARVIS)
PROTEGIDOS = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
    "memory compression", "secure system", "python.exe", "pythonw.exe", "node.exe", "claude.exe",
}


class EncerrarParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(min_length=2, max_length=80, description="Nome do processo, ex.: chrome.exe")


def _norm_exe(nome: str) -> str:
    n = nome.strip().lower()
    return n if n.endswith(".exe") else f"{n}.exe"


def encerrar_processo(p: EncerrarParams, ctx: ToolContext) -> str:
    alvo = _norm_exe(p.nome)
    if alvo in PROTEGIDOS or p.nome.strip().lower() in PROTEGIDOS:
        raise ToolError(f"{p.nome} é protegido e não pode ser encerrado")
    me = {os.getpid(), os.getppid()}
    encerrados = 0
    for pr in psutil.process_iter(["pid", "name"]):
        try:
            if (pr.info["name"] or "").lower() == alvo and pr.info["pid"] not in me:
                pr.terminate()
                encerrados += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not encerrados:
        raise ToolError(f"nenhum processo {alvo} encontrado (ou sem permissão)")
    return f"{encerrados} processo(s) {alvo} encerrado(s)."


# ── hardware ─────────────────────────────────────────────────
NVIDIA_SMI_ARGS = ("--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                   "--format=csv,noheader,nounits")


def _numero(v: str):
    return int(v) if v.isdigit() else v  # "[N/A]" fica como texto


def _gpus():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "nenhuma GPU NVIDIA encontrada (nvidia-smi ausente)"
    try:
        out = subprocess.run([exe, *NVIDIA_SMI_ARGS], capture_output=True, text=True, timeout=10,  # nosec B603
                             check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return f"nvidia-smi falhou: {type(e).__name__}"
    gpus = []
    for ln in out.strip().splitlines():
        nome, uso, usada, total, temp = (c.strip() for c in ln.split(","))
        gpus.append({"nome": nome, "uso_percent": _numero(uso), "vram_usada_mb": _numero(usada),
                     "vram_total_mb": _numero(total), "temperatura_c": _numero(temp)})
    return gpus


def hardware_info(_: _Vazio, ctx: ToolContext) -> str:
    freq = psutil.cpu_freq()
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return json.dumps({
        "cpu": {
            "nucleos_fisicos": psutil.cpu_count(logical=False), "nucleos_logicos": psutil.cpu_count(),
            "frequencia_mhz": round(freq.current) if freq else None, "uso_percent": psutil.cpu_percent(interval=0.3),
            "temperatura": "não disponível: o Windows não expõe a temperatura da CPU sem ferramenta do fabricante",
        },
        "gpu": _gpus(),
        "bateria": {"percent": round(bat.percent), "na_tomada": bat.power_plugged} if bat else "sem bateria (desktop)",
    }, ensure_ascii=False)


# ── comandos da lista fixa ───────────────────────────────────
# nome → (argumentos exatos, efeito explicado no card de aprovação). Nada fora daqui é executado.
COMANDOS = {
    "desligar_wsl": (("wsl", "--shutdown"),
                     "desliga todas as distros do WSL e a VM (libera a RAM do Vmmem); o que roda no Linux é encerrado"),
    "limpar_cache_dns": (("ipconfig", "/flushdns"), "limpa o cache de DNS do Windows"),
}


class ComandoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: Literal[tuple(COMANDOS)] = Field(description="Comando da lista permitida")  # type: ignore[valid-type]


def _texto_saida(raw: bytes) -> str:
    if b"\x00" in raw:  # wsl.exe escreve em UTF-16
        return raw.decode("utf-16-le", errors="replace")
    for enc in ("oem", "cp850"):  # ipconfig usa a página de código do console
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def comando_seguro(p: ComandoParams, ctx: ToolContext) -> str:
    argv = COMANDOS[p.nome][0]
    exe = shutil.which(argv[0])
    if not exe:
        raise ToolError(f"{argv[0]} não encontrado neste PC")
    try:
        # argumentos só da lista fixa COMANDOS, sem shell; o código de saída é tratado abaixo
        r = subprocess.run([exe, *argv[1:]], check=False, capture_output=True, timeout=120)  # nosec B603
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{' '.join(argv)} não terminou em 2 minutos") from e
    saida = " ".join(_texto_saida(r.stdout + r.stderr).split())[:300]
    if r.returncode != 0:
        raise ToolError(f"{' '.join(argv)} falhou (código {r.returncode}): {saida}")
    return f"{' '.join(argv)}: concluído. {saida}".strip()


SYSTEM_TOOLS = [
    Tool(
        name="hardware_info",
        description="Hardware do PC: GPU NVIDIA (uso, VRAM, temperatura), CPU (núcleos, frequência) e bateria. "
                    "A temperatura da CPU não é legível no Windows.",
        params=_Vazio, run=hardware_info, summary=lambda p: "consultou o hardware",
    ),
    Tool(
        name="comando_seguro",
        description="Executa um comando da lista fixa: desligar_wsl (wsl --shutdown, libera a RAM do WSL) ou "
                    "limpar_cache_dns (ipconfig /flushdns). Chame direto; a confirmação é automática.",
        params=ComandoParams, run=comando_seguro, needs_approval=True,
        summary=lambda p: f"executar {' '.join(COMANDOS[p.nome][0])}",
        details=lambda p, ctx: {"comando": " ".join(COMANDOS[p.nome][0]), "efeito": COMANDOS[p.nome][1]},
    ),
    Tool(
        name="status_sistema",
        description="Telemetria atual do PC (CPU, RAM, disco C:, rede, tempo ligado). Use quando o usuário "
                    "perguntar sobre desempenho, lentidão, memória ou espaço em disco.",
        params=_Vazio, run=status_sistema, summary=lambda p: "consultou o status do sistema",
    ),
    Tool(
        name="processos_pesados",
        description="Lista os processos que mais consomem memória ou CPU. Use para diagnosticar lentidão ou "
                    "antes de sugerir encerrar algo.",
        params=ProcessosParams, run=processos_pesados,
        summary=lambda p: f"listou os {p.top} processos mais pesados ({p.ordenar_por})",
    ),
    Tool(
        name="abrir_app",
        description="Abre um aplicativo da lista permitida. Chame direto quando o usuário pedir para abrir; "
                    "o sistema pede a confirmação dele automaticamente.",
        params=AbrirAppParams, run=abrir_app, summary=lambda p: f"abrir {p.nome}", needs_approval=True,
    ),
    Tool(
        name="encerrar_processo",
        description="Encerra todos os processos com o nome dado (ex.: chrome.exe). Processos do sistema são "
                    "protegidos. Chame direto quando o usuário pedir; a confirmação é automática.",
        params=EncerrarParams, run=encerrar_processo, summary=lambda p: f"encerrar {_norm_exe(p.nome)}",
        needs_approval=True,
    ),
]
