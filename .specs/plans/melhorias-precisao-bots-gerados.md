# Plano: Melhorias de Precisão e Qualidade dos Robôs Gerados

**Origem:** Auditoria de arquitetura RPA (skill `rpa-architecture-auditor`), refinada por reflexão contra `README.md`.
**Data:** 2026-07-06
**Status:** Revisado via `plan-critic` em 2026-07-06 (7 ajustes aplicados) — pronto para decomposição em backlog

---

## 1. Contexto e Objetivo

A auditoria confirmou que o pipeline de geração (Fase 4) é sólido — Ralph Loop, validação AST profunda (`validate_bot_structure`, `_validate_runner_call_contract`), dry-run em sandbox e boilerplate canônico já eliminam quase toda alucinação de LLM no `bot_producao.py`.

A precisão quebra hoje **em runtime**, não na geração. A dor documentada release após release no README (modo `strict=True`, sensor `needs_review`, Padrão R de flaky-retry) tem uma causa raiz comum: **quando o seletor primário falha, o único caminho de recuperação é não-determinístico** (LLM vision / coordenada gravada), que "adivinha" e erra.

**Objetivo:** aumentar a taxa de acerto determinístico dos bots gerados e tornar visível toda ação silenciosamente sem efeito, sem regredir os mecanismos calibrados existentes.

### Restrições operacionais

- **Navegador: MS Edge sempre.** O runner já usa `channel="msedge"` por default (runner.py:1614 — Playwright lança o engine Chromium do Edge instalado). Nenhuma melhoria pode alterar esse default, e **toda validação/piloto deste plano roda em Edge** (headed ou headless), nunca em Chromium puro. Testes novos que instanciem browser devem passar `channel="msedge"` explícito.

### Fora de escopo (explícito)

- **Funcionalidade de Skills** (`skills_lib.py`) — não está em uso hoje; validação da compilação de skills fica para quando voltar ao roadmap.
- **Remover ou reordenar `force=True` nos cliques** — README itens 9, 10 e 11 provam que é peça estrutural com três mecanismos construídos ao redor (`_wait_for_known_disabled_button`, `_wait_if_wizard_transition_button`, polling de `is_enabled()` no `fill_human_like`). Não tocar.
- Arquitetura enterprise (filas, multi-tenancy, paralelismo de execução).

---

## 2. Visão Geral das Melhorias

| # | Melhoria | Módulos | Esforço | Impacto | Risco de regressão |
|---|---|---|---|---|---|
| M1 | `error_message_selector` configurável por projeto | code_generator | Baixo | Médio | Baixo |
| M2 | Sensor `CLICK_NO_EFFECT` (detecção de passo fantasma) | runner | Baixo-Médio | Alto | Baixo (detecção-apenas) |
| M3 | Enforcement de `weak_selector` no plano e validação | recorder, sanitizer, step_validator, code_generator | Médio | Médio | Baixo |
| M4 | Dry-run sobre todas as linhas do dataset | step_validator | Baixo | Médio | Baixo |
| M5 | `fallback_selectors` determinísticos gravados na captura | recorder, sanitizer, runner, code_generator | Alto | **Muito alto** | Médio |

**Ordem de implementação:** M0 (baseline) → M1 → M2 → M4 → M3 → M5.
**M0 — pré-requisito:** capturar baseline do `projects/portal_segura/tests/001_teste` (3 execuções em Edge, ver seção 8.1) **antes de qualquer código**. Sem baseline não há gate de regressão.
Racional: quick wins primeiro (M1, M2, M4 são independentes e pequenos); M3 prepara o schema do plano que M5 estende; M5 por último por ser a maior mudança e atravessar 4 módulos.

**Dependências:** M1, M2 e M4 são totalmente independentes entre si. M3 e M5 tocam ambos o schema de `plano_execucao.json` e `validate_resilience_patterns` — M3 antes de M5 evita conflito de merge conceitual. Nenhuma melhoria depende de outra em runtime.

---

## 3. M1 — `error_message_selector` configurável por projeto

### Problema
O boilerplate canônico fixa `".toast-error, .alert-danger"` para todo projeto ([code_generator.py:78](../../aegis_sanitizer/code_generator.py) em `canonical_main` e code_generator.py:755). Apps com outro padrão de toast fazem erro de negócio virar `SYSTEM_FAILED` (runner.py:1842-1876), poluindo relatório, gastando diagnóstico de IA e desviando a correção cirúrgica.

### Mudanças

1. **`aegis_sanitizer/code_generator.py`**
   - Em `generate()`, ao ler `project.json` (já carregado em `project_json_path`, linha ~155), ler campo opcional `error_message_selector`.
   - Em `_normalize_boilerplate()`: parametrizar a linha do `canonical_main` que instancia `TransactionRunner` — usar o valor do projeto se presente, senão o default atual `".toast-error, .alert-danger"`. `_normalize_boilerplate` passa a receber o valor (novo parâmetro com default) ou lê de `self` (setado no `generate()`).
   - Mesmo tratamento na segunda ocorrência (linha ~755, fluxo de prompt/template).

2. **`projects/<slug>/project.json`** (schema, sem código)
   - Novo campo opcional: `"error_message_selector": ".minha-classe-de-erro"`.
   - Documentar no README (seção Fase 4).

### Compatibilidade
Projetos sem o campo mantêm comportamento idêntico (default atual). Zero mudança no runner (já aceita o parâmetro).

### DoD
- [ ] Projeto com campo em `project.json` gera bot com o seletor customizado no `__main__`.
- [ ] Projeto sem o campo gera bot byte-idêntico ao atual no bloco `__main__`.
- [ ] Teste unitário novo: `aegis_sanitizer/test_error_selector_config.py` cobrindo os dois casos (roda com `python <arquivo>`).
- [ ] README atualizado.

---

## 4. M2 — Sensor `CLICK_NO_EFFECT` (passo fantasma visível)

### Problema
`click_resilient` usa `loc.click(force=True)` (runner.py:411). `force=True` pula a checagem de actionability do Playwright — clique em elemento coberto por overlay "passa" e é logado `SUCCESS`. A falha real estoura N passos depois, e a correção cirúrgica (ancorada em `step_id`) mira o passo errado. Diferente de healing, esse caso **não** gera entrada `needs_review` — é invisível ao pipeline de rastreabilidade (README item 12).

### Princípio de design
**Detecção-apenas, nunca bloqueio.** O sensor não muda o resultado do passo (continua `SUCCESS`), não adiciona retry, não mexe no `force=True`. Só registra evidência para revisão humana — mesmo contrato do Sensor F1 (`_register_healing_for_review`, runner.py:223).

### Mudanças

1. **`aegis_runner/runner.py` — `click_resilient()`**
   - Antes do loop de candidatos ao clique físico (caminho `validate_navigation=False`), capturar snapshot barato do estado da página em uma única chamada `page.evaluate()`:
     ```js
     () => ({
         url: location.href,
         domSize: document.getElementsByTagName('*').length,
         overlays: document.querySelectorAll('.cdk-overlay-container *, [role=dialog], .modal.show').length
     })
     ```
   - **Sinais de "efeito": URL, contagem de nós DOM (tolerância ±2), contagem de overlays.**
     `document.activeElement` **NÃO** é evidência de efeito: no engine Chromium (usado pelo MS Edge) o próprio clique move o foco (para o alvo ou para o overlay que o cobre), então incluí-lo como sinal faria o sensor nunca disparar exatamente no caso de passo fantasma (clique `force=True` em elemento coberto — o foco vai para o overlay e "mascara" a falta de efeito). Uso opcional invertido: foco pós-clique caindo em nó **dentro** de container de overlay conta como suspeita adicional, nunca como efeito.
   - Após o clique bem-sucedido (e após `_wait_if_wizard_transition_button`), **polling com early-exit**: recapturar em ~100ms, ~300ms e ~800ms; qualquer sinal mudou → sai imediatamente (efeito detectado, custo ~100ms no caso comum). Só chega aos 800ms o clique suspeito. Se ao fim **nenhum** sinal mudou:
     - Logar `[AEGIS RUNNER] ⚠️ CLICK_NO_EFFECT | {step_id} | {selector}`.
     - Registrar via `_register_healing_for_review(step_id, selector, "click", healing_method="click_no_effect")` — reusa dedup por `(action, failed_selector)`, lock de arquivo e escrita atômica existentes. Entrada nasce `needs_review` e aparece no painel de Histórico de Problemas do Cockpit sem nenhuma mudança de frontend.
   - Passo continua retornando `True` e logando `SUCCESS`.
   - **Overhead estimado:** ~100ms por clique normal (primeira checagem já detecta efeito); 800ms apenas em cliques sem efeito detectável. Batch de 30 cliques × 200 linhas ≈ +10min no pior caso teórico (todos suspeitos), +~10s no caso típico.

2. **Fase piloto log-only:** primeira versão só loga `CLICK_NO_EFFECT` (sem gravar `needs_review`). Após calibrar sinais/janela em projeto-piloto real (taxa de falso positivo aceitável), ativar o registro. Evita poluir `correcoes_acumuladas.json` com sensor descalibrado.

3. **Flag de controle:** `AEGIS_CLICK_EFFECT_SENSOR` (default `true`). Permite desligar em apps onde cliques legitimamente inertes sejam comuns.

4. **Exclusões (reduzir falso positivo):**
   - Não aplicar quando `validate_navigation=True` (já tem verificação própria).
   - Não aplicar em seletores da família conhecida de wizard/disabled (já cobertos pelos itens 9/10 do README).
   - Falha do próprio `page.evaluate()` (página navegando) = considerado "efeito detectado", nunca erro.

### Riscos e mitigação
- **Falso positivo** (clique legítimo sem efeito visível, ex.: focar campo; ou efeito assíncrono mais lento que 800ms): mitigado por (a) fase piloto log-only antes de gravar `needs_review`; (b) status apenas `needs_review` — humano descarta com 1 clique no Cockpit; (c) dedup — mesmo par `(action, selector)` conta `occurrences`, não duplica; (d) flag de desligamento.
- **Latência:** polling early-exit limita overhead a ~100ms por clique normal; 800ms só em clique suspeito (ver estimativa acima).
- **Limitação conhecida do dedup do Sensor F1** (herdada, runner.py:291-309): se já existe correção com status `applied`/`resolved`/`pending`/`failed_attempt` para o mesmo par `(action, selector)`, novas ocorrências **não são registradas** (nem incrementam `occurrences`). Regressão pós-correção do mesmo seletor fica invisível ao painel. Correção (reabrir entrada `resolved` após novas ocorrências) fica **fora de escopo** deste plano — documentar no README.

### DoD
- [ ] Polling early-exit implementado (checagens em ~100/300/800ms; saída imediata ao detectar efeito) — espera fixa de 800ms é reprovação.
- [ ] `activeElement` ausente do conjunto de sinais de efeito.
- [ ] Fase log-only: overlay de teste cobrindo o alvo gera log `CLICK_NO_EFFECT`; após ativação do registro, gera entrada `needs_review` com `healing_method="click_no_effect"` em `correcoes_acumuladas.json`.
- [ ] Clique normal com navegação/mutação não gera log nem entrada.
- [ ] `AEGIS_CLICK_EFFECT_SENSOR=false` desativa completamente (zero `evaluate()` extra).
- [ ] Teste em `aegis_runner/test_runner_integration.py` (novo caso) passa junto com a suíte existente.
- [ ] README: item novo na seção "Mecanismos de Resiliência Nativos" + limitação do dedup documentada.

---

## 5. M3 — Enforcement de `weak_selector` (score consumido downstream)

### Problema
`evaluate_selector_reliability()` (recorder.py:859) gera score usado só em tempo de gravação (alerta `[⚠️ AEGIS RECORDER ALERT]` quando < 70%, README:231) e como badge no `relatorio.md` (sanitizer.py:333). Nada downstream reage: um seletor frágil (id dinâmico tipo `mat-input-3`) entra no `plano_execucao.json` com o mesmo tratamento de um `data-testid`, e a LLM pode ignorar o badge em markdown.

### Precedente a seguir
**Padrão Q** (README:242): o sanitizer já faz enforcement na origem (remove token dinâmico do `has_text` direto no plano, em vez de só alertar). M3 replica essa filosofia para score de seletor.

### Mudanças

1. **`aegis_blackbox/recorder.py`** — gravar `confidence` também nos eventos de click/fill em `gravacao.json`:
   - A infra já existe: `evaluate_selector_reliability` (recorder.py:859, função pura de string) já é chamada para campos de fill e outputs do `dicionario.json` (recorder.py:1132, 1158), persistindo `confidence`. Falta só o evento de click. Mudança: 1 linha no ponto de montagem do evento.
   - **Sem import cruzado** `aegis_blackbox → aegis_sanitizer` e sem módulo comum novo: o score nasce na captura (onde a função já vive) e trafega no evento.

2. **`aegis_sanitizer/sanitizer.py`** — na geração do plano (método com docstring "Gera plano_execucao.json...", sanitizer.py:926):
   - Para cada step, ler `event.confidence` (fallback: 40 se ausente, mesmo default já usado em sanitizer.py:311). Se `confidence < 70`: adicionar `"weak_selector": true` ao step.
   - Gravações antigas sem o campo: default 40 marcaria tudo como weak — para retrocompat, campo ausente = **não** marcar (`weak_selector` só com score explícito < 70).

3. **`aegis_sanitizer/step_validator.py` — `validate_resilience_patterns()`** (linha 699):
   - Novo check `WEAK_SELECTOR_WITHOUT_ANCHOR`: step com `weak_selector: true` no plano **exige** no código gerado ao menos um reforço: `has_text` no parent (literal ou dinâmico via `dict_dynamic_keys`) ou chamada `click_chained`/`fill_chained` com `parent=`. Sem nenhum → erro de validação (alimenta o Ralph Loop como os checks existentes).
   - **`original_coords` NÃO conta como reforço**: o validador já força sua presença quando o plano tem coords (checks `MISSING_*_COORDS`, step_validator.py:829-928), então aceitá-lo tornaria o check um carimbo que nunca falha. Coords são fallback de self-healing, não ancoragem determinística.

4. **`aegis_sanitizer/code_generator.py`**:
   - No prompt principal, para steps `weak_selector: true`, injetar instrução destacada: "seletor de baixa confiabilidade — obrigatório ancorar com parent/has_text (chained ou :has-text)".
   - `weak_selector` **não** entra em `_strip_internal_step_fields` (a LLM deve vê-lo).

### Compatibilidade
Planos antigos sem o campo: nenhum check novo dispara (`weak_selector` ausente = false). Gravações antigas não têm `confidence` no evento → nunca marcadas (comportamento atual preservado); o campo passa a existir em gravações novas.

### DoD
- [ ] Evento de click em gravação nova carrega `confidence` (score de `evaluate_selector_reliability`).
- [ ] Gravação com seletor `#mat-input-3` gera step com `weak_selector: true` no plano.
- [ ] Bot gerado sem ancoragem `has_text`/chained para esse step falha validação com `WEAK_SELECTOR_WITHOUT_ANCHOR` e o Ralph Loop corrige — presença de `original_coords` sozinha **não** passa.
- [ ] Step com `data-testid` não recebe a flag.
- [ ] Gravação antiga (sem `confidence` no evento) não gera flag nem check.
- [ ] Teste unitário novo: `aegis_sanitizer/test_weak_selector_enforcement.py`.

---

## 6. M4 — Dry-run sobre todas as linhas do dataset

### Problema
`dry_run_bot()` (step_validator.py:1400) exercita só `rows[0]` (linhas 1419-1435). Branch por conteúdo de linha (`if row.get("tipo") == "PJ":`) com erro que só ocorre na linha 2+ passa no gate e quebra em produção — o próprio comentário no código admite o padrão (bug real de `strptime` só com dado real).

### Mudanças

1. **`aegis_sanitizer/step_validator.py` — `dry_run_bot()`**:
   - Carregar **todas** as linhas do `dataset_inicial.json` (não só a primeira), com teto `AEGIS_DRYRUN_MAX_ROWS` (default 20, evita datasets gigantes).
   - **Um único subprocess** (não N): o harness recebe a lista de rows e itera internamente, chamando `fn(fake_page, row, fake_runner)` por linha. Custo adicional ~milissegundos por linha (sem browser, sem I/O).
   - Em erro, incluir no `detail` o `id` da linha que falhou: `"DRYRUN_RUNTIME_ERROR::TypeError::... (linha do dataset id=7)"` — o Ralph Loop já repassa `detail` ao prompt, então a LLM ganha contexto de qual dado quebra.
   - Bloco `__main__` continua executado uma única vez (comportamento atual preservado).

### Compatibilidade
Assinatura mantém `dataset_dir` opcional; sem dataset, comporta-se como hoje (row vazio).

### DoD
- [ ] Bot com `datetime.strptime(row["data"], ...)` que só quebra na linha 3 do dataset falha no dry-run com o id da linha no erro.
- [ ] Dataset de 100 linhas roda no máximo `AEGIS_DRYRUN_MAX_ROWS` e termina dentro do timeout (30s).
- [ ] Suíte existente de geração continua passando.
- [ ] Teste unitário novo cobrindo erro em linha ≠ 0.

---

## 7. M5 — `fallback_selectors` determinísticos gravados na captura

### Problema (causa raiz da dor documentada)
`getAegisSelector()` (recorder.py:86, JS injetado) ranqueia internamente múltiplas estratégias (data-testid → id → explicit-label → implicit-label → sibling-label → mat-form-field → form-group → has-text) mas **descarta as perdedoras** — só o vencedor vai para `gravacao.json` (recorder.py:586). Quando esse único seletor morre (id dinâmico, label movido), a recuperação salta direto para não-determinismo: LLM vision ou coordenada gravada — exatamente o que `strict=True` (README:317), `needs_review` (README:325) e Padrão R (README:327) existem para conter. Grep por `fallback_selector` no repo: zero ocorrências.

### Princípio de design (precedente: Padrão R)
> "O bot compilado e o Code Generator não mudam em nada — toda a decisão vive centralizada no `TransactionRunner`." (README:327)

Os fallbacks trafegam **pelo plano**, não pelo código gerado. O runner carrega `plano_execucao.json` e resolve fallback por `step_id`. A LLM nunca vê os fallbacks (menos confusão de prompt, mesmo padrão de `_strip_internal_step_fields`).

### Mudanças

1. **`aegis_blackbox/recorder.py` — JS injetado**
   - Nova função `getAegisSelectorCandidates(element)`: reaproveita a cascata existente de `getAegisSelector`, mas em vez de retornar no primeiro match, **coleta até 3 candidatos de estratégias distintas** (ex.: `[data-testid=...]`, `#id`, `label >> input`), cada um validado com `queryLength(sel) === 1` (unicidade no DOM no momento da captura — a maior vantagem: o elemento está comprovadamente presente e único agora).
   - `getAegisSelector` vira wrapper que retorna `candidates[0]` (zero mudança de comportamento para todo código existente).
   - Handlers de click/fill gravam `fallback_selectors: candidates.slice(1)` no evento.
   - **Não** aplicar em eventos que não têm seletor primário confiável (coordenada pura).

2. **`aegis_sanitizer/sanitizer.py`**
   - Propagar `fallback_selectors` do evento para o step correspondente do `plano_execucao.json` (geração em sanitizer.py:926).
   - Aplicar as sanitizações existentes também aos fallbacks: Padrão Q (token dinâmico) e dedup contra o seletor primário.
   - `_reorder_dropdown_pairs`: steps colapsados `type: "select"` carregam fallbacks do trigger e da option separadamente (`fallback_selectors_trigger`, `fallback_selectors_option`) — se complexidade estourar, dropdowns ficam de fora da v1 (decidir na revisão).

3. **`aegis_sanitizer/code_generator.py`**
   - Adicionar `fallback_selectors` (e variantes de dropdown) a `_strip_internal_step_fields` (code_generator.py:113) — LLM não vê, não confunde com kwarg.

4. **`aegis_runner/runner.py` — `TransactionRunner`**
   - **Reusar a carga de plano existente** em `run()` (runner.py:1626-1637): o runner **já** carrega `plano_execucao.json` em `self.execution_plan` e já monta mapa por step_id (`self.flaky_step_ids`, linha 1637). Mudança: adicionar ao lado `self.fallback_selectors_by_step = {s['step_id']: s.get('fallback_selectors', []) for s in ...}`. **Não** criar segunda carga no `__init__` — um único ponto de verdade. Arquivo ausente ou step sem fallbacks = mapa vazio, comportamento atual intacto.
   - **`click_resilient` / `fill_resilient`:** novo nível na cadeia, **entre** a heurística determinística atual (retry com Escape / multi-elemento) e o fallback cognitivo (self-healing vision / coordenadas):
     - Para cada fallback do step (ordem gravada): tentar a operação com timeout curto (~2s). Primeiro que funcionar resolve o passo.
     - Sucesso via fallback → logar status `HEALED` com método próprio e registrar `_register_healing_for_review(step_id, selector, action, healing_method="fallback_selector")` — o QA vê que o seletor primário apodreceu e pode promover o fallback a primário na próxima gravação/correção. Reusa 100% da infra do Sensor F1 (herda também a limitação de dedup descrita em M2).
     - **Semântica strict (decidida na revisão):** fallback determinístico **roda** mesmo com `strict=True` — é determinístico, não adivinhação; e não interfere no Padrão R: flake de timing significa elemento ainda ausente do DOM, logo os fallbacks (outras estratégias para o **mesmo** elemento) também falham e o restart de linha acontece como hoje. Fallback só absorve o caso de seletor apodrecido, que é o objetivo. Gate aplica-se onde o parâmetro existe (`click_resilient`; `fill_resilient` não tem `strict` hoje). Healing cognitivo continua bloqueado sob strict como hoje.
   - `select_option_resilient`: fora da v1 (usa dropdown_label/option_text, mecânica própria); avaliar em iteração seguinte.

5. **Cockpit** — nenhuma mudança obrigatória (entradas `needs_review` novas já aparecem no painel existente). Melhoria opcional futura: badge "fallback usado".

### Compatibilidade
- Gravações antigas sem `fallback_selectors`: mapa vazio, cadeia idêntica à atual.
- Bots já compilados: **funcionam sem regeneração** (fallback resolvido pelo runner via plano — precedente Padrão R).
- `dry_run_bot`: `_FakeRunner` não muda (assinaturas dos métodos públicos intactas).

### Riscos e mitigação
- **Fallback aponta para elemento errado após mudança de layout:** mitigado por (a) unicidade validada na captura; (b) timeout curto; (c) uso de fallback sempre logado `HEALED` e registrado como `needs_review` — com a ressalva da limitação de dedup do Sensor F1 (par já corrigido/resolvido não re-registra; ver M2, documentar no README).
- **Crescimento do `gravacao.json`/plano:** +2 strings por evento; irrelevante.
- **Complexidade no JS do recorder:** maior risco real do plano. Mitigar com refactor mínimo — extrair a cascata existente para lista de "provedores de estratégia" sem reescrever heurísticas individuais.

### DoD
- [ ] Gravação nova em página de teste gera eventos com `fallback_selectors` (estratégias distintas, únicos no DOM).
- [ ] `plano_execucao.json` propaga os fallbacks; prompt da LLM não os contém (verificar dump do prompt).
- [ ] Cenário sintético: quebrar seletor primário (renomear id no HTML de teste) → bot resolve o passo pelo fallback, loga `HEALED`, gera `needs_review` com `healing_method="fallback_selector"`, **sem** chamada LLM.
- [ ] Gravação antiga (sem o campo) executa byte-idêntico ao comportamento atual.
- [ ] `python aegis_runner/test_runner_integration.py` e `python aegis_runner/test_cognitive_fallback.py` passam.
- [ ] README: documentar novo nível da cadeia de resiliência e campos novos do plano.

---

## 8. Validação Macro (aceite do plano inteiro)

Toda validação roda em **MS Edge** (`channel="msedge"`, default do runner).

### 8.1. Gate de regressão obrigatório: Portal Segura `001_teste`

`projects/portal_segura/tests/001_teste` é o gate de regressão de **cada melhoria** (M1 a M5), não só do plano inteiro:

1. **Baseline antes de qualquer implementação:** 3 execuções completas do `001_teste`, registrando por execução: taxa de sucesso de transações, nº de restarts flaky (Padrão R), nº de passos `HEALED` por método, nº de entradas `needs_review` novas, tempo total. Baseline versionado junto ao plano (ex.: `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`).
2. **Após cada melhoria mergeada:** repetir as 3 execuções. Critério de aprovação:
   - Taxa de sucesso **≥ baseline** (idealmente 100%).
   - Restarts flaky e passos `HEALED` **≤ baseline** — os flaky points atuais do 001 devem diminuir ou permanecer; **qualquer aumento = regressão, bloqueia a melhoria** até diagnóstico.
   - Bot existente do 001 roda **sem regeneração** (compatibilidade retroativa de M2/M5 comprovada na prática).
3. **Expectativa direcional:** M5 (fallback determinístico) e M2 (visibilidade de passo fantasma) devem **reduzir** os flaky points documentados do 001 — é o critério "funciona perfeitamente ou melhor".

### 8.1.1. Nota pós-baseline (2026-07-06) — baseline saiu em 0%, não só "flaky"

O M0 (baseline real, ver `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`) revelou que o `001_teste` hoje falha **em 100% das 3 execuções**, cada uma num ponto diferente do fluxo (execuções 1-2: `.mat-row` não encontrado pós-tela de PIX; execução 3: dropdown "Uso do Veículo" — o mesmo achado do handoff `autocomplete-select-nao-verificavel`). Isso é mais grave que "flaky points" pontuais — é falha end-to-end não determinística.

**Consequência para o critério de aprovação:** com baseline em 0%, "taxa de sucesso ≥ baseline" e "HEALED ≤ baseline" perdem poder de sinal — quase qualquer resultado passa. O critério real para este ciclo, **decidido com o usuário**, é:
- **Não pode piorar** (regressão real = qualquer novo tipo de falha introduzido pela melhoria, ou aumento de tempo/instabilidade sem explicação).
- **Direção esperada de melhora:** M2 e M5 atacam diretamente os dois pontos de falha observados (seletor de linha da tabela não encontrado / dropdown que não abre) — expectativa é que, ao final de M5, ao menos uma das duas classes de falha pare de ocorrer.
- Gate por melhoria (M1/M2/M4/M3/M5) segue rodando conforme 8.1, mas o veredito deve reportar explicitamente se a taxa de sucesso subiu, manteve ou piorou frente ao baseline real de 0%, sem inflar "aprovado" como se 0% fosse um patamar saudável.

### 8.2. Piloto em site novo (anti-viés Portal Segura)

Maior risco do framework: calibração excessiva para a estrutura do Portal Segura (Angular Material, CDK overlays, wizard). Etapa obrigatória antes do aceite final:

1. **Site/sistema fornecido pelo usuário** — o plano **não** prevê criação nem escolha de site de teste; a URL/acesso será entregue no início da etapa. Premissa: stack distinta do Portal Segura e nenhuma gravação prévia dele no workspace. Bloqueio de entrada da etapa: site ainda não fornecido.
2. **Pipeline completo do zero:** gravar → sanitizar → validar → gerar → executar (Edge), sem nenhum ajuste manual de seletor.
3. **Medir generalização:**
   - % de eventos com `fallback_selectors` capturados (a cascata de estratégias funciona fora do Angular?).
   - % de steps marcados `weak_selector` (estrutura nova degrada a qualidade dos seletores primários?).
   - Taxa de sucesso na primeira execução e nº de `HEALED`/`needs_review`.
   - Falsos positivos do sensor `CLICK_NO_EFFECT` (site sem CDK overlay usa os seletores de overlay do snapshot? Ajustar lista se necessário).
4. **Saída da etapa:** relatório curto em `.specs/` com os números acima + lista de fragilidades encontradas (vira insumo do próximo ciclo). O piloto **não precisa atingir 100%** — precisa tornar as fragilidades com estruturas novas **mensuráveis e rastreáveis** em vez de desconhecidas.

### 8.3. Aceite geral

1. Suítes existentes: `python aegis_runner/test_runner_integration.py` e `python aegis_runner/test_cognitive_fallback.py` verdes.
2. Comparação com baseline (001 e site novo):
   - Taxa de sucesso de transações ≥ baseline.
   - Chamadas de LLM vision em runtime ≤ baseline (M5 deve reduzi-las).
   - Nenhum passo `SUCCESS` novo sem efeito real (amostragem manual com M2 ativo).
3. Painel de Histórico de Problemas exibe as novas entradas `needs_review` (`click_no_effect`, `fallback_selector`) sem quebra de UI.
4. Regra de isolamento respeitada: artefatos de projeto só em `projects/` (o piloto do site novo é um projeto normal criado via Cockpit); mudanças de framework só em `aegis_*`.

## 9. Métricas de sucesso (pós-implementação, por projeto-piloto)

| Métrica | Fonte | Direção esperada |
|---|---|---|
| % passos resolvidos por self-healing cognitivo | `historico_passos.json` (HEALED por método) | ↓ (M5 absorve) |
| Passos fantasma detectados | `needs_review` com `click_no_effect` | > 0 nas primeiras execuções, depois ↓ |
| Falhas de geração por linha de dataset ≠ 0 | erros `DRYRUN_*` com id de linha | pegos no gate, não em produção |
| Erros de negócio classificados como `SYSTEM_FAILED` | relatório CSV | ↓ em projetos com toast customizado (M1) |
| Restarts flaky no Portal Segura `001_teste` | histórico Padrão R (3 execuções vs baseline) | ↓ ou igual — nunca ↑ (gate 8.1) |
| Generalização em site novo (sem viés Angular) | relatório do piloto 8.2 | fragilidades mensuráveis, seletores/fallbacks capturados fora do Angular |

---

## 10. Changelog da revisão `plan-critic` (2026-07-06)

1. **M2:** `activeElement` removido dos sinais de efeito (o clique em si move o foco em Chromium — incluí-lo mataria a detecção no caso-alvo de clique `force=True` sob overlay). Uso opcional invertido (foco em overlay = suspeita).
2. **M2:** espera fixa de 800ms substituída por polling early-exit (100/300/800ms) — requisito de DoD; overhead estimado documentado.
3. **M2:** fase piloto log-only antes de gravar `needs_review`.
4. **M3:** eliminado import cruzado `aegis_blackbox → aegis_sanitizer`; `confidence` passa a ser gravado no evento pelo recorder (infra já existente em recorder.py:1132-1161) e lido pelo sanitizer.
5. **M3:** `original_coords` removido dos reforços aceitos pelo check `WEAK_SELECTOR_WITHOUT_ANCHOR` — o validador já força coords quando disponíveis (step_validator.py:829-928), aceitá-las tornaria o check inócuo.
6. **M5:** carga de `plano_execucao.json` reaproveita o ponto existente em `run()` (runner.py:1626-1637) em vez de nova carga no `__init__`.
7. **M5/M2:** semântica strict decidida (fallback determinístico roda sob strict; Padrão R preservado) e limitação de dedup do Sensor F1 (runner.py:291-309, supressão pós-correção) documentada como herdada e fora de escopo.

## 11. Ajustes solicitados pelo usuário (2026-07-06, pós-revisão)

8. **Navegador:** MS Edge sempre (`channel="msedge"`, já default do runner em runner.py:1614) — restrição operacional explícita; toda validação/piloto em Edge.
9. **Validação Macro 8.2:** nova etapa obrigatória de piloto em site/sistema novo com stack distinta do Portal Segura (anti-viés Angular Material) — objetivo: tornar a fragilidade com estruturas novas mensurável. Site **fornecido pelo usuário** (plano não cria nem escolhe site de teste).
10. **Validação Macro 8.1:** gate de regressão por melhoria no `projects/portal_segura/tests/001_teste` — baseline de 3 execuções antes de implementar; taxa de sucesso ≥ baseline e flaky points ≤ baseline (aumento bloqueia merge); bot do 001 roda sem regeneração.
