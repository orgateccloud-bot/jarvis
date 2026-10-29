# J.A.R.V.I.S. 4.0

Assistente pessoal para Windows, conversacional e proativo, que roda no próprio PC e usa **só modelos Claude**
(Anthropic). Conversa por texto ou voz num HUD cinematográfico, executa ações reais no computador sempre com
aprovação humana, lembra do usuário entre conversas e responde perguntas jurídicas e fiscais citando lei e artigo
de uma base local.

> Projeto pessoal da ORGATEC. API local em `127.0.0.1`, protegida por token; nada é exposto na rede.

## Destaques

| Área | O que faz |
|---|---|
| **Roteamento de modelos** | Classificador determinístico (sem LLM): Haiku 5.5 para o simples, Sonnet 5.5 para o intermediário, Opus 5.5 para o complexo. Respostas por regra (hora, data, status) custam zero. Prefixos `/haiku`, `/sonnet`, `/opus` forçam a camada. |
| **Custo controlado** | Teto mensal (padrão US$ 15): a 80% entra em modo economia, a 100% o Claude pausa. Cache de prompt, resumo automático (compaction) a partir de 60 mil tokens e conversa nova após 30 min parada. Ledger em SQLite com preço oficial por modelo. |
| **Ferramentas com aprovação** | Status e hardware do PC, processos, abrir apps (lista fixa), encerrar processos, ler/buscar arquivos, lembretes (únicos e recorrentes), gestão de disco (analisar, mover reversível, Lixeira), telas do Windows e comandos de lista fixa (`wsl --shutdown`, `ipconfig /flushdns`). Toda ação com efeito mostra um card no HUD e espera "sim". |
| **Memória** | Ferramenta `memory_20250818` com back-end local (`dados/memories/`): perfil, preferências e decisões sobrevivem entre conversas. CPF/CNPJ mascarados antes de gravar; apagar vai para `.lixeira/`. |
| **Especialista multiárea** | Base local de leis (CTN, LC 123/2006, Estatuto da OAB, baixadas do Planalto sem trechos revogados) e documentos do usuário, cortados por artigo, com busca BM25 em Python puro. Perguntas tributárias, de OAB ou contábeis sobem no mínimo para o Sonnet e citam lei e artigo. |
| **Web e arquivos gerados** | Busca e leitura de páginas (Sonnet/Opus). Arquivos que o sandbox de código gera (CSV, PDF, gráficos) são baixados pela Files API para `JARVIS-Arquivo\Gerados\<data>\`. |
| **Proatividade** | Monitores de RAM, CPU, disco e orçamento; lembretes; saudação; avisos por voz, no HUD e por notificação do Windows. |
| **HUD e voz** | React 19 + Vite com cena WebGL2 (galáxia e sol cuja classe estelar muda com o modelo). Voz pelo navegador: mãos livres, palavra de ativação "Jarvis", aprovação por "sim/não" e correção de termos (siglas fiscais, variantes do nome). |
| **Privacidade** | CPF/CNPJ mascarados e nomes pseudonimizados antes de qualquer envio à nuvem; trilha de auditoria encadeada por hash (`dados/audit.jsonl`). |

## Arquitetura

```
jarvis-hud/dist  (React buildado)  ──SSE──►  jarvis/api  (FastAPI, 127.0.0.1:8000, token; serve o HUD)
                                              │
                         ┌────────────────────┼──────────────────────┐
                    core/router          core/session            proactive/
                 (camada e área)   (loop agêntico, aprovações,   (monitores, lembretes,
                                    custo, auditoria)             toasts, /events)
                                              │
                    core/llm ── Claude API (Haiku | Sonnet | Opus, cache, compaction, fallback)
                                              │
                 tools/ (sistema, arquivos, disco, tarefas, memória, conhecimento, gerados)
```

## Requisitos

- Windows 10/11
- Python 3.12+ e Node.js 20+
- Uma credencial da Anthropic (`ANTHROPIC_API_KEY` no `.env` ou `ant auth login`)

## Instalação

```bat
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
copy .env.example .env
cd jarvis-hud && npm ci && npm run build && cd ..
```

Edite o `.env` (ao menos a credencial da Anthropic). Opcional, para a base de leis:

```bat
.venv\Scripts\python -m jarvis.knowledge baixar
```

## Uso

```bat
start-jarvis.bat
```

Sobe só a API, que também serve o HUD buildado: abra **`http://127.0.0.1:8000`**. Se ainda não houver build,
o script roda `npm run build` antes. Não há servidor de desenvolvimento rodando, então o HUD não gasta RAM com o
Vite. Depois de mudar o código do HUD, rode `npm run build` em `jarvis-hud` (a API pega o build novo sem
reiniciar).

O token da API é entregue na própria página, e só quando ela é aberta por um endereço local (`127.0.0.1`,
`localhost`); o build em disco nunca contém o token.

Para desenvolver o HUD com recarga automática, rode `npm run dev` em `jarvis-hud` (porta 5299, com a API rodando
à parte); nesse modo o Vite lê o token de `dados\.token`.

| Endpoint | Função |
|---|---|
| `GET /health` | Estado e modelos |
| `POST /chat/stream` | Conversa em SSE (rota, pensamento, texto, ferramentas, aprovações, custo) |
| `POST /approvals/{id}` | Aprova ou nega uma ação |
| `GET /events` | Avisos proativos em SSE |
| `GET /costs` | Gasto do dia e do mês |
| `GET /audit/verify` | Confere a cadeia de auditoria |

## Configuração

Todas as opções estão comentadas em [`.env.example`](.env.example). As principais:

| Variável | Padrão | Para quê |
|---|---|---|
| `JARVIS_BUDGET_USD` | `15` | Teto mensal com o Claude |
| `JARVIS_MODELO_SIMPLES/MEDIO/COMPLEXO` | Haiku/Sonnet/Opus 5.5 | Modelos de cada camada |
| `JARVIS_SESSAO_OCIOSA_MIN` | `30` | Minutos parados até começar uma conversa nova |
| `JARVIS_PASTAS` | pastas pessoais | O que as ferramentas de arquivo podem ler |
| `JARVIS_ARQUIVO` | `D:\JARVIS-Arquivo` | Destino reversível dos movimentos e dos arquivos gerados |
| `JARVIS_CONHECIMENTO` | `D:\JARVIS-Conhecimento` | Base de leis e documentos (uma subpasta por área) |

## Testes e qualidade

```bat
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check jarvis tests
.venv\Scripts\bandit -q -r jarvis -ll
cd jarvis-hud && npm run lint && npm test && npm run build
```

Os testes usam um Claude simulado: nenhum chama a API real nem gasta dinheiro. O CI do GitHub roda tudo isso a
cada push.

## Estrutura

```
jarvis/            núcleo Python (api, core, tools, proactive, knowledge)
jarvis-hud/        interface React + WebGL2 e voz
tests/             testes do núcleo (Claude simulado)
_legado/           versões 1 a 3, arquivadas com plano de volta (LEIA-ME.md)
start-jarvis.bat   sobe a API, que serve o HUD buildado
```

Dados locais (`dados/`: conversas, memória, ledger, auditoria, token) e o `.env` nunca vão para o git.
