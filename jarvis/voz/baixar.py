"""Baixa os modelos de voz uma única vez, com internet, para JARVIS_VOZ_DIR\\modelos.

    python -m jarvis.voz.baixar            baixa o que falta e grava o manifesto (SHA-256 de cada arquivo)
    python -m jarvis.voz.baixar --listar   mostra o que está baixado, sem rede

Idempotente: arquivo presente com o hash do manifesto não é baixado de novo. Na execução do serviço nada é baixado:
os modelos carregam por caminho local e `verificar()` confere os hashes antes de usar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from jarvis.voz.config import MODELOS_ATIVACAO, Pastas, pastas


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_manifesto(p: Pastas) -> dict:
    if not p.manifesto.exists():
        return {}
    return json.loads(p.manifesto.read_text(encoding="utf-8"))


def verificar(p: Pastas, nomes: list[str]) -> list[str]:
    """Problemas encontrados nos modelos pedidos (faltando, fora do manifesto ou com hash diferente)."""
    manifesto = ler_manifesto(p)
    erros = []
    for nome in nomes:
        arq = p.ativacao / nome
        reg = manifesto.get(f"openwakeword/{nome}")
        if not arq.exists():
            erros.append(f"{nome}: ausente (rode python -m jarvis.voz.baixar)")
        elif not reg:
            erros.append(f"{nome}: fora do manifesto")
        elif sha256(arq) != reg["sha256"]:
            erros.append(f"{nome}: hash diferente do manifesto")
    return erros


def baixar(p: Pastas, saida=print) -> dict:
    import httpx  # só aqui: o serviço de voz em execução nunca importa este módulo

    p.ativacao.mkdir(parents=True, exist_ok=True)
    manifesto = ler_manifesto(p)
    with httpx.Client(follow_redirects=True, timeout=60) as cli:
        for nome, url in MODELOS_ATIVACAO.items():
            chave, arq = f"openwakeword/{nome}", p.ativacao / nome
            if arq.exists() and manifesto.get(chave, {}).get("sha256") == sha256(arq):
                saida(f"ok      {chave}")
                continue
            r = cli.get(url)
            r.raise_for_status()
            parcial = arq.with_suffix(arq.suffix + ".parcial")
            parcial.write_bytes(r.content)
            parcial.replace(arq)
            manifesto[chave] = {"url": url, "sha256": sha256(arq), "bytes": arq.stat().st_size,
                                "baixado_em": datetime.now().isoformat(timespec="seconds")}
            saida(f"baixado {chave} ({arq.stat().st_size / 2**20:.1f} MB)")
    p.manifesto.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifesto


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.voz.baixar", description=__doc__.splitlines()[0])
    ap.add_argument("--listar", action="store_true", help="só lista o que está baixado (sem rede)")
    args = ap.parse_args(argv)
    p = pastas()
    if args.listar:
        for chave, reg in ler_manifesto(p).items():
            print(f"{chave}  {reg['bytes'] / 2**20:.1f} MB  {reg['sha256'][:12]}  {reg['baixado_em']}")
        return 0
    baixar(p)
    erros = verificar(p, list(MODELOS_ATIVACAO))
    for e in erros:
        print("ERRO", e, file=sys.stderr)
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
