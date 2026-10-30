# JARVIS HUD

Interface do J.A.R.V.I.S. 4.0: React 19 + Vite, cena WebGL2 (galáxia em expansão e sol cuja classe estelar muda
com o modelo em uso) e voz pelo navegador (Web Speech: mãos livres, palavra de ativação "Jarvis", aprovação por voz).

```bash
npm ci
npm run build    # gera dist/, que a API serve em http://127.0.0.1:8000
npm run dev      # desenvolvimento com recarga: http://localhost:5299
npm run lint
npm test         # divisor de frases da fala e correção de termos da voz
npm run build
```

No uso normal o HUD é buildado (`npm run build`) e servido pela própria API em `http://127.0.0.1:8000`, que
entrega o token na página. Com `npm run dev`, o Vite injeta o token lido de `../dados/.token`, e a API
(`python -m jarvis`) precisa estar rodando em `127.0.0.1:8000`.

- `src/cosmos/`: cena WebGL2 (`cosmic.html` é a bancada visual; em dev, `window.__cosmosStill({t})` desenha um
  quadro estático).
- `src/lib/voice/`: fala em streaming, gatilhos de voz e correção de termos. Para testar sem microfone, abra com
  `?voz=simulada` e use `window.__voiceInject(texto, final)`.
- `src/hooks/`, `src/components/`: conversa, aprovações, custos e telemetria.

Veja o [README do projeto](../README.md).
