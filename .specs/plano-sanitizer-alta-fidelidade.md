# Plano de Refatoração — Sanitizer de Alta Fidelidade (Fase 2: de "Deletar" para "Classificar")

**Data:** 2026-07-11
**Módulo alvo:** `aegis_sanitizer/sanitizer.py`
**Módulos impactados:** `aegis_sanitizer/step_validator.py`, `aegis_sanitizer/code_generator.py`, `aegis_cockpit/static/index.html`, `aegis_mentor/skills/rpa-copilot-coder.md`, `docs/`
**Módulos que NÃO mudam:** `aegis_runner/runner.py`, `aegis_cockpit/cockpit.py` (backend), `aegis_blackbox/recorder.py`
**Revisão 2026-07-11 (rodada 1, `plan-critic`):** achado principal — a alegação original de que `aegis_cockpit/cockpit.py` "não quebra" estava incompleta (o backend não quebra; o frontend `static/index.html` quebra e entrou em escopo via T5b).
**Revisão 2026-07-11 (rodada 2, segunda opinião independente, modelo diferente):** 2 achados BLOQUEANTES corrigidos — (1) Seção 5.1 não renomeia mais `STEP_ID_MISMATCH`, pois isso quebraria o gatilho de autocorreção de ordem em `code_generator.py:603` para todo projeto v1 já existente; (2) o interleave de `sup_` na Seção 8/T2 deixou de ser um sort global por `position_anchor` (que reordenaria os `st_` entre si) e virou merge-insert (preserva a ordem dos `st_` intocada). Também corrigidos: exemplo canônico do schema (Seção 3, select supersedido), campo fantasma `dedup_group` (Seção 6.1), 3º ponto de renderização do prompt não mapeado (Seção 6.2), citação de linha `cockpit.py` (Seção 7), guard `alreadyMerged` e fallback legado ausentes da correção da Cockpit UI (T5b).
**Revisão 2026-07-11 (rodada 3, terceira opinião independente, verificação linha-a-linha contra o código real):** os 2 fixes bloqueantes da rodada 2 foram confirmados corretos na intenção e todas as citações de linha novas batem com o código real (`code_generator.py:603/826-831/1148/1329-1334/1353-1356/1456`, `sanitizer.py:760-761/925-1102/1029`, `step_validator.py:349/383-397/732/834` — todas conferidas por leitura direta). 4 problemas novos, menores mas reais, corrigidos: (1) `position_anchor`/"eventos-fonte" (Seção 8) não definia COMO extrair índices de um `st_step` que tem `merged_from` ou `source_events` em vez de `original_index` simples — ler só o campo raiz dá o valor ERRADO (não só impreciso) sempre que `choose()` elege o clique mais recente como sobrevivente, o que é exatamente o caso da própria fixture de [SUBAGENTE 02]; adicionada definição obrigatória de `_source_indices(step)`. (2) O passo "ORDEM" da Seção 5.1 não excluía ids fora do plano (extra/alucinados pela LLM — o erro mais comum deste pipeline) antes de mapear `code_id → índice no plano`; sem esse filtro, um lookup por valor ingênuo lança exceção não tratada nesse caso comum, o que o `code_generator.py` converteria em abort fatal do Ralph Loop — corrigido para filtrar por `emit_allowed` primeiro. (3) Seção 6.1 atribuía a linha `code_generator.py:1148` à função `_build_scoped_edit_plan`; na verdade essa linha está em `_surgical_correct_scoped` (`_build_scoped_edit_plan` só localiza blocos de código, nunca recebe `plan_steps`) — corrigido. (4) O backlog (T6/[SUBAGENTE 09]) citava `position_anchor` como exemplo de "campo aditivo" que poderia aparecer num step colapsado, contradizendo a própria Seção 8/6.1 do plano (que afirma duas vezes que esse campo NUNCA é persistido) — corrigido para `step_role`/`source_events`.

---

## 1. Diagnóstico: inventário das operações destrutivas atuais

Levantamento com evidência de linha (estado atual do repo):

### 1.1 Destruição na origem — `gravacao.json` é reescrito sem os eventos removidos

`sanitize()` deleta eventos da lista e **salva o arquivo por cima** (`sanitizer.py:222-227`). A telemetria bruta é perdida em disco na primeira sanitização. Qualquer decisão errada de dedup é irrecuperável sem re-gravar. Este é o ponto mais grave em relação ao novo paradigma — a fidelidade não é perdida só no plano, é perdida no artefato-fonte.

### 1.2 Bloco de deleção de eventos (`sanitize()`, `sanitizer.py:152-201`)

| Regra | Linhas | O que deleta | Risco de fidelidade |
|---|---|---|---|
| R1 — cliques consecutivos no mesmo seletor | 161-165 | 2º clique idêntico seguido | Baixo (mesmo widget), mas duplo-clique intencional é perdido |
| R2 — cliques em overlay genérico CDK / backdrop / "Nenhum resultado" | 167-178 | Clique inteiro | **Alto** — clique em backdrop é exatamente o gesto de "fechar overlay invisível" que o usuário citou como gatilho essencial |
| R3 — clique em painel autocomplete órfão (sem fill prévio) | 180-188 | Clique inteiro | Médio — heurística de painel stale pode errar |
| R4 — fill duplicado (mesmo cenário+seletor+valor) | 190-197 | Fill inteiro. **Não é consecutivo**: `seen_fills` é um dict que cobre a gravação inteira | **Alto** — um re-preenchimento tardio (re-disparo de validação, blur trigger, wizard revisitado) é engolido. O próprio framework já reconhece esse padrão como essencial: existe `required_reopen` em `correcoes_acumuladas.json` e `_recover_via_recent_fills` no runner justamente para re-fills que o bot deixou de fazer |

### 1.3 Reordenação física (Padrão P, `sanitizer.py:135-150`)

Pares autocomplete gravados invertidos são fisicamente trocados na lista de eventos. Correto para execução, mas a ordem original da gravação se perde sem rastro.

### 1.4 Deleções/mutações no nível do plano (`_write_execution_plan`, `sanitizer.py:925-1102`)

| Operação | Linhas | Efeito destrutivo |
|---|---|---|
| Filtro `allowed_types = {click, fill, filechooser}` | 929, 976-979 | Annotations e demais eventos ficam fora do plano (só aparecem no relatorio.md) |
| Padrão Q (`sanitize_has_text`) | 949-974, 1058 | Token dinâmico é removido do `has_text`; valor original não é preservado em lugar nenhum do plano |
| Achatamento `label:has-text(...) input` → `label` | 1053-1056 | Seletor original reescrito, `parent` descartado, sem rastro |
| `text` do clique não serializado | 1024-1029 | Contexto do texto clicado não chega ao Code Generator (só via `description`) |
| `_dedup_consecutive_clicks` | 831-923 | Merge de cliques do mesmo widget: evento absorvido some sem rastro (`choose()` decide o seletor sobrevivente) |
| `_reorder_dropdown_pairs` | 686-763 | Colapso abridor+opção → 1 step `select` (necessário e correto), mas os 2 eventos físicos originais somem sem rastro; steps intercalados são movidos para depois sem marcação |
| `_drop_redundant_select_corrections` | 766-800 | Select anterior (correção do usuário durante gravação) é deletado |
| `_drop_redundant_pretrigger_clicks` | 803-829 | Clique fantasma pré-select é deletado |
| `step_id` posicional `st_{i+1:03d}` | 1079 | Qualquer mudança de resultado do dedup desloca TODOS os ids seguintes — instabilidade que já forçou o workaround de herança de `flaky` por `(type, selector)` (linhas 936-947) |

### 1.5 O que já é bom e deve ser mantido como está

- `fix_encoding`, normalização de datas — cosméticos, não-destrutivos semanticamente.
- `refine_semantics_with_llm` — puro enriquecimento (chaves semânticas + `business_description`).
- Propagação de `fallback_selectors` (1010-1023) — puro enriquecimento com sanitização coerente.
- Flag `weak_selector` (1000-1002) — classificação, não deleção. **Este é o modelo a seguir**: o sanitizer marca, o validador cobra, o Code Generator decide como ancorar.
- Conversão `fill` em `<select>` → `select_native` — reclassificação semântica correta.

---

## 2. Decisões de arquitetura (o novo contrato)

### D1 — `gravacao.json` para de perder eventos

O bloco R1-R4 vira `_classify_raw_events(events)`: **nenhum evento é removido**; cada evento classificado como ruído recebe uma tag in-place:

```json
{
  "type": "click",
  "selector": ".cdk-overlay-backdrop",
  "sanitizer_class": { "role": "overlay_noise", "keep": false, "reason": "clique em backdrop genérico de CDK" },
  "original_index": 14
}
```

- Todo evento ganha `original_index` antes de qualquer reordenação (Padrão P continua trocando a ordem física — a execução precisa disso — mas o rastro fica).
- `gravacao.json` reescrito continua sendo o contrato do pipeline (encoding corrigido, descrições de negócio), agora **superset** do que era: mesma informação + tags. Quem quiser a visão "limpa" filtra por `sanitizer_class.keep != false`.
- O recorder segue sobrescrevendo `gravacao.json` a cada re-gravação (lição nº 4 do CLAUDE.md permanece válida — re-sanitizar após re-gravar).

### D2 — Plano v2: classificar em vez de deletar, com dois espaços de id

Todos os eventos de interação entram no array `steps`, com um contrato de execução explícito:

- `execution_hint`: `"required"` (default; campo ausente = required — retrocompatibilidade total com planos v1) | `"optional"` | `"skip"`.
- **Dois espaços de id:**
  - Steps emitíveis (`required`/`optional`) recebem `st_NNN` numerados **exatamente na mesma sequência que o pipeline atual produz**. Como a lógica de detecção não muda (só o efeito muda de "deletar" para "marcar"), os steps emitíveis de uma mesma gravação são idênticos aos de hoje → **zero drift de step_id**. `correcoes_acumuladas.json`, baselines do regression gate e bots já compilados continuam válidos.
  - Steps suprimidos recebem `sup_NNN`, intercalados no array na sua posição física original.
- Isso é deliberadamente diferente de numerar tudo sequencialmente: numerar suprimidos com `st_` deslocaria todos os ids em projetos existentes, quebrando correções acumuladas e baselines.
- Bônus de estabilidade: como nada é mais deletado, uma decisão de classificação borderline que mude entre re-sanitizações **não desloca mais a numeração** dos steps emitíveis vizinhos (hoje desloca tudo).

### D3 — Merge continua merge; supressão vira step classificado

Distinção conceitual importante:

- **Mesmo gesto físico contado 2x** (cliques consecutivos no mesmo widget, clique fantasma pré-trigger, par abridor+opção do dropdown): continua colapsando em 1 step — reintroduzir o duplicado seria errado por definição. A fidelidade fica em `merged_from` (lista de `original_index` dos eventos absorvidos, com snapshot de seletor/coords).
- **Gesto físico distinto julgado redundante** (R2 overlay, R3 painel órfão, R4 re-fill, select supersedido por correção do usuário): vira step `sup_NNN` com `execution_hint: "skip"`, `step_role` e `suppression_reason`. O Code Generator vê e tem a palavra final.

### D4 — Transformações de seletor viram não-destrutivas

- Padrão Q: `parent.has_text` continua saindo sanitizado (é o valor operacional correto), mas ganha irmão `has_text_original` quando houve remoção de token + `sanitization_notes: ["padrao_q: removido token 'PRO-80935'"]`.
- Achatamento `label>input`: ganha `selector_original` no step.
- O campo operacional mantém o MESMO nome de hoje (`has_text`, `selector`) — validador e runner não percebem diferença.

### D5 — Validador hint-aware (subsequência obrigatória)

`validate_bot_against_plan` deixa de exigir igualdade total e passa a validar:

1. Todos os `step_id` com hint `required` presentes no código, na ordem relativa do plano (subsequência).
2. Ids emitidos que sejam `optional`/`skip` são aceitos **desde que existam no plano e respeitem a ordem relativa** (checagem por índice-no-plano monotônico).
3. Ids fora do plano continuam `EXTRA_STEPS` (a tolerância existente de `required_reopen` permanece).
4. `COUNT_MISMATCH` passa a comparar apenas o subconjunto required.

### D6 — Code Generator tem a palavra final

- Steps `skip` aparecem no prompt em forma compacta (1 linha: id, tipo, seletor, motivo), com instrução: "não emitir por default; emitir apenas se uma correção pendente ou o contexto do fluxo exigir (ex.: fechar overlay, re-disparar validação); se emitir, usar o `step_id` do plano e manter a ordem relativa".
- Steps `optional` aparecem completos, a critério da LLM com justificativa em comentário.
- Se uma correção acumulada apontar que falta um gatilho (blur, fechar overlay), a LLM pode **reintroduzir o `sup_NNN` já existente** em vez de inventar um passo sem id — o validador aceita porque o id está no plano. Isso substitui, no médio prazo, parte da briga atual do `required_reopen` (a chamada extra passa a ter id legítimo).

---

## 3. Esquema do `plano_execucao.json` v2

```json
{
  "version": "2.0",
  "test_dir": "001_teste",
  "generated_at": "2026-07-11T10:00:00",
  "total_steps": 42,
  "total_recorded_steps": 51,
  "fidelity_summary": {
    "raw_events": 58,
    "steps_required": 41,
    "steps_optional": 1,
    "steps_suppressed": 9,
    "merges": 7
  },
  "steps": [
    {
      "step_id": "st_012",
      "type": "click",
      "selector": "#btn-buscar-cpf",
      "description": "Buscar dados do CPF",
      "scenario": "default",
      "text": "Buscar",
      "coords": [0.4512, 0.3321],
      "merged_from": [{ "original_index": 15, "selector": "span.mat-button-wrapper", "reason": "clique consecutivo no mesmo widget" }]
    },
    {
      "step_id": "sup_003",
      "execution_hint": "skip",
      "step_role": "overlay_noise",
      "suppression_reason": "Clique em backdrop genérico de CDK — provável gesto de fechar overlay. Reintroduzir se um passo seguinte falhar por overlay aberto.",
      "type": "click",
      "selector": ".cdk-overlay-backdrop",
      "description": "Fechar overlay",
      "original_index": 16
    },
    {
      "step_id": "sup_004",
      "execution_hint": "skip",
      "step_role": "superseded_correction",
      "superseded_by": "st_013",
      "suppression_reason": "Usuário selecionou 'Diesel' e corrigiu para 'Álcool' logo em seguida, durante a gravação.",
      "type": "select",
      "dropdown_label": "Combustível",
      "option_text": "Diesel",
      "source_events": [20, 21]
    },
    {
      "step_id": "st_013",
      "type": "select",
      "dropdown_label": "Combustível",
      "option_text": "Álcool",
      "trigger_selector": "mat-select#combustivel",
      "option_selector": "[role='option']:has-text('Álcool')",
      "coords_trigger": [0.3, 0.5],
      "coords_option": [0.3, 0.58],
      "step_role": "composite_select",
      "source_events": [23, 24],
      "description": "Selecionar 'Álcool' em 'Combustível'"
    },
    {
      "step_id": "st_020",
      "type": "click",
      "selector": "label:has-text('Aceito os termos')",
      "selector_original": "label:has-text('Aceito os termos') input",
      "description": "Aceitar termos",
      "parent": {
        "selector": "tr.linha-cobertura",
        "has_text": "Vidros Completos",
        "has_text_original": "PRO-80935 Vidros Completos"
      },
      "sanitization_notes": ["padrao_q: removido token dinâmico 'PRO-80935' de parent.has_text"]
    }
  ]
}
```

Catálogo de `step_role` para steps suprimidos: `overlay_noise` (R2), `stale_panel_click` (R3), `redundant_refill` (R4), `raw_duplicate_click` (R1 quando não-consecutivo pós-merge), `superseded_correction`, `phantom_click`. Para steps emitíveis: ausente (default `primary`) ou `composite_select`.

`fidelity_summary.merges` conta **operações de merge que absorveram pelo menos 1 evento** (chamadas de `_merge_consecutive_clicks` que reduziram N eventos para 1 step), não o total de eventos absorvidos — ex.: se um step único absorve 3 cliques consecutivos do mesmo widget, isso é `merges: 1` (uma operação), não `merges: 3`. Campo informativo para o relatório/UI, não usado por nenhuma validação — sem exigência de exatidão milimétrica, só de não regredir entre execuções do mesmo projeto.

Regras de retrocompatibilidade do schema:

- Campo ausente `execution_hint` ⇒ `required`. Plano v1 lido pelo validador novo se comporta exatamente como hoje.
- `total_steps` mantém a semântica atual (= emitíveis) para não mudar o que o Cockpit exibe; `total_recorded_steps` é novo.
- `flaky` e `weak_selector` inalterados; herança de `flaky` por `(type, selector)` passa a casar apenas contra steps emitíveis.
- **Invariante de schema (achado da 2ª revisão independente, 2026-07-11 — declarado para impedir estado inconsistente):** `step_id.startswith("sup_") ⟺ execution_hint == "skip"`. Um `st_` nunca tem `execution_hint: "skip"`; um `sup_` sempre tem. T2 deve garantir isso por construção (são espaços de numeração disjuntos, nunca hidratados fora desse par); T3 pode opcionalmente assertar o invariante como sanity-check em `test_write_execution_plan_v2.py`, não como regra de negócio nova.

---

## 4. Preservação das lógicas valiosas (mapa função → novo comportamento)

| Função atual | Detecção | Novo efeito |
|---|---|---|
| Bloco R1-R4 em `sanitize()` | **idêntica** | Extraída para `_classify_raw_events()`; tag em vez de `continue`/descarte; evento permanece em `gravacao.json` e vira `sup_` no plano |
| Padrão P (inversão autocomplete) | idêntica | Mantém a troca física (necessária p/ execução) + `original_index` preserva rastro |
| `_dedup_consecutive_clicks` | idêntica (incl. guard `texts_differ` e `choose()` de seletor) | Renomeada `_merge_consecutive_clicks`; absorvido vai para `merged_from` do sobrevivente |
| `_reorder_dropdown_pairs` | idêntica (incl. `_lookup_dropdown_label_by_value`) | Step `select` colapsado ganha `step_role: "composite_select"` + `source_events`; steps intercalados movidos ganham `reordered_from: <original_index>` |
| `_drop_redundant_select_corrections` | idêntica (prova via `parent.has_text` contendo `option_text` anterior) | Renomeada `_mark_superseded_selects`; select anterior vira `sup_` com `superseded_by` |
| `_drop_redundant_pretrigger_clicks` | idêntica (distância < 0.05 do `coords_trigger`) | Renomeada `_mark_phantom_pretrigger_clicks`; clique vira `sup_` `phantom_click` (é o mesmo gesto físico, mas manter como `sup_` em vez de `merged_from` é mais barato aqui, pois o step já existe como entidade separada) |
| Padrão Q (`sanitize_has_text`) | idêntica | Valor operacional continua sanitizado; adiciona `has_text_original` + `sanitization_notes`. Fallback_selectors: mesma sanitização de hoje (sem campo original — anotar em `sanitization_notes` basta) |
| Achatamento `label>input` | idêntica | Adiciona `selector_original` |
| `weak_selector`, `fallback_selectors`, herança `flaky` | idêntica | Inalteradas (herança flaky restrita a emitíveis) |
| Relatório: auditoria Padrão Q, anti-bot, low-confidence | idêntica | Inalteradas |

**Invariante de migração (teste de ouro):** para qualquer gravação, a sequência de steps emitíveis (`st_`) do plano v2 deve ser **byte-idêntica** (mesmos ids, tipos, seletores, campos operacionais) à sequência do plano v1 atual, exceto pelos campos novos aditivos. Isso é verificável mecanicamente e é o gate principal da refatoração.

---

## 5. Impacto no `step_validator.py`

### 5.1 `validate_bot_against_plan` (linha 349)

Reescrever a comparação:

```
emit_required = [s.step_id for s in steps se hint em (ausente, "required")]
emit_allowed  = set(todos os step_id do plano)  # required + optional + skip
code_ids      = extract_step_ids_from_code(bot_code)  # inalterado

1. EXTRA_STEPS: ids em code_ids fora de emit_allowed (mantém tolerância required_reopen).
2. MISSING_STEPS: ids required ausentes de code_ids.
3. ORDEM: **primeiro filtre `code_ids` para a subsequência `code_ids_in_plan = [cid for cid in code_ids if cid in emit_allowed]`** (achado da 3ª revisão independente, 2026-07-11 — sem esse filtro explícito, "mapear cada code_id para seu índice no plano" é ambíguo para um id que NÃO está no plano: um lookup por valor tipo `planned_ids.index(cid)` lança `ValueError`/crasha nesse caso, e um id extra/alucinado no código é o cenário MAIS COMUM de erro de LLM neste pipeline, não uma raridade — é exatamente o que o passo 1 (EXTRA_STEPS) já existe para reportar, e é o motivo do bloco `PROIBIÇÃO ABSOLUTA` sobre `EXTRA_STEPS` no prompt em `code_generator.py:1463-1469`; hoje esse caso NUNCA derruba o validador, só produz mismatches posicionais adicionais — a versão nova não pode regredir para uma exceção não tratada, que o `code_generator.py` converte em `RuntimeError` fatal e aborta o Ralph Loop inteiro, ver `except Exception as validator_err: raise RuntimeError(...)` ao redor de toda chamada a `validate_bot_against_plan`). Só então, sobre essa subsequência filtrada (ids fora do plano NUNCA entram nesse cálculo — já foram tratados no passo 1), mapear cada code_id para seu índice no plano; a sequência de índices
   deve ser estritamente crescente. Mantém o TIPO de erro como
   `STEP_ID_MISMATCH` — NÃO renomear para `STEP_ORDER_VIOLATION` (achado da
   2ª revisão independente, 2026-07-11: `code_generator.py:603` dispara a
   reordenação automática determinística checando literalmente
   `error_types.issubset({"STEP_ID_MISMATCH"})`; um rename quebraria esse
   gatilho para TODOS os projetos, não só os re-sanitizados em v2 — o
   validador é compartilhado — e o mesmo literal aparece no prompt em
   `code_generator.py:1456` e no comentário `1353-1356`). Só a LÓGICA de
   detecção muda (de igualdade posicional estrita para subsequência
   monotônica); tipo e formato da mensagem de erro ficam idênticos ao atual
   (mesmas chaves `position`/`expected_id`/`found_id`/`detail` do dict de erro —
   `code_generator.py:1379-1382` lê `expected_id`/`found_id` para decidir o
   escopo da correção cirúrgica; omitir essas chaves não quebra a validação em
   si, mas degrada esse direcionamento).
4. COUNT_MISMATCH: len(required ∩ code) vs len(required) — mensagens mantêm formato.
```

Plano v1 (sem hints) ⇒ todos required ⇒ comportamento bit-a-bit igual ao atual (mesmos erros nos mesmos casos). Isso permite trocar o algoritmo sem esperar o sanitizer novo.

### 5.2 `validate_resilience_patterns` (linha 732 — corrigido; citação original "709" apontava para a linha errada, confirmado por leitura direta do código em 2026-07-11)

Adicionar imediatamente antes do loop principal (`for step in plan.get("steps", []):`, linha 834): `code_ids = set(extract_step_ids_from_code(bot_code))`; logo no topo do corpo do loop, `if step.get("execution_hint") in ("optional", "skip") and step["step_id"] not in code_ids: continue`. Confirmado por leitura do código: é um único corpo de loop sequencial (não blocos aninhados independentes) — o guard nessa posição cobre todos os sub-checks (`select_native`, `select`, `parent`/chained, `coords`, `weak_selector`, `human_like`) numa única alteração. **Posição importa**: um guard colocado só antes do bloco `select`, por exemplo, deixaria os demais sub-checks vulneráveis a falsos positivos em steps `sup_`/`optional` não emitidos. Steps suprimidos emitidos pela LLM **são** validados pelos padrões (se emitiu um select suprimido, tem que usar `select_option_resilient` do mesmo jeito). Steps required mantêm o comportamento atual.

### 5.3 `reorder_steps_to_match_plan` (autocorreção determinística, `code_generator.py:606`)

A ordem esperada deixa de ser `planned_ids` completo e passa a ser "ids do plano filtrados aos que aparecem no código, na ordem do plano". Ajuste pequeno na construção da lista alvo.

### 5.4 O que não muda

`validate_bot_structure`, `validate_dataset_field_names`, `validate_required_wait_patterns`, `validate_required_reopen_patterns`, `validate_required_method_patterns`, `extract_step_ids_from_code` — nenhum depende de contagem total do plano.

---

## 6. Impacto no `code_generator.py`

1. **`_strip_internal_step_fields` (linha 174)** — estender a lista de campos internos com bookkeeping puro que a LLM confundiria com kwargs ou não deve manipular: `merged_from`, `source_events`, `original_index`, `reordered_from`, `superseded_by`. (`position_anchor` NÃO precisa entrar aqui — é variável interna do Sanitizer, nunca chega a ser serializada num step; nada a stripar. Removido também `dedup_group` desta lista — achado da 2ª revisão independente, 2026-07-11: campo fantasma, nunca aparece no schema da Seção 3 nem é produzido por nenhuma função descrita no plano.) Manter visíveis: `execution_hint`, `step_role`, `suppression_reason`, `sanitization_notes`, `scenario`, `text`, `selector_original`, `has_text_original` — são contexto legítimo (nenhum colide com nome de kwarg do runner).
2. **Renderização do plano no prompt — TRÊS pontos de chamada, não dois (achado da 2ª revisão independente: a citação original "~830 e ~1318" deixava de fora o modo cirúrgico escopado)** — linhas `code_generator.py:826-831` (geração nova, dentro de `_generate_new_code`), `:1329-1334` (cirúrgica full-file, dentro de `_surgical_correct`) e `:1148` (`plan_slice_json`, cirúrgica ESCOPADA — **correção da 3ª revisão independente, 2026-07-11: a linha 1148 está dentro de `_surgical_correct_scoped` (que recebe `plan_steps` como parâmetro), não de `_build_scoped_edit_plan` — essa outra função, linhas 1078-1121, só localiza blocos de código por `step_id` via `_parse_step_blocks` e nunca toca em `plan_steps`/`plan_slice_json`; `_surgical_correct_scoped` é quem CONSOME o `scoped_plan` que `_build_scoped_edit_plan` produz**). Nova função `_render_plan_for_prompt(steps)` usada nos 3 pontos: steps emitíveis em JSON completo (como hoje, pós-strip); steps `skip` agrupados numa seção compacta ("PASSOS SUPRIMIDOS — contexto de fidelidade") com 1 linha por step. No modo escopado (`:1148`), a decisão é: `sup_` NÃO entram no `plan_slice` (o escopo cirúrgico já é definido por `target_step_ids` explícitos — um `sup_` só entra se ele mesmo for um `target_step_id`, nunca como contexto adicional automático). Controla custo de token e reduz tentação de emissão indevida.
3. **Contrato no prompt** (novo bloco nas duas variantes — geração nova e cirúrgica): regras de `execution_hint` (skip: não emitir salvo necessidade justificada; optional: critério da LLM; se emitir suprimido, usar o `step_id` do plano e preservar ordem relativa; nunca inventar id).
4. **Playbook `aegis_mentor/skills/rpa-copilot-coder.md`** — nova seção espelhando o contrato (o playbook é a fonte que a LLM segue com mais fidelidade).
5. **Correção cirúrgica** — sem mudança estrutural: `_build_scoped_edit_plan` ancora por `step_id` no código existente. Um `sup_` referenciado por correção e ausente do código cai no fallback atual (reescrita completa com a correção em prosa) — comportamento aceitável para v1.

---

## 7. Impacto nos demais consumidores (por que não quebram)

| Consumidor | Uso do plano | Efeito |
|---|---|---|
| `runner.py:2127-2138` | Só constrói `flaky_step_ids` de `plan["steps"]` | Steps `sup_` entram no mapa e nunca são consultados (código não os emite por default). Zero mudança |
| `cockpit.py:344` (backend — corrigido de "339" na 2ª revisão independente; 339 é o campo `validation`, não `execution_plan`) | Envia plano inteiro à SPA | Sem mudança — só serializa o JSON como está. Nota: `runner.py:2132` loga `len(execution_plan['steps'])` — no v2 esse log conta `st_+sup_` juntos (inflado); é só log, não afeta execução, não corrigido nesta rodada |
| `static/index.html:3760-3792` (frontend, achado do plan-critic) | Constrói `robotSteps` a partir do histórico real (3731-3758, um item por `step_id` executado) e depois **fatia `executionPlan.steps` por posição** (`planSteps[robotSteps.length..]`) para marcar o resto como `STOPPED` — assume alinhamento posicional 1:1 entre os dois arrays | **QUEBRA.** Com `sup_` intercalado no array na posição física original (D2), essa suposição falha em qualquer execução com supressão — mesmo 100% bem-sucedida. Ex.: plano `[st_001, sup_001(skip), st_002, st_003]` todo executado com sucesso → `robotSteps.length` = 3, `planSteps.length` = 4 → o corte pega `planSteps[3]` (= `st_003`, que já teve sucesso) e o duplica na tela como `STOPPED`. Corrigido por **T5b** |
| `cockpit.py:1597` (mark-flaky) e `1654` (mark-failed) | Casam por `step_id` string | `sup_NNN` funciona sem alteração; QA pode inclusive marcar um suprimido como causa de falha — exatamente o caso "gatilho essencial deletado" |
| `correcoes_acumuladas.json` | Referencia `step_id` | Ids `st_` não deslocam (D2) — correções antigas continuam válidas |
| Skills `aegis-regression-gate` / `aegis-pipeline-forensics` | Baseline usa bot compilado (não regenerado); forense compara cadeia de artefatos | Gate: inalterado (bot antigo + plano novo só muda flaky map). Forense: atualizar doc da skill para conhecer `sup_`/`merged_from` (T8) |
| `dataset_validator.py` | Não lê plano | Zero impacto |

---

## 8. Plano de ação sequencial

> Convenção: cada tarefa fecha com comando de validação executável. Mudança em `aegis_*` core ⇒ gate de regressão obrigatório no final (working agreement).

> **Gate antes de iniciar T1 (achado do plan-critic, 2026-07-11):** este documento já passou por uma rodada de `plan-critic`, que encontrou e motivou as correções desta revisão. Como `plano_execucao.json` alimenta execução automatizada sem supervisão humana direta (Ralph Loop na Fase 4 e o Runner em produção na Fase 5), rodar uma segunda revisão independente (outro agente/modelo, sem o contexto desta) sobre esta versão já ajustada antes de começar T1.

**T0 — Baseline de ouro (sem código)**
Copiar um projeto de referência real (ex.: `portal_segura/tests/001_teste`) para pasta descartável; rodar o sanitizer ATUAL; guardar `plano_execucao.json` e `gravacao.json` resultantes como golden files do invariante da Seção 4. **Capturar a partir de um checkout/tag/stash do código anterior a QUALQUER mudança de T1** — T1 já altera o que `gravacao.json` contém, então gerar os golden files depois de T1 mesclado invalida a linha de base contra a qual T2 prova "zero drift". Incluir no golden set um caso com um clique R1-duplicado adjacente a um clique merge-duplicado no mesmo widget (necessário para o DoD de T2 abaixo).
*DoD:* golden files versionados em `.specs/golden/` (ou fixture de teste), com anotação do commit/tag que os gerou.

**T1 — `_classify_raw_events` (sanitizer.py)**
Extrair o bloco R1-R4 (linhas 152-201) para método que retorna TODOS os eventos com `sanitizer_class`/`original_index` (estampar `original_index` antes do Padrão P). `sanitize()` passa a gravar `gravacao.json` com todos os eventos taggeados. O relatório e o restante do fluxo interno passam a filtrar por `keep != false` onde hoje recebiam a lista já podada (comportamento do relatório inalterado nesta tarefa).
*Funções:* `sanitize()` (bloco 135-227), novo `_classify_raw_events`.
*DoD:* teste novo `test_classify_raw_events.py` (R1-R4 viram tags; nenhum evento sumiu; `original_index` estável) + suíte existente verde.

**T2 — Reescrita de `_write_execution_plan` (núcleo)**
- Construir steps a partir de todos os eventos de interação (taggeados inclusive).
- **Composição R1 × merge — RESOLVIDA (1ª revisão independente); algoritmo de interleave CORRIGIDO (2ª revisão independente, 2026-07-11 — o sort global proposto na primeira versão desta seção reordenaria os `st_` entre si; ambas as decisões registradas aqui para não deixar o subagente de codificação inventar):**
  ```
  # 1. Estampagem de original_index: ANTES do Padrão P (antes de sanitizer.py:135),
  #    num loop dedicado sobre `events` bruto — preserva a ordem FÍSICA real da
  #    gravação, não a ordem pós-inversão-de-autocomplete. `_classify_raw_events`
  #    só LÊ esse campo depois (nunca o cria) — ele roda depois do Padrão P.
  for i, ev in enumerate(events):
      ev["original_index"] = i

  # 2. Padrão P roda normalmente (troca física de posição, necessária para execução).

  # 3. Classificação R1-R4 — TAG, não remove. R1 continua rodando estritamente
  #    ANTES do merge, exatamente como hoje; a única mudança é que filtra por
  #    PREDICADO em vez de remover fisicamente da lista:
  all_events = _classify_raw_events(events)         # mesmo comprimento da entrada
  kept_events = [e for e in all_events if e.get("sanitizer_class", {}).get("keep", True)]

  # 4. Cadeia de steps roda EXATAMENTE como hoje, só que sobre a view filtrada:
  steps = _build_steps(kept_events)
  steps = _merge_consecutive_clicks(steps)          # same_widget() idêntico a hoje — nunca vê um evento R1-tagged
  steps = _reorder_dropdown_pairs(steps)
  steps = _mark_superseded_selects(steps)
  steps = _mark_phantom_pretrigger_clicks(steps)
  # numeração st_NNN sequencial sobre `steps`, NESTA ORDEM. A partir daqui a
  # ordem relativa de `steps` entre si NUNCA é alterada (ver passo 5).

  # 5. Interleave por MERGE-INSERT, NÃO por sort global (achado da 2ª revisão:
  #    `_reorder_dropdown_pairs` move deliberadamente steps "between" para
  #    depois do select colapsado — o anchor de `steps` NÃO é monotônico em
  #    original_index. Ordenar por anchor reordenaria os `st_` entre si,
  #    quebrando a promessa da D2 ("mesma sequência que o pipeline atual
  #    produz") e causando STEP_ORDER_VIOLATION espúrio no validador da Seção
  #    5.1, que valida contra a ordem-no-plano). `position_anchor` é uma
  #    variável AUXILIAR interna desta função — NUNCA é persistida no schema
  #    final (não é campo de nenhum step no JSON de saída).
  suppressed = sorted(
      [_step_from_raw_event(e) for e in all_events if not kept(e)],
      key=lambda s: s["original_index"]
  )  # sup_NNN atribuído nesta ordem

  final_steps = []
  sup_iter = iter(suppressed)
  next_sup = next(sup_iter, None)
  for st_step in steps:                              # itera `steps` NA SUA PRÓPRIA ORDEM — nunca reordenado
      st_anchor = min(_source_indices(st_step))        # NUNCA leia só st_step["original_index"] isolado — ver definição abaixo
      while next_sup is not None and next_sup["original_index"] < st_anchor:
          final_steps.append(next_sup)
          next_sup = next(sup_iter, None)
      final_steps.append(st_step)
  while next_sup is not None:                         # sup_ remanescentes (posteriores ao último st_)
      final_steps.append(next_sup)
      next_sup = next(sup_iter, None)
  ```
  **Definição obrigatória de `_source_indices(step)` (achado da 3ª revisão independente, 2026-07-11 — sem isso `position_anchor` fica subespecificado e um agente frio pode implementar uma versão que dá o valor ERRADO, não só impreciso):**
  ```
  def _source_indices(step):
      idxs = []
      if "original_index" in step:
          idxs.append(step["original_index"])
      idxs += [m["original_index"] for m in step.get("merged_from", [])]
      idxs += step.get("source_events", [])
      return idxs
  ```
  Um `st_step` carrega seus eventos-fonte em campos DIFERENTES dependendo de como foi produzido — step simples (só `original_index`), sobrevivente de `_merge_consecutive_clicks` (`original_index` próprio + `merged_from`), ou `select` composto de `_reorder_dropdown_pairs` (só `source_events`, sem `original_index` no nível raiz — ver exemplo `st_013` na Seção 3). `position_anchor` é o MÍNIMO entre TODOS os valores que existirem, nunca um único campo lido isoladamente. Isso importa na prática, não só em teoria: `choose()` (`sanitizer.py:911-914`) usa como critério default "mantém o candidato" — ou seja, ELEGE O CLIQUE MAIS RECENTE como sobrevivente ("Mantém apenas o último clique", ver docstring de `_dedup_consecutive_clicks`) sempre que o candidato não é um selector genérico solto (`input`/`span`/`div` puro) enquanto o mantido já é específico; então o `original_index` que sobra no campo raiz do step sobrevivente costuma ser o do evento MAIS TARDIO do grupo, não o mais cedo — o(s) evento(s) mais cedo(s) do merge ficam só dentro de `merged_from`. Ler apenas `step.get("original_index")` (ignorando `merged_from`) dá um anchor ATRASADO para qualquer step que tenha absorvido um clique anterior, o que pode colocar um `sup_` que aconteceu cronologicamente ANTES do primeiro clique do grupo depois dele por engano. É exatamente o formato do exemplo `st_012` da Seção 3 (sobrevivente = `span.mat-button-wrapper`; o clique absorvido mora só em `merged_from`) e da fixture de [SUBAGENTE 02]/T0b (3 cliques no mesmo widget, evento 1 e evento 3 se fundem via `same_widget()`, `choose()` tende a eleger o evento 3 como conteúdo — o `original_index` do evento 1 sobrevive só em `merged_from`; a posição correta do `sup_001` resultante do R1 do evento 2, cujo `original_index` fica ENTRE o do evento 1 e o do evento 3, só sai certa se `position_anchor` considerar `merged_from`, não só o campo raiz). `_source_indices` acima cobre os 3 formatos com uma função só — usar sempre ela, nunca `step.get("original_index")` isolado, para calcular `position_anchor`.

  R1 e merge operam sobre CONJUNTOS DISJUNTOS de eventos (idêntico ao pipeline atual, onde merge nunca vê o que R1 já removeu fisicamente) — a única diferença é que os eventos R1 continuam existindo como entidades (viram `sup_`) em vez de desaparecerem. E o merge-insert do passo 5 NUNCA reordena `steps` entre si — o `for st_step in steps` acima itera na ordem já fixada pelo passo 4, só decidindo ONDE intercalar cada `sup_`. Por isso a prova de "byte-idêntico" (ids, tipos, seletores, campos operacionais **e ordem relativa**) fica trivial para a subsequência `st_`: é literalmente o mesmo código operando sobre o mesmo conjunto de dados que processa hoje, só que via filtro em vez de exclusão física.
- Converter as 3 funções de dedup de steps para versões não-destrutivas (Seção 4): `_merge_consecutive_clicks`, `_mark_superseded_selects`, `_mark_phantom_pretrigger_clicks`; `_reorder_dropdown_pairs` ganha `source_events`/`reordered_from`.
- Padrão Q com `has_text_original` + `sanitization_notes`; achatamento com `selector_original`; serializar `text` (já computado hoje em `sanitizer.py:1029`, só não serializado no plano final) e `scenario` (campo NOVO — hoje só existe no escopo de `sanitize()`, nunca é lido dentro de `_write_execution_plan`; implementar do zero, não "resgatar").
- Numeração dupla `st_`/`sup_`; `total_steps` = emitíveis; `total_recorded_steps` + `fidelity_summary`; herança `flaky` restrita a emitíveis; `version: "2.0"`.
*DoD:* invariante da Seção 4 contra golden do T0 (script de diff: campos operacionais dos `st_` idênticos **E na mesma ORDEM relativa** — achado da 2ª revisão independente: comparar só o conteúdo dos campos não basta, o merge-insert do passo 5 do algoritmo acima precisa ser testado explicitamente contra um caso onde `_reorder_dropdown_pairs` já quebra a monotonicidade de `original_index`), incluindo o caso R1×merge adjacente do golden set, + testes novos de classificação.

**T3 — `step_validator.py` hint-aware**
Implementar 5.1 e 5.2. Primeiro os testes (plano v1 ⇒ mesmíssimos erros; matriz v2: só required = PASS; optional emitido em ordem = PASS; skip emitido em ordem = PASS; ordem violada = FAIL; required faltando = FAIL; id inventado = EXTRA_STEPS; tolerância required_reopen preservada). **Caso adicional obrigatório (achado do plan-critic):** definir se `planned_set_for_reopen` (`step_validator.py:384`, hoje = todos os ids do plano) inclui ids `skip` no plano v2, e testar explicitamente o cenário habilitado por D6 — a LLM reintroduz um `sup_NNN` já existente na posição entre `after_step_id` e `target_id` como parte de uma correção `required_reopen` legítima; a tolerância não pode tratar esse id como "desconhecido/inventado".
*Funções:* `validate_bot_against_plan`, `validate_resilience_patterns`.
*DoD:* novo `test_step_validator_hints.py` verde (incluindo o caso `sup_NNN` + `required_reopen`) + suítes existentes verdes.

**T4 — `code_generator.py` + playbook**
Itens 1-4 da Seção 6 (`_strip_internal_step_fields`, `_render_plan_for_prompt`, contrato no prompt das duas rotas, `reorder_steps_to_match_plan`, playbook).
*DoD:* `test_error_selector_config.py` e `test_dryrun_multirow.py` verdes; inspeção do prompt renderizado com plano v2 de fixture (snapshot test simples).

**T5 — Relatório com fidelidade**
`relatorio.md`: eventos suprimidos aparecem com badge (`🔇 SUPRIMIDO (motivo)`) em vez de invisíveis; contagem "Ações Gravadas" distingue total × emitíveis.
*DoD:* geração manual sobre o projeto de referência; leitura visual.

**T5b — Correção da reconciliação de passos não-executados na Cockpit UI (achado do plan-critic — estava fora de escopo na v1 deste plano, agora obrigatória)**
`aegis_cockpit/static/index.html:3760-3792`: constrói `robotSteps` a partir do histórico real (3731-3758, um item por `step_id` executado) e depois fatia `executionPlan.steps` **por posição** (`planSteps[robotSteps.length..]`) para marcar o resto como `STOPPED` — assume alinhamento posicional 1:1 entre os dois arrays. Com `sup_` intercalado no array na posição física original (D2), essa suposição falha em qualquer execução com supressão, mesmo 100% bem-sucedida: plano `[st_001, sup_001(skip), st_002, st_003]` todo executado com sucesso → `robotSteps.length` = 3, `planSteps.length` = 4 → o corte pega `planSteps[3]` (= `st_003`, já bem-sucedido) e o duplica na tela como `STOPPED`. Correção: trocar o corte posicional por reconciliação via conjunto de `step_id` — `const executedIds = new Set(robotSteps.map(s => String(s.index)));` — e só empurrar `STOPPED` para steps do plano com `execution_hint` ausente ou `"required"` cujo `step_id` não está em `executedIds`. Steps `skip`/`optional` ausentes de `executedIds` são o caso esperado (não foram emitidos pelo bot), não uma falha, e não devem gerar entrada. **Dois cuidados adicionais (achado da 2ª revisão independente, 2026-07-11):** (1) preservar o guard `alreadyMerged` existente (linha 3769, `robotSteps.some(s => s.status === 'STOPPED')`) — ele evita re-expandir um histórico que já foi mesclado/editado antes; a correção não deve rodar se esse guard já for `true`. (2) `robotSteps` é construído (linha 3743) com `stepId = s.step_id ?? (s.index || idx+1)` — uma execução LEGADA sem `step_id` gravado produz índices numéricos puros (`1`, `2`, ...) que nunca vão bater com strings `"st_NNN"` em `executedIds`, o que marcaria o plano INTEIRO como `STOPPED` por engano. Tratar explicitamente: só aplicar a reconciliação nova por `step_id` quando `robotSteps` tiver `step_id` string real (checar `typeof s.index === 'string' && s.index.startsWith('st_')` em pelo menos uma entrada); caso contrário, manter o comportamento posicional legado como fallback.
*Arquivo:* `aegis_cockpit/static/index.html:3760-3792`.
*DoD:* Cockpit aberta com um `historico_passos.json` de execução 100% bem-sucedida + `plano_execucao.json` v2 contendo `sup_`/`skip` intercalados — nenhum `st_` bem-sucedido aparece duplicado/`STOPPED`; um `st_` `required` genuinamente não alcançado (ex.: execução interrompida no meio) continua aparecendo como `STOPPED` normalmente; um histórico já mesclado (`alreadyMerged === true`) não é re-expandido; um histórico legado sem `step_id` string cai no fallback posicional sem marcar tudo como `STOPPED`.

**T6 — Adaptação da suíte existente**
- `test_sanitizer_execution_plan.py`: `test_dropdown_pair_with_fallbacks_collapses_without_fallback_field` — colapso continua produzindo 1 step emitível; ajustar asserts para tolerar campos aditivos (`source_events` etc.). Demais testes devem passar sem edição (checar; se falhar, é regressão real, não teste a "consertar" — lição nº 3 do CLAUDE.md vale nos dois sentidos).
- `test_weak_selector_enforcement.py`: inalterado (weak flag não mudou).
*DoD:* `python aegis_sanitizer/test_*.py` tudo verde + `python aegis_runner/test_runner_integration.py` verde.

**T7 — Validação de ponta a ponta real (working agreement nº 1)**
1. Re-sanitizar o projeto de referência real; conferir diff do plano (só adições).
2. Rodar `aegis-regression-gate` (bot compilado existente + plano novo, N execuções vs baseline — runner só lê flaky map, mas o gate é obrigatório para mudança core).
3. Em CÓPIA do projeto: regenerar Fase 4 com o plano v2 e executar o bot contra o site real, medindo que a geração respeita o contrato (nenhum `sup_` emitido sem necessidade; validador PASS).
*DoD:* veredito APROVADO do gate + execução real da cópia com taxa de sucesso ≥ baseline.

**T8 — Documentação**
`docs/aegis_architecture_manual.md` (schema v2, contrato de hints), `docs/aegis_rpa_suite_walkthrough.md`, CLAUDE.md (seção do Sanitizer), skill `aegis-pipeline-forensics` (conhecer `sup_`/`merged_from`/`original_index` na cadeia forense). Atenção: os dois docs já têm modificações locais não commitadas — coordenar.
*DoD:* docs coerentes com o código; commit.

Dependências: T0 → T1 → T2 → {T3, T4, T5, T5b em paralelo} → T6 → T7 → T8. T3 pode começar antes de T2 (retrocompatível com plano v1); T5b depende só do schema v2 (Seção 3), pode começar assim que T2 fixar o schema. T0 deve rodar a partir do código pré-T1 (ver nota na descrição de T0) — não é intercambiável em ordem com T1.

---

## 9. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| LLM emite steps `skip` indevidamente (fidelidade demais vira ruído no bot) | Renderização compacta + contrato no prompt + ordem validada. **Fora do escopo desta rodada (contingência futura, não entregável de T0-T8 — achado do plan-critic):** se recorrente em produção, env `AEGIS_PLAN_FORBID_SKIP=true` transformaria emissão de skip em erro do validador; documentado aqui como opção, não implementado até haver caso real |
| Crescimento de tokens no prompt da Fase 4 | Seção compacta de suprimidos (1 linha/step); `merged_from`/`source_events` já são stripados |
| Classificação nova diverge da deleção antiga (invariante quebra) | Golden files T0 + script de diff automático no T2; qualquer divergência de `st_` é bug da refatoração, por definição |
| Composição R1 (evento bruto) × merge (step) ambígua desloca numeração `st_` silenciosamente (achado do plan-critic — maior risco técnico do plano) | Pseudocódigo de composição obrigatório antes de codificar T2 + caso de golden dedicado (ver T0/T2); risco concreto em projetos com `correcoes_acumuladas.json` populado |
| Cockpit UI conta passos por tamanho de array em vez de por `step_id`, exibindo `st_` bem-sucedidos como `STOPPED` sob qualquer supressão (achado do plan-critic) | Deixou de ser cosmético — é bug funcional real, corrigido por **T5b** antes de T7 |
| Projeto re-sanitizado com sanitizer novo + bot antigo | Ids `st_` idênticos ⇒ bot antigo continua casando com o plano; flaky map ganha chaves extras inofensivas |
| Gravações antigas (gravacao.json já podado por sanitizer velho) | Nada a recuperar — eventos já foram perdidos; pipeline segue funcionando, plano v2 simplesmente não terá `sup_` dessas perdas. Re-gravação repõe fidelidade |

## 10. Fora de escopo (anti-overengineering deliberado)

- **Ids por content-hash** em vez de posicionais — a numeração dupla resolve o drift sem migração; hash fica para quando houver caso real.
- **`plan_overrides.json` / UI para promover `sup_` → `required`** — v2; por ora a promoção acontece via correção acumulada + LLM emitindo o id existente.
- **Mudanças no recorder** — nenhum byte; a fidelidade é responsabilidade da Fase 2.
- **Mudanças no runner/healing chain** — nenhum byte.
- **Incluir eventos `annotation`/`scroll`/`keypress` como steps do plano** — annotations já chegam ao codegen via relatorio.md; incluir no plano é enriquecimento incremental de v2, não pré-requisito.

---

## Apêndice — resumo do porquê desta forma

O insight central: **as heurísticas de detecção do Sanitizer atual são boas e validadas em produção (st_049, st_063, caso PCD, caso Combustível) — o que está errado é só o efeito colateral (deletar) e a falta de rastro.** Este plano não toca em nenhuma heurística; troca o verbo de todas elas. Por isso o invariante da Seção 4 é verificável: mesmo input ⇒ mesmos steps emitíveis ⇒ mesmo bot gerado, agora com o mapa completo da gravação ao lado para o Code Generator, o QA (mark-failed em `sup_`) e o ciclo de correções usarem quando a reprodução fiel exigir um gesto que hoje é invisível.
