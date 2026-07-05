# Handoff — Suporte a `<select>` nativo + bugs de gravação (2026-07-05)

## Contexto

Objetivo da sessão: testar o pipeline Aegis (5 fases) contra um site real
fora do universo já testado (portal_segura, todo Angular Material). Escolhido
o formulário público de teste da Katalon
(`https://katalon-test.s3.amazonaws.com/aut/html/form.html`), que tem campos
comuns nunca exercitados antes pela suíte: `<select>` HTML nativo, checkboxes
com `<label>` genérico (sem id/data-testid), radio buttons.

Projeto criado: `projects/katalon_demo_form/tests/002_preenchimento_completo/`.

Como a gravação foi feita sem tocar em `aegis_*` (regra do "motor selado"):
script descartável em scratchpad que faz `import aegis_blackbox.recorder as
recorder_mod` e reatribui `recorder_mod.run_auto_simulation` em runtime para
uma sequência de ações Playwright reais no site novo, depois chama
`AegisRecorder(...).start()` normalmente — reaproveita 100% do motor real de
captura (listeners JS, `record_action`, `save_telemetry_files_disk`), só troca
o "roteiro" que seria hardcoded pro portal_segura.

## Bugs encontrados e corrigidos (commit `b01e19f`)

### 1. `<select>` nativo classificado como `"string"` no dicionário

`aegis_blackbox/recorder.py`, `record_action()`: o campo `"type"` do
dicionário de dados só considerava `"date"` ou `"string"`, nunca checava
`ev.get("tag") == "select"`. Resultado real observado: `dicionario.json`
marcava `#role` (um `<select>`) como `"type": "string"`, o gerador de código
(LLM) tratava como input de texto e emitia `fill_resilient()` — que quebra em
runtime porque `Locator.fill()` do Playwright só aceita `<input>`,
`<textarea>`, `[contenteditable]`:

```
Locator.fill: Error: Element is not an <input>, <textarea> or [contenteditable] element
```

**Fix**: `type` agora vira `"select"` quando a tag é `SELECT` (nos dois
branches, `fill` e `scan_field`).

### 2. Valor fantasma de `<select>` capturado no primeiro clique da gravação

`flushAllInputs()` (JS injetado) varria `input, textarea, select` e gravava
qualquer valor não-vazio como se fosse uma ação recém-feita. Um `<select>`
nativo **sempre** tem `.value` não-vazio (a 1ª `<option>` vem pré-selecionada
antes de qualquer interação humana) — então o primeiro clique de qualquer tipo
na página disparava esse flush e gravava um passo fantasma tipo `FILL #role
Developer` (valor default do HTML, nunca escolhido pelo usuário) antes da
seleção real. `<input>`/`<textarea>` não sofrem disso porque começam vazios.

**Fix**: `flushAllInputs()` agora varre só `input, textarea`. `<select>` já é
coberto de forma confiável pelo listener nativo `change`, que só dispara numa
escolha real do usuário.

### 3. Cliques distintos com selector genérico idêntico colapsados em 1 só

`aegis_sanitizer/sanitizer.py`, `_dedup_consecutive_clicks` / `same_widget()`:
comparava só `selector` (e `parent.selector`/`parent.has_text`), nunca o texto
do clique. Dois checkboxes reais e distintos (`"Read books"` e `"Join tech
cons"`) ambos resolviam pro mesmo selector de fallback genérico `"label"`
(nenhum tinha id/data-testid, e `<label>` não entra no tratamento
`:has-text()` reservado a BUTTON/A/menu/role) — o segundo colapsava no
primeiro, uma das duas ações reais gravadas sumia silenciosamente do
`plano_execucao.json` final.

**Fix**: `same_widget()` agora calcula `texts_differ` (verdadeiro só quando
ambos os lados têm texto e ele difere) e bloqueia os 4 critérios de "mesmo
widget" nesse caso. Precisou também propagar o campo `text` bruto pro dict
`step` interno em `_write_execution_plan` (antes só existia em `description`,
que já vem *depois* de traduzido semanticamente pela IA — não dava pra
comparar).

## Feature nova: suporte a `<select>` nativo

Ao investigar o bug 1 a fundo, achado que **o framework não tinha nenhum
caminho de execução pra `<select>` nativo**: `select_option_resilient`
existente é inteiramente desenhado pra dropdown customizado/overlay JS
(Angular Material / CDK `[role='option']`) — abre um painel clicando num
"trigger", procura a opção dentro do overlay. Não existe, nunca existiu,
nenhuma chamada `page.select_option()` em `runner.py`. Corrigir só o
dicionário (bug 1) teria deixado o gerador sem NENHUM método correto pra
chamar.

Adicionado (aprovado explicitamente pelo usuário como escopo extra, via
`AskUserQuestion`):

- `aegis_runner/runner.py`: novo método `select_option_native_resilient(page,
  selector, option_text, target_description, timeout=5000, step_id=None)` —
  usa `page.select_option()` direto no seletor gravado (não adivinha por
  label como o `_resilient` original), com fallback por `value=`, limpeza via
  Escape, e self-healing visual via `CognitiveGateway` como último recurso.
- `aegis_sanitizer/sanitizer.py`, `_write_execution_plan`: evento de `fill`
  com `tag == SELECT` agora vira step `"type": "select_native"` no plano
  (carrega `option_text`).
- `aegis_sanitizer/step_validator.py`, `validate_resilience_patterns`: novo
  step type `"select_native"` exige chamada a
  `select_option_native_resilient` no código gerado (mesmo padrão de erro
  mecânico já usado pra `"select"` → `select_option_resilient`).
- `aegis_sanitizer/code_generator.py`: nova regra no prompt ("Padrão 13 —
  Select Nativo") ensinando a IA a distinguir os dois métodos.

## Validação end-to-end

Projeto regravado do zero com o recorder corrigido, rodadas as 5 fases:
sanitizer (14 steps, ambos checkboxes presentes, `select_native` corretos) →
dataset_validator (100% válido) → code_generator (convergiu na 1ª tentativa,
1/15) → execução real (`bot_producao.py`): **14/14 passos SUCCESS, zero
HEALED/FAILED**, confirmado por screenshot real do formulário preenchido e
"Successfully submitted!" (não só pelos marcadores de log — regra da sessão
de nunca confiar só em texto de IA/marcador de sucesso).

Um bug próprio introduzido durante a implementação (não do usuário): esqueci
`target_description` na assinatura de `select_option_native_resilient` na
1ª versão — o código gerado já chamava com esse kwarg (convenção de todos os
outros métodos do runner), quebrou na 1ª execução com
`TypeError: unexpected keyword argument 'target_description'`. A IA de
diagnóstico visual (`CognitiveGateway.diagnose_failure`) alucinou uma causa
completamente errada (datepicker bloqueando a tela) — mais uma confirmação
empírica de não confiar no texto de diagnóstico da IA sem checar a exceção
real no mesmo log. Corrigido, revalidado, aí sim rodou limpo.

## Fragilidades / dívidas que ficaram

1. **`flushAllInputs()` ainda pode ter o mesmo problema pra outros elementos
   com valor padrão não-vazio.** A correção foi específica pra `<select>`.
   Um `<input type="checkbox">`/`<input type="radio">` já vem pré-marcado no
   HTML (`checked` no markup) teria o mesmo tipo de falso-positivo se algum
   dia isso for testado — não verificado nesta sessão, não corrigido
   preventivamente (YAGNI: sem caso real observado ainda).

2. **`same_widget()` age só sobre cliques *consecutivos*.** Se dois elementos
   com selector genérico idêntico e texto diferente aparecerem
   NÃO-consecutivamente no fluxo mas ainda colidirem em algum outro critério
   de dedup mais adiante (`_reorder_dropdown_pairs`,
   `_drop_redundant_select_corrections`,
   `_drop_redundant_pretrigger_clicks`), esse texto novo (`step["text"]`) não
   foi propagado pra esses outros dedups — só pra `_dedup_consecutive_clicks`.
   Não observado como bug real ainda, mas é a mesma classe de risco.

3. **`select_option_native_resilient` não tem cobertura de teste automatizado.**
   Validado só manualmente contra o Katalon form. `aegis_runner/test_*.py`
   não ganhou nenhum caso novo pro método.

4. **Campo `text` no `step` dict do `plano_execucao.json` é interno,
   não-documentado no schema do plano.** Só existe em memória durante a
   geração (`_write_execution_plan` → `_dedup_consecutive_clicks`), nunca é
   serializado. Se o plano algum dia for consumido por outra ferramenta que
   espera um schema fixo, isso é invisível — não é bug, é só uma nota pra
   quem for mexer nessa função de novo.

5. **`select_option_native_resilient` não tem suporte a multi-select
   (`<select multiple>`).** Só testado com single-select. `page.select_option`
   aceita lista de valores, mas o método novo só passa `label=` /`value=`
   singular.

6. **README.md não foi atualizado com o novo padrão de resiliência #13
   (select nativo).** Diferente da sessão anterior (onde
   `strict=True`/`has_text` dinâmico foram documentados no README), esse
   commit não tocou documentação de usuário — só o handoff técnico que é
   este arquivo. Se for pra virar prática oficial do time, falta esse passo.

## Arquivos tocados (commit `b01e19f`)

- `aegis_blackbox/recorder.py`
- `aegis_runner/runner.py`
- `aegis_sanitizer/code_generator.py`
- `aegis_sanitizer/sanitizer.py`
- `aegis_sanitizer/step_validator.py`

Projeto de teste (gitignored, não versionado):
`projects/katalon_demo_form/tests/002_preenchimento_completo/`
