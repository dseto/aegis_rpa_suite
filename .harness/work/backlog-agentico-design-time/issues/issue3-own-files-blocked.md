# [design] Guard bloqueia escrita nos próprios arquivos de bookkeeping do harness e na saída canônica das skills de gate; escape sancionado (`harness task add-file`) inalcançável

## Contexto

O guard libera escrita em `.harness/work/**`, `docs/**`, e nos arquivos de contrato declarados em `files[]` da tarefa. Tudo mais é negado:

> `arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este path em files[])`

## Comportamento atual — três problemas encadeados

1. **`claude-progress.md` é gerado pelo próprio `compile-session`, mas é negado à escrita.** O agente é impedido de atualizar o arquivo de progresso **do próprio harness**. Auto-derrotante.

2. **A saída canônica das skills de gate é negada.** A skill `aegis-regression-gate` (e o padrão de outras) foi projetada para **anexar seu veredito** a um baseline em `.specs/plans/<...>.baseline-*.md`. Com contrato ativo, esse path não está em `files[]` de nenhuma tarefa → o artefato de aceitação do contrato **não pode ir para o lugar canônico dele**.

3. **O escape oficial não é alcançável.** A skill `plan` documenta `harness task add-file <id> <path>` para ampliar a superfície de uma tarefa. Mas `task` **não está na lista de subcomandos `harness` liberados pelo guard** (a lista inclui `compile`, `verify`, `supervise`, `review`, `team`, etc., mas não `task`). Resultado: o guard fecha a porta **e esconde a chave**.

4. **Bônus:** o guard também nega escrita no diretório de scratchpad do host (fora do repo, em `%TEMP%`), então nem staging de rascunho fora do repo funciona — a única área gravável de fato é `.harness/work/**`.

## Evidência (sessão real de uso)

- `Write` em `.specs/plans/portal-segura.baseline-001.md` (veredito do gate) → negado.
- `Write`/`Edit` em `claude-progress.md` → negado.
- `Write` em `%TEMP%\...\scratchpad\issue1.md` → negado.
- `harness task add-file ...` não está na superfície → também negado.

O veredito de aceitação teve que ser gravado em `.harness/work/**` (única área livre) e o baseline/progress ficaram pendentes de merge manual pelo humano.

## Impacto

- O harness impede o agente de manter os artefatos que o próprio harness/skills produzem.
- Fricção "sem saída": nem o path canônico, nem o escape sancionado, nem o scratchpad funcionam.

## Proposta

1. Tratar `claude-progress.md` como superfície gravável (como `docs/**` / `.harness/work/**`) — é bookkeeping do harness, não código que quebra teste.
2. Permitir escrita em outputs declarados de skills de gate (ex.: um campo `skill_outputs`/glob no perfil, ou tratar `.specs/plans/*.baseline-*.md` como superfície de documentação).
3. Adicionar `task` à lista de subcomandos `harness` liberados pelo guard, para que `harness task add-file` (o escape oficial) seja alcançável pelo agente.
4. Considerar liberar o diretório de scratchpad do host (fora do repo) para staging read/write.

## Não-objetivo

Não afrouxar floor/feature-lock nem a disciplina de escopo sobre **código de aplicação** (`aegis_*`/`src/**`). A proposta é só sobre bookkeeping do harness, saída de skills, e o escape já sancionado.
