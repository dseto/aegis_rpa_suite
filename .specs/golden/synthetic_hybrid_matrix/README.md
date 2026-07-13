# Fixture sintética — matriz de casos do Code Generator Híbrido

Complementa `.specs/golden/real_portal_segura_001_v2/` (golden real, rico) e
`.specs/golden/synthetic_r1_merge_case/` (caso de merge pontual). Este golden
existe só para fechar as células da matriz de casos [a]-[h] do inventário em
`.specs/baseline-codegen-hibrido.md` que o golden real **não** exercita, mais
os testes negativos da linha de corte (Seção 2.2 de
`.specs/plano-codegen-hibrido-deterministico.md`).

**Não é um plano de execução realista de site nenhum** — é uma fixture
mínima, uma tela sintética genérica de "cadastro", desenhada só para acionar
cada branch de `classify_step` de forma isolada e legível. As FORMAS de campo
(nomes de chave, aninhamento, tipos) foram copiadas dos steps reais de
`projects/portal_segura/tests/001_teste/plano_execucao.json` /
`.specs/golden/real_portal_segura_001_v2/plano_execucao.json` e do
`select_native` real de
`projects/katalon_demo_form/tests/002_preenchimento_completo/plano_execucao.json`
— nenhum nome de campo foi inventado.

## Nota de precisão de nomenclatura

O enunciado desta tarefa cita os campos de coords do `select` customizado
como `original_coords_trigger`/`original_coords_option`. Essa é a forma do
**kwarg do runner** (`select_option_resilient(original_coords_trigger=...,
original_coords_option=...)`, ver Seção 2.1 do plano). No **plano JSON** em
si, o campo real (verificado em `st_010`/`st_027`/`sup_004` do golden real
v2) é `coords_trigger`/`coords_option`, sem o prefixo `original_`. Esta
fixture usa a forma real do plano (`coords_trigger`/`coords_option`) — o
mapeamento para o kwarg `original_coords_*` acontece no emissor, não no
schema do plano.

## Cobertura da matriz — nenhuma célula [a]-[h] vazia (golden real + esta fixture)

| Célula | Coberta por | Onde (golden) |
|---|---|---|
| [a] `optional` | **Esta fixture** (ausente no golden real) | `st_001` |
| [b] `parent`+`has_text` | Golden real (ex. `st_050`) **e** esta fixture | `st_002` |
| [c] `select` com `trigger_selector`/`coords_trigger`/`coords_option` | Golden real (15 steps `select`) **e** esta fixture | `st_003` |
| [d] `weak_selector: true` | **Esta fixture** (ausente no golden real) | `st_008` (com âncora), `st_009` (sem âncora) |
| [e] Padrão Q (`parent.has_text_original`) | Golden real (`st_062`) **e** esta fixture | `st_005` |
| [f] autocomplete com valor de negócio no seletor | Golden real (`st_023`/`st_024`/`st_025`) **e** esta fixture (positivo + negativo) | `st_006` (positivo), `st_007` (negativo) |
| [g] `sup_`/`skip` | Golden real (`sup_001`-`sup_004`) **e** esta fixture | `sup_001` |
| [h] `select_native` | **Esta fixture** (ausente no golden real) | `st_004` |

## Tabela step → célula → condição C → resultado esperado de `classify_step`

Condições C1-C10 conforme Seção 2.2 de
`.specs/plano-codegen-hibrido-deterministico.md`. "N/A" = condição não se
aplica ao tipo do step (nunca reprova por si só).

| step_id | Célula | Tipo | Condição decisiva | Resultado `classify_step` | Justificativa |
|---|---|---|---|---|---|
| `st_001` | [a] | click | **C2 falha** (`execution_hint: "optional"`) | **cognitive** | Decisão de emitir ou não o step é da LLM (contrato D6, Seção 2.3 "convenção de bloco-vazio"). |
| `st_002` | [b] | click | C1-C10 todas passam (C4/C9 N/A p/ click) | **deterministic** | `parent.has_text` não-nulo, sem `has_text_original`, sem token de negócio no seletor → `click_chained(parent={...}, child={"selector": "table #grid-tbody tr button:has-text('Detalhes')"})`. |
| `sup_001` | [g] | click | **C2** (`execution_hint: "skip"`) | **omit** | Contrato v2 vigente (D6): `sup_`/`skip` nunca vira código por default; só reintroduzido via `reintroduce_step_id` (Seção 3.1) ou correção QA explícita. |
| `st_003` | [c] | select (customizado) | C4 casa por **`trigger_selector`** (`fields["estado_civil_cliente"].selector == step.trigger_selector`); demais condições passam | **deterministic** | `_emit_select` → `select_option_resilient(option_text=row.get("estado_civil_cliente", ""), original_coords_trigger=(0.5, 0.6), original_coords_option=(0.5, 0.65), ...)`. `selector` do step é `""` de propósito (forma real dos 15 `select` do golden real) — o binding NUNCA usa esse campo vazio. |
| `st_004` | [h] | select_native | C4 casa por **`selector`** (`fields["nivel_experiencia_profissional"].selector == step.selector == "#nivel_experiencia"`, SEM `trigger_selector`); demais condições passam | **deterministic** | `_emit_select_native` → `select_option_native_resilient(option_text=row.get("nivel_experiencia_profissional", ""))`. Confirma o achado R1 da re-checagem: `select_native` nasce de `fill` em `<select>` e binda como `fill` (por `selector`), nunca por `trigger_selector`. |
| `st_005` | [e] | click | **C3 falha** (`parent.has_text_original` presente e diferente de `parent.has_text`, mais `sanitization_notes` com `padrao_q`) | **cognitive** | Padrão Q é sempre cognitivo (Seção 3.3) — o emissor nunca decide sozinho entre o literal sanitizado (`"cliente exemplo 12345678900 categoria"`) e uma composição dinâmica com `row`. |
| `st_006` | [f] positivo | click | C1-C9 passam; **C10 falha** — seletor contém `:has-text('Curitiba')` e `'Curitiba'` é `observed_value` de `cidade_cliente` em `dicionario.json` | **cognitive** | Caso C10/B1: emitir o literal seria hardcode que nenhum validador estático pega (`HARDCODED_TEXT_VAL` só olha kwarg `text_val`); o bot correto parametriza `child={"selector": f"div:has-text('{row.get('cidade_cliente', '')}')"}`. |
| `st_007` | [f] negativo | click | C1-C9 passam; **C10 passa** — seletor contém `:has-text('Nenhuma cidade encontrada')`, mas esse literal não casa nenhum `observed_value` de `dicionario.json` | **deterministic** | Teste negativo do emissor (Seção 4.1 item 4): prova que C10 é uma checagem precisa contra `observed_value` real, não um bloqueio genérico de qualquer `:has-text(...)` em painel de autocomplete — mensagens estáticas do próprio widget continuam determinísticas. |
| `st_008` | [d] positivo | click | `weak_selector: true`; **C5 passa** — `parent.has_text: "Confirmar Endereço"` é material de ancoragem mecânica | **deterministic** | `weak_selector` sozinho não força cognitive: com âncora (`parent.has_text` ou `text` do step p/ `:has-text(...)`), o emissor gera `click_chained(parent={"selector": ".card-endereco", "has_text": "Confirmar Endereço"}, child={"selector": "button.btn-icon"})` — mesma forma que `WEAK_SELECTOR_WITHOUT_ANCHOR` (`step_validator.py:1021-1065`) aceitaria. |
| `st_009` | [d] negativo | click | `weak_selector: true`; **C5 falha** — sem `parent`, sem campo `text`, sem `:has-text(...)` no seletor | **cognitive** | Sem nenhum material de ancoragem, nem o emissor nem a LLM podem inventar seletor — cai para cognitive (mesmo comportamento que hoje resultaria em `WEAK_SELECTOR_WITHOUT_ANCHOR` se emitido ingenuamente). |

## Contagens (`fidelity_summary`)

- `raw_events`: 10 (sem merges nesta fixture — 9 steps emitíveis `st_*` + 1 `sup_001`, cada um mapeado 1:1 a um evento bruto).
- `steps_required`: 8 (todos exceto `st_001`, que é `optional`).
- `steps_optional`: 1 (`st_001`).
- `steps_suppressed`: 1 (`sup_001`).
- `merges`: 0.
- `total_steps` (9) = `steps_required` (8) + `steps_optional` (1) — mesma convenção do golden real v2 (`total_steps: 63` = `steps_required: 63` + `steps_optional: 0`).
- `total_recorded_steps` (10) = `raw_events` (10), consistente com `merges: 0` (sem merge, nenhum evento bruto é colapsado — mesma relação `raw_events == array_length + merges` verificada em `synthetic_r1_merge_case`, onde `3 == 2 + 1`).

## O que esta fixture deliberadamente NÃO cobre

- Padrão N (menu suspenso `.sub-menu`/`.dropdown-menu`/`#menu-item-`, C6) — não é uma célula lettered [a]-[h] do inventário; fica fora de escopo desta tarefa.
- `pending_corrections`/C8 — exigiria um segundo artefato (`correcoes_acumuladas.json`) fora do par plano+dicionário pedido; não é célula da matriz [a]-[h].
- `filechooser` (fora de escopo do híbrido por design, Seção 8 do plano).
- Skills (`skills_used` não-vazio, C7) — condição global que joga o arquivo inteiro pro fluxo full-LLM; não há `skills_used` nesta fixture (implicitamente vazio, já que o campo não existe no plano — mesma convenção dos goldens existentes).
