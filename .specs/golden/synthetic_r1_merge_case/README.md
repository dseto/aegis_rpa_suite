# Fixture sintética — ambiguidade R1 × merge (T0b)

Golden fixture mínima e sintética que força o caso-limite "clique R1-duplicado
adjacente a um clique merge-duplicado no mesmo widget", citado como obrigatório
no golden set de T0 (`.specs/plano-sanitizer-alta-fidelidade.md`, Seção 8, T0)
e usado como DoD de T2 ("incluindo o caso R1×merge adjacente do golden set").

Esta fixture **não foi executada contra código real** — `_classify_raw_events`
e `_merge_consecutive_clicks` ainda não existem (são T1/T2, tarefas futuras).
`plano_execucao_esperado.json` foi calculado **manualmente**, aplicando à mão
o algoritmo já resolvido na Seção 8 do plano (bloco "Composição R1 × merge —
RESOLVIDA") e as regras R1-R4/`same_widget()`/`choose()` exatamente como estão
escritas hoje em `aegis_sanitizer/sanitizer.py`. Serve de teste de regressão
para a futura implementação de T2 (`test_write_execution_plan_v2.py`, ver
backlog `[SUBAGENTE 04]`).

## Os 3 eventos e o papel de cada um

| # | original_index | selector | papel pretendido | mecanismo |
|---|---|---|---|---|
| 1 | 0 | `#btn-abrir-modal` | "kept" inicial do merge | nenhum (primeiro evento) |
| 2 | 1 | `#btn-abrir-modal` | duplicado R1 | `selector` idêntico ao do evento anterior **mantido** (`cleaned_events[-1]`) |
| 3 | 2 | `span.mat-button-wrapper` | candidato do merge, funde com o evento 1 | `same_widget()` via `parent` idêntico (+ coords a 0.0011 de distância, dentro do limiar 0.02) |

`original_index` é estampado por um loop dedicado sobre os eventos brutos,
**antes** do Padrão P (Seção 8, passo 1: `for i, ev in enumerate(events): ev["original_index"] = i`).
Nenhum dos 3 eventos é `click`+`fill` de autocomplete, então o Padrão P
(inversão de pares, `sanitizer.py:135-150`) não dispara — a ordem física
final é idêntica à ordem de gravação, `original_index` = índice no array
(0, 1, 2).

### Por que o evento 2 dispara R1 (`sanitizer.py:161-165`)

```python
if cleaned_events:
    last = cleaned_events[-1]
    if ev_type == "click" and last.get("type") == "click" and selector == last.get("selector"):
        continue
```

O evento 2 é `click` com `selector == "#btn-abrir-modal"`, idêntico ao
`selector` do último evento **mantido** (`cleaned_events[-1]`, que no ponto em
que o evento 2 é avaliado é o evento 1 — o único evento processado até
então). A condição não olha `text`/`coords`/`parent`; só tipo e selector
literal. R1 dispara. Em T1, isso vira tag
`sanitizer_class = {"role": "raw_duplicate_click", "keep": false, "reason": "..."}`
em vez de `continue` — o evento permanece em `gravacao.json`, mas é
excluído de `kept_events`.

**Nota para quem implementar T1:** a comparação é contra o **último evento
mantido**, não contra o evento bruto imediatamente anterior no array (hoje
isso é implícito porque `cleaned_events` só contém eventos não descartados;
numa função que tageia em vez de deletar, isso exige uma variável separada
tipo `last_kept_click`, não `events[i-1]`). Nesta fixture específica as duas
interpretações dão o mesmo resultado para o evento 3 (seu selector não bate
nem com o do evento 1 nem com o do evento 2), então este fixture **não**
discrimina entre as duas implementações — é uma nota de cuidado para T1, não
uma alegação de cobertura desta fixture.

### Por que o evento 3 NÃO é ruído R2/R3 antes de chegar ao merge

`span.mat-button-wrapper` foi escolhido deliberadamente por **não** conter
nenhum dos gatilhos de R2/R3 (`sanitizer.py:167-188`):

- não contém `cdk-overlay-container`
- não contém `backdrop`
- não contém `Nenhum resultado` (nem no selector, nem em `text`/`business_description`)
- não contém `mat-autocomplete-panel-`

Se qualquer um desses substrings aparecesse no selector do evento 3, R2/R3
o classificariam `keep: False` **antes** do merge sequer rodar (R1-R4 e o
merge operam em fases sequenciais, não em paralelo) — o evento 3 nunca
chegaria a `_merge_consecutive_clicks`, o merge não aconteceria, e o
resultado degeneraria para 2 `sup_` (evento 2 via R1 + evento 3 via
R2/R3) e 1 `st_` (só o evento 1, sozinho, sem `merged_from`). Esse cenário
degenerado é exatamente o que esta fixture existe para **evitar** — o caso
que ela precisa provar é R1 e merge disputando o **mesmo** widget físico por
sinais diferentes, não R1 e R2/R3 coexistindo trivialmente.

### Por que o evento 3 funde com o evento 1 via `same_widget()` (`sanitizer.py:861-901`)

`same_widget(a=step_do_evento_3, b=step_do_evento_1)` (a ordem de chamada em
`_dedup_consecutive_clicks` é `same_widget(s, result[-1])`, ou seja
`a=candidato novo`, `b=kept atual`):

1. **Guard `texts_differ`:** `step["text"]` é preenchido em
   `_write_execution_plan` (`sanitizer.py:1029`) via `ev.get("text", "")` —
   **sempre** presente no step, mas vazio (`""`) se o evento bruto não tem
   campo `text`. O evento 3 **não tem** `text` no `gravacao.json` (de
   propósito) → `step3["text"] == ""` → `bool("") == False` →
   `texts_differ = bool(text_a) and bool(text_b) and ... = False and ... = False`,
   **independente** do que o evento 1 tiver em `text`. O guard nunca bloqueia
   este merge. Se o evento 3 tivesse um `text` diferente de `"Abrir Modal"`,
   `texts_differ` seria `True` e bloquearia os 3 critérios seguintes — é
   exatamente o motivo de omitir `text` no evento 3 em vez de repetir
   `"Abrir Modal"` ou usar um texto diferente.
2. **Critério 1 (`a["selector"] == b["selector"]`):** `"span.mat-button-wrapper" != "#btn-abrir-modal"` → falso, não casa por aqui.
3. **Critério 2 (`parent` idêntico — o que esta fixture usa):**
   `pa = {"selector": "div.modal-trigger-wrapper", "has_text": "Abrir Modal"}`
   (evento 3) e `pb` = idêntico (evento 1). `pa.get("selector")` é truthy,
   `pa.selector == pb.selector`, `pa.has_text == pb.has_text`, `not texts_differ`
   → **todas as condições batem → retorna `True`**. É este critério que
   funde o evento 3 com o evento 1.
4. **Sinal secundário (não necessário, mas presente para robustez):** as
   coordenadas dos 2 eventos (`[0.45, 0.33]` vs `[0.451, 0.3305]`) estão a
   distância euclidiana `≈0.001118` — bem abaixo do limiar `0.02` do
   critério de último recurso (`sanitizer.py:896-900`). Mesmo se o critério
   de `parent` não existisse, o merge ainda aconteceria por coordenadas.

### `choose()` decide quem sobrevive (`sanitizer.py:909-914`)

```python
GENERIC_TAG_SELECTORS = {"input", "span", "div"}

def choose(kept, candidate):
    if candidate["selector"] in GENERIC_TAG_SELECTORS and kept["selector"] not in GENERIC_TAG_SELECTORS:
        return kept
    return candidate
```

`choose(kept=step_evento_1, candidate=step_evento_3)`. `candidate["selector"]`
é a **string composta** `"span.mat-button-wrapper"`, que **não é** igual a
`"span"` — o teste é `in {"input", "span", "div"}` (membership de string
exata, não prefixo/tag-name). Logo a condição do `if` é `False`, e `choose()`
cai no `return candidate` — **o evento 3 vence** e seu conteúdo (selector,
`text`, `coords`, `parent`, `description`) se torna o step sobrevivente. O
evento 1 (o "kept" descartado) é quem vai para `merged_from`.

Isso é consistente com a docstring de `_dedup_consecutive_clicks`: "Mantém
apenas o último clique (mais próximo do elemento real)" — o evento mais
recente processado (evento 3) vence por padrão, e só perderia se seu
selector fosse um *bare tag* genérico (`"input"`/`"span"`/`"div"` sem classe/id)
enquanto o `kept` já fosse específico — não é o caso aqui.

## Por que o resultado tem exatamente 1 `sup_` e 1 `st_` (não 2 de cada)

- **Evento 1** nunca vira step independente: ele é o "kept" inicial de
  `_merge_consecutive_clicks`, mas perde a disputa de `choose()` contra o
  evento 3 e é **absorvido** — sobrevive só dentro de `merged_from` do
  step que o evento 3 produz. Não gera `sup_` (não foi classificado como
  ruído por nenhuma regra R1-R4) nem `st_` próprio (foi fundido).
- **Evento 2** é excluído de `kept_events` por R1 antes do merge rodar —
  vira `sup_001`, com `step_role: "raw_duplicate_click"`. Ele **nunca**
  chega a `_merge_consecutive_clicks` (R1 e merge operam sobre conjuntos
  disjuntos de eventos — ver Seção 8: "R1 e merge operam sobre CONJUNTOS
  DISJUNTOS de eventos, idêntico ao pipeline atual, onde merge nunca vê o
  que R1 já removeu fisicamente"), então não pode se fundir com nada nem
  virar `st_`.
- **Evento 3** vence o merge e se torna o único step emitível: `st_001`.

Resultado: **1 `st_`** (o merge de evento 1 + evento 3, conteúdo do evento 3,
`merged_from` apontando pro evento 1) **+ 1 `sup_`** (o evento 2, tag R1). Se
a implementação futura produzir 2 `sup_` (ex.: não excluir o evento R1 do
merge, ou tratar o evento 1 absorvido como um `sup_` extra em vez de só
`merged_from`) ou 2 `st_` (ex.: não fundir 1 e 3), a fixture falha — é
exatamente o que este golden existe para pegar.

## Por que `sup_001` aparece DEPOIS de `st_001` (não antes)

Este é o ponto mais fácil de acertar por acidente com o raciocínio errado —
documentado explicitamente porque a 3ª revisão independente do plano
identificou esta fixture como o caso que expõe o bug se alguém usar só
`step.get("original_index")` isolado.

### Definição obrigatória de `_source_indices` (Seção 8)

```python
def _source_indices(step):
    idxs = []
    if "original_index" in step:
        idxs.append(step["original_index"])
    idxs += [m["original_index"] for m in step.get("merged_from", [])]
    idxs += step.get("source_events", [])
    return idxs
```

`position_anchor(step) = min(_source_indices(step))`.

### Aplicando a `st_001` desta fixture

`st_001` é o step sobrevivente do merge: conteúdo = evento 3
(`original_index: 2`, campo raiz), `merged_from = [{"original_index": 0, ...}]`
(evento 1 absorvido).

```
_source_indices(st_001) = [2] + [0] + [] = [2, 0]
position_anchor(st_001) = min(2, 0) = 0
```

**Se alguém ler só `st_001.get("original_index")` isolado (ignorando
`merged_from`)**, o anchor sairia `2` (o índice do evento 3, que é o mais
TARDIO do grupo fundido, porque `choose()` elege o clique mais recente como
conteúdo — ver seção acima). Isso é o anchor ERRADO: ele ignora que o step
também "representa" fisicamente o evento 1 (índice 0), que aconteceu ANTES
do evento 2.

### Comparando com `sup_001`

`sup_001` é um step simples (não fundido): `original_index: 1` (o próprio
evento 2, sem `merged_from`/`source_events`).

```
_source_indices(sup_001) = [1]
position_anchor(sup_001) = 1
```
(`sup_001["original_index"]` já é o valor usado para ordenar/intercalar
`sup_` — Seção 8, passo 5: `suppressed = sorted([...], key=lambda s: s["original_index"])`.)

### O algoritmo de interleave (Seção 8, passo 5 — merge-insert, não sort global)

```python
final_steps = []
sup_iter = iter(suppressed)          # [sup_001], original_index=1
next_sup = next(sup_iter, None)      # sup_001

for st_step in steps:                # steps = [st_001] (único)
    st_anchor = min(_source_indices(st_step))   # = 0 (via merged_from)
    while next_sup is not None and next_sup["original_index"] < st_anchor:
        # sup_001["original_index"] == 1; "1 < 0" é False → loop não roda
        final_steps.append(next_sup)
        next_sup = next(sup_iter, None)
    final_steps.append(st_step)      # final_steps = [st_001]

while next_sup is not None:          # sup_001 ainda pendente
    final_steps.append(next_sup)     # final_steps = [st_001, sup_001]
    next_sup = next(sup_iter, None)
```

**Com o anchor CORRETO (`0`, via `_source_indices`/`merged_from`):**
`sup_001.original_index (1) < st_anchor (0)`? **Não** (`1 < 0` é falso) → o
laço `while` nunca insere `sup_001` antes de `st_001`. `sup_001` só entra no
laço final de "remanescentes", **depois** de `st_001`. Ordem final:
`[st_001, sup_001]` — exatamente a ordem usada em
`plano_execucao_esperado.json`.

**Com o anchor ERRADO (`2`, ignorando `merged_from`, só o campo raiz):**
`sup_001.original_index (1) < st_anchor errado (2)`? **Sim** (`1 < 2` é
verdadeiro) → o laço `while` inseriria `sup_001` **antes** de `st_001`.
Ordem resultante: `[sup_001, st_001]` — **invertida**, e errada não por um
detalhe estético: o evento 2 (R1, cronologicamente entre o evento 1 e o
evento 3) apareceria posicionado como se tivesse acontecido antes de
qualquer parte do grupo fundido, quando na verdade ele aconteceu no MEIO do
grupo (depois do evento 1, antes do evento 3) — o merge apenas escolheu
representar o grupo pelo conteúdo do evento mais tardio (3), o que não muda
quando o evento 1 aconteceu.

**Conclusão normativa:** a ordem correta e esperada é `st_001` primeiro,
`sup_001` depois. Um README ou implementação que justificasse essa ordem
usando só o `original_index` de topo do `st_001` (2) chegaria à ordem
oposta e errada — não só imprecisa.

## `fidelity_summary` — como cada número foi calculado

```json
{
  "raw_events": 3,
  "steps_required": 1,
  "steps_optional": 0,
  "steps_suppressed": 1,
  "merges": 1
}
```

- `raw_events: 3` — total de eventos em `gravacao.json` (todos os 3 são
  `click`, um tipo "interação"; não há eventos `annotation`/`scroll`/
  `keypress` nesta fixture, então esse número coincide com
  `total_recorded_steps` — coincidência desta fixture minimalista, não uma
  igualdade garantida em geral: gravações reais com anotações têm
  `raw_events > total_recorded_steps`).
- `total_recorded_steps: 3` — eventos de tipo em `allowed_types =
  {click, fill, filechooser}` (`sanitizer.py:929`) que entram na cadeia de
  construção de steps: os 3 eventos, todos `click`.
- `steps_required: 1` — só `st_001` (contagem de `execution_hint` ausente/`required`).
- `steps_optional: 0` — nenhum step `optional` nesta fixture.
- `steps_suppressed: 1` — só `sup_001`.
- `merges: 1` — **uma operação** de merge que absorveu eventos (evento 1
  absorvido pelo step do evento 3), não o total de eventos absorvidos.
  Citação do plano (Seção 3): "conta operações de merge que absorveram pelo
  menos 1 evento (...), não o total de eventos absorvidos". Como só há 1
  merge (evento 1 → step do evento 3), `merges = 1`, não `2`.
- `total_steps: 1` = `steps_required + steps_optional` = `1 + 0` (Seção 3:
  "`total_steps` mantém a semântica atual (= emitíveis)").

Reconciliação de contagens (não é um campo do schema, só verificação
interna): 3 eventos brutos → 1 merge consome 2 deles (eventos 1 e 3) em 1
step → sobra 1 evento (evento 2) como 1 step suprimido → total de **2**
entradas no array `steps` (`st_001` + `sup_001`) representando **3** eventos
brutos. A diferença (3 eventos vs 2 steps) é inteiramente explicada pelo
único merge.

## Campos normativos vs. ilustrativos

Conforme o prompt desta tarefa, os campos que uma implementação futura de
T2 deve comparar **mecanicamente** contra este golden são: sequência de
`step_id`, `execution_hint` (valor efetivo, ver nota abaixo), `step_role`,
`type`, `selector`, `merged_from` (os `original_index` dos absorvidos),
`original_index` dos `sup_`, e `fidelity_summary`. Os demais campos
(`description`, `coords`, `text`, `scenario`, `parent`, `suppression_reason`)
foram preenchidos seguindo a derivação real de `_write_execution_plan` (hoje)
+ Seção 3 do plano (campos novos), então devem bater na prática, mas **não**
são o alvo primário de uma comparação estrita campo-a-campo — um teste que
quiser ser resiliente a texto ilustrativo (ex.: a frase exata de
`suppression_reason`, ou `description`) deve comparar por presença/tipo, não
por igualdade literal de string, para não ficar frágil a reformulações de
texto que não mudam a semântica.

Duas decisões de formato que valem a pena destacar (não são ambíguas, mas
não são óbvias de primeira leitura):

1. **`execution_hint` ausente em `st_001`** — o exemplo canônico da Seção 3
   (`st_012`/`st_013`/`st_020`) **omite** `execution_hint` em steps
   emitíveis, contando com a regra de retrocompatibilidade "campo ausente ⇒
   `required`" (Seção 3, "Regras de retrocompatibilidade do schema"). Só
   `sup_003`/`sup_004` mostram o campo explícito (`"skip"`). Este golden
   segue a mesma convenção: `st_001` não tem `execution_hint` no JSON, e um
   comparador correto deve ler o valor efetivo via
   `step.get("execution_hint", "required")`, não afirmar a presença literal
   da chave.
2. **`step_role` ausente em `st_001`** — mesma lógica: o catálogo da Seção 3
   diz "Para steps emitíveis: ausente (default `primary`) ou
   `composite_select`". `st_001` é um clique fundido simples, não um
   `composite_select` (esse é produzido só por `_reorder_dropdown_pairs`,
   que não participa desta fixture) — então `step_role` fica ausente
   (default `primary`), igual ao exemplo `st_012`/`st_013`/`st_020` da
   Seção 3 (só `st_013`, o composite_select, mostra o campo).

## Campos fora de comparação

- **`generated_at`** — timestamp de geração (`datetime.now().isoformat(...)`
  em `sanitizer.py`), não-determinístico por natureza. O valor presente
  neste arquivo (`"2026-07-11T09:15:01"`) é só um placeholder plausível.
- **`test_dir`** — `os.path.basename(self.telemetry_dir)`
  (`sanitizer.py:1074`). Tecnicamente determinístico *se* o sanitizer rodar
  direto contra esta pasta, mas outras tarefas do backlog (ex.:
  `[SUBAGENTE 03]`/T1) instruem explicitamente copiar a fixture para uma
  pasta temporária isolada antes de rodar (nunca rodar contra o golden
  commitado) — nesse caso `test_dir` reflete o nome da pasta temporária, não
  `"synthetic_r1_merge_case"`. Por isso fica fora da comparação, mesmo sendo
  determinístico neste arquivo específico.

## Checklist de não-contaminação (o que esta fixture deliberadamente NÃO exercita)

Para manter o golden focado só na ambiguidade R1×merge, nenhum destes outros
mecanismos do sanitizer é acionado por esta fixture (verificado campo a
campo acima):

- R2/R3 (overlay/painel órfão) — nenhum selector contém os gatilhos.
- R4 (fill duplicado) — não há eventos `fill`/`change`.
- Padrão P (inversão autocomplete) — não há par `click`+`fill` de
  autocomplete.
- Padrão Q (token dinâmico em `has_text`) — `"Abrir Modal"` não casa com
  `\b[A-Za-zÀ-ÿ]{2,8}-\d{3,}\b` (não há hífen+dígitos).
- Achatamento `label:has-text(...) input` → `label` — nenhum selector bate
  com esse padrão.
- `_reorder_dropdown_pairs`/`_mark_superseded_selects`/
  `_mark_phantom_pretrigger_clicks` — nenhum evento é `select`/
  `[role='option']`, então essas 3 funções são no-ops sobre a saída do
  merge (`steps` permanece `[st_001]` depois delas).
- `weak_selector`/`fallback_selectors`/`flaky` herdado — nenhum evento tem
  `confidence`/`fallback_selectors`, e não existe `plano_execucao.json`
  anterior nesta pasta para herdar `flaky`.

## Validação de JSON

```bash
python -c "import json; json.load(open('.specs/golden/synthetic_r1_merge_case/gravacao.json', encoding='utf-8'))"
python -c "import json; json.load(open('.specs/golden/synthetic_r1_merge_case/dicionario.json', encoding='utf-8'))"
python -c "import json; json.load(open('.specs/golden/synthetic_r1_merge_case/plano_execucao_esperado.json', encoding='utf-8'))"
```
