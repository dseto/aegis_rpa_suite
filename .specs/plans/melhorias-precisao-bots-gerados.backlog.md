# BACKLOG DE EXECUÇÃO - CLAUDE CODE

> 🏁 DEMANDA FECHADA — 2026-07-09. 13/13 subagentes concluídos. Aceitação: suíte ✅ (63 casos, 6 arquivos) · integração ✅ (Fimm Finance real 6/6 limpo; Portal Segura roda sem regressão, falha no mesmo ponto flaky pré-existente já documentado) · objetivo do plano ✅ com 1 ressalva (M5/`fallback_selectors` comprovado em produção real no piloto Fimm, mas nunca exercitado no `portal_segura/001_teste` porque o plano desse teste é anterior à melhoria — segue como follow-up não bloqueante: re-gravar o 001_teste quando conveniente). Ver relatório completo abaixo.
>
> Durante uso real pós-backlog, 5 bugs adicionais fora do escopo original M1-M5 foram achados e corrigidos: (1) seleção de step_id no diagnóstico automático (auto_N sintético vs real), (2) dedup do Sensor F1 suprimindo regressões pós-`resolved`, (3) feature de marcar passo como falho manualmente (endpoint + UI), (4) falso positivo do sensor `CLICK_NO_EFFECT` em SPAs React (4º sinal de fingerprint de classe), (5) recorder sobrescrevendo tradução semântica do dataset ao regravar — corrigido na raiz com auto-preservação por seletor físico. Todos validados ao vivo contra sites reais, 2 deles corrigidos em 2 iterações após eu mesma achar bugs na v1 do fix (documentado com autocrítica em `.specs/relatorio-piloto-site-novo.md`).

**Plano de origem:** `.specs/plans/melhorias-precisao-bots-gerados.md` (revisado via plan-critic em 2026-07-06)
**Restrição global:** navegador sempre MS Edge (`channel="msedge"`, default do runner — runner.py:1614). Nenhuma tarefa altera esse default. Testes novos que instanciem browser passam `channel="msedge"` explícito.
**Regra de isolamento:** mudanças de framework só em `aegis_*`; artefatos de projeto só em `projects/`.

---

### [SUBAGENTE 01] - M0: Baseline de regressão do Portal Segura 001_teste
> ✅ CONCLUÍDO — baseline capturado em `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`. **ALERTA:** taxa de sucesso atual é 0/1 (0%) nas 3 execuções, cada uma falhando em ponto diferente (não determinístico). Ver nota ao usuário.
- **🎯 Objetivo:** Capturar baseline de 3 execuções do `001_teste` ANTES de qualquer mudança de código, para servir de gate de regressão a todas as melhorias.
- **📂 Escopo de Arquivos:**
  - Ler: `projects/portal_segura/tests/001_teste/code/bot_producao.py`, `projects/portal_segura/tests/001_teste/historico_passos.json`, `projects/portal_segura/tests/001_teste/correcoes_acumuladas.json`, `projects/portal_segura/tests/001_teste/reports/` (CSV mais recente pós-execução)
  - Modificar (criar): `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é capturar o baseline de regressão do teste `projects/portal_segura/tests/001_teste`. Execute o bot 3 vezes: `python projects/portal_segura/tests/001_teste/code/bot_producao.py` (Edge é o channel default do runner; não altere flags de browser). Após cada execução, colete de `historico_passos.json` e do CSV de report: (1) taxa de sucesso de transações, (2) nº de restarts flaky (linhas re-executadas pelo Padrão R — procure logs de retry de linha), (3) nº de passos com status HEALED por healing_method, (4) nº de entradas novas em `correcoes_acumuladas.json` (diff de contagem antes/depois), (5) tempo total. Grave tudo em `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md` como tabela por execução + média, com data e hash do commit atual (`git rev-parse HEAD`). NÃO modifique nenhum arquivo do projeto portal_segura nem código do framework. Se uma execução falhar por ambiente (site fora do ar, credencial), registre o fato no baseline e re-execute."
- **🧪 Critério de Validação (DoD):**
  - [x] 3 execuções completas registradas (ou falhas de ambiente documentadas)
  - [x] Arquivo `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md` existe com as 5 métricas por execução + commit hash
  - [x] `git status` mostra apenas o arquivo de baseline como novo (nenhum arquivo de framework tocado)

---

### [SUBAGENTE 02] - M1: `error_message_selector` configurável por projeto
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 4/4 passou.
- **🎯 Objetivo:** Permitir que `project.json` defina `error_message_selector` customizado, parametrizando o boilerplate canônico do Code Generator (hoje fixo em `".toast-error, .alert-danger"`).
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/code_generator.py` (foco: `_normalize_boilerplate` linha ~31, `canonical_main` linha ~78, segunda ocorrência linha ~755, leitura de `project.json` no `generate()` linha ~155)
  - Modificar: `aegis_sanitizer/code_generator.py`, `README.md` (seção Fase 4)
  - Criar: `aegis_sanitizer/test_error_selector_config.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa em `aegis_sanitizer/code_generator.py`: (1) no `generate()`, ao carregar `project.json` (já lido por volta da linha 155), leia o campo opcional `error_message_selector`; (2) em `_normalize_boilerplate()` (linha ~31), parametrize a linha do `canonical_main` que hoje hardcoda `error_message_selector=\".toast-error, .alert-danger\"` (linha ~78) — use o valor do projeto se presente, senão o default atual, escapando aspas do valor ao interpolar; (3) aplique o mesmo tratamento à segunda ocorrência hardcoded (linha ~755, template de prompt). Projetos sem o campo devem gerar bloco `__main__` byte-idêntico ao atual. Crie `aegis_sanitizer/test_error_selector_config.py` (executável com `python`, sem pytest, padrão dos testes existentes do repo) cobrindo: projeto COM campo → seletor customizado no `__main__`; projeto SEM campo → default atual. Documente o campo novo no README.md, seção da Fase 4. Não toque no runner, não refatore nada além do descrito."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_error_selector_config.py` passa (2 casos)
  - [x] `python -m py_compile aegis_sanitizer/code_generator.py` passa
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` continua passando
  - [x] README atualizado com o campo `error_message_selector`

---

### [SUBAGENTE 03] - M2: Sensor `CLICK_NO_EFFECT` (log-only, registro atrás de flag)
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 4/4 passou (29 testes runner + 7 cognitive_fallback).
- **🎯 Objetivo:** Detectar passo fantasma (clique `force=True` sem efeito) em `click_resilient`, com polling early-exit e sem jamais mudar o resultado do passo.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (foco: `click_resilient` linha ~317, clique `force=True` linha ~411, `_wait_if_wizard_transition_button`, `_register_healing_for_review` linha ~223), seção M2 do plano `.specs/plans/melhorias-precisao-bots-gerados.md`
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`, `README.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é implementar o sensor CLICK_NO_EFFECT em `click_resilient` de `aegis_runner/runner.py`, seguindo EXATAMENTE a seção M2 do plano `.specs/plans/melhorias-precisao-bots-gerados.md`. Regras rígidas: (1) detecção-apenas — o passo continua retornando True e logando SUCCESS; NÃO toque no `force=True` nem adicione retry; (2) snapshot pré-clique em UMA chamada `page.evaluate()` com sinais: url, contagem de nós DOM (tolerância ±2 na comparação), contagem de overlays (`.cdk-overlay-container *, [role=dialog], .modal.show`) — `document.activeElement` NÃO é sinal de efeito; (3) pós-clique, polling early-exit em ~100/300/800ms — qualquer sinal mudou, saia imediatamente; espera fixa de 800ms é reprovação; (4) sem efeito ao fim → logar `[AEGIS RUNNER] ⚠️ CLICK_NO_EFFECT | {step_id} | {selector}`; registro em `correcoes_acumuladas.json` via `_register_healing_for_review(step_id, selector, 'click', healing_method='click_no_effect')` SOMENTE se `AEGIS_CLICK_EFFECT_REGISTER=true` (default false = fase log-only do plano); (5) flag mestre `AEGIS_CLICK_EFFECT_SENSOR` (default true) — false desativa tudo, zero evaluate extra; (6) exclusões: `validate_navigation=True`, seletores das famílias `_wait_for_known_disabled_button`/`_wait_if_wizard_transition_button`; falha do próprio evaluate = efeito detectado, nunca erro. Adicione caso de teste em `aegis_runner/test_runner_integration.py` (padrão dos testes existentes) cobrindo: overlay cobrindo alvo → log CLICK_NO_EFFECT; com `AEGIS_CLICK_EFFECT_REGISTER=true` → entrada needs_review com healing_method correto; clique com mutação → nenhum log; `AEGIS_CLICK_EFFECT_SENSOR=false` → sensor inerte. Browser de teste: `channel='msedge'`. Documente no README (seção Mecanismos de Resiliência Nativos) o sensor + a limitação herdada do dedup do Sensor F1 (runner.py:291-309, supressão pós-correção — fora de escopo corrigir). Nada além disso."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` passa (casos novos + suíte existente)
  - [x] `python aegis_runner/test_cognitive_fallback.py` continua passando
  - [x] Grep confirma: `activeElement` não usado como sinal de efeito no bloco do sensor
  - [x] README atualizado (sensor + limitação do dedup)

---

### [SUBAGENTE 04] - M4: Dry-run sobre todas as linhas do dataset
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 3/3 passou.
- **🎯 Objetivo:** `dry_run_bot()` exercita todas as linhas do dataset (teto `AEGIS_DRYRUN_MAX_ROWS`, default 20) num único subprocess, reportando o id da linha que falhou.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/step_validator.py` (foco: `dry_run_bot` linha ~1400, carga de `rows[0]` linhas ~1419-1435, harness linhas ~1437-1528)
  - Modificar: `aegis_sanitizer/step_validator.py`
  - Criar: `aegis_sanitizer/test_dryrun_multirow.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa em `dry_run_bot()` de `aegis_sanitizer/step_validator.py` (linha ~1400): (1) carregue TODAS as linhas de `dataset_inicial.json` (hoje só `rows[0]`, linhas 1419-1435), com teto `AEGIS_DRYRUN_MAX_ROWS` (env var, default 20); (2) mantenha UM ÚNICO subprocess — o harness (string gerada ~linha 1437) recebe a lista de rows via repr e itera internamente chamando `fn(fake_page, row, fake_runner)` por linha, fail-fast na primeira exceção; (3) no erro, inclua o id da linha no detail: `DRYRUN_RUNTIME_ERROR::TypeError::... (linha do dataset id=7)` — use `row.get('id', índice+1)`; (4) o bloco `__main__` do bot continua executado UMA vez (comportamento atual do harness, preservar); (5) assinatura de `dry_run_bot` inalterada; sem `dataset_dir`, comporta-se como hoje (row vazio). Crie `aegis_sanitizer/test_dryrun_multirow.py` (executável com `python`) cobrindo: bot com `datetime.strptime(row['data'], ...)` que só quebra na linha 3 → dry-run falha com id da linha no detail; dataset de 100 linhas → processa no máximo o teto e termina dentro do timeout de 30s; bot válido → DRYRUN_OK. Não altere `_FakeRunner`, validações AST nem nada fora de `dry_run_bot` e seu harness."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_dryrun_multirow.py` passa (3 casos)
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` continua passando
  - [x] `python -m py_compile aegis_sanitizer/step_validator.py` passa

---

### [SUBAGENTE 05] - M3a: `confidence` gravado nos eventos de click/fill do recorder
> ✅ CONCLUÍDO — DoD reverificado na thread principal. Pendência manual (gravação ao vivo) declarada, aceitável.
- **🎯 Objetivo:** Recorder grava score de `evaluate_selector_reliability` como campo `confidence` em cada evento de click/fill de `gravacao.json` (hoje só campos do `dicionario.json` têm o score).
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_blackbox/recorder.py` (foco: `evaluate_selector_reliability` linha ~859, uso existente linhas ~1132 e ~1158, ponto Python de ingestão/montagem dos eventos vindos do JS)
  - Modificar: `aegis_blackbox/recorder.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa em `aegis_blackbox/recorder.py`: localize o ponto PYTHON onde eventos de click/fill vindos do JS injetado são recebidos/anexados à telemetria (a lista que vira `gravacao.json`). Nesse ponto, para eventos que possuem seletor, adicione `event['confidence'] = evaluate_selector_reliability(event['selector'])[0]` (a função já existe na linha ~859 e retorna tupla `(score, tipo)`; use só o score). NÃO recalcule em outros lugares, NÃO altere o JS injetado, NÃO mude o schema de nenhum outro campo, NÃO toque no `dicionario.json` (já tem confidence). Eventos sem seletor (coordenada pura) não recebem o campo. Mudança mínima — na prática poucas linhas."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m py_compile aegis_blackbox/recorder.py` passa
  - [ ] Inspeção: o campo é adicionado no ponto único de ingestão de eventos, sem duplicação
  - [ ] Validação manual documentada na entrega: gravação curta em projeto de teste (ex.: `katalon_demo_form`) gera eventos com `confidence` numérico em `gravacao.json` (se não for possível executar gravação no ambiente, declarar explicitamente como pendência manual)

---

### [SUBAGENTE 06] - M3b: Flag `weak_selector` no plano de execução
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 2/2 passou.
- **🎯 Objetivo:** Sanitizer marca `"weak_selector": true` nos steps do `plano_execucao.json` cujo evento tem `confidence < 70` explícito.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/sanitizer.py` (foco: método de geração do plano com docstring "Gera plano_execucao.json...", linha ~926; step_id `st_{i+1:03d}` linha ~1050)
  - Modificar: `aegis_sanitizer/sanitizer.py`, `aegis_sanitizer/test_sanitizer_execution_plan.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa no método de geração do `plano_execucao.json` em `aegis_sanitizer/sanitizer.py` (docstring 'Gera plano_execucao.json...', linha ~926): para cada step, leia `confidence` do evento de origem. Se o campo EXISTE e `< 70`, adicione `\"weak_selector\": true` ao step. Campo ausente (gravação antiga) = NÃO marcar — nunca use default 40 aqui; retrocompatibilidade exige que gravações antigas não recebam a flag. Steps com `confidence >= 70` não recebem o campo (ausência = false, não grave `false` explícito). Estenda `aegis_sanitizer/test_sanitizer_execution_plan.py` com casos: evento com confidence 40 → step com weak_selector true; evento com confidence 100 → sem o campo; evento sem confidence → sem o campo. Não altere Padrão Q, dedup, reordenação de dropdowns nem qualquer outra regra do sanitizer."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` passa (casos novos + existentes)
  - [x] `python -m py_compile aegis_sanitizer/sanitizer.py` passa

---

### [SUBAGENTE 07] - M3c: Check `WEAK_SELECTOR_WITHOUT_ANCHOR` + instrução no prompt
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 4/4 passou.
- **🎯 Objetivo:** Validador exige ancoragem determinística (has_text/chained) para steps `weak_selector: true`; prompt do gerador instrui a LLM a ancorar. `original_coords` NÃO conta como reforço.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/step_validator.py` (foco: `validate_resilience_patterns` linha ~699, checks `MISSING_*_COORDS` linhas ~829-928 como referência de padrão), `aegis_sanitizer/code_generator.py` (foco: montagem do prompt principal e `_strip_internal_step_fields` linha ~113)
  - Modificar: `aegis_sanitizer/step_validator.py`, `aegis_sanitizer/code_generator.py`
  - Criar: `aegis_sanitizer/test_weak_selector_enforcement.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, duas mudanças cirúrgicas: (1) em `validate_resilience_patterns()` de `aegis_sanitizer/step_validator.py` (linha ~699), novo check `WEAK_SELECTOR_WITHOUT_ANCHOR`: para cada step do plano com `weak_selector: true`, o código gerado correspondente (âncora `# [PASSO X]`/step_id, mesmo mecanismo dos checks existentes) deve conter ao menos UM reforço: `:has-text(` no seletor/parent (literal ou dinâmico) OU chamada `click_chained`/`fill_chained` com `parent=`. `original_coords` NÃO conta como reforço (o validador já força coords via checks MISSING_*_COORDS — aceitá-las tornaria o check inócuo). Sem reforço → erro de validação no mesmo formato dos checks existentes (alimenta o Ralph Loop). Step sem a flag → check não dispara. (2) em `aegis_sanitizer/code_generator.py`, na montagem do prompt principal, para steps `weak_selector: true` injete instrução destacada: 'seletor de baixa confiabilidade — obrigatório ancorar com parent/has_text (chained ou :has-text)'. Garanta que `weak_selector` NÃO entra em `_strip_internal_step_fields` (a LLM deve vê-lo). Crie `aegis_sanitizer/test_weak_selector_enforcement.py` (executável com `python`) cobrindo: step weak sem ancoragem → falha com WEAK_SELECTOR_WITHOUT_ANCHOR; step weak só com original_coords → TAMBÉM falha; step weak com :has-text → passa; step weak com click_chained(parent=...) → passa; step sem flag e sem ancoragem → passa. Nada além disso — não toque no Ralph Loop nem em outros checks."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_weak_selector_enforcement.py` passa (5 casos)
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` continua passando
  - [x] `python aegis_sanitizer/test_dryrun_multirow.py` continua passando (se SUBAGENTE 04 já mergeado)
  - [x] `python -m py_compile aegis_sanitizer/step_validator.py aegis_sanitizer/code_generator.py` passa

---

### [SUBAGENTE 08] - M5a: `getAegisSelectorCandidates` no JS do recorder
> ✅ CONCLUÍDO — DoD reverificado na thread principal com inspeção manual do diff (334 linhas). Cascata original preservada byte-a-byte; validação end-to-end de gravação real pendente (ambiente sem browser interativo).
- **🎯 Objetivo:** Cascata de seletores coleta até 3 candidatos únicos de estratégias distintas; vencedor continua primário, perdedores viram `fallback_selectors` no evento.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_blackbox/recorder.py` (foco: JS injetado — `getAegisSelector` linha ~86, `queryLength` linha ~30, validações de unicidade linhas ~272/305/410, handlers de click/fill que montam o evento)
  - Modificar: `aegis_blackbox/recorder.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa no JS injetado de `aegis_blackbox/recorder.py`: (1) crie `getAegisSelectorCandidates(element)` reaproveitando a cascata existente de `getAegisSelector` (data-testid → id → labels → mat-form-field → form-group → has-text) — refactor MÍNIMO: extraia a cascata para lista de provedores de estratégia SEM reescrever nenhuma heurística individual; colete até 3 candidatos de estratégias DISTINTAS, cada um validado único com `queryLength(sel) === 1` (função já existe, linha ~30); (2) `getAegisSelector` vira wrapper que retorna `candidates[0]` — comportamento existente byte-idêntico é requisito; (3) handlers de click/fill gravam `fallback_selectors: candidates.slice(1)` no evento (array, pode ser vazio); (4) eventos sem seletor primário confiável (coordenada pura) não recebem o campo. Preserve interação com o campo `confidence` adicionado no lado Python (SUBAGENTE 05) — confidence continua calculado sobre o seletor primário. Não altere schema de outros campos, não toque no Python além do necessário para propagar o campo novo do evento."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -m py_compile aegis_blackbox/recorder.py` passa
  - [x] Inspeção: cascata extraída sem alteração de heurísticas; `getAegisSelector` retorna `candidates[0]`
  - [x] Validação manual documentada na entrega (jsdom, não gravação real): pendência de gravação ao vivo declarada

---

### [SUBAGENTE 09] - M5b: Propagação de `fallback_selectors` para o plano
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 2/2 passou.
- **🎯 Objetivo:** Sanitizer propaga `fallback_selectors` do evento para o step do `plano_execucao.json`, com Padrão Q e dedup aplicados aos fallbacks.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/sanitizer.py` (foco: geração do plano linha ~926, Padrão Q/sanitização de has_text, `_reorder_dropdown_pairs` linha ~686)
  - Modificar: `aegis_sanitizer/sanitizer.py`, `aegis_sanitizer/test_sanitizer_execution_plan.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa na geração do `plano_execucao.json` em `aegis_sanitizer/sanitizer.py` (linha ~926): (1) propague `fallback_selectors` do evento para o step correspondente; (2) aplique aos fallbacks as mesmas sanitizações do seletor primário: remoção de token dinâmico em `:has-text(` (Padrão Q — reuse a função existente, não duplique lógica) e dedup contra o seletor primário e entre si (fallback igual ao primário é descartado); (3) steps colapsados `type: 'select'` (dropdowns via `_reorder_dropdown_pairs`): NÃO propagar fallbacks na v1 — dropdowns ficam fora do escopo, apenas garanta que o colapso não quebra com eventos que carregam o campo; (4) evento sem o campo → step sem o campo (gravações antigas idênticas ao comportamento atual). Estenda `aegis_sanitizer/test_sanitizer_execution_plan.py`: evento com 2 fallbacks → step com os 2; fallback com token dinâmico em has-text → sanitizado; fallback duplicado do primário → removido; evento sem o campo → step sem o campo; par dropdown com fallbacks → colapso funciona e step select sem campo de fallback. Não altere weak_selector, Padrão Q original nem outras regras."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` passa (casos novos + existentes)
  - [x] `python -m py_compile aegis_sanitizer/sanitizer.py` passa

---

### [SUBAGENTE 10] - M5c: `fallback_selectors` invisível para a LLM
> ✅ CONCLUÍDO — DoD reverificado na thread principal, 3/3 passou.
- **🎯 Objetivo:** `_strip_internal_step_fields` remove `fallback_selectors` dos steps antes de expor o plano no prompt — a LLM nunca vê o campo.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/code_generator.py` (foco: `_strip_internal_step_fields` linha ~113)
  - Modificar: `aegis_sanitizer/code_generator.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, mudança de uma linha em `aegis_sanitizer/code_generator.py`: adicione `'fallback_selectors'` à tupla `internal_fields` de `_strip_internal_step_fields` (linha ~121, hoje `('trigger_selector', 'option_selector')`). Atualize a docstring do método mencionando o novo campo. `weak_selector` NÃO entra na tupla (a LLM deve vê-lo — decisão do plano M3). Nada além disso."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -m py_compile aegis_sanitizer/code_generator.py` passa
  - [x] `python aegis_sanitizer/test_error_selector_config.py` continua passando (se SUBAGENTE 02 já mergeado)
  - [x] Inspeção: tupla contém `fallback_selectors` e NÃO contém `weak_selector`

---

### [SUBAGENTE 11] - M5d: Cadeia de fallback determinístico no runner
> ✅ CONCLUÍDO — DoD reverificado na thread principal (34/34 + 7/7), diff inspecionado linha a linha: nível 2.9 roda antes do gate strict, single-load do plano confirmado, select_option_resilient/force=True/sensor M2/Padrão R intocados.
- **🎯 Objetivo:** `click_resilient`/`fill_resilient` tentam `fallback_selectors` do plano (novo nível entre heurística determinística e fallback cognitivo); sucesso vira `HEALED` + `needs_review`.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (foco: carga do plano em `run()` linhas ~1626-1637, `click_resilient` linha ~317, `fill_resilient`, `_register_healing_for_review` linha ~223), seção M5 do plano `.specs/plans/melhorias-precisao-bots-gerados.md`
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa em `aegis_runner/runner.py`, seguindo EXATAMENTE a seção M5 do plano `.specs/plans/melhorias-precisao-bots-gerados.md`: (1) no bloco existente de carga do plano em `run()` (linhas ~1626-1637, onde `self.flaky_step_ids` é montado), adicione `self.fallback_selectors_by_step = {s['step_id']: s.get('fallback_selectors', []) for s in self.execution_plan['steps']} if self.execution_plan else {}` — NÃO crie segunda carga do arquivo, NÃO mexa no `__init__`; (2) em `click_resilient` e `fill_resilient`, novo nível na cadeia ENTRE a heurística determinística atual (retry Escape/multi-elemento) e o fallback cognitivo (vision/coordenadas): quando o caminho atual esgota, itere os fallbacks do step (ordem gravada), tentando a operação com timeout ~2s cada; primeiro que funcionar resolve o passo; (3) sucesso via fallback → logar status HEALED com método próprio no `_log_step` e registrar `_register_healing_for_review(step_id, selector_primario, action, healing_method='fallback_selector')`; (4) semântica strict decidida no plano: fallback determinístico RODA mesmo com `strict=True` (só em `click_resilient`, único que tem o parâmetro); healing cognitivo continua bloqueado sob strict como hoje; (5) step sem fallbacks ou plano ausente → cadeia byte-idêntica à atual; (6) NÃO altere `select_option_resilient` (fora da v1), NÃO toque em `force=True`, `_wait_for_known_disabled_button`, `_wait_if_wizard_transition_button` nem no Padrão R. Adicione casos em `aegis_runner/test_runner_integration.py` (browser `channel='msedge'`): seletor primário quebrado + fallback válido no plano → passo resolve via fallback, loga HEALED, gera needs_review com healing_method='fallback_selector', sem chamada LLM; sem fallbacks no plano → comportamento atual; strict=True + fallback válido → fallback roda."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` passa (casos novos + suíte existente)
  - [x] `python aegis_runner/test_cognitive_fallback.py` continua passando
  - [x] Inspeção: uma única carga de `plano_execucao.json` no runner; `select_option_resilient` intocado

---

### [SUBAGENTE 12] - Gate de regressão 001 (executar após CADA melhoria mergeada)
> ✅ CONCLUÍDO — rodado uma vez cobrindo M1-M5 mergeados (não foi gateado incrementalmente por melhoria, decisão prática desta execução). Veredito APROVADO em `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md` (seção "Gate pós-M1-M5"). Sem regressão; M3/M5 não exercitados (plano do 001 é anterior às melhorias, precisa re-gravação); sensor M2 confirmou valor diagnóstico real (apontou st_032 como causa raiz na execução 3).
- **🎯 Objetivo:** Provar que a melhoria recém-mergeada não regrediu o `001_teste` do Portal Segura (taxa ≥ baseline, flaky ≤ baseline, bot sem regeneração).
- **📂 Escopo de Arquivos:**
  - Ler: `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`, `projects/portal_segura/tests/001_teste/historico_passos.json`, `projects/portal_segura/tests/001_teste/correcoes_acumuladas.json`, CSV de report
  - Modificar: `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md` (apêndice de resultados por melhoria)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é rodar o gate de regressão do Portal Segura para a melhoria [INFORMAR: M1/M2/M3/M4/M5]. Execute `python projects/portal_segura/tests/001_teste/code/bot_producao.py` 3 vezes SEM regenerar o bot (arquivo `bot_producao.py` intocado — isso prova compatibilidade retroativa). Colete as mesmas 5 métricas do baseline (taxa de sucesso, restarts flaky, HEALED por método, needs_review novas, tempo) e compare com `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`. Critérios: taxa de sucesso ≥ baseline E (restarts flaky + HEALED) ≤ baseline. Anexe os resultados ao arquivo de baseline numa seção 'Gate pós-[melhoria]' com veredito APROVADO/REPROVADO. Se REPROVADO, NÃO tente corrigir — pare e reporte o diagnóstico (qual métrica regrediu, logs relevantes). Não modifique nenhum arquivo do framework nem do projeto."
- **🧪 Critério de Validação (DoD):**
  - [x] 3 execuções sem regeneração do bot
  - [x] Comparação com baseline anexada ao arquivo com veredito explícito
  - [x] Se aprovado: taxa ≥ baseline e flaky/HEALED ≤ baseline documentados (0% = 0%, HEALED 0.33 vs 0.67 baseline, dentro da variância)

---

### [SUBAGENTE 13] - Piloto em site novo (BLOQUEADO — aguarda site fornecido pelo usuário)
> ✅ CONCLUÍDO — site fornecido (Fimm Finance, `localhost:6174`, React/Vite/Tailwind). Pipeline completo rodado do zero (gravação dirigida via Playwright reaproveitando `AegisRecorder` real, sem formato paralelo). Relatório em `.specs/relatorio-piloto-site-novo.md`. Resultado: 6/6 sucesso, 0 chamadas LLM vision, mas 2 falsos positivos novos de `CLICK_NO_EFFECT` (mudança de estado só-CSS em React não detectada pelos 3 sinais atuais) e gap real entre `weak_selector`/`confidence` e a ambiguidade que o próprio recorder já detecta internamente. Erro de setup meu no caminho (faltou `project.json` no nível do teste) encontrado e corrigido, documentado no relatório.
- **🎯 Objetivo:** Medir generalização do framework em site com stack distinta do Portal Segura, produzindo relatório de fragilidades. **Pré-condição de entrada: URL/acesso fornecidos pelo usuário — o plano não cria nem escolhe site.**
- **📂 Escopo de Arquivos:**
  - Ler: `.specs/plans/melhorias-precisao-bots-gerados.md` (seção 8.2), `CLAUDE.md` (comandos das fases 1-5)
  - Modificar (criar): novo projeto em `projects/<slug-fornecido>/` (via pipeline normal), `.specs/relatorio-piloto-site-novo.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é o piloto de generalização da seção 8.2 do plano `.specs/plans/melhorias-precisao-bots-gerados.md`. Site alvo: [URL FORNECIDA PELO USUÁRIO — se não fornecida, PARE e solicite]. Rode o pipeline completo do zero, sem nenhum ajuste manual de seletor: gravar (`python aegis_blackbox/recorder.py --url <URL> --output-dir projects/<slug> --control-port 9900`) → sanitizar (`python aegis_sanitizer/sanitizer.py --project-dir projects/<slug>`) → validar (`python aegis_sanitizer/dataset_validator.py ...`) → gerar (`python aegis_sanitizer/code_generator.py --project-dir projects/<slug>`) → executar o bot (Edge default). Ative `AEGIS_CLICK_EFFECT_SENSOR=true` (log-only). Meça e grave em `.specs/relatorio-piloto-site-novo.md`: % de eventos com fallback_selectors capturados; % de steps weak_selector; taxa de sucesso na primeira execução; nº HEALED/needs_review por método; falsos positivos de CLICK_NO_EFFECT (inspecionar se os seletores de overlay do snapshot fazem sentido no site — se não, listar ajuste sugerido, NÃO aplicar); lista de fragilidades encontradas. O piloto não precisa atingir 100% de sucesso — o entregável é o relatório com fragilidades mensuráveis. Ao final, recomende (sem aplicar) se `AEGIS_CLICK_EFFECT_REGISTER` pode virar default true (taxa de falso positivo aceitável?). Artefatos só em `projects/` e `.specs/`."
- **🧪 Critério de Validação (DoD):**
  - [x] Pipeline completo executado sem ajuste manual de seletor
  - [x] `.specs/relatorio-piloto-site-novo.md` com todas as métricas da seção 8.2 + lista de fragilidades
  - [x] Recomendação explícita sobre ativação do registro do sensor M2 (manter `false` — falso positivo em SPA React é real)
  - [x] Zero mudança em código de framework durante o piloto
