# JARVIS HUD

Interface do J.A.R.V.I.S. 4.0: React 19 + Vite, cena WebGL2 (galáxia em expansão e sol cuja classe estelar muda
com o modelo em uso) e voz pelo navegador (Web Speech: mãos livres, palavra de ativação "Jarvis", aprovação por voz).

```bash
npm ci
npm run dev      # http://localhost:5299 (a 5173 fica livre para outros projetos)
npm run lint
npm test         # divisor de frases da fala e correção de termos da voz
npm run build
```

Em desenvolvimento o Vite injeta o token da API lido de `../dados/.token`. A API (`python -m jarvis`) precisa estar
rodando em `127.0.0.1:8000`.

- `src/cosmos/`: cena WebGL2 (`cosmic.html` é a bancada visual; em dev, `window.__cosmosStill({t})` desenha um
  quadro estático).
- `src/lib/voice/`: fala em streaming, gatilhos de voz e correção de termos. Para testar sem microfone, abra com
  `?voz=simulada` e use `window.__voiceInject(texto, final)`.
- `src/hooks/`, `src/components/`: conversa, aprovações, custos e telemetria.

Veja o [README do projeto](../README.md).
