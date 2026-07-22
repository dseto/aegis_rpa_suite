# [DX] boundary_guard bloqueia comandos shell read-only sem valor de segurança

## Contexto

O `boundary_guard.py` (hook PreToolUse gerado pelo `compile-session`) só libera, no Bash, comandos que prefixam a superfície compilada do contrato (`verify_cmd`/lint/typecheck/build/install/git local/subcomandos `harness`). Qualquer outro é negado com:

> `comando fora da superficie compilada do contrato (verify_cmd/lint/typecheck/build/install/git local); replaneje via /harness-creator:plan se precisar de outro comando`

## Comportamento atual

Utilitários **read-only** de inspeção são negados, mesmo sobre arquivos de scratchpad/log temporários e sem efeito colateral:

- `tail`, `head`, `wc`, `grep`, `echo`
- Pipes de filtro read-only encadeados a um comando permitido (`pytest ... | head`, `harness verify --help | head`)

## Evidência (sessão real de uso)

Com contrato ativo, todos bloqueados:

- `wc -l <log no scratchpad>`
- `python -m harness.cli verify --help | head -40` (bloqueado pelo `| head`)
- `tail`/`grep` sobre `.output` de tarefas em background

O agente foi forçado a rotear tudo para as ferramentas Read/Grep do host. Funciona, mas é atrito puro: ler o final de um log virou paginação manual com `offset/limit`.

## Impacto

- Zero ganho de segurança (leitura pura).
- Custo cognitivo/round-trips constante em qualquer sessão que inspecione logs.
- A mensagem sugere "replaneje via /plan" — desproporcional para um `wc -l`.

## Proposta

Allowlist fixa de utilitários read-only sempre liberada (independente do contrato): `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `echo`, `ls`, `find` (sem `-delete`/`-exec`). E permitir esses filtros **após pipe** de um comando já permitido (`<allowed> | head -N`).

## Não-objetivo

Não afrouxar runtime floor (segredos/rede/push) nem feature-lock (`passes:true` só com evidência verde).
