# _legado — código aposentado do JARVIS (2026-10-23)

Nada aqui foi apagado; foi movido com `git mv` quando o JARVIS 4.0 (pacote `jarvis/`) assumiu.

| Pasta/arquivo | O que era | Por que saiu |
|---|---|---|
| `jarvis_app_v1/` | v1: FastAPI + Gemini/ChatGPT, agenda e voz | importava o módulo `ai`, que não existe |
| `hyperagent_v2/` | v2: orquestrador + 7 sub-agentes, Ollama/Claude | shell livre e execução de código sem autenticação; roteamento por JSON |
| `api_v3/` | v3: backend do HUD (SSE), consciência, ChromaDB, OCR | `brain.py` quebrado (`NameError`), memória e consciência nunca ligadas |
| `gerar_jarvis.py`, `convert_to_pdf.py`, `launch.py` | scripts soltos | substituídos por `python -m jarvis` |
| `Modelfile.txt` | modelo Ollama `jarvis-otimizado` (llama3) | o modo local usa `gemma3:4b` |
| `docker-compose.yml`, `Dockerfile.hyperagent`, `requirements*.txt`, `start-jarvis.bat` | infraestrutura da v2/v3 | substituídos por `pyproject.toml` e o novo `start-jarvis.bat` |

O que será reaproveitado nas próximas fases: as funções de `hyperagent_v2/agents/*` (status do sistema,
processos, arquivos, CSV, cotações, clima) viram ferramentas tipadas na F3; `api_v3/memory.py` serve de base
para a memória vetorial na F2.

## Rollback

```bash
git log --oneline -- _legado            # acha o commit de aposentadoria
git revert <hash-do-commit>             # devolve tudo aos caminhos antigos
```

Backups completos anteriores à mudança: `D:\backup\jarvis-2026-10-23.git` (espelho git) e
`D:\backup\jarvis-workdir-2026-10-23.tgz` (árvore de trabalho).
