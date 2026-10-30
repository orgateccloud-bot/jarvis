"""Programas: abrir (lista permitida em config/apps.json), descobrir os instalados e ver as janelas abertas.

A lista permitida vive só no JSON: o enum de abrir_app e a linha do system prompt são gerados dele. JSON inválido
não derruba a API: abrir_app passa a responder com o erro, e as outras ferramentas seguem funcionando."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import psutil
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, create_model

from ..config import ROOT
from ..core.privacy import sanitizar
from . import Tool, ToolContext, ToolError
from .files import confinar

CATALOGO_PADRAO = ROOT / "config" / "apps.json"
TIPOS = ("app", "editor")
MAX_LISTA = 300


# ── catálogo (fonte única) ───────────────────────────────────
@dataclass(frozen=True)
class App:
    nome: str
    tipo: str
    abrir: str | None = None          # alvo do "start" do cmd.exe (resolve como o os.startfile)
    exe: Path | None = None           # executável chamado com lista de argumentos, sem shell
    terminal: bool = False            # abre o exe no Windows Terminal, na pasta
    pasta_padrao: Path | None = None
    aliases: tuple[str, ...] = ()
    ativo: bool = True
    motivo: str = ""                  # por que está inativo


@dataclass(frozen=True)
class Catalogo:
    apps: dict[str, App] = field(default_factory=dict)
    erro: str | None = None           # JSON ausente/inválido: abrir_app responde com isto

    def ativos(self) -> dict[str, App]:
        return {n: a for n, a in self.apps.items() if a.ativo}

    def nomes(self) -> list[str]:
        """Valores aceitos em abrir_app.nome: nomes e aliases dos apps ativos."""
        return sorted({n for a in self.ativos().values() for n in (a.nome, *a.aliases)})

    def resolver(self, nome: str) -> App | None:
        alvo = nome.strip().lower()
        return next((a for a in self.ativos().values() if alvo == a.nome or alvo in a.aliases), None)


def _caminho(valor: str) -> Path:
    return Path(os.path.expandvars(valor))


def _entrada(nome: str, d: dict) -> App:
    if not isinstance(d, dict):
        raise TypeError("a entrada precisa ser um objeto")
    tipo = d.get("tipo")
    if tipo not in TIPOS:
        raise ValueError(f"tipo deve ser 'app' ou 'editor', não {tipo!r}")
    exe = _caminho(d["exe"]) if d.get("exe") else None
    if exe and exe.suffix.lower() != ".exe":
        # .cmd/.bat passam pelo cmd.exe mesmo sem shell=True e abririam espaço para injeção
        raise ValueError(f"'exe' precisa ser um .exe, não {exe.name}")
    if not exe and not d.get("abrir"):
        raise ValueError("informe 'abrir' ou 'exe'")
    if tipo == "editor" and not exe:
        raise ValueError("editor precisa de 'exe' para abrir uma pasta")
    if d.get("terminal") and not exe:
        raise ValueError("'terminal' precisa de 'exe'")
    ativo, motivo = bool(d.get("ativo", True)), "" if d.get("ativo", True) else "desativado no apps.json"
    if ativo and exe and not exe.is_file():
        ativo, motivo = False, f"executável não encontrado: {exe}"
    return App(nome=nome, tipo=tipo, abrir=d.get("abrir"), exe=exe, terminal=bool(d.get("terminal")),
               pasta_padrao=_caminho(d["pasta_padrao"]) if d.get("pasta_padrao") else None,
               aliases=tuple(str(x).strip().lower() for x in d.get("aliases", [])), ativo=ativo, motivo=motivo)


def carregar_catalogo(path: Path = CATALOGO_PADRAO) -> Catalogo:
    """Nunca levanta: problema no arquivo vira Catalogo.erro; problema numa entrada a deixa inativa."""
    try:
        bruto = json.loads(path.read_text(encoding="utf-8"))
        entradas = bruto["apps"]
        if not isinstance(entradas, dict):
            raise TypeError("'apps' precisa ser um objeto")
    except FileNotFoundError:
        return _falha(f"lista de programas não encontrada: {path}")
    except json.JSONDecodeError as e:
        return _falha(f"{path.name} inválido (linha {e.lineno}, coluna {e.colno}): {e.msg}")
    except (KeyError, TypeError) as e:
        return _falha(f"{path.name} inválido: precisa de um objeto 'apps' ({e})")
    apps = {}
    for nome, d in entradas.items():
        n = str(nome).strip().lower()
        try:
            apps[n] = _entrada(n, d)
        except (ValueError, KeyError, TypeError) as e:
            apps[n] = App(nome=n, tipo="app", abrir=None, ativo=False, motivo=f"entrada inválida: {e}")
        if not apps[n].ativo and apps[n].motivo != "desativado no apps.json":
            logger.warning(f"apps.json: '{n}' inativo — {apps[n].motivo}")
    return Catalogo(apps=apps)


def _falha(msg: str) -> Catalogo:
    logger.error(f"abrir_app desativado: {msg}")
    return Catalogo(erro=msg)


# ── abrir_app ────────────────────────────────────────────────
def _plano(p, ctx: ToolContext, cat: Catalogo) -> tuple[str, list[str] | str]:
    """Valida o pedido e devolve ("startfile", alvo) ou ("processo", argv). Não executa nada."""
    if cat.erro:
        raise ToolError(f"não consigo abrir programas: {cat.erro}")
    app = cat.resolver(p.nome)
    if app is None:
        raise ToolError(f"'{p.nome}' não está na lista permitida (config/apps.json)")
    if p.pasta is not None and app.tipo != "editor":
        raise ToolError(f"{app.nome} não abre pastas: só programas do tipo editor aceitam 'pasta'")
    pasta = confinar(p.pasta, ctx) if p.pasta is not None else (app.pasta_padrao if app.terminal else None)
    if pasta is not None and not pasta.is_dir():
        raise ToolError(f"{pasta} não é uma pasta")
    if app.terminal:
        if ";" in str(pasta):  # o Windows Terminal usa ';' para separar comandos
            raise ToolError("pasta com ';' não pode ser aberta no Windows Terminal")
        wt = shutil.which("wt.exe")
        if not wt:
            raise ToolError("Windows Terminal (wt.exe) não encontrado")
        return "processo", [wt, "-d", str(pasta), str(app.exe)]
    if pasta is not None:
        return "processo", [str(app.exe), str(pasta)]
    if app.abrir:
        return "startfile", app.abrir
    return "processo", [str(app.exe)]


SENSIVEIS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_NOME_SENSIVEL = re.compile(r"KEY|TOKEN|SECRET", re.IGNORECASE)
_META_CMD = re.compile(r'[&|<>^%!"\r\n]')  # o cmd.exe interpreta estes mesmo dentro de aspas


def ambiente_filho(base: dict[str, str] | None = None) -> dict[str, str]:
    """Cópia do ambiente para o programa aberto, sem chaves, tokens e segredos. Não altera os.environ."""
    base = os.environ if base is None else base
    return {k: v for k, v in base.items() if k.upper() not in SENSIVEIS and not _NOME_SENSIVEL.search(k)}


def _executar(modo: str, alvo) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if modo == "startfile":
        # os.startfile não aceita ambiente próprio e passaria as chaves do JARVIS ao programa. O "start" do
        # cmd.exe resolve o alvo do mesmo jeito (App Paths, protocolos como spotify:) com o ambiente filtrado.
        if os.name != "nt":
            raise ToolError("abrir aplicativos só é suportado no Windows")
        if _META_CMD.search(alvo):
            raise ToolError(f"alvo inválido no apps.json: {alvo!r}")
        alvo = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "start", "", alvo]  # DETACHED: sem console
    # lista de argumentos vinda do apps.json + pasta validada por confinar(); sem shell
    subprocess.Popen(alvo, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # nosec B603
                     stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=ambiente_filho())


def _params_abrir(cat: Catalogo) -> type[BaseModel]:
    nomes = cat.nomes()
    tipo_nome = Literal[tuple(nomes)] if nomes else str  # type: ignore[valid-type]
    return create_model(
        "AbrirAppParams", __config__=ConfigDict(extra="forbid"),
        nome=(tipo_nome, Field(description="Programa da lista permitida")),
        pasta=(str | None, Field(default=None, min_length=1, max_length=400,
                                 description="Só para editores: pasta a abrir (absoluta ou relativa à pasta do "
                                             "usuário)")),
    )


def _descricao_abrir(cat: Catalogo) -> str:
    if cat.erro:
        return "Abre programas da lista permitida (lista indisponível: config/apps.json com erro)."
    editores = sorted(n for n, a in cat.ativos().items() if a.tipo == "editor")
    return (f"Abre um programa da lista permitida: {', '.join(sorted(cat.ativos()))}. "
            f"Editores ({', '.join(editores) or 'nenhum'}) aceitam 'pasta'. Chame direto quando o usuário pedir; "
            "a confirmação é automática.")


# ── listar_apps ──────────────────────────────────────────────
def _norm(nome: str) -> str:
    """Nome comparável: minúsculo, sem versão nem sufixos de instalação."""
    n = re.sub(r"\(.*?\)|\bv?\d+(\.\d+)+\b", " ", nome.lower())
    return " ".join(n.split())


def ler_lnk(path: Path) -> str | None:
    """Alvo de um atalho .lnk (formato MS-SHLLINK), sem COM: LinkInfo ou, se não houver, o bloco de variáveis
    de ambiente. Devolve None quando o atalho não aponta para um caminho de arquivo (ex.: apps da Store)."""
    try:
        b = path.read_bytes()
        if len(b) < 0x4C or struct.unpack_from("<I", b, 0)[0] != 0x4C:
            return None
        flags = struct.unpack_from("<I", b, 0x14)[0]
        pos = 0x4C
        if flags & 0x01:  # HasLinkTargetIDList
            pos += 2 + struct.unpack_from("<H", b, pos)[0]
        if flags & 0x02:  # HasLinkInfo
            ini = pos
            tam, cab, li_flags, _vol, base, _rede, sufixo = struct.unpack_from("<7I", b, ini)
            if li_flags & 0x01:  # VolumeIDAndLocalBasePath
                if cab >= 0x24:
                    base_u, sufixo_u = struct.unpack_from("<2I", b, ini + 28)
                    caminho = _cstr_utf16(b, ini + base_u) + _cstr_utf16(b, ini + sufixo_u)
                else:
                    caminho = _cstr_ansi(b, ini + base) + _cstr_ansi(b, ini + sufixo)
                if caminho:
                    return caminho
            pos = ini + tam
        if flags & 0x200:  # HasExpString: EnvironmentVariableDataBlock no ExtraData
            i = b.find(struct.pack("<I", 0xA0000001), pos)
            if i >= 4:
                alvo = b[i + 4 + 260:i + 4 + 260 + 520].decode("utf-16-le", "ignore").split("\0")[0]
                return os.path.expandvars(alvo) or None
    except (OSError, struct.error, UnicodeDecodeError):
        return None
    return None


def _cstr_ansi(b: bytes, i: int) -> str:
    return b[i:b.index(b"\0", i)].decode("mbcs" if sys.platform == "win32" else "latin-1", "ignore")


def _cstr_utf16(b: bytes, i: int) -> str:
    fim = i
    while b[fim:fim + 2] != b"\0\0":
        fim += 2
    return b[i:fim].decode("utf-16-le", "ignore")


def _atalhos_menu_iniciar() -> list[tuple[str, str]]:
    pastas = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
              Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs"]
    out = []
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for lnk in pasta.rglob("*.lnk"):
            if re.search(r"uninstall|desinstal", lnk.stem, re.IGNORECASE):
                continue
            out.append((lnk.stem, ler_lnk(lnk) or str(lnk)))
    return out


def _registro_uninstall() -> list[tuple[str, str]]:
    try:
        import winreg
    except ImportError:
        return []
    chave = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    fontes = [(winreg.HKEY_LOCAL_MACHINE, chave), (winreg.HKEY_LOCAL_MACHINE, chave.replace("Software\\", "Software\\WOW6432Node\\", 1)),
              (winreg.HKEY_CURRENT_USER, chave)]
    out = []
    for raiz, sub in fontes:
        try:
            k = winreg.OpenKey(raiz, sub)  # só leitura (KEY_READ é o padrão)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as app:
                        valores = {n: _valor(app, n) for n in ("DisplayName", "DisplayIcon", "InstallLocation",
                                                                 "SystemComponent", "ParentKeyName")}
                except OSError:
                    continue
                if not valores["DisplayName"] or valores["SystemComponent"] == 1 or valores["ParentKeyName"]:
                    continue
                icone = str(valores["DisplayIcon"] or "").split(",")[0].strip().strip('"')
                caminho = icone if icone.lower().endswith(".exe") else str(valores["InstallLocation"] or "")
                out.append((str(valores["DisplayName"]), caminho))
    return out


def _valor(chave, nome):
    import winreg

    try:
        return winreg.QueryValueEx(chave, nome)[0]
    except OSError:
        return None


class ListarAppsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filtro: str | None = Field(default=None, max_length=60, description="Trecho do nome para filtrar (opcional)")


def listar_apps(p: ListarAppsParams, cat: Catalogo) -> str:
    permitidos_exe = {str(a.exe).lower() for a in cat.ativos().values() if a.exe}
    permitidos_nome = {_norm(n) for n in cat.nomes()} | {Path(a.abrir).stem.lower() for a in cat.ativos().values()
                                                       if a.abrir and a.abrir.lower().endswith(".exe")}
    vistos_nome, vistos_caminho, itens = set(), set(), []
    for origem, fonte in (("menu iniciar", _atalhos_menu_iniciar), ("registro", _registro_uninstall)):
        for nome, caminho in fonte():
            chave_nome, chave_caminho = _norm(nome), caminho.lower()
            if not chave_nome or chave_nome in vistos_nome or (caminho and chave_caminho in vistos_caminho):
                continue
            vistos_nome.add(chave_nome)
            if caminho:
                vistos_caminho.add(chave_caminho)
            exe = Path(caminho).stem.lower() if caminho.lower().endswith(".exe") else ""
            na_lista = chave_caminho in permitidos_exe or chave_nome in permitidos_nome or exe in permitidos_nome
            itens.append({"nome": nome, "caminho": caminho, "origem": origem, "na_lista": na_lista})
    if p.filtro:
        f = p.filtro.lower()
        itens = [i for i in itens if f in i["nome"].lower()]
    itens.sort(key=lambda i: i["nome"].lower())
    return json.dumps({"total": len(itens), "mostrando": min(len(itens), MAX_LISTA), "apps": itens[:MAX_LISTA]},
                      ensure_ascii=False)


# ── apps_abertos ─────────────────────────────────────────────
def _janelas() -> list[tuple[str, int]]:
    """(título, pid) de cada janela visível e não oculta (cloaked), via user32/dwmapi."""
    if sys.platform != "win32":
        raise ToolError("listar janelas só é suportado no Windows")
    import ctypes
    from ctypes import wintypes

    user32, dwm = ctypes.WinDLL("user32"), ctypes.WinDLL("dwmapi")
    out: list[tuple[str, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd) and (n := user32.GetWindowTextLengthW(hwnd)):
            oculta = wintypes.DWORD()
            dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(oculta), ctypes.sizeof(oculta))  # DWMWA_CLOAKED
            if not oculta.value:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((buf.value, pid.value))
        return True

    user32.EnumWindows(cada, 0)
    return out


class _Vazio(BaseModel):
    model_config = ConfigDict(extra="forbid")


def apps_abertos(_: _Vazio, ctx: ToolContext) -> str:
    janelas = []
    for titulo, pid in _janelas():
        try:
            proc = psutil.Process(pid)  # só nome e memória: a linha de comando pode conter tokens
            nome, mem = proc.name(), proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        janelas.append({"titulo": sanitizar(titulo, salt=ctx.salt)[:120], "processo": nome, "pid": pid,
                        "memoria_mb": round(mem / 2**20)})
    janelas.sort(key=lambda j: j["memoria_mb"], reverse=True)
    return json.dumps(janelas, ensure_ascii=False)


# ── registro das ferramentas ─────────────────────────────────
def app_tools(cat: Catalogo) -> list[Tool]:
    params = _params_abrir(cat)

    def resumo(p) -> str:
        return f"abrir {p.nome}" + (f" na pasta {p.pasta}" if getattr(p, "pasta", None) else "")

    def detalhes(p, ctx) -> dict:
        modo, alvo = _plano(p, ctx, cat)
        return {"comando": alvo if modo == "startfile" else " ".join(f'"{a}"' if " " in a else a for a in alvo)}

    def abrir(p, ctx) -> str:
        plano = _plano(p, ctx, cat)
        try:
            _executar(*plano)
        except OSError as e:  # mesma mensagem do abrir_app anterior à Etapa 1b
            raise ToolError(f"não consegui abrir {p.nome}: {e.strerror or e}") from e
        return f"{p.nome} aberto" + (f" em {p.pasta}" if p.pasta else "") + "."

    return [
        Tool("abrir_app", _descricao_abrir(cat), params, abrir, resumo, needs_approval=True, details=detalhes),
        Tool("listar_apps",
             "Lista os programas instalados (Menu Iniciar e registro), com o caminho e se já estão na lista "
             "permitida. Só informa: não adiciona nada à lista.",
             ListarAppsParams, lambda p, ctx: listar_apps(p, cat), lambda p: "listou os programas instalados"),
        Tool("apps_abertos",
             "Lista as janelas abertas agora, com título, processo, PID e memória.",
             _Vazio, apps_abertos, lambda p: "listou as janelas abertas"),
    ]
