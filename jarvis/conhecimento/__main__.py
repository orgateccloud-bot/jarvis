"""python -m jarvis.conhecimento <comando>

  validar                                   confere os catálogos (_catalogo/*.toml) e lista os erros
  status                                    fontes por biblioteca, o que já foi baixado e o tamanho do índice
  atualizar [--biblioteca X] [--fonte Y] [--seco] [--forcar]
                                            baixa as fontes APROVADAS (sem a API do Claude) e reindexa
  buscar "consulta" [--area A] [--uf GO] [--tipo T] [--esfera E] [--vigente-em AAAA-MM-DD]

A pasta é JARVIS_CONHECIMENTO (padrão D:\\JARVIS-Conhecimento).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from .base import KnowledgeBase
from .catalogo import carregar_catalogos, dominio_permitido
from .documento import ler_cabecalho


def _raiz() -> Path:
    from ..config import get_settings

    return get_settings().knowledge_dir()


def validar(root: Path) -> int:
    carga = carregar_catalogos(root / "_catalogo")
    for c in carga.catalogos:
        sit = Counter(f.situacao for f in c.fontes)
        print(f"{c.arquivo.name}: {c.biblioteca.id} (área {c.biblioteca.area}) — {len(c.fontes)} fontes, "
              f"{sit['aprovado']} aprovadas, {sit['proposto']} propostas, {sit['suspenso']} suspensas")
        for f in c.fontes:
            if f.situacao == "aprovado" and f.url and not dominio_permitido(f.url, c.seguranca.dominios):
                carga.erros.append(f"{c.arquivo.name}: fonte '{f.id}': url fora de [seguranca].dominios")
    for e in carga.erros:
        print(f"ERRO {e}")
    print(f"{len(carga.fontes())} fontes válidas, {len(carga.erros)} erro(s)")
    return 1 if carga.erros else 0


def status(root: Path) -> int:
    kb = KnowledgeBase(root)
    resumo = kb.resumo()
    carga = kb.carga
    for c in carga.catalogos:
        aprovadas = [f for f in c.fontes if f.situacao == "aprovado"]
        print(f"[{c.biblioteca.id}] {c.biblioteca.nome}: {len(c.fontes)} fontes, {len(aprovadas)} aprovadas")
        for f in aprovadas:
            arq = root / carga.arquivo_de(f.id)
            cab = ler_cabecalho(arq.read_text(encoding="utf-8", errors="replace")[:4000])[0] if arq.exists() else None
            estado = f"baixado em {cab.baixado_em or '?'}" if cab else "ainda não baixado"
            print(f"   {f.id:24} {f.adaptador:12} {estado}")
    db = root / "_indice" / "base.db"
    tamanho = sum(p.stat().st_size for p in db.parent.glob("base.db*")) / 2**20 if db.exists() else 0
    print(f"índice ({resumo['motor']}): {resumo['arquivos']} arquivos, {resumo['trechos']} trechos, "
          f"{tamanho:.1f} MB em disco; {resumo['erros_catalogo']} erro(s) de catálogo")
    relatorios = sorted((root / "_relatorios").glob("*.md")) if (root / "_relatorios").is_dir() else []
    if relatorios:
        print(f"último relatório: {relatorios[-1]}")
    return 0


def atualizar(root: Path, args) -> int:
    from ..config import get_settings
    from .coleta import atualizar as coletar

    carga = carregar_catalogos(root / "_catalogo")
    for e in carga.erros:
        print(f"ERRO {e}")
    rel = coletar(root, carga, args.biblioteca, args.fonte, args.seco, args.forcar, salt=get_settings().salt())
    print(rel.markdown("Resultado").strip())
    print(f"relatório: {rel.caminho}")
    if not args.seco:
        print(KnowledgeBase(root).resumo())
    return 1 if rel.falhas or rel.recusados else 0


def buscar(root: Path, args) -> int:
    kb = KnowledgeBase(root)
    vigente = date.fromisoformat(args.vigente_em) if args.vigente_em else None
    for s, t in kb.buscar(args.consulta, args.area, uf=args.uf, tipo=args.tipo, esfera=args.esfera,
                          vigente_em=vigente):
        extra = " | ".join(x for x in (t.situacao, f"capturado {t.baixado_em}" if t.baixado_em else "", t.aviso) if x)
        print(f"{s:6.2f}  {t.fonte} — {t.rotulo}  [{extra}]\n        {t.url}\n        {t.texto[:160]!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m jarvis.conhecimento", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("validar")
    sub.add_parser("status")
    a = sub.add_parser("atualizar")
    a.add_argument("--biblioteca")
    a.add_argument("--fonte")
    a.add_argument("--seco", action="store_true", help="mostra o que faria, sem gravar")
    a.add_argument("--forcar", action="store_true", help="baixa mesmo o que está dentro da frequência")
    b = sub.add_parser("buscar")
    b.add_argument("consulta")
    for opcao in ("--area", "--uf", "--tipo", "--esfera", "--vigente-em"):
        b.add_argument(opcao)
    args = p.parse_args(argv)
    root = _raiz()
    if args.comando == "validar":
        return validar(root)
    if args.comando == "status":
        return status(root)
    if args.comando == "atualizar":
        return atualizar(root, args)
    return buscar(root, args)


if __name__ == "__main__":
    sys.exit(main())
