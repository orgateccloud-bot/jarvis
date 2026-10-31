# J.A.R.V.I.S. 4.0

Assistente pessoal para Windows, conversacional e proativo, que roda no próprio PC e usa **só modelos Claude**
(Anthropic). Conversa por texto ou voz num HUD cinematográfico, executa ações reais no computador sempre com
aprovação humana, lembra do usuário entre conversas e responde perguntas jurídicas e fiscais citando lei e artigo
de uma base local.

> Projeto pessoal da ORGATEC. API local em `127.0.0.1`, protegida por token; nada é exposto na rede.

## Destaques

| Área | O que faz |
|---|---|
| **Roteamento de modelos** | Classificador determinístico (sem LLM): Haiku 5.5 para o simples (esforço `low`), Sonnet 5.5 para o intermediário (`high`), Opus 5.5 para o complexo (`xhigh`) e Fable 5.1 só para o topo da complexidade (`high`, calibrado em ~5% das perguntas). Respostas por regra (hora, data, status) custam zero. Prefixos `/haiku`, `/sonnet`, `/opus`, `/fable` forçam a camada. |
| **Custo controlado** | Teto mensal (padrão US$ 30): a 80% entra em modo economia, a 100% o Claude pausa. Cache de prompt, resumo automático (compaction) a partir de 60 mil tokens e conversa nova após 30 min parada. Ledger em SQLite com preço oficial por modelo. |
| **Ferramentas com aprovação** | Status e hardware do PC, processos, abrir programas (lista em `config/apps.json`, editores numa pasta), listar programas instalados e janelas abertas, encerrar processos, ler/buscar arquivos, lembretes (únicos e recorrentes), gestão de disco (analisar, mover reversível, Lixeira), telas do Windows e comandos de lista fixa (`wsl --shutdown`, `ipconfig /flushdns`). Toda ação com efeito mostra um card no HUD e espera "sim". |
| **Memória** | Ferramenta `memory_20250818` com back-end local (`dados/memories/`): perfil, preferências e decisões sobrevivem entre conversas. CPF/CNPJ mascarados antes de gravar; apagar vai para `.lixeira/`. |
| **Especialista multiárea** | Base local de leis (CTN, LC 123/2006, Estatuto da OAB, baixadas do Planalto sem trechos revogados) e documentos do usuário, cortados por artigo, com busca BM25 em Python puro. Perguntas tributárias, de OAB ou contábeis sobem no mínimo para o Sonnet e citam lei e artigo. |
| **Web e arquivos gerados** | Busca e leitura de páginas (Sonnet/Opus). Arquivos que o sandbox de código gera (CSV, PDF, gráficos) são baixados pela Files API para `JARVIS-Arquivo\Gerados\<data>\`. |
| **Proatividade** | Monitores de RAM, CPU, disco e orçamento; lembretes; saudação; avisos por voz, no HUD e por notificação do Windows. |
| **HUD e voz** | React 19 + Vite com cena WebGL2 (galáxia e sol cuja classe estelar muda com o modelo). Voz pelo navegador: mãos livres, palavra de ativação "Jarvis", aprovação por "sim/não" e correção de termos (siglas fiscais, variantes do nome). Ou, com `JARVIS_VOZ_LOCAL=1`, [voz local](#voz-local-sem-o-hud): escuta com o HUD fechado e sem áudio na nuvem. |
| **Agentes (Etapa 3)** | O JARVIS é o cérebro: cria, observa, atualiza e comanda agentes subordinados, que não recebem ordem de mais ninguém. O primeiro é o [agente tributário](#agentes-etapa-3): dúvidas com a base local, análise de lançamentos com índice de risco de autuação, cenários atual × pós-Reforma (IBS/CBS) e laudo em 4 partes. |
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
                 tools/ (sistema, arquivos, disco, tarefas, memória, conhecimento, gerados, agentes)
                                              │
                 agentes/orquestrador ──► agentes/tributario  (só por Recursos: gateway do Claude, base, pasta)
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

### Iniciar no logon (opcional)

O script [`scripts/registrar-jarvis-logon.ps1`](scripts/registrar-jarvis-logon.ps1) cria no Agendador do
Windows a tarefa **JARVIS**:
- roda `.venv\Scripts\pythonw.exe -m jarvis` sem janela, 30 s depois do seu logon;
- usa o seu usuário, sem administrador, sem limite de tempo, e reinicia até 3 vezes se cair;
- grava a saída em `logs\api-console.log`.

O HUD fica em `http://127.0.0.1:8000`. Rode no PowerShell, na pasta do projeto:

```powershell
# 1. ver o que será registrado (não altera nada)
powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1 -DryRun
# 2. registrar
powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1
# iniciar agora, sem sair da conta
Start-ScheduledTask -TaskName JARVIS
```

Equivalente com `schtasks`, sem o atraso de 30 s nem o reinício automático. Pode exigir um terminal de
administrador:

```bat
schtasks /Create /TN "JARVIS" /SC ONLOGON /RL LIMITED /F /TR "\"D:\01_Projetos_Ativos\jarvis\.venv\Scripts\pythonw.exe\" -m jarvis"
```

**Para remover:** só a tarefa sai do Agendador; nenhum arquivo do JARVIS é apagado.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1 -Remover
# ou: schtasks /Delete /TN "JARVIS" /F
```

Com a tarefa ativa, não rode o `start-jarvis.bat` ao mesmo tempo, porque a porta 8000 já estará em uso. Para
parar a instância em execução: `Stop-ScheduledTask -TaskName JARVIS`.

| Endpoint | Função |
|---|---|
| `GET /health` | Estado e modelos |
| `POST /chat/stream` | Conversa em SSE (rota, pensamento, texto, ferramentas, aprovações, custo) |
| `POST /approvals/{id}` | Aprova ou nega uma ação |
| `GET /events` | Avisos proativos em SSE |
| `GET /costs` | Gasto do dia e do mês |
| `GET /audit/verify` | Confere a cadeia de auditoria |

## Voz local (sem o HUD)

Com `JARVIS_VOZ_LOCAL=1`, a API sobe e supervisiona o serviço `python -m jarvis.voz`: o JARVIS escuta e
responde falando com o HUD fechado, e o áudio não sai do PC. A única chamada à nuvem continua sendo a pergunta ao
Claude, feita pela API. Com a flag em `0` (padrão), nada disto existe: nem rota, nem processo.

**Instalar uma vez:**

```bat
.venv\Scripts\pip install -e .[voz,voz-gpu]
.venv\Scripts\python -m jarvis.voz.baixar
```

O `baixar` traz os modelos (cerca de 610 MB) para `D:\JARVIS-Voz\modelos` (`JARVIS_VOZ_DIR`) e grava um manifesto
com SHA-256. Em execução nada é baixado: os modelos carregam da pasta local e o processo de voz só consegue abrir
conexões para `127.0.0.1`. O `[voz-gpu]` traz o cuBLAS e o cuDNN da NVIDIA (cerca de 2 GB); sem GPU NVIDIA, use só
`[voz]` e o Whisper roda na CPU, mais devagar.

**Como funciona:**

| Etapa | O que faz |
|---|---|
| Escuta | Microfone a 16 kHz; o VAD Silero recorta cada fala. |
| Ativação | Toda fala curta (até 8 s) vai ao Whisper `small` na GPU (`int8_float16`, cerca de 0,35 s). Ela só vale se começar por "Jarvis" ou por "Ok", "Ei" ou "Oi" seguido de "Jarvis". |
| Comando | "Jarvis, X" pergunta X; "Jarvis" sozinho responde "Pois não?" e deixa a conversa aberta por 12 s, sem precisar repetir o nome; "Ok, Jarvis" sozinho arquiva a conversa e começa outra ("Nova conversa."); "Jarvis, pare" interrompe. |
| Resposta | A mesma pergunta do HUD (`/chat/stream`, sessão `hud`), falada frase a frase com a mesma voz do HUD: "Microsoft Daniel", rate 1.05, pitch 0.92. |
| Confirmação | "Confirma: ...? Diga sim ou não." e a resposta por voz. "Ok, Jarvis" com uma confirmação pendente nega e nunca aprova. |
| Half-duplex | O microfone fica mudo enquanto o JARVIS fala e por mais 1,5 s. Com fone, `JARVIS_VOZ_INTERROMPER=1` mantém o microfone aberto para "Jarvis, pare" interromper. |

**Com o HUD aberto:** o serviço continua sendo o dono do microfone e do alto-falante. O HUD não ouve nem fala:
mostra o estado do serviço no sol (ouvindo, pensando, falando), e o sol, o mudo e o Esc viram comandos para o
serviço. Se o serviço parar, o HUD mostra "Escuta local parada" e oferece o microfone do navegador; o Chrome envia
esse áudio ao servidor dele, por isso só com o seu clique, e até você devolver.

**Diagnóstico:**

```bat
.venv\Scripts\python -m jarvis.voz --listar-microfones
.venv\Scripts\python -m jarvis.voz --sem-api          :: só escuta e registra em logs\voz.log
.venv\Scripts\python -m jarvis.voz.gravar             :: grava ~60 frases suas (fora do git)
.venv\Scripts\python -m jarvis.voz.gravar --avaliar   :: mede o acerto nas suas gravações
```

O log da voz (`logs\voz.log`) guarda só métricas; o texto transcrito só entra com `JARVIS_VOZ_LOG_TEXTO=1`, com CPF
e CNPJ mascarados. A tarefa de logon da seção anterior já cobre a voz: a API sobe o serviço sozinha.

## Agentes (Etapa 3)

O JARVIS comanda agentes subordinados; o usuário comanda o JARVIS. A cadeia é garantida no código:

| Elo | Como |
|---|---|
| Usuário → JARVIS | Toda rota `/agentes*` exige o token da API (um teste percorre o OpenAPI e cobra 401 de toda rota). |
| JARVIS → orquestrador | Só a API e as ferramentas do cérebro alcançam o orquestrador; cada ordem grava a origem (`usuario_api` ou `jarvis_conversa`) e tem id único. |
| Orquestrador → agente | Objeto-capacidade: só o orquestrador guarda a referência do agente. O agente recebe `Recursos` (gateway do Claude, base de conhecimento só para leitura, pasta de entrega) e nada mais; um teste de lista branca de imports impede rede, API e ferramentas no código de agente. |
| Mudanças | Atualizar, pausar, retomar ou reverter pelo JARVIS pede aprovação, com o diff no cartão. Cada mudança vira uma versão nova da configuração (nada é apagado). |

**Agente tributário v1:**

| Tarefa | Claude? | O que faz |
|---|---|---|
| `analisar_lancamentos` | não (US$ 0) | Classifica lançamentos de um CSV (`;`, vírgula decimal) e calcula o índice heurístico de risco de autuação (5 a 99%, fórmula do MiniSaaS) com cada fator e os grupos de fracionamento. |
| `consultar` | Opus 5.5, `medium` | Responde com os trechos da base local, cita lei e artigo e compara com o pós-Reforma quando couber; fonte citada fora dos trechos é marcada. |
| `comparar_cenarios` | Opus 5.5, `high` | A calculadora local aplica o cronograma da EC 132/2023 e da LC 214/2025 (`jarvis/agentes/tributario/regras/cronograma_reforma.json`); o Claude só comenta. A alíquota de referência (28%) é estimativa. Não cobre o Simples Nacional. |
| `laudo` | Opus 5.5, `high` | Base normativa, cenários, probabilidade de autuação (índice calculado pelo sistema, nunca pelo modelo) e resumo executivo, salvo em `.md` em `JARVIS-Arquivo\Agentes\tributario\`. |

O agente roda só no Opus (decisão do usuário): trocar o modelo para outra família é recusado, e uma configuração
antiga é migrada para o Opus 5.5 no boot. Uma chamada ao Claude por tarefa (cerca de US$ 0,04 a 0,18), pelo gateway: CPF, CNPJ e nomes mascarados antes de
sair, teto conferido no pior caso (gasto do mês + 12 mil tokens de saída) contra o teto geral e o subteto do agente,
effort `low` no modo economia e custo no mesmo ledger (`/costs` mostra `por_origem`). No teto, as tarefas com Claude
param e a análise de lançamentos continua.

**Como acionar:** por voz ou texto, "Jarvis, pede ao agente tributário…" (o turno do JARVIS vai ao Sonnet com
esforço baixo e delega); ou direto pela API:

```bat
curl -H "Authorization: Bearer %JARVIS_TOKEN%" http://127.0.0.1:8000/agentes
curl -H "Authorization: Bearer %JARVIS_TOKEN%" -H "Content-Type: application/json" ^
     -d "{\"tarefa\": \"analisar_lancamentos\", \"arquivo\": \"Downloads\\extrato.csv\"}" ^
     http://127.0.0.1:8000/agentes/tributario/tarefas
```

Tarefa que passa de 20 s (`JARVIS_AGENTES_ESPERA_S`) responde "em andamento" (HTTP 202) e libera a conversa; o fim
vira aviso falado no HUD e o resultado fica em `GET /agentes/tarefas/{id}`. `GET /agentes/tarefas/{id}/verificar`
recalcula o sha256 do resultado e confere o selo na trilha de auditoria. A paridade do núcleo fiscal com o MiniSaaS
roda com `pytest -m mini` (precisa do Mini na máquina e do pandas).

## Configuração

Todas as opções estão comentadas em [`.env.example`](.env.example). As principais:

| Variável | Padrão | Para quê |
|---|---|---|
| `JARVIS_BUDGET_USD` | `30` | Teto mensal com o Claude |
| `JARVIS_MODELO_SIMPLES/MEDIO/COMPLEXO` | Haiku/Sonnet/Opus 5.5 | Modelos de cada camada |
| `JARVIS_SESSAO_OCIOSA_MIN` | `30` | Minutos parados até começar uma conversa nova |
| `JARVIS_PASTAS` | pastas pessoais | O que as ferramentas de arquivo podem ler e de onde podem mover (**substitui** o padrão; veja abaixo) |
| `JARVIS_ARQUIVO` | `D:\JARVIS-Arquivo` | Destino reversível dos movimentos e dos arquivos gerados |
| `JARVIS_CONHECIMENTO` | `D:\JARVIS-Conhecimento` | Base de leis e documentos (uma subpasta por área) |
| `JARVIS_VOZ_LOCAL` | `0` | `1` liga a [voz local](#voz-local-sem-o-hud) (a API sobe o serviço de voz) |
| `JARVIS_VOZ_DIR` | `D:\JARVIS-Voz` | Modelos de voz e gravações de teste (fora do repositório) |
| `JARVIS_VOZ_MICROFONE` | o do Windows | Parte do nome do microfone (`--listar-microfones`) |
| `JARVIS_VOZ_INTERROMPER` | `0` | `1` = modo fone: microfone aberto durante a fala, para "Jarvis, pare" |
| `JARVIS_AGENTES` | `tributario` | [Agentes](#agentes-etapa-3) ativos, separados por vírgula; vazio ou `0` desliga a camada |
| `JARVIS_AGENTES_ESPERA_S` | `20` | Segundos que o JARVIS espera uma tarefa de agente antes de responder "em andamento" |

> **Atenção: `JARVIS_PASTAS` substitui a lista padrão, não soma a ela.**
>
> - **Vazia:** o JARVIS usa `Documents`, `OneDrive\Documentos`, `Downloads`, `Desktop`, `OneDrive\Desktop`,
>   `OneDrive\Área de Trabalho` (as que existirem na sua pasta de usuário) e a pasta do projeto.
> - **Definida:** vale **só** o que estiver listado. Toda pasta padrão que você não repetir, inclusive o Desktop e
>   a pasta do projeto, deixa de ser lida e de poder ter arquivos movidos.
> - **Pasta inexistente:** é ignorada sem aviso.
> - **`JARVIS_ARQUIVO`:** continua sendo somado automaticamente para leitura, mas nunca como origem de movimentos.
>
> Para manter Documentos e Downloads e trocar o Desktop por `D:\Projetos`:
>
> ```ini
> JARVIS_PASTAS=C:\Users\Veloso\Documents;C:\Users\Veloso\Downloads;D:\Projetos
> ```
>
> Caminhos relativos pedidos ao JARVIS (ex.: "Downloads") partem da sua pasta de usuário. Ainda assim, só são
> aceitos se caírem dentro de uma das pastas permitidas.

## Programas

| Ferramenta | O que faz | Aprovação |
|---|---|---|
| `abrir_app` | Abre um programa da lista permitida. Editores aceitam `pasta`, que precisa estar numa pasta permitida (`confinar`). | sim |
| `listar_apps` | Lista os programas instalados (atalhos do Menu Iniciar do usuário e de todos os usuários, e chaves `Uninstall` do registro), com caminho e se já estão na lista. Aceita `filtro`; mostra até 300. **Só informa:** não adiciona nada à lista. | não |
| `apps_abertos` | Lista as janelas visíveis: título (CPF/CNPJ mascarados), processo, PID e memória. Não lê a linha de comando dos processos. | não |

A lista permitida mora só em [`config/apps.json`](config/apps.json). Dela saem os nomes que `abrir_app` aceita e a
linha do system prompt; não há outra cópia no código. Para adicionar um programa:

```json
"meu app": { "tipo": "app", "exe": "C:\\Program Files\\MeuApp\\MeuApp.exe", "aliases": ["meuapp"] }
```

| Campo | Uso |
|---|---|
| `tipo` | `"app"` ou `"editor"`. Só editor aceita `pasta`. |
| `abrir` | Alvo do `os.startfile`, como um nome com App Paths (`chrome.exe`) ou um protocolo (`spotify:`). |
| `exe` | Caminho de um **`.exe`**, chamado com lista de argumentos e sem shell. `.cmd` e `.bat` são recusados, porque passam pelo `cmd.exe`. `%VARIAVEIS%` são expandidas. |
| `terminal` | `true` abre o `exe` no Windows Terminal, na pasta. É usado pelo Claude Code. |
| `pasta_padrao` | Pasta usada quando nenhuma é pedida. |
| `aliases` | Outros nomes aceitos. |
| `ativo` | `false` desliga a entrada sem apagá-la. JSON não aceita comentários, por isso é um campo. |

Uma entrada com `exe` inexistente ou com erro fica inativa e gera um aviso no log. Um `apps.json` inválido não
derruba a API: `abrir_app` responde com o erro (arquivo, linha e coluna). **Reinicie a API depois de editar.**

Pasta pedida ao Claude Code (ou a outro editor) precisa estar numa pasta permitida. Para abrir em outros projetos de
`D:\01_Projetos_Ativos`, inclua essa pasta no `JARVIS_PASTAS`, lembrando que ele substitui a lista padrão.

## Testes e qualidade

```bat
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check jarvis tests
.venv\Scripts\bandit -q -r jarvis -ll
cd jarvis-hud && npm run lint && npm test && npm run build
```

Os testes usam um Claude simulado: nenhum chama a API real nem gasta dinheiro. O teste de fumaça que lê o Windows
de verdade (Menu Iniciar, registro e janelas) fica fora da execução padrão. Para rodá-lo:
`.venv\Scripts\python -m pytest -m windows_real -v`. O CI do GitHub roda tudo isso a
cada push.

Os testes da voz local usam WAVs sintéticos (vozes Daniel e Maria do Windows, `scripts/gerar_wavs_teste.py`), nunca
gravações de pessoas, e não chamam o Claude: a integração sobe a API com um Claude simulado. Os que precisam dos
modelos (marcador `voz_modelos`) são pulados quando eles não estão baixados, como no CI. A paridade do texto falado
com o HUD é conferida pelos mesmos casos dos dois lados (`tests/fixtures/voz/casos.json`, gerado por
`node scripts/gerar_casos_voz.mjs`).

## Estrutura

```
jarvis/            núcleo Python (api, core, tools, proactive, knowledge, agentes)
jarvis-hud/        interface React + WebGL2 e voz
tests/             testes do núcleo (Claude simulado)
_legado/           versões 1 a 3, arquivadas com plano de volta (LEIA-ME.md)
start-jarvis.bat   sobe a API, que serve o HUD buildado
scripts/           registrar-jarvis-logon.ps1 (iniciar no logon pelo Agendador)
```

Dados locais (`dados/`: conversas, memória, ledger, auditoria, token) e o `.env` nunca vão para o git.
