# Baseline — Demanda "Code Generator Híbrido"

## Hash de commit congelado

`b5cc4e79f27fba399c66406201b5058cb03133a6` (branch `main`).

Confirmado válido via `git cat-file -e b5cc4e79f27fba399c66406201b5058cb03133a6`.

No momento desta captura, `git status --porcelain` mostrava apenas arquivos novos não
rastreados (`??`) — documentação solta (`.agents/skills/aegis_skills.md`, `.claude/CLAUDE.md`,
`.claude/settings.json`, `.gemini/`, `.mcp.json`, `.specs/plano-codegen-hibrido-deterministico*`,
`.specs/plans/motor_simulacao_humana_fiel.backlog.md`, `GEMINI.md`,
`aegis_*/aegis_*.md`, `docs/aegis_bot_generation_flow.md`, uma pasta de perfil de usuário
mal-formada) — e **nenhuma modificação (`M`) em nenhum arquivo `aegis_*`**. Ou seja, o código
de produção (runner, sanitizer, code generator, cockpit) estava idêntico ao commit acima.

## Bot de referência (compilado, congelado)

`projects/portal_segura/tests/001_teste/code/bot_producao.py`

**NUNCA regenerar este arquivo durante esta demanda.** Ele é o artefato de referência para o
gate de regressão (`aegis-regression-gate`) e para qualquer comparação "antes/depois" da
geração híbrida de código. Qualquer necessidade de regenerar deve ser tratada como uma tarefa
explícita e separada, nunca um efeito colateral de uma tarefa de investigação/captura.

## Goldens pré-existentes

- **`.specs/golden/real_portal_segura_001/`** — plano v1 puro (schema `"version": "1.0"`),
  63 steps, zero `execution_hint`, zero `sup_` (steps suprimidos). Capturado do Sanitizer
  **pré-refatoração** no commit `dc32ab3ffff26e5ea093ceae4947fbeb033eb291`. Contém também
  `gravacao.json`/`dicionario.json` golden (idênticos byte-a-byte à entrada real do projeto
  na época da captura).
- **`.specs/golden/synthetic_r1_merge_case/`** — plano v2 mínimo (sintético), 2 steps. Cobre
  um caso pontual de merge, não a matriz completa.

## Golden v2 rico (novo, desta captura)

**`.specs/golden/real_portal_segura_001_v2/`** — plano v2 rico (schema `"version": "2.0"`),
63 steps emitíveis + 4 suprimidos (67 entradas totais no array `"steps"`), gerado
re-sanitizando a MESMA gravação (`gravacao.json`/`dicionario.json`) de
`real_portal_segura_001/` com o Sanitizer v2 já commitado neste HEAD
(`b5cc4e79f27fba399c66406201b5058cb03133a6`). Ver `.specs/golden/real_portal_segura_001_v2/META.md`
para o procedimento completo, comando exato e checksums.

## Inventário da matriz de casos (plano v2 rico capturado)

Fonte: `.specs/golden/real_portal_segura_001_v2/plano_execucao.json` (67 entradas em
`"steps"`, 63 emitíveis + 4 `sup_*`).

| # | Caso | Presente? | Step_id(s) de evidência |
|---|------|-----------|--------------------------|
| [a] | Step `optional` | **NÃO** | — (nenhuma entrada com a chave `"optional"` em todo o plano) |
| [b] | Step com `parent` + `has_text` (não nulo) | **SIM** | `st_010`, `st_011`, `st_017`, `st_027`, `st_030`, `sup_004`, `st_031`, `st_033`, `st_039`, `st_044`–`st_049`, `st_050`, `st_057`, `st_062` |
| [c] | `select` com coords de trigger/option (`coords_trigger`/`coords_option` — schema atual; não usa a nomenclatura `original_coords_trigger`/`original_coords_option`) | **SIM** | `st_010`, `st_011`, `st_017`, `st_027`, `st_030`, `sup_004`, `st_031`, `st_033`, `st_039`, `st_044`–`st_049` (todos os steps `type: "select"` do plano) |
| [d] | `weak_selector: true` | **NÃO** | — (nenhuma entrada com `"weak_selector": true`; a lógica de score de confiabilidade existe em `sanitizer.py` mas não marcou nenhum seletor deste dataset como fraco) |
| [e] | Padrão Q (step com `parent.has_text_original` presente) | **SIM** | `st_062` |
| [f] | Click de opção de autocomplete com valor de negócio no seletor (forma real do `st_023`: `:has-text('<literal>')` cujo literal é um `observed_value` do `dicionario.json`, com `parent.has_text` nulo) | **SIM** | `st_023` (`"Hyundai"`), `st_024` (`"Creta"`), `st_025` (`"Creta Limited 1.0 Turbo Flex"`) — todos os 3 literais confirmados como `observed_value` em `.specs/golden/real_portal_segura_001/dicionario.json`. (Existem 2 outras entradas visualmente parecidas, `sup_001` e `sup_003`, mas seus literais — `"Sexo"`, `"Combustível"` — são rótulos de campo, não valores de negócio observados, e portanto **não** contam para este caso; ambas já estão suprimidas.) |
| [g] | Steps `sup_`/`skip` | **SIM** | `sup_001`, `sup_002`, `sup_003`, `sup_004` (4 no total; nenhum step com `"type": "skip"` — a supressão neste plano é sinalizada via prefixo `sup_` + campos `execution_hint`/`suppression_reason`, não via um `type` dedicado) |
| [h] | `select_native` | **NÃO** | — (nenhuma entrada com `"type": "select_native"`; todos os 15 steps de seleção usam `"type": "select"`) |

**Casos ausentes neste dataset ([a] `optional`, [d] `weak_selector`, [h] `select_native`):** o
dataset real de `portal_segura/tests/001_teste` simplesmente não exercita essas três formas —
não há field opcional no fluxo gravado, nenhum seletor caiu abaixo do limiar de confiabilidade
que dispara `weak_selector: true`, e não há `<select>` HTML nativo (só Angular Material
`mat-select`, que o Sanitizer trata como `type: "select"` com trigger/option). Isso define o
escopo de **[SUBAGENTE 02]**: qualquer verificação da geração híbrida para esses 3 casos
precisa de um plano sintético adicional (nos moldes de
`.specs/golden/synthetic_r1_merge_case/`) — este golden real não cobre.

## Regras de reprodução determinística

- `AEGIS_COGNITIVE_ENABLED=false` é obrigatório ao rodar o Sanitizer para qualquer captura
  golden — sem isso, `refine_semantics_with_llm()` reescreve `business_description` a cada
  execução via LLM, quebrando a comparação byte-a-byte.
- `"generated_at"` e `"test_dir"` no topo de `plano_execucao.json` nunca são
  byte-idênticos entre capturas (timestamp + nome da pasta temporária usada). Uma comparação
  de regressão deve ignorar/normalizar esses 2 campos e comparar `"total_steps"` + o array
  `"steps"` inteiro.

## O que NÃO foi tocado nesta captura

- `projects/portal_segura/tests/001_teste/` (incluindo `bot_producao.py`) — apenas lido.
- `.specs/golden/real_portal_segura_001/` (golden v1 pré-existente) — apenas lido.
- `aegis_sanitizer/sanitizer.py` e qualquer outro módulo `aegis_*` — apenas executado, nunca
  modificado.
