# Mapeamento do HUD do JARVIS

Data: 06/11/2026. Só leitura: nenhum código foi alterado.

Base conferida: `main` em 4b32c49, `jarvis-tributario` em f06a3b2, `jarvis-trilhum` em 9a1484f e `jarvis-iurisnotitia` em 1400c32. Li o código dos quatro e consultei as APIs no ar: 8000 e 8002 com rotas protegidas, 8003 nas rotas citadas, e a 8004 só pelo `/health` e pelo diff. Abri o HUD real da 8000 para conferir a tela. Os números de linha valem para o `main`.

Esforço: **P** até cerca de 40 linhas, **M** de 40 a 100, **G** mais de 100 (segue a regra de plano primeiro e a palavra "execute").

## 1. Resumo

1. **No JARVIS principal, o HUD não enxerga a conversa por voz.** O serviço de voz chama `/chat/stream` por conta própria, e cada stream só vai para quem pediu. Pergunta, resposta, ferramentas, modelo, custo, pensamento e até o card de aprovação não aparecem. Só o estado do sol muda. É a maior causa de o HUD parecer parado, porque a voz é o uso principal.
2. **A onda da fala no sol fica fixa com a voz local.** A energia que faz o sol pulsar vem do texto do stream ou da voz do navegador, e nenhum dos dois existe nesse caso.
3. **Tudo o que o HUD sabe some no F5.** A conversa e os avisos vivem só no navegador, embora a API guarde a conversa.
4. **Os avisos só informam.** O alerta de memória diz "Posso listar os processos mais pesados", mas não há botão para isso.
5. **Muito do que o backend sabe só o modelo alcança.** Lembretes, memória, movimentos de arquivos, base de conhecimento e agenda do Trilhum não têm rota HTTP. No Tributário, os agentes têm rotas completas e nenhuma tela.
6. **Os JARVIS especializados quase não têm cara própria.** Só o Tributário tem cards próprios. As sugestões do Tributário e do IurisNotitia ainda falam do disco C:.

A ordem que recomendo está na seção 6: primeiro o pacote "Vivo já", barato e nos quatro; depois fazer o HUD enxergar a voz.

## 2. O que existe hoje

### 2.1 A tela

```
TopBar: marca · estado e camada · online · ouvir · fone · limpar · minimizar · mudo · relógio

Sistema        |                                   | Avisos
Custo Claude   |     astro em WebGL + legenda      | Neural
               |     conversa (36% da altura,      |
               |     últimas 12 mensagens)         |
               |     sugestões (só antes da        |
               |     primeira pergunta)            |
               |     dock: modo, texto, microfone  |

Toasts por cima. Abaixo de 900 px, os cards viram gaveta.
```

### 2.2 Componentes

| Peça | Arquivo | O que faz | De onde vêm os dados |
|---|---|---|---|
| Cosmos | `cosmos/CosmosScene.jsx`, `shaders.js`, `pacing.js` | Universo, galáxia e astro. 30 fps em repouso, 60 pensando ou falando, para com a aba oculta, resolução adaptativa | `phase`, camada, alerta, `energyRef` |
| Astro de cada JARVIS | `lib/astro.js` | Sol, Vênus, Marte ou Netuno, compilado com `#define ASTRO` | Constante `ASTRO` |
| Abertura | `Overlays.jsx` (`BootIgnition`) | Quatro frases a cada 850 ms | Nenhum dado real |
| Astro clicável e legenda | `Overlays.jsx` (`SunButton`, `Caption`) | Abre ou fecha a conversa, mostra "Ouvindo…", "Pensando…" | `useConversation` |
| Barra de cima | `TopBar.jsx` | Estado, camada, conexão, botões, relógio | `phase`, `online`, flags da conversa |
| Sistema | `Cards.jsx` (`VitalsCard`) | Anéis de CPU, RAM e disco, linhas dos últimos 3 min | `/system/status` |
| Custo Claude | `Cards.jsx` (`CostCard`, `Telemetria`) | Uso do teto, hoje, mês, cache, custo por modelo, projeção, fatia do Fable | `/costs` |
| Avisos | `Cards.jsx` (`AvisosCard`), `lib/avisos.js` | Saudação, alertas e lembretes, até 20, o mais novo em cima | `/events` |
| Neural | `Cards.jsx` (`NeuralCard`) | Camada, modelo, estrela, esforço, pensamento, custo do turno, selo | Eventos `route`, `thinking`, `usage` |
| Conversa | `Transcript.jsx` | Balões em Markdown, chips de ferramenta, card de aprovação com contagem | `/chat/stream` |
| Dock | `CommandDock.jsx` | Modo (Auto, Haiku, Sonnet, Opus, Fable), texto, microfone, quatro sugestões fixas | Estado local |
| Tela limpa | `lib/telaLimpa.js`, `hooks/useCards.js` | Minimizar cards, limpar a conversa da tela | `localStorage` |
| Hooks | `useJarvis.js`, `useConversation.js`, `useVozLocal.js` | Stream, polling e avisos; voz do navegador; serviço de voz | API |
| Voz do navegador | `lib/voice/` | Web Speech, filtro de eco, divisão de frases, decisão do que fazer com a fala, correção de termos, ponte com o serviço | Navegador |

`lib/marca.js` não existe no `main`, onde o nome "JARVIS" está escrito direto no código. Ele só existe nos outros três branches. A lógica pura fica em `lib/` com testes em `tests/` (12 arquivos, `node --test`).

### 2.3 Como o astro reage hoje

A fase visual sai de `App.jsx:94`: o estado do serviço de voz manda, depois a voz do navegador, depois o stream, depois a escuta.

| Situação | O que muda | Limite |
|---|---|---|
| Ouvindo | A coroa brilha mais | Com a voz local, chega com até 1 s de atraso |
| Pensando | O astro ferve mais, a galáxia gira e expande, 60 fps | Modelo pensando, ferramenta rodando e espera de aprovação parecem iguais |
| Falando | Onda de voz e pulsação pela energia | Com a voz local, a energia fica em zero (`CosmosScene.jsx:186`) |
| Camada | Cor, tamanho e tinta da galáxia | Volta à classe G2V depois de 30 s em espera |
| Alerta | Ejeção coronal por 3 s; contínua no teto de custo | Só nível crítico ou evento `error` |

### 2.4 O que chega da API

| Canal | Ritmo | Observação |
|---|---|---|
| `/health`, `/system/status`, `/costs` | A cada 3 s | Três consultas por rodada, por HUD aberto |
| `/voz` | 3 s, ou 30 s se der 404 | 404 é normal sem a voz local |
| `/events` (SSE) | Ao vivo | Reconecta depois de 3 s |
| `/chat/stream` (SSE) | Por pergunta | Só para quem perguntou |
| `/painel/*` | 60 s | Só no Tributário |

Eventos de `/chat/stream`:

| Evento | Campos | O HUD usa | O HUD ignora |
|---|---|---|---|
| `route` | `rota`, `modelo`, `effort`, `motivo`, `orcamento`, `nova_conversa` | `rota`, `modelo`, `effort`; `motivo` só até chegar o pensamento | `orcamento`, `nova_conversa` |
| `thinking` | Texto | Últimos 360 caracteres | Nada |
| `text` | Trecho | Balão, energia, fala no navegador | Nada |
| `tool` | `fase`, `nome`, `resumo`, `ok`, `negado` | Chips | Nada; não existe duração |
| `approval` | `id`, `nome`, `resumo`, `args`, `expira_s`, `detalhes` | Card com contagem | `args` |
| `usage` | `modelo`, `custo_usd`, `entrada`, `saida`, `cache_read`, `cache_write`, `buscas_web`, `audit_hash`, `estado_orcamento` | Custo, modelo, tokens, cache lido, selo | `cache_write`, `buscas_web`, `estado_orcamento` |
| `error` | Texto | Toast vermelho e alerta de 3 s | Nada |
| `done` | Nenhum | Não usa; o fim do stream encerra | Nada |

Eventos de `/events`: `saudacao`, `alerta_ram`, `alerta_disco`, `alerta_cpu`, `orcamento`, `lembrete` e `info` vão para o card Avisos, e o que passa de `info` gera toast. `voz` e `nova_conversa` só mudam o estado. O Tributário acrescenta `agente`. O campo `at` não é usado: a hora mostrada é a da chegada ao HUD.

## 3. O que está parado ou pouco aproveitado

### 3.1 Consultado e não mostrado

- `/health`: `versao` e `modelos` não são lidos. A barra mostra "v4 · Claude" fixo.
- `/system/status`: `process_count`.
- `/voz`: `dono` e as situações `iniciando` e `reiniciando`. Só `parado` e `falhou` geram aviso.
- `/costs`: `fatia_req_pct`, `media_usd` e `requisicoes` aparecem no máximo em dica de mouse.
- `/audit/verify`: o HUD não chama. No principal essa rota dá erro (seção 3.5).
- O `motivo` da rota some assim que chega o pensamento.

### 3.2 O backend tem e o HUD não alcança

| Capacidade | Onde está | Rota HTTP | Vale em |
|---|---|---|---|
| Lembretes pendentes | `ReminderStore.pending()`; a saudação só diz quantos são | Não | Todos |
| Conversa atual | `dados/sessions/hud.json` | Não | Todos |
| Conversas arquivadas | `dados/sessions/arquivo/` | Não | Todos |
| Memória de longo prazo | `dados/memories/`, ferramenta `memory` | Não | Todos |
| Movimentos e desfazer | `MoveJournal.recent()` | Não | Principal, Tributário, IurisNotitia |
| Processos, GPU, rede, disco D: | `status_sistema`, `hardware_info`, `processos_pesados` | Não | Principal, Tributário, IurisNotitia |
| Gasto por dia | Tabela `usage`; a API só soma hoje e o mês | Não | Todos |
| Base de conhecimento | `KnowledgeBase.resumo()`, `buscar()` local e sem custo de API | Não | Todos |
| Fontes citadas | A saída de `buscar_conhecimento` traz fonte, rótulo, URL, vigência e aviso; só o modelo vê | Não | Todos |
| Roteador | `decide()` é determinístico e não custa nada | Não | Todos |
| Agentes | `/agentes`: estado, saúde, execuções, falhas, custo, últimas tarefas, versões, pausar, retomar | **Sim, sem tela** | Tributário |
| Agenda e progresso de estudo | `trilhum_agenda`, `trilhum_progresso`, `trilhum_planos`; `jarvis/estudos/` | Não (`/trilhum` dá 404) | TRILHUM |

### 3.3 Pontos cegos com a voz local (só no principal)

| Ponto | Evidência |
|---|---|
| Turno de voz invisível | `jarvis/voz/cliente.py:38` abre o próprio stream; `jarvis/api/server.py` só responde a quem pediu |
| Aprovação por voz sem card | O comentário em `jarvis/voz/conversa.py:188` diz "decidida pelo HUD", mas o HUD nunca recebe esse evento |
| Onda da fala fixa | `CosmosScene.jsx:186`; a energia só vem de `useJarvis.js:151` e `useConversation.js:130` |
| Estado atrasado em até 1 s | Batimento de 1 s em `jarvis/voz/servico.py:23`; a API só avisa no batimento (`jarvis/api/voz.py:73`) |
| Botões sem efeito | Ouvir e fone (`TopBar.jsx:48` e `:55`) mexem na voz do navegador, que fica parada enquanto o serviço é o dono |
| Estado de repouso impreciso | A barra mostra "Em espera", embora o serviço esteja ouvindo "Jarvis" |
| Mudo pode divergir | O HUD guarda o mudo no navegador, e `/voz` não informa o mudo do serviço |
| Resposta digitada fica muda | `useConversation.js:71` não fala porque "o serviço fala por ele mesmo", mas o serviço só fala o que ele perguntou. Falta decidir se isso é desejado |
| Microfone sem diagnóstico | Microfone em uso, reserva, silêncio digital e latência ficam só em `logs/voz.log` |

### 3.4 Código parado

- `src/spike/` (painel holográfico, modo palco, `?holo=1`, tecla P): marcado como descartável, sobrou do modo vidro revertido em 2160104, mas `App.jsx` ainda o importa.
- Branch local `claude/hud-esfera-logo`: 5 commits com o logo ORGATEC vivo, nunca mesclados e sem cópia no GitHub.
- Arquivos sem nenhuma referência no código: `orgatec-logo.png`, `orgatecIA.jpeg`, `orgatecIA.jpg`, `icons.svg`, `favicon.svg` (o ícone está embutido no `index.html`), `assets/hero.png`, `assets/react.svg`, `assets/vite.svg`.
- A sugestão "Briefing do dia" vira um turno comum: não existe ferramenta de briefing.

### 3.5 Defeitos achados (não corrigidos)

| Defeito | Evidência | Efeito |
|---|---|---|
| `/audit/verify` dá 500 no principal | Reproduzi em cópia do arquivo: a linha 2 de `dados/audit.jsonl` (23/10) tem `route: "chat"`, valor que o `Route` de hoje recusa; são 3 registros assim | A verificação quebra antes de terminar, então a integridade da cadeia do principal segue sem conferência. Tributário e TRILHUM respondem `integra: true` |
| `/system/status` trava o laço da API por 0,1 s | `psutil.cpu_percent(interval=0.1)` dentro de `async def` (`server.py:168`), a cada 3 s por HUD aberto | Pode causar microtravadas no streaming; não medi |
| Escalada normal parece erro | `session.py:326` manda `error`; o HUD mostra toast vermelho e alerta. A nova camada não vai ao HUD (`session.py:236`) | Susto sem motivo, e a estrela fica na camada antiga |
| Busca na web sem aviso ao vivo | `llm.py:164` só trata `content_block_delta`; o chip sai no fim (`session.py:334`) | Longos segundos sem dizer o que está acontecendo |
| Texto cortado em 1024 px | Dica do dock e "Fable · meta" cortados na tela real | Cosmético |
| Botões de modelo enganam o aluno do Trilhum | Com `JARVIS_PLANO`, o prefixo não troca o modelo, mas o dock mostra os botões | Só em instância de aluno |

## 4. Os quatro JARVIS

| | Principal | Tributário | TRILHUM | IurisNotitia |
|---|---|---|---|---|
| Branch e porta | `main`, 8000 | `jarvis-tributario`, 8002 | `jarvis-trilhum`, 8003 | `jarvis-iurisnotitia`, 8004 |
| Astro | Sol | Vênus | Marte | Netuno |
| Nome no HUD | Fixo no código | `marca.js` | `marca.js` | `marca.js` |
| Voz local | Sim | Não | Não | Não |
| Coluna esquerda | Sistema, Custo | Tributário, Cliente | Custo (Sistema some) | Sistema, Custo |
| Coluna direita | Avisos, Neural | Avisos, Neural, Sistema, Custo | Avisos, Neural | Avisos, Neural |
| Sugestões | PC e lembrete | As do principal | Trilhum e súmula | As do principal |
| Rotas extras | `/voz*` | `/painel/*`, `/agentes*` | Nenhuma | Nenhuma |
| Ferramentas extras | Nenhuma | Agentes | `trilhum_*` | Nenhuma |
| Perfil | Completo | Completo | Só Trilhum e jurídico: sem web, arquivos, disco nem leitura do Windows | Completo, voltado à base jurídica |

Hoje a API do Tributário tem um agente (`tributario`), 29 itens no painel (12 prazos e 17 de legislação) e **nenhum cliente cadastrado**. O TRILHUM também ganhou coach de constância, planos de aluno e avisos por WhatsApp, nada disso no HUD.

**Pontos de conflito no cherry-pick:** `App.jsx`, `TopBar.jsx`, `Overlays.jsx`, `CommandDock.jsx` e `styles/app.css`. A proposta B1 reduz esse custo, e componentes novos em arquivos novos evitam a maior parte dele.

## 5. Propostas

Letras em "Vale em": **P** Principal, **T** Tributário, **Tr** TRILHUM, **I** IurisNotitia.

### 5.1 Prioridade

| # | ID | Proposta | Tipo | Impacto | Esforço | Vale em |
|---|---|---|---|---|---|---|
| 1 | V1 | Fala que pulsa na voz local | Vivo | Alto | P | P |
| 2 | V2 | Estado da voz na hora | Vivo | Médio | P | P |
| 3 | V3 | Astro reage a ferramenta e aprovação | Vivo | Alto | M | Todos |
| 4 | V4 | Números vivos | Vivo | Médio | P | Todos |
| 5 | B1 | Perfil único de cada JARVIS | Base | Médio, e barateia o resto | P a M | Todos |
| 6 | B2 | Espelho do turno de voz | Base | **O maior** | G | P |
| 7 | B3 | Conversa volta depois do F5 | Base | Alto | M | Todos |
| 8 | I1 | Avisos com ação | Inteligente | Alto | M | Todos |
| 9 | I2 | Sugestões conforme o contexto | Inteligente | Alto | M | Todos |
| 10 | I3 | Modelo previsto ao digitar | Inteligente | Médio | M | Todos |
| 11 | I4 | Fontes visíveis | Inteligente | Alto em T, I e Tr | M | Todos |
| 12 | B4 | Turno com mais detalhe | Base | Médio | M | Todos |
| 13 | I5 | Avisos que ficam | Inteligente | Médio | M a G | Todos |
| 14 | I6 | Voz e microfone à vista | Inteligente | Médio | M | P |
| 15 | I10 | Agentes no HUD | Inteligente | Alto no T | M a G | T |
| 16 | I11 | Hoje no Trilhum | Inteligente | Alto no Tr | M a G | Tr |
| 17 | I12 | Biblioteca viva | Inteligente | Alto no I | M | I, depois T e Tr |
| 18 | I7 | Previsão antes do alerta | Inteligente | Médio | M | Custo em todos; disco em P, T, I |
| 19 | V5 | Turno à vista no card Neural | Vivo | Médio | M a G | Todos |
| 20 | V6 | Abertura com checagens reais | Vivo | Médio | P | Todos |
| 21 | V7 | Presença no título da aba | Vivo | Baixo a médio | P | Todos |
| 22 | V8 | Conexão visível | Vivo | Baixo a médio | P | Todos |
| 23 | V9 | Repouso e despertar da tela | Vivo | Médio | P a M | Todos |
| 24 | V10 | Cosmos respira com a máquina | Vivo | Baixo a médio | P | P, T, I |
| 25 | V11 | Áudio real no astro | Vivo | Médio | M | P |
| 26 | I8 | Linha do dia | Inteligente | Médio, alto em T e Tr | G | Todos |
| 27 | I9 | Memória e ações à vista | Inteligente | Médio | G | Todos |
| 28 | I13 | Cliente em foco | Inteligente | Alto, depois de cadastrar clientes | M | T |

Mockup antes do código: V5, I8, I9, I10, I11 e I12.

### 5.2 Base

**B1. Perfil único de cada JARVIS** (médio, P a M, todos)
- Muda: `marca.js` chega ao `main` com nome e sugestões. Depois, `/health` informa as capacidades, e o HUD liga cards e botões por elas, sem diferença de código entre branches.
- Arquivos: `src/lib/marca.js`, `TopBar.jsx`, `Overlays.jsx`, `CommandDock.jsx`, `App.jsx`, `index.html`, `jarvis/api/server.py`, `jarvis/config.py`.
- Dados: existem `assistente` nos três branches e `versao`. Faltam `capacidades` (voz, sistema, painel, agentes, plano) e `assistente` no `main`.
- Também corrige "v4 · Claude" fixo e os botões de modelo do aluno.

**B2. Espelho do turno de voz** (o maior impacto, G, Principal; plano primeiro)
- Muda: o turno pedido pela voz aparece no HUD como um digitado: pergunta, resposta, ferramentas, custo, pensamento e card de aprovação clicável.
- Arquivos: `jarvis/api/server.py`, `jarvis/core/contracts.py`, `jarvis/proactive/bus.py` ou canal novo, `jarvis/voz/cliente.py`, `hooks/useJarvis.js`, `lib/api.js`, testes dos dois lados.
- Dados: todos os eventos já existem. Faltam a difusão, a origem do turno e o texto da pergunta.
- Cuidados: a fila do barramento guarda 50 eventos e descarta os mais antigos, então trechos de texto precisam de canal próprio ou agrupamento. Só vai ao HUD a fala que virou pergunta, nunca a conversa da casa (decisão de 31/10, quando o log de texto foi desligado).

**B3. Conversa volta depois do F5** (alto, M, todos)
- Muda: ao abrir, o HUD pede as últimas mensagens e mostra um marcador quando a API começou conversa nova.
- Arquivos: `jarvis/core/session.py`, `jarvis/api/server.py`, `lib/api.js`, `hooks/useJarvis.js`, `lib/telaLimpa.js`.
- Dados: existem o histórico e o `nova_conversa` do evento `route`. Falta a rota que extrai só o texto, sem notas de sistema nem blocos de ferramenta.
- Cuidado: quem limpou a tela não pode ver tudo voltar no F5, então a limpeza precisa guardar até onde foi limpo.

**B4. Turno com mais detalhe** (médio, M, todos)
- Muda: início de busca na web ao vivo, escalada como aviso e não como erro, nova camada enviada ao HUD, área da pergunta no evento `route`.
- Arquivos: `jarvis/core/llm.py`, `jarvis/core/session.py`, `jarvis/core/contracts.py`, `hooks/useJarvis.js`.
- Dados: `Decision.area` existe e não é enviada. Falta tratar `content_block_start` no streaming e criar o evento de aviso.

### 5.3 Vivo

**V1. Fala que pulsa na voz local** (alto, P, Principal)
- Muda: enquanto o serviço fala, o HUD gera energia em ritmo de sílaba, como a bancada já faz (`cosmic-demo.jsx:26`). É simulação, não o áudio real (o real é a V11).
- Arquivos: `src/App.jsx` ou `hooks/useVozLocal.js`.
- Dados: o estado `falando` já chega. Não falta nada.

**V2. Estado da voz na hora** (médio, P, Principal)
- Muda: o serviço manda o batimento assim que o estado muda. Opcional: novo estado `captando` enquanto alguém fala, sem nenhum texto.
- Arquivos: `jarvis/voz/servico.py`, `jarvis/api/voz.py`, `lib/voice/servico.js`.
- Dados: `conversa.estado()` e `escuta.gravando` existem.
- Decisão sua: `captando` faria o sol reagir a qualquer conversa na sala. Pode ser vivo ou incômodo.

**V3. Astro reage a ferramenta e aprovação** (alto, M, todos)
- Muda: cada ferramenta dá um pulso no astro. A legenda diz o que está acontecendo ("Consultando a base", "Buscando na web"). A espera de aprovação vira uma fase própria, mais lenta e a 30 fps, e a barra mostra "Aguardando você".
- Arquivos: `hooks/useJarvis.js`, `App.jsx`, `Overlays.jsx`, `TopBar.jsx`, `cosmos/CosmosScene.jsx`, `cosmos/pacing.js`, `tests/pacing.test.mjs`.
- Dados: `tool` e `approval` já chegam. Não muda o shader.

**V4. Números vivos** (médio, P, todos)
- Muda: custo e anéis contam até o valor novo, o custo do turno sobe por um instante ("+US$ 0,0021"), o anel pulsa ao cruzar 75% e 90%, e a chegada de um aviso se destaca.
- Arquivos: `components/Gauges.jsx`, `components/Cards.jsx`, `styles/app.css`.
- Dados: existem.

**V5. Turno à vista no card Neural** (médio, M a G, todos; mockup)
- Muda: linha do tempo do turno (rota, pensamento, cada ferramenta com duração, primeira palavra, fim), e o motivo da camada fica fixo na tela.
- Arquivos: `hooks/useJarvis.js`, `components/Cards.jsx`, `styles/app.css`, nova `lib/turno.js` com testes.
- Dados: as durações podem ser medidas no navegador. A área depende da B4.

**V6. Abertura com checagens reais** (médio, P, todos)
- Muda: as frases passam a refletir o que foi conferido: API, voz e microfone, custo, painel ou agentes.
- Arquivos: `components/Overlays.jsx`, `App.jsx`.
- Dados: `/health`, `/voz`, `/costs`. Não cabe citar a auditoria antes de corrigir a rota.

**V7. Presença no título da aba** (baixo a médio, P, todos)
- Muda: o título mostra o estado e os avisos não vistos enquanto a aba está em segundo plano.
- Arquivos: `App.jsx` ou novo `hooks/usePresenca.js`.
- Dados: existem.

**V8. Conexão visível** (baixo a médio, P, todos)
- Muda: a barra separa online, reconectando e fora, inclusive quando só o `/events` caiu.
- Arquivos: `hooks/useJarvis.js`, `TopBar.jsx`.
- Dados: falta só guardar o estado que o laço de eventos já conhece.

**V9. Repouso e despertar da tela** (médio, P a M, todos)
- Muda: sem uso, os cards recuam e o cosmos ganha a tela. Voltam com mouse, voz ou aviso. Card minimizado pulsa quando chega algo novo.
- Arquivos: `App.jsx`, `styles/app.css`, `hooks/useCards.js`, `lib/telaLimpa.js`.
- Dados: existem.

**V10. Cosmos respira com a máquina** (baixo a médio, P, Principal, Tributário, IurisNotitia)
- Muda: a carga da CPU acelera um pouco a rotação da galáxia. Sem mudança de shader.
- Arquivos: `cosmos/CosmosScene.jsx`, `App.jsx`.
- Dados: `cpu_percent`. O TRILHUM não lê o sistema.

**V11. Áudio real no astro** (médio, M, Principal)
- Muda: o serviço manda o envelope de cada frase antes de tocá-la, e o nível do microfone só enquanto estiver ouvindo.
- Arquivos: `jarvis/voz/fala.py`, `jarvis/voz/servico.py`, `jarvis/voz/cliente.py`, `jarvis/api/voz.py`, `hooks/useVozLocal.js`, `App.jsx`.
- Dados: o áudio de cada frase já existe em `fala.py`. Faltam calcular o envelope e a rota. Só vai o nível, nunca o áudio.

### 5.4 Inteligente

**I1. Avisos com ação** (alto, M, todos)
- Muda: cada aviso traz botões. RAM: "Ver processos". Disco: "O que ocupa o C:". Depois, lembrete com "Adiar 10 min" e agente com "Ver resultado".
- Arquivos: `jarvis/proactive/bus.py`, `jarvis/proactive/monitors.py`, `lib/avisos.js`, `components/Cards.jsx`, `App.jsx`, testes dos dois lados. Adiar pede rota nova e `jarvis/proactive/reminders.py`.
- Dados: o texto já sugere a ação. Falta o campo `acoes` no evento. Cada clique vira um turno normal, com custo só se usado.

**I2. Sugestões conforme o contexto** (alto, M, todos)
- Muda: as sugestões saem de regras sem custo de API e continuam depois da primeira pergunta. Exemplos: disco alto, lembrete próximo, prazo que vence, bloco de estudo. Depois de cada resposta, o próximo passo segundo a ferramenta usada.
- Arquivos: novo `jarvis/proactive/sugestoes.py`, `jarvis/api/server.py`, `components/CommandDock.jsx`, nova `lib/sugestoes.js`.
- Dados: hora, sistema, lembretes, custo, nomes das ferramentas. No T, prazos; no Tr, agenda. Falta a rota. Vitória imediata no T e no I: trocar as sugestões sobre o disco C:.

**I3. Modelo previsto ao digitar** (médio, M, todos)
- Muda: enquanto digita, o dock mostra para onde a pergunta deve ir ("Opus · tributário · cerca de US$ 0,03") e a estrela já muda de tom.
- Arquivos: `jarvis/api/server.py`, `components/CommandDock.jsx`, `App.jsx`, `lib/api.js`.
- Dados: `decide()` é grátis; `media_usd` dá a estimativa, que é só uma média. No Tr vale `decidir()`, por causa do plano.

**I4. Fontes visíveis** (alto em T, I e Tr, M, todos)
- Muda: a resposta jurídica traz chips com lei, artigo, data, situação e link. Aviso de vigência aparece junto.
- Arquivos: `jarvis/tools/__init__.py`, `jarvis/tools/knowledge.py`, `jarvis/core/session.py`, `components/Transcript.jsx`, `styles/app.css`.
- Dados: a saída de `buscar_conhecimento` já traz tudo. Falta passar esses campos no evento `tool`.
- Combina com a regra do painel fiscal: dado sem fonte verificável não aparece como fato.

**I5. Avisos que ficam** (médio, M a G, todos)
- Muda: os avisos sobrevivem ao F5, e ao abrir o HUD aparece um resumo do que aconteceu com ele fechado.
- Arquivos: novo `jarvis/proactive/historico.py`, `jarvis/proactive/monitors.py`, `jarvis/api/server.py`, `hooks/useJarvis.js`, `lib/avisos.js`.
- Dados: `ProactiveEvent.at` existe. Falta gravar em SQLite.

**I6. Voz e microfone à vista** (médio, M, Principal)
- Muda: chip com o microfone em uso, aviso de reserva ou de silêncio digital, latência, mudo do serviço. Botões ouvir e fone somem enquanto o serviço é o dono. Útil para o K8 e para o viva-voz planejado.
- Arquivos: `jarvis/voz/servico.py`, `jarvis/voz/cliente.py`, `jarvis/api/voz.py`, `lib/voice/servico.js`, `TopBar.jsx`, `hooks/useConversation.js`.
- Dados: tudo existe no serviço. Falta incluir no batimento.

**I7. Previsão antes do alerta** (médio, M, custo em todos, disco em P, T, I)
- Muda: avisa quando a projeção passa do teto, antes dos 80%. Mostra a data provável do teto. Depois, quando o disco C: deve encher.
- Arquivos: `jarvis/proactive/monitors.py`, `components/Cards.jsx`; para o disco, tabela nova de amostras.
- Dados: `projecao_mes_usd` existe, mas é uma média simples por dia, fraca no começo do mês, então só deveria valer após alguns dias. Falta histórico do disco.

**I8. Linha do dia** (médio, alto em T e Tr; G; todos; mockup)
- Muda: card "Próximos" com contagem regressiva: lembretes, prazos fiscais ou blocos de estudo.
- Arquivos: rota `/hoje` por branch, novo `components/ProximosCard.jsx`, novo hook, `App.jsx`.
- Dados: lembretes em todos, `/painel/tributario` no T, `trilhum_agenda` no Tr. O JARVIS não tem acesso a agenda pessoal.

**I9. Memória e ações à vista** (médio, G, todos; mockup)
- Muda: painel com o que o JARVIS guardou, o que ele fez hoje e o que pode ser desfeito.
- Arquivos: rotas novas em `jarvis/api/`, novo componente e hook.
- Dados: `dados/memories/`, `audit.jsonl`, `MoveJournal.recent()`. Desfazer continua pedindo aprovação.

**I10. Agentes no HUD** (alto no T, M a G, Tributário; mockup)
- Muda: card com estado, saúde, execuções, falhas, custo e últimas tarefas, com pausar e retomar. Tarefas locais sem custo, como a anterioridade, podem ganhar atalho.
- Arquivos: novo `components/AgentesCard.jsx`, novo `hooks/useAgentes.js`, `App.jsx`, `styles/app.css`.
- Dados: `/agentes` já entrega tudo. Não falta backend.

**I11. Hoje no Trilhum** (alto no Tr, M a G, TRILHUM; mockup)
- Muda: card com os blocos de hoje, o que foi feito, pendências e desempenho por disciplina.
- Arquivos: novo `jarvis/api/trilhum.py`, `jarvis/api/server.py`, novo `components/TrilhumCard.jsx`, novo `hooks/useTrilhum.js`, `App.jsx`.
- Dados: `Trilhum` e `andamento.py` existem. Falta rota. A agenda já levou de 4 a 6 s para abrir, então precisa de cache e consulta espaçada.

**I12. Biblioteca viva** (alto no I, M, IurisNotitia, depois T e Tr; mockup)
- Muda: card com documentos, trechos e áreas, mais busca instantânea sem gastar API.
- Arquivos: novo `jarvis/api/conhecimento.py`, `jarvis/api/server.py`, novo `components/BibliotecaCard.jsx`, novo hook.
- Dados: `resumo()`, `buscar()` e `areas_em_uso()` existem. Fontes aprovadas e última coleta estão só no comando `status`.

**I13. Cliente em foco** (alto, M, Tributário)
- Muda: o cliente escolhido no card vira contexto da conversa, com atalhos como "Prazos deste cliente".
- Arquivos: `jarvis/core/contracts.py`, `jarvis/core/session.py`, `App.jsx`, `CommandDock.jsx`, `hooks/usePainelFiscal.js`.
- Dados: `/painel/clientes` existe, mas está vazio: só vale depois de cadastrar clientes. Ao Claude só vai dado mascarado.

## 6. Ordem recomendada

Situação em 06/11/2026: o pacote A foi mesclado no PR #24, e o B foi feito logo depois, com a sua decisão de mostrar o texto da voz quando ela vira pergunta.

| Pacote | Itens | O que você ganha | Tamanho |
|---|---|---|---|
| **A. Vivo já** | V1, V2, V3, V4 | O HUD reage de verdade, com quase nada no backend | Cerca de 150 linhas: plano e "execute" |
| **B. O HUD enxerga a voz** | B2, B3, B4 | Conversa por voz na tela, com aprovação clicável, e nada some no F5 | G: plano e "execute" |
| **C. Inteligente sem gastar** | B1, I1, I2, I3 | Avisos com botão e sugestões úteis, por regras | G: plano e "execute" |
| **D. Cada JARVIS com cara própria** | I4, I10, I11, I12 | Fontes, agentes, estudo e biblioteca | Um plano e um mockup por JARVIS |

Recomendo começar pelo A: entrega resultado visível rápido e não depende de nenhuma decisão de arquitetura. O B vem logo depois porque é o que mais muda o uso diário. No pacote C, a B1 vem primeiro: quanto mais cedo entrar, menos conflito nos cherry-picks seguintes.

## 7. Cuidados

- **Desempenho.** O cosmos já foi otimizado (sem `backdrop-filter`, 30 fps em repouso, resolução adaptativa). Efeito novo deve usar variável em JavaScript ou `transform` e `opacity` no CSS. No painel embutido do app, a CPU foi de 30% para 98% com o HUD aberto. Não tratei isso como medida, porque o painel estava oculto e pode rodar sem GPU: convém medir no Chrome antes do pacote A.
- **Privacidade.** Texto de voz só depois de virar pergunta. Nível de microfone é número, nunca áudio. CPF e CNPJ continuam mascarados antes do Claude.
- **Propagação.** Mudança comum entra no `main` e vai por cherry-pick; nunca merge do `main` no `jarvis-tributario`. Mudança só de HUD pede `npm run build` em cada pasta. Mudança na API pede reiniciar a instância.
- **Eventos novos.** `kind` em `ProactiveEvent` é uma lista fechada, e o Tributário já acrescentou `agente`. O serviço de voz também assina `/events`: evento novo precisa de `falar=False`.

## 8. Decisões que dependem de você

1. Qual pacote vem primeiro.
2. Texto da sua voz na tela do HUD: pode aparecer quando virar pergunta? (B2) **Decidido em 06/11/2026: sim.**
3. O sol pode reagir a qualquer fala na sala? (V2, estado `captando`)
4. Resposta digitada deve ser falada quando o serviço de voz está ativo?
5. `src/spike/`: aposentar em `_legado/`, ou o modo palco ainda interessa?
6. Branch `claude/hud-esfera-logo`: retomar ou deixar de lado?
