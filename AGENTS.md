# AGENTS.md — Diretrizes para Agentes

<!-- harness:lifecycle:begin -->
## Agent Session Lifecycle (gerado — 16 passos, docs/project/ROADMAP.md Fase 2)

1. Ler `AGENTS.md`.
2. Rodar `init.sh`/`init.ps1` (deps + health check do profile).
3. Ler `claude-progress.md`.
4. Ler `feature_list.json`.
5. Checar `git log`.
6. Escolher exatamente UMA feature pendente.
7. Planejar a implementação da feature escolhida.
8. Implementar a mudança dentro do raio de impacto declarado.
9. Rodar `verify_cmd` da tarefa.
10. Se falhar: autocorrigir e re-rodar `verify_cmd` até passar.
11. Registrar a prova (evidência da verificação bem-sucedida).
12. Atualizar `claude-progress.md` com o estado atual.
13. Marcar a feature concluída em `feature_list.json`.
14. Documentar o que ficou quebrado, se houver.
15. Commit apenas em estado retomável.
16. Deixar a working tree limpa.

Detalhe de cada passo: ver `.harness/LIFECYCLE.md`.
<!-- harness:lifecycle:end -->
