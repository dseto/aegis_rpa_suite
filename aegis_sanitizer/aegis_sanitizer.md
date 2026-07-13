# 🛡️ Aegis Sanitizer (Fase 2) - Documentação Técnica e Funcional

Este documento especifica o módulo **Aegis Sanitizer** (`aegis_sanitizer/sanitizer.py`), a segunda fase do pipeline do **Aegis RPA Suite**. Cobre o contrato de alta fidelidade do schema v2 (`plano_execucao.json`), introduzido em 2026-07 para substituir o paradigma anterior de deleção física por classificação. Público-alvo: arquitetos e desenvolvedores que mantêm ou estendem o framework, e qualquer pessoa depurando divergência entre `gravacao.json` e o robô final.

---

## 📖 1. Visão Geral e Propósito

O **Aegis Sanitizer** consome a telemetria bruta gravada pelo BlackBox (`gravacao.json` + `dicionario.json`) e produz três artefatos consumidos pelas fases seguintes:

```
┌─────────────────┐     ┌──────────────────────────────────────────┐     ┌────────────────────────┐
│ 1. Aegis         │     │ 2. Aegis Sanitizer (Este)                │     │ 3. Dataset             │
│    BlackBox      ├────►│    sanitizer.py                          ├────►│    Validator           │
│   (Gravador)     │     │                                          │     │   (Validação Dados)    │
└─────────────────┘     │  gravacao.json → gravacao.json (superset  │     └───────────┬────────────┘
                         │  taggeado, nada é removido)               │                 │
                         │  dicionario.json → refinado semanticamente│                 ▼
                         │  → plano_execucao.json (schema v2)        │       dataset_inicial.json
                         │  → relatorio.md                           │       dicionario.json
                         └─────────────────┬──────────────────────────┘                │
                                           │                                            │
                                           └──────────────────┬─────────────────────────┘
                                                              ▼
                                                ┌────────────────────────┐
                                                │ 4. Aegis Code Generator │
                                                └────────────────────────┘
```

### Filosofia de Design (D1-D6, `.specs/plano-sanitizer-alta-fidelidade.md`)

* **Classificar, nunca deletar (D1).** Até 2026-07, o Sanitizer descartava fisicamente eventos considerados ruído (cliques duplicados, overlays, painéis stale) com `continue` — o evento simplesmente desaparecia de `gravacao.json`. Isso tornava qualquer auditoria ou correção manual cega ao que realmente aconteceu na gravação. Agora todo evento sobrevive; o que muda é a tag `sanitizer_class` anexada a ele.
* **Fidelidade byte-a-byte com o pipeline v1 para o que já funciona (D2).** A sequência de `step_id`s `st_NNN` emitida pelo schema v2 é **idêntica**, na mesma ordem, à que o pipeline v1 sempre produziu. Zero drift para bots e `correcoes_acumuladas.json` já existentes — verificável via `golden_diff.py` (Seção 7).
* **Compilador tem a palavra final sobre reintroduzir um step suprimido (D3/D6).** Um gesto físico julgado redundante ou ruído de gravação não é apagado — vira `step_role`/`suppression_reason` num `sup_NNN`. Se uma correção acumulada ou o próprio fluxo exigir, o Code Generator (Fase 4) pode reintroduzi-lo reusando o `step_id` já existente, nunca inventando um novo.
* **Duas camadas de supressão, duas causas diferentes.** Nível-evento (`sanitizer_class`, regras R1-R4 em `_classify_raw_events`) cobre ruído de captura (duplicação/overlay). Nível-step (`step_role`/`sup_NNN`, produzido dentro de `_write_execution_plan`) cobre correções feitas durante a própria gravação (o usuário reabriu um dropdown e escolheu outra opção) e cliques fantasmas de bubbling. As duas são independentes e podem ambas aparecer no mesmo `relatorio.md`.

### Gap conhecido: fidelidade em autocompletes dependentes (achado no gate H8 do gerador híbrido, 2026-07-13)

Uma cadeia de autocomplete Angular Material onde um campo (ex. "Versão") só popula depois que campos anteriores ("Marca", "Modelo") já foram selecionados (`main.js:1852-1856` do Portal Segura de referência) expõe um gap real de fidelidade: o Sanitizer emite todos os `fill`s do grupo e depois todos os `click`s de opção, na ordem física da gravação — não intercalados por dependência. Combinado com `fill_human_like` (`aegis_runner/runner.py`) disparando `blur` incondicional ao final da digitação (o que fecha o painel de autocomplete sempre que HUMAN_LIKE é a estratégia do campo que precede o clique), o `click` da opção seguinte pode falhar 100% das vezes com timeout — o painel nunca reabre sozinho. Workaround validado (fora do Sanitizer, via `correcoes_acumuladas.json`): `required_reopen` — re-disparar o campo anterior com `strategy="DIRECT"` (nunca HUMAN_LIKE) entre a seleção e o clique da opção. Correção estrutural real (não implementada): (1) emitir a ordem fiel intercalada fill→seleção→próximo campo para autocompletes dependentes; (2) emitir automaticamente um `required_reopen` antes do clique de opção quando o fill anterior puder ter usado HUMAN_LIKE. Ver `.specs/plano-codegen-hibrido-deterministico.md` Seção 8 ("Fora de escopo") para a investigação completa.

---

## 🏗️ 2. Arquitetura de Dados e Integração

### Insumos (Inputs)
1. **`gravacao.json`:** Telemetria bruta do BlackBox — lista de eventos (`click`, `fill`, `filechooser`, `annotation`, `call_skill`) na ordem física da gravação.
2. **`dicionario.json`:** Dicionário de dados físico (`fields`/`inputs`/`outputs`) com seletores e valores observados.
3. **`project.json`** (opcional): `business_description`/`expected_business_outcome`, usados pelo refinamento semântico cognitivo.
4. **`dataset_inicial.json`** (opcional): usado pelo Padrão Q (detecção de token dinâmico hardcoded em `has_text`).

### Saídas (Outputs)
1. **`gravacao.json` (reescrito):** superset completo — mesmo número de eventos da gravação original, cada um com `original_index` e, quando aplicável, `sanitizer_class`. Datas normalizadas para `DD/MM/YYYY`; encoding corrigido.
2. **`dicionario.json` (reescrito):** chaves semânticas refinadas via LLM quando `AEGIS_COGNITIVE_ENABLED=true`.
3. **`plano_execucao.json` (schema v2):** o contrato consumido por `step_validator.py` e `code_generator.py` — ver Seção 3.
4. **`relatorio.md`:** relatório humano/LLM-readable com o fluxo de passos, supressões de ambas as camadas, payloads de rede, e alertas de auditoria (seletor fraco, token dinâmico hardcoded).

---

## 📐 3. Schema v2 de `plano_execucao.json`

### Estrutura de topo

```json
{
  "version": "2.0",
  "test_dir": "001_teste",
  "generated_at": "2026-07-12T10:30:00",
  "total_steps": 42,
  "total_recorded_steps": 51,
  "fidelity_summary": {
    "raw_events": 58,
    "steps_required": 40,
    "steps_optional": 2,
    "steps_suppressed": 9,
    "merges": 3
  },
  "steps": [ /* ver abaixo — dois espaços de id disjuntos, intercalados */ ]
}
```

* **`total_steps`** = número de steps emitíveis (`st_NNN`).
* **`total_recorded_steps`** = total de eventos brutos com tipo em `{click, fill, filechooser}`, antes de qualquer classificação/merge — referência de "quanto a gravação continha".
* **`fidelity_summary`** é o resumo de auditoria de uma linha: `raw_events` (tamanho do superset de `gravacao.json`), `steps_required`/`steps_optional` (partição do `st_` por `execution_hint`), `steps_suppressed` (total de `sup_`), `merges` (quantos `st_` absorveram outro clique via `merged_from`).

### Dois espaços de id disjuntos

| Espaço | Significado | `execution_hint` |
|---|---|---|
| `st_NNN` | Step emitível — numerado sequencialmente na **mesma ordem que o pipeline v1 sempre produziu** (zero drift). | ausente (= `required`), `"optional"`, ou `"skip"`* |
| `sup_NNN` | Step suprimido — nunca emitido pelo Code Generator por padrão, mas presente no array `steps` na sua posição física original (intercalado, nunca reordena os `st_`). | sempre `"skip"` |

\* Na prática, `sup_NNN` é quem carrega `execution_hint: "skip"`; um `st_NNN` normalmente tem o campo ausente (`required`) ou `"optional"`.

### Exemplo de step emitível simples

```json
{
  "step_id": "st_012",
  "type": "fill",
  "selector": "input[formcontrolname='cpf']",
  "description": "Preencher CPF do cliente",
  "scenario": "default",
  "original_index": 14
}
```

### Exemplo de step suprimido nível-evento (R1-R4, `sanitizer_class`)

```json
{
  "step_id": "sup_003",
  "execution_hint": "skip",
  "step_role": "raw_duplicate_click",
  "suppression_reason": "clique consecutivo no mesmo seletor do clique anterior mantido",
  "type": "click",
  "selector": "button.mat-focus-indicator",
  "description": "Avançar",
  "scenario": "default",
  "original_index": 8
}
```

### Exemplo de step suprimido nível-step (correção durante a gravação)

```json
{
  "step_id": "sup_005",
  "execution_hint": "skip",
  "step_role": "superseded_correction",
  "suppression_reason": "Selecionou 'Álcool' em 'Combustível' e corrigiu para 'Diesel' no mesmo campo, ainda durante a gravação.",
  "superseded_by": "st_018",
  "type": "select",
  "dropdown_label": "Combustível",
  "option_text": "Álcool",
  "trigger_selector": "label:has-text('Combustível')",
  "option_selector": "[role='option']:has-text('Álcool')",
  "source_events": [21, 22]
}
```

### Exemplo de step colapsado por merge (`merged_from`)

```json
{
  "step_id": "st_007",
  "type": "click",
  "selector": "span.mdc-checkbox__ripple",
  "description": "Marcar aceite dos termos",
  "scenario": "default",
  "original_index": 11,
  "merged_from": [
    {"original_index": 10, "selector": "input[type='checkbox']", "reason": "clique consecutivo no mesmo widget"}
  ]
}
```

### Catálogo de `step_role` (steps `sup_`)

| `step_role` | Produzido por | Camada | Carrega `superseded_by`? |
|---|---|---|---|
| `raw_duplicate_click` (R1) | `_classify_raw_events` | evento | não |
| `overlay_noise` (R2) | `_classify_raw_events` | evento | não |
| `stale_panel_click` (R3) | `_classify_raw_events` | evento | não |
| `redundant_refill` (R4) | `_classify_raw_events` | evento | não |
| `superseded_correction` | `_mark_superseded_selects` | step | sim |
| `phantom_click` | `_mark_phantom_pretrigger_clicks` | step | não |
| `composite_select` | `_reorder_dropdown_pairs` | — **não é supressão**, é o `step_role` de um `st_` emitível colapsado (abridor+opção de dropdown viram 1 step) | n/a |

### Campos auxiliares por step

* **`fallback_selectors`**: seletores alternativos únicos gravados pelo Recorder, sanitizados (Padrão Q) e deduplicados contra o primário. Usados no Tier 2.9 da cadeia de fallback do Runner.
* **`weak_selector: true`**: presente quando o evento de origem tem `confidence < 70` (avaliado em `evaluate_selector_reliability`). Ausente (nunca `false`) em gravações antigas sem o campo `confidence`.
* **`selector_original`**: presente quando um `click` em `label:has-text(...) input` foi achatado para o `<label>` (clicar no input escondido por CSS trava o `scroll_into_view_if_needed` do Playwright). O `selector` operacional é o achatado; `selector_original` preserva o seletor pré-achatamento para auditoria.
* **`sanitization_notes`**: lista de strings registrando toda vez que o Padrão Q removeu um token dinâmico (`has_text` ou `fallback_selectors`) que não aparece em `dataset_inicial.json`.
* **`flaky: true`**: herdado do plano anterior por casamento `(type, selector)` — não por `step_id`, que é posicional e desloca a cada regeração. Só herda entre `st_` (nunca de um `sup_` que só coincidentemente compartilhe `(type, selector)`).
* **`original_index`** / **`merged_from[].original_index`** / **`source_events`**: os três formatos possíveis de rastreabilidade até o(s) evento(s) bruto(s) de origem — ver `_source_indices` na Seção 4.

---

## ⚙️ 4. Algoritmo Interno — Composição R1 × Merge

O núcleo do módulo é `sanitize()` orquestrando duas camadas de classificação **disjuntas**, seguidas de uma numeração e um merge-insert que nunca reordena o resultado final:

```
gravacao.json (eventos brutos, ordem física)
        │
        ▼
1. Estampa original_index (ANTES do Padrão P — precisa refletir a ordem
   física ORIGINAL, não a pós-inversão de autocomplete)
        │
        ▼
2. Padrão P: inverte pares click→fill de autocomplete gravados fora de ordem
   (troca de POSIÇÃO na lista, não recria os dicts — original_index viaja junto)
        │
        ▼
3. _classify_raw_events (R1-R4): tagueia (nunca remove) ruído de captura
   → gravacao.json final é este superset completo + tagueado
        │
        ▼
4. kept_events = filtro por sanitizer_class.keep (view interna, não é
   um arquivo à parte)
        │
        ▼
5. _write_execution_plan(events=SUPERSET COMPLETO, dataset_rows):
   a. build_step_from_event() roda IGUAL para eventos mantidos e excluídos
      por R1-R4 — a supressão é só metadado adicionado DEPOIS
   b. cadeia de merge/reorder roda SÓ sobre os steps mantidos:
      _merge_consecutive_clicks → _reorder_dropdown_pairs →
      _mark_superseded_selects → _mark_phantom_pretrigger_clicks
   c. numera st_NNN sobre o resultado da cadeia (ordem NUNCA mais muda)
   d. numera sup_NNN sobre {R1-R4 excluídos} ∪ {superseded} ∪ {phantom},
      ordenados por position_anchor
   e. merge-insert: percorre st_steps na sua ordem fixa, intercalando
      cada sup_ na posição correta comparando position_anchor —
      NUNCA um sort global (isso reordenaria st_steps entre si)
        │
        ▼
plano_execucao.json (schema v2)
```

### Por que não um sort global

Uma primeira versão do algoritmo ordenava `st_` + `sup_` juntos por `original_index`. Isso quebra porque `_reorder_dropdown_pairs` já **intencionalmente** move steps "entre" um par abridor→opção para depois do step colapsado — ou seja, a ordem de `st_steps` entre si **não é** monotônica em `original_index` por design. Um sort global reordenaria esses `st_` de volta, invalidando a garantia de zero-drift (D2). O merge-insert corrige isso: itera `st_steps` na ordem que a cadeia de merge/reorder já decidiu (nunca mexe nela) e só decide *onde* encaixar cada `sup_`.

### `_source_indices` — extração do anchor por formato de step

```python
@staticmethod
def _source_indices(step: dict) -> list:
    idxs = []
    if "original_index" in step:
        idxs.append(step["original_index"])
    idxs += [m["original_index"] for m in step.get("merged_from", [])]
    idxs += step.get("source_events", [])
    return idxs
```

`position_anchor(step) = min(_source_indices(step))`. Ler só `step.get("original_index")` isolado dá o anchor **errado** para um step que absorveu um clique anterior via merge: `choose()` em `_merge_consecutive_clicks` tipicamente elege o clique **mais recente** como sobrevivente, então o `original_index` de nível-raiz reflete o evento mais tardio do grupo — as evidências mais antigas só sobrevivem em `merged_from`. Um step `select` composto (`_reorder_dropdown_pairs`) nunca tem `original_index` no nível raiz — só `source_events`. Caso de teste concreto: `.specs/golden/synthetic_r1_merge_case/`.

### Mecanismos de classificação nível-evento (`_classify_raw_events`, R1-R4)

| Regra | `step_role` | Gatilho |
|---|---|---|
| R1 | `raw_duplicate_click` | Clique consecutivo no mesmo seletor do clique anterior mantido. |
| R2 | `overlay_noise` | Clique em overlay genérico de CDK/backdrop, ou em placeholder "Nenhum resultado" (nunca uma opção específica dentro do overlay). |
| R3 | `stale_panel_click` | Clique em painel de autocomplete Angular Material sem nenhum preenchimento prévio no fluxo (painel stale/leftover). |
| R4 | `redundant_refill` | Preenchimento duplicado — mesmo seletor **e** mesmo valor já vistos no mesmo cenário (não precisa ser consecutivo). |

### Mecanismos de classificação nível-step

* **`_merge_consecutive_clicks`** (ex-`_dedup_consecutive_clicks`): colapsa cliques consecutivos no mesmo widget físico (`same_widget`: mesmo seletor, mesmo `parent`, achatamento label→input, ou distância de coordenadas < 2% quando não há seletor em comum — bubbling div→span→input). Guarda de texto (`texts_differ`) impede colapsar 2 widgets físicos distintos que só coincidentemente compartilham seletor genérico. O perdedor vira uma entrada em `merged_from` do vencedor (nunca desaparece).
* **`_reorder_dropdown_pairs`**: detecta pares abertura→opção de dropdown Angular Material gravados fora de ordem (executar outra ação entre abrir e selecionar fecha o overlay em replay real) e os colapsa num único step `type: "select"` com `step_role: "composite_select"`.
* **`_mark_superseded_selects`** (ex-`_drop_redundant_select_corrections`): detecta quando o usuário reabriu o **mesmo widget** de dropdown durante a gravação para corrigir a escolha (sinal: `parent.has_text` do segundo select contém o `option_text` que o primeiro acabou de escolher — não usa `dropdown_label` puro, que colide entre linhas de uma mesma tabela/grid). Cadeias de 3+ correções propagam `superseded_by` sempre para o vencedor **final**, nunca um elo intermediário.
* **`_mark_phantom_pretrigger_clicks`** (ex-`_drop_redundant_pretrigger_clicks`): detecta um clique solto imediatamente antes de um `select` colapsado cujas coordenadas caem a menos de 5% de distância do `coords_trigger` do próprio select — mesmo gesto físico contado 2x pelo Recorder antes do overlay estabilizar.

---

## 🛡️ 5. Impacto em `step_validator.py`

`validate_bot_against_plan` é **hint-aware**: em vez de exigir igualdade posicional estrita entre os `step_id`s do código e do plano, agora:

1. **`EXTRA_STEPS`**: ids no código fora do conjunto de TODOS os ids do plano (`required`+`optional`+`skip`) — calculado **antes** do check de ordem, para que um id alucinado nunca vire um `ValueError` não tratado (`list.index()`).
2. **`MISSING_STEPS`**: ids com hint ausente/`required` que não aparecem no código.
3. **`STEP_ID_MISMATCH`** (tipo **não renomeado** — `code_generator.py:603` dispara reordenação automática determinística checando esse literal; renomear quebraria o gatilho para todo projeto v1 existente): agora exige **subsequência monotônica**, não mais igualdade posicional total. Ids `optional`/`skip` emitidos pela LLM são aceitos desde que respeitem a ordem relativa do plano.
4. **`COUNT_MISMATCH`**: compara só o subconjunto `required` — ids `optional`/`skip` não emitidos não contam como "faltando".

Um plano v1 (sem nenhum `execution_hint`) tem todos os ids implicitamente `required`, reduzindo este validador ao comportamento anterior — retrocompatibilidade total.

**Caveat do `required_reopen` (gap conhecido, achado no gate H8 do gerador híbrido):** um step ad-hoc `*_reopen` (workaround do gap de autocompletes dependentes acima) é tolerado como não-`EXTRA_STEPS` só enquanto a correção `required_reopen` que o originou ainda está em `pending_corrections`. Assim que ela é marcada `applied`/`resolved`, o bloco reopen sai do conjunto de tolerância (`planned_set_for_reopen`) e passa a contar como `EXTRA_STEPS` — qualquer ciclo cirúrgico QA subsequente mirando outro step (sem relação com o reopen) falha imediatamente. Não corrigido; ver `aegis_code_generator.md` Seção 8.

`validate_resilience_patterns` também é ciente de `execution_hint`: um step `optional`/`skip` que a LLM decidiu não emitir não é cobrado pelas checagens de padrão de resiliência (seletor encadeado, `weak_selector`, coordenadas físicas) — só steps efetivamente `required` são.

---

## 🤖 6. Impacto em `code_generator.py`

* **`_render_plan_for_prompt`** (usado nos 3 sites de renderização: `_generate_new_code`, `_surgical_correct`, `_surgical_correct_scoped`): steps `sup_` são renderizados de forma compacta no prompt (não o JSON completo), com instrução explícita para a LLM só emitir um `sup_` quando uma correção pendente ou o próprio fluxo genuinamente exigir — sempre reusando o `step_id` já existente, nunca inventando um novo (D6).
* O contrato de fidelidade é adicionado ao prompt: a LLM é informada de que o plano é a fonte de verdade completa da gravação, incluindo o que foi suprimido e por quê.

---

## 🖥️ 7. Impacto no Cockpit (UI)

O bloco de reconciliação de execução (`aegis_cockpit/static/index.html`, ~linha 3760) foi reescrito para reconciliação baseada em `Set` de `executedIds`, com guard `hasStStepIds`: quando o histórico de execução tem `step_id`s no novo espaço `st_`/`sup_`, reconcilia por id; quando é um histórico legado (pré-schema v2, sem `step_id`), cai de volta para a lógica posicional antiga. Isso corrigiu um bug de duplicação do badge `STOPPED` que ocorria quando `sup_` steps intercalados deslocavam a contagem posicional.

---

## ✅ 8. Verificação de Fidelidade (`golden_diff.py`)

`aegis_sanitizer/golden_diff.py` compara, posição a posição (não por conjunto), a subsequência `st_` de um plano v2 contra uma captura golden do output v1 equivalente — a garantia D2 ("zero drift de `step_id`") é uma invariante testável, não só uma afirmação de design. Fixtures em `.specs/golden/`:

* **`real_portal_segura_001/`**: captura real de um projeto de referência, usada para provar que a refatoração não alterou a sequência `st_` de um caso real já em produção.
* **`synthetic_r1_merge_case/`**: fixture sintética mínima construída especificamente para exercitar a composição R1×merge (`_source_indices` de um step que absorveu um evento via `merged_from`), com o resultado esperado documentado (`README.md` do fixture).

```powershell
python aegis_sanitizer/golden_diff.py --golden .specs/golden/real_portal_segura_001 --project-dir projects/portal_segura/tests/001_teste
```

Exit code `0` = subsequência `st_` idêntica à golden.

---

## ⚙️ 9. Manual de Operação e Configuração

### CLI

```powershell
python aegis_sanitizer/sanitizer.py --project-dir <caminho_do_projeto>
```

* **Exemplo:** `python aegis_sanitizer/sanitizer.py --project-dir projects/portal_segura/tests/001_teste`

### Variáveis de Ambiente Relevantes

* **`AEGIS_COGNITIVE_ENABLED`**: quando `true` (default em `.env`), ativa `refine_semantics_with_llm` — reescreve `business_description`/chaves semânticas via LLM a cada execução, o que é **não-determinístico entre rodadas**. Para gerar um artefato de referência/comparação (golden, baseline), force explicitamente `AEGIS_COGNITIVE_ENABLED=false` na chamada — nunca confie no default do `.env` (ver memória de projeto `project-aegis-projects-dir-gotchas`).
* **`AEGIS_COGNITIVE_API_KEY`/`AEGIS_COGNITIVE_PROVIDER`/`AEGIS_COGNITIVE_MODEL`**: mesmas variáveis usadas pelo Code Generator (Seção 7 de `aegis_code_generator.md`).

### Efeitos colaterais a ter em mente

* `sanitize()` **reescreve** `gravacao.json`, `dicionario.json`, `plano_execucao.json`, `relatorio.md`, e normaliza datas em `dataset_inicial.json`/CSVs existentes **in-place**. Não é uma operação read-only — rodar contra o projeto de referência de verdade sem uma cópia isolada muta permanentemente esse projeto.
* Uma nova gravação (Recorder) sobrescreve `dicionario.json`/`dataset_inicial.json` incondicionalmente — sempre re-rodar Sanitizer + Code Generator após qualquer re-gravação de um projeto já sanitizado, mesmo sem warning explícito.

---

## 🔍 10. Diagnóstico de Divergências Comuns

| Sintoma | Causa Provável | Onde Olhar |
|---|---|---|
| Um passo que existia na gravação sumiu do bot, mas não aparece como erro | Step está classificado como `sup_NNN` (`execution_hint: "skip"`) — comportamento esperado, não um bug. | `plano_execucao.json` → busque o `step_id`/seletor em `steps[].step_role`; seção `## 🔇 Passos Suprimidos no Plano de Execução` do `relatorio.md`. |
| Contagem de passos do bot não bate com o número de cliques/fills da gravação | Esperado — merges (`merged_from`) e supressões (`sup_`) reduzem o total emitível. Confira `fidelity_summary` no topo do plano. | `fidelity_summary.raw_events` vs `total_steps` vs `steps_suppressed`/`merges`. |
| `parent_locator` de um dropdown nunca resolve após a gravação, apesar de ter funcionado na captura | Token dinâmico gerado em runtime (protocolo, número de proposta) hardcoded em `has_text` — Padrão Q deveria ter removido; confira se o token aparece em `dataset_inicial.json` (se aparecer, não é removido por design). | `sanitization_notes` do step; seção `## 🚨 Alerta CRÍTICO` do `relatorio.md`. |
| `STEP_ID_MISMATCH` em massa após re-sanitizar um projeto já corrigido | Comportamento esperado do validador hint-aware — checa subsequência, não igualdade posicional. Se a ordem relativa realmente mudou, o Code Generator reordena automaticamente (gatilho por tipo de erro). | `step_validator.py::validate_bot_against_plan`, `code_generator.py:603`. |
| `plano_execucao.json` regenerado tem `business_description` diferentes a cada rodada, mesmo sem mudar a gravação | `AEGIS_COGNITIVE_ENABLED=true` (default) — `refine_semantics_with_llm` é não-determinístico. | Force `AEGIS_COGNITIVE_ENABLED=false` para reprodutibilidade. |
| `golden_diff.py` reporta divergência na subsequência `st_` após uma mudança em `sanitizer.py` | Regressão real na garantia D2 — algo na cadeia de merge/reorder/numeração mudou a ordem relativa dos `st_`. | Reveja qualquer mudança em `_merge_consecutive_clicks`, `_reorder_dropdown_pairs`, ou o merge-insert de `_write_execution_plan`; nunca deveria mudar a ordem de `st_steps` entre si. |
