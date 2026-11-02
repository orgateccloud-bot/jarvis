# _legado/supabase — leitura do progresso do Trilhum pelo Supabase (aposentada em 2026-11-02)

Nada foi apagado: `jarvis/estudos/sincronizacao.py` foi movido com `git mv` para `sincronizacao_supabase.py` quando
o Trilhum concentrou tudo no Firebase (commit `3559352` do Trilhum). O projeto Supabase da Trilha
(`cbzaghttykchvjqsnqyo`) também foi aposentado; o código dele está em `D:\01_Projetos_Ativos\Trilha\_legado\supabase`.

| Antes (Supabase) | Agora (Firestore) |
|---|---|
| `POST <url>/rest/v1/rpc/trilha_sync_get` com a chave publishable e o token | `sync/{uid}/planos/{plano}` (campos `json` e `em`) pelo Admin SDK (`jarvis/estudos/sync_trilhum.mjs`) |
| `JARVIS_TRILHUM_SYNC_URL`, `JARVIS_TRILHUM_SYNC_CHAVE`, `JARVIS_TRILHUM_SYNC_TOKEN` | `JARVIS_TRILHUM_UID` (o código de "Copiar código para o JARVIS"), `JARVIS_FIREBASE_CREDENCIAIS` e, no modo teste, `JARVIS_FIRESTORE_EMULADOR` |
| `Settings.trilhum_sync()` | `Settings.firebase()` e `SincronizacaoTrilhum.da_config(settings, salt)` |

O formato do JSON não mudou (`{app, plano, ts, data, em}`; o catálogo no plano `_planos`), e os modelos
`Progresso` e `FeedbackJarvis` continuam os mesmos em `jarvis/estudos/sincronizacao.py`.

## Rollback

Só funciona enquanto o Supabase da Trilha existir; depois de apagado o projeto, não há para onde voltar.

```bash
git log --oneline -- _legado/supabase   # acha o commit de aposentadoria
git revert <hash-do-commit>             # devolve o leitor do Supabase e as variáveis JARVIS_TRILHUM_SYNC_*
```
