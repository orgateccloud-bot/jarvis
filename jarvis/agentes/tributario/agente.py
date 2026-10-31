"""Agente tributário v1: consultar, analisar lançamentos, comparar cenários da Reforma e laudo em 4 partes.

Sem laço de ferramentas: o código busca os trechos da base, monta o cronograma e calcula os números; depois faz uma
única chamada ao Claude (pelo gateway), com saída estruturada. Números, índice de risco e textos falados saem do código.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import ClassVar

from ...core.privacy import sanitizar
from ..base import Agente
from ..contratos import ConfigAgente, Lancamento, PedidoTarefa, SaidaTarefa, TarefaRecusada
from . import prompts, reforma
from .lancamentos import analisar


def _num(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


REFORMA = re.compile(r"\b(reforma|ibs|cbs|imposto seletivo|lc 214|ec 132|split payment|20(2[6-9]|3[0-3]))\b",
                     re.IGNORECASE)


class AgenteTributario(Agente):
    tipo = "tributario"
    nome = "agente tributário"
    descricao = ("Dúvidas tributárias com a base local de leis, análise de lançamentos com índice de risco de "
                 "autuação, cenários atual × pós-Reforma (IBS/CBS) e laudo em 4 partes.")
    versao_codigo = "1.0.0"
    tarefas: ClassVar[dict[str, str]] = {
        "consultar": "Responde dúvida tributária com a base local de leis, cita lei e artigo e compara com o "
                     "pós-Reforma quando couber (usa o Claude).",
        "analisar_lancamentos": "Classifica lançamentos (CSV ou lista) e calcula o índice de risco de autuação com "
                                "cada fator e os grupos de fracionamento (local, sem custo).",
        "comparar_cenarios": "Calcula os tributos sobre consumo hoje e com IBS/CBS no ano pedido (calculadora "
                             "local) e comenta riscos e oportunidades (usa o Claude).",
        "laudo": "Laudo em 4 partes: base normativa, cenários, probabilidade de autuação (índice calculado) e "
                 "resumo executivo; salvo em .md (usa o Claude).",
    }
    com_claude = frozenset({"consultar", "comparar_cenarios", "laudo"})
    modelos = ("claude-opus",)   # decisão do usuário (31/10/2026): o agente tributário roda só no Opus
    # decisão do usuário (31/10/2026): effort baixo em todas; a configuração do agente pode subir (com aprovação)
    EFFORT: ClassVar[dict[str, str]] = {"consultar": "low", "comparar_cenarios": "low", "laudo": "low"}

    @classmethod
    def config_padrao(cls) -> ConfigAgente:
        return ConfigAgente(modelo="claude-opus-5-5")

    # ---------- apoio ----------
    def _gateway(self):
        if self.recursos.claude is None:
            raise TarefaRecusada("o agente está sem acesso ao Claude; só a análise de lançamentos funciona")
        return self.recursos.claude

    def _system(self, config: ConfigAgente) -> str:
        extra = config.instrucoes_extras.strip()
        return prompts.SYSTEM + (f"\n\nInstruções do usuário para este agente:\n{extra}" if extra else "")

    def _trechos(self, consulta: str) -> list[dict]:
        consulta = sanitizar(consulta, salt=self.recursos.salt)
        return (self.recursos.conhecimento.buscar(consulta, "tributario")
                or self.recursos.conhecimento.buscar(consulta, None))

    @staticmethod
    def _nomes(lancs: list[Lancamento] | None) -> list[str]:
        return sorted({n for x in lancs or [] for n in (x.nome, x.contraparte) if n.strip()}, key=len, reverse=True)

    @staticmethod
    def _fontes(ids: list[str], achados: list[dict]) -> tuple[list[dict], list[str]]:
        """Separa as fontes citadas que existem nos trechos das que o modelo citou sem estarem lá."""
        validas, fora = [], []
        for i in dict.fromkeys(ids):
            n = i.strip().upper().removeprefix("T")
            if n.isdigit() and 1 <= int(n) <= len(achados):
                t = achados[int(n) - 1]
                validas.append({"id": f"T{n}", "fonte": t["fonte"], "trecho": t["trecho"], "arquivo": t["arquivo"]})
            else:
                fora.append(i)
        return validas, fora

    # ---------- tarefas ----------
    async def tarefa_analisar_lancamentos(self, pedido: PedidoTarefa, config: ConfigAgente) -> SaidaTarefa:
        if not pedido.lancamentos:
            raise TarefaRecusada("envie os lançamentos (um CSV nas pastas permitidas ou a lista)")
        a = analisar(pedido.lancamentos, config.regras_extras, self.recursos.salt)
        indice = a["risco"]["indice"]
        periodo = f" de {a['periodo']['inicio']} a {a['periodo']['fim']}" if a["periodo"] else ""
        return SaidaTarefa(
            resumo=f"{a['total_lancamentos']} lançamentos{periodo}; índice de risco de autuação {_num(indice)}% "
                   f"(heurístico); {len(a['grupos_fracionamento'])} grupo(s) de possível fracionamento.",
            resumo_voz=f"Analisei {a['total_lancamentos']} lançamentos. O índice de risco de autuação ficou em "
                       f"{indice:.0f} por cento.",
            saida=a,
        )

    async def tarefa_consultar(self, pedido: PedidoTarefa, config: ConfigAgente) -> SaidaTarefa:
        if not pedido.pedido.strip():
            raise TarefaRecusada("a consulta precisa do texto da dúvida")
        gateway = self._gateway()
        achados = self._trechos(pedido.pedido)
        blocos = [prompts.trechos(achados)]
        if REFORMA.search(pedido.pedido):
            blocos.append(f"<cronograma>\n{reforma.resumo_cronograma()}\n</cronograma>")
        r = await gateway.chamar(self._system(config), prompts.mensagem(pedido.pedido, *blocos,
                                                                        tarefa=prompts.TAREFA_CONSULTAR),
                                 config.modelo, config.effort or self.EFFORT["consultar"],
                                 esquema=prompts.RespostaConsulta, nomes=self._nomes(pedido.lancamentos))
        validas, fora = self._fontes(r.dados["fontes_usadas"], achados)
        base = f"com {len(validas)} fonte(s) da base local" if validas else "sem fonte da base local"
        return SaidaTarefa(
            resumo=f"Consulta respondida, {base}." + (f" {len(fora)} citação(ões) fora dos trechos." if fora else ""),
            resumo_voz=f"A resposta do agente tributário está pronta, {base}.",
            saida={"resposta": r.dados["resposta"], "resumo_curto": r.dados["resumo_voz"], "fontes": validas,
                   "fontes_fora_da_base": fora, "dualidade": r.dados["dualidade"],
                   "nao_verificado": r.dados["nao_verificado"], "trechos_consultados": len(achados)},
        )

    async def tarefa_comparar_cenarios(self, pedido: PedidoTarefa, config: ConfigAgente) -> SaidaTarefa:
        if pedido.cenario is None:
            raise TarefaRecusada("informe o cenário: faturamento anual, regime, atividade e ano")
        gateway = self._gateway()
        calc = reforma.calcular(pedido.cenario)
        r = await gateway.chamar(
            self._system(config),
            prompts.mensagem(pedido.pedido or "comparar o cenário atual com o pós-Reforma",
                             f"<cronograma>\n{reforma.resumo_cronograma()}\n</cronograma>",
                             prompts.dados("calculo_cenario", calc), tarefa=prompts.TAREFA_CENARIOS),
            config.modelo, config.effort or self.EFFORT["comparar_cenarios"], esquema=prompts.AnaliseCenarios)
        return SaidaTarefa(resumo=self._resumo_calculo(calc), resumo_voz=self._voz_calculo(calc),
                           saida={"calculo": calc, **r.dados})

    async def tarefa_laudo(self, pedido: PedidoTarefa, config: ConfigAgente) -> SaidaTarefa:
        if not pedido.pedido.strip():
            raise TarefaRecusada("o laudo precisa do contexto: quem, qual período e o que avaliar")
        gateway = self._gateway()
        analise = analisar(pedido.lancamentos, config.regras_extras, self.recursos.salt) if pedido.lancamentos \
            else None
        calc = reforma.calcular(pedido.cenario) if pedido.cenario else None
        achados = self._trechos(pedido.pedido)
        blocos = [prompts.trechos(achados), f"<cronograma>\n{reforma.resumo_cronograma()}\n</cronograma>"]
        if analise:
            blocos.append(prompts.dados("analise_lancamentos", {k: v for k, v in analise.items() if k != "risco"}))
        if calc:
            blocos.append(prompts.dados("calculo_cenario", calc))
        r = await gateway.chamar(self._system(config), prompts.mensagem(pedido.pedido, *blocos,
                                                                        tarefa=prompts.TAREFA_LAUDO),
                                 config.modelo, config.effort or self.EFFORT["laudo"], esquema=prompts.TextoLaudo,
                                 nomes=self._nomes(pedido.lancamentos))
        validas, fora = self._fontes(r.dados["fontes_usadas"], achados)
        parte3 = self._parte3(analise)
        texto = self._laudo_md(pedido, r.dados, parte3, calc, validas, fora)
        self.recursos.pasta.mkdir(parents=True, exist_ok=True)
        arquivo = self.recursos.pasta / f"laudo-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.md"
        arquivo.write_text(texto, encoding="utf-8")
        indice = f" Índice de risco de autuação: {parte3['indice']:.0f} por cento." if parte3["calculado"] else ""
        return SaidaTarefa(
            resumo=f"Laudo em 4 partes salvo em {arquivo.name}.",
            resumo_voz=f"O laudo está pronto e salvo na pasta de agentes.{indice}",
            saida={"arquivo": str(arquivo), "parte3": parte3, "resumo_executivo": r.dados["parte4_resumo_executivo"],
                   "fontes": validas, "fontes_fora_da_base": fora, "nao_verificado": r.dados["nao_verificado"]},
            arquivo=str(arquivo),
        )

    # ---------- textos montados pelo código ----------
    @staticmethod
    def _resumo_calculo(calc: dict) -> str:
        if not calc["suportado"]:
            return f"Cenário {calc['ano']}: Simples Nacional fora da calculadora; só análise qualitativa."
        a, p, d = calc["atual"], calc["pos_reforma"], calc["diferenca"]
        return (f"Cenário {calc['ano']}: carga sobre consumo de {_num(a['carga_pct'], 2)}% hoje para "
                f"{_num(p['carga_pct'], 2)}% (diferença de R$ {_brl(d['valor'])} no ano).")

    @staticmethod
    def _voz_calculo(calc: dict) -> str:
        if not calc["suportado"]:
            return "A calculadora não cobre o Simples Nacional; o agente fez só a análise qualitativa."
        a, p = calc["atual"]["carga_pct"], calc["pos_reforma"]["carga_pct"]
        return (f"Em {calc['ano']}, a carga sobre o consumo vai de {_num(a)} para {_num(p)} por cento do "
                "faturamento, pela calculadora local.")

    @staticmethod
    def _parte3(analise: dict | None) -> dict:
        if not analise:
            return {"calculado": False, "motivo": "sem lançamentos: o índice não foi calculado e o laudo não estima "
                                                  "probabilidade sem dados"}
        risco = analise["risco"]
        return {"calculado": True, "indice": risco["indice"], "natureza": risco["natureza"],
                "fatores": risco["fatores"], "grupos_fracionamento": analise["grupos_fracionamento"],
                "total_lancamentos": analise["total_lancamentos"]}

    @staticmethod
    def _laudo_md(pedido: PedidoTarefa, texto: dict, parte3: dict, calc: dict | None, validas: list[dict],
                  fora: list[str]) -> str:
        linhas = [f"# Laudo tributário — {datetime.now():%d/%m/%Y %H:%M}", "",
                  f"> Pedido: {sanitizar(pedido.pedido)[:500]}", "",
                  "## 1. Relatório jurídico/fiscal e base normativa", "", texto["parte1_base_normativa"], "",
                  "## 2. Cenários futuros (ganhos × riscos)", ""]
        if calc and calc["suportado"]:
            a, p = calc["atual"], calc["pos_reforma"]
            linhas += ["| Tributo | Hoje (R$) | " + f"{calc['ano']} (R$) |", "|---|---:|---:|"]
            linhas += [f"| {k} | {_brl(a[k])} | {_brl(p[k])} |"
                       for k in ("pis_cofins", "icms", "iss", "ipi", "cbs", "ibs", "total")]
            carga = (f"Carga: {_num(a['carga_pct'], 2)}% hoje → {_num(p['carga_pct'], 2)}% em {calc['ano']} "
                     "(calculadora local).")
            linhas += ["", carga, "", "Premissas: " + " ".join(calc["premissas"]), ""]
        linhas += [texto["parte2_cenarios"], "", "## 3. Probabilidade de autuação (índice calculado pelo sistema)",
                   ""]
        if parte3["calculado"]:
            f = parte3["fatores"]
            linhas += [f"**Índice de risco de autuação: {_num(parte3['indice'])}%** — {parte3['natureza']}.", "",
                       "| Fator | % | Pontos |", "|---|---:|---:|", f"| Base | — | {_num(f['base'])} |"]
            linhas += [f"| {rotulo} | {_num(f[k]['pct'])} | {_num(f[k]['pontos'])} |" for k, rotulo in (
                ("sem_contraparte", "Sem contraparte"), ("fracionamento", "Fracionamento"),
                ("nao_classificados", "Não classificados"))]
            analisados = (f"Lançamentos analisados: {parte3['total_lancamentos']}; grupos de possível "
                          f"fracionamento: {len(parte3['grupos_fracionamento'])}.")
            linhas += ["", analisados, ""]
        else:
            linhas += [f"Não calculado: {parte3['motivo']}.", ""]
        linhas += ["## 4. Resumo executivo", "", texto["parte4_resumo_executivo"], "", "## Fontes", ""]
        linhas += [f"- {v['id']}: {v['fonte']}, {v['trecho']}" for v in validas] or ["- nenhuma da base local"]
        if fora:
            linhas += [f"- citadas sem estar nos trechos (não verificadas): {', '.join(fora)}"]
        if texto["nao_verificado"]:
            linhas += ["", "## Não verificado", "", *(f"- {x}" for x in texto["nao_verificado"])]
        if calc:
            linhas += ["", "## Limites do cálculo", "", *(f"- {x}" for x in calc["limitacoes"])]
        linhas += ["", "---", "Gerado pelo agente tributário do JARVIS. Rascunho técnico: revisar antes de assinar."]
        return "\n".join(linhas) + "\n"
