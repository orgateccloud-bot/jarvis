# JARVIS HUD

Interface do J.A.R.V.I.S. 4.0: React 19 + Vite, cena WebGL2 (galáxia em expansão e sol cuja classe estelar muda
com o modelo em uso) e voz pelo navegador (Web Speech: mãos livres, palavra de ativação "Jarvis", aprovação por voz).

```bash
npm ci
npm run build    # gera dist/, que a API serve em http://127.0.0.1:8000
npm run dev      # desenvolvimento com recarga: http://localhost:5299
npm run lint
npm test         # fala, voz, ritmo de quadros, arranjo do vidro e palco holográfico
```

No uso normal o HUD é buildado (`npm run build`) e servido pela própria API em `http://127.0.0.1:8000`, que
entrega o token na página. Com `npm run dev`, o Vite injeta o token lido de `../dados/.token`, e a API
(`python -m jarvis`) precisa estar rodando em `127.0.0.1:8000`.

- `src/cosmos/`: cena WebGL2 (`cosmic.html` é a bancada visual; em dev, `window.__cosmosStill({t})` desenha um
  quadro estático).
- `src/lib/voice/`: fala em streaming, gatilhos de voz e correção de termos. Para testar sem microfone, abra com
  `?voz=simulada` e use `window.__voiceInject(texto, final)`.
- `src/hooks/`, `src/components/`: conversa, aprovações, custos e telemetria.
- `src/holo/`: modo vidro e palco holográfico (abaixo).

## Modo vidro e palco holográfico

Em telas de pelo menos 1280×680 com aspecto 1,45 ou mais, os cards viram painéis de vidro parados em volta de
um sol maior (raio 0,2 da altura): CPU e RAM, custo, modelos, neural, último turno e um decorativo. Enquanto o
JARVIS fala, uma onda de luz atravessa o sol. Telas menores mantêm o layout plano e a gaveta.

O palco holográfico abre pelo botão "Palco" no alto, por "/holo projetos" ou "/holo custos" no dock, ou por voz
("mostra os projetos", "mostra os custos", "fecha o palco"). Esses comandos são resolvidos no HUD, sem ir ao
núcleo. Esc fecha e as setas trocam de categoria. Ao abrir, o sol vai para a esquerda e encolhe, os painéis viram
blocos compactos, o palco 3D (Three.js) ocupa o centro e os detalhes ficam à direita; a conversa não sai do lugar.

| Categoria | Representação | Dados |
| --- | --- | --- |
| Projetos | constelação: nó por projeto (tamanho pelo último commit, cor pelo grupo) e ligações | instantâneo estático em `src/holo/conteudo/projetos.json` (pastas com git em `D:\01_Projetos_Ativos`) |
| Custos | barra por modelo, altura pelo custo do mês a partir de zero | telemetria real de `/costs` |

Decisões de desempenho (GTX 1660 SUPER, medidas com `nvidia-smi` e contador de quadros):

- painéis em DOM com CSS 3D, escala 1 e sem `backdrop-filter`; o palco é o único canvas extra, só na área dele;
- chamas do sol calculadas só na área absoluta do sol antigo (`limiteChamas` em `src/cosmos/sol.js`);
- `three` (0.186.1, fixado) fica num pedaço separado, baixado no ócio; a cena só nasce depois da transição do
  sol, com compilação assíncrona dos shaders; 30 fps girando e 60 fps só na entrada e na saída; ao fechar, o
  canvas e o contexto WebGL são descartados.

Posições: `src/holo/arranjo.js` (testado em cinco tamanhos de tela: nada cobre a conversa nem outro painel).
Estado e comandos do palco: `src/holo/palco.js`.

Veja o [README do projeto](../README.md).
