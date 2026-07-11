# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Origem: .specs/plans/self-healing-tracking-e-flaky-retry.design.md
# Revisão: 2026-07-05 (2ª revisão — adenda do plan-critic verificados contra o código e integrados; design doc atualizado na mesma revisão para eliminar divergências de rótulo)

> 🏁 DEMANDA FECHADA — 2026-07-06

## 🗺️ Mapa de Dependências dos Subagentes

- 🟢 Fase 1: [SUBAGENTE 01] `runner.py` — sensor de healing + [SUBAGENTE 04] `sanitizer.py` — merge do campo `flaky` (paralelo — arquivos disjuntos, ambos são fundação)
- 🟡 Fase 2: [SUBAGENTE 02] `cockpit.py` — contagem `needs_review` (depende de 01) + [SUBAGENTE 05] `runner.py` — `FlakyStepFailure` e leitura do mapa flaky (depende de 01, mesmo arquivo — roda depois dele) — paralelos entre si (arquivos diferentes: `cockpit.py` × `runner.py`)
- 🟡 Fase 3: [SUBAGENTE 03] `index.html` — badge `needs_review` (depende de 02) + [SUBAGENTE 06] `runner.py` — laço de restart em `run()` (depende de 05, mesmo arquivo) — paralelos entre si
- 🟡 Fase 4: [SUBAGENTE 07] `cockpit.py` + `index.html` — UI de marcação `flaky` (depende de 04; toca `index.html` de novo — despachar **depois** de 03 terminar, mesmo arquivo) + [SUBAGENTE 08] `rpa-copilot-coder.md` — documenta Padrão R (depende de 06) — paralelos entre si (arquivos disjuntos)

**Fora deste backlog, por decisão do plano:** auto-marcação de `flaky` por `occurrences >= N` fica para um incremento futuro (depende de dados reais de produção pós-Fase 1) — não há tarefa para isso aqui.

**Correções desta revisão (todas verificadas por leitura direta de `aegis_runner/runner.py` e `aegis_sanitizer/sanitizer.py`; o design doc foi atualizado junto):**
1. `:806`/`:816` pertencem a `select_option_native_resilient` (def `:767`, `<select>` HTML nativo, action `select_native`) — versões anteriores do design rotulavam como `select_option_resilient`. O dropdown custom `select_option_resilient` (def `:551` — o método do st_034/st_052, motivação central do design) é um método distinto e também precisa de instrumentação (Subagentes 01 e 05).
2. `select_option_resilient` hoje loga `status="SUCCESS"` (`:759`) mesmo quando quem resolveu foi coordenada gravada (`:715-728`) ou cognitive (`:740-751`) — a fonte de healing mais relevante do framework é invisível. Subagente 01 corrige para emitir `HEALED` nesses caminhos.
3. Chave do merge de `flaky` no Sanitizer é `(type, selector)`, NÃO `step_id` — `step_id` é regenerado posicionalmente (`f"st_{i+1:03d}"` por `enumerate`, `sanitizer.py:1032`), então steps inseridos/removidos deslocariam a marcação para o passo errado. Testes do Subagente 04 harmonizados com essa chave (a versão anterior do bloco ainda descrevia testes por `step_id`).
4. Subagente 06 recupera o tratamento de falha definitiva quando o laço de restart esgota (a versão anterior perdeu esse detalhe ao incorporar o adendo do critic) e documenta o branch defensivo inalcançável.
5. Mantidas da revisão anterior: lógica `flaky_healing_unlocked` (4ª tentativa libera self-healing), lista completa de status que bloqueiam duplicação (`needs_review`/`pending`/`applied`/`resolved`/`failed_attempt`), exclusão explícita de `click_by_coordinates` do sensor.

---

### [SUBAGENTE 01] - Sensor de healing: registrar HEALED como needs_review
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Toda vez que `_log_step` gravar `status="HEALED"`, criar/atualizar automaticamente uma entrada `status="needs_review"` em `correcoes_acumuladas.json` do teste atual, com dedup por `(action, failed_selector)` e escrita segura (lock read-modify-write). Inclui corrigir `select_option_resilient` (dropdown custom), que hoje loga `SUCCESS` mesmo quando um fallback de healing resolveu.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (método `_log_step` em `runner.py:75`; os 6 pontos que chamam `status="HEALED"` em `runner.py:488`, `:504`, `:816`, `:1124`, `:1207`, `:1292`; `select_option_resilient` def `:551`, fallback de coordenada `:715-728`, fallback cognitive `:740-751`, log final `:759`; padrão de path na `:1707`); `aegis_cockpit/cockpit.py:598-611` e `:1448-1456` (só para copiar o padrão de dedup `(action, failed_selector)` já usado no Cockpit — não modificar este arquivo aqui)
  - Modificar: `aegis_runner/runner.py`
  - Modificar (testes): `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_runner/runner.py`, adicione um parâmetro opcional `healing_method: str = None` ao método `_log_step` (linha 75) e passe um valor apropriado (`'coordinate'`, `'js_evaluate'` ou `'visual_ai'`, conforme o mecanismo real de cada chamada) nos 6 pontos que hoje chamam `_log_step(..., status='HEALED')` (linhas 488, 504, 816, 1124, 1207, 1292). NÃO mexa em `click_by_coordinates` (linha 358) — esse método sempre reporta `status='SUCCESS'`, nunca `'HEALED'`, é estratégia primária determinística e não faz parte deste sensor.
  >
  > Além disso, corrija `select_option_resilient` (def na linha 551): hoje ele loga `status='SUCCESS'` na linha 759 mesmo quando quem selecionou a opção foi o fallback de coordenada gravada (linhas 715-728) ou o cognitive/IA visual (linhas 740-751). Adicione uma flag local (ex.: `healed_via_fallback`, com o método usado) setada nesses dois caminhos, e no log final (linha 759) emita `status='HEALED'` com o `healing_method` correspondente (`'coordinate'` ou `'visual_ai'`) quando a flag estiver setada — mantendo `status='SUCCESS'` quando a seleção veio dos seletores normais ou da geometria viva (`_click_by_live_geometry`, que é determinística). Não mude nenhuma outra lógica do método.
  >
  > Dentro de `_log_step`, quando `status == 'HEALED'`, chame um novo método `self._register_healing_for_review(step_id, selector, action, healing_method)`.
  >
  > Implemente `_register_healing_for_review` em `TransactionRunner`: ele deve localizar `correcoes_acumuladas.json` **na raiz de `self.project_dir`** (mesmo diretório onde a linha 1707 grava o `historico_passos.json` de raiz), abrir o arquivo com um lock exclusivo de arquivo (leia-modifique-escreva atômico — use `msvcrt.locking` no Windows via um wrapper simples, já que o projeto roda em Windows), procurar uma entrada existente com o MESMO par `(action, failed_selector)` cujo `status` seja `needs_review`, `pending`, `applied`, `resolved` OU `failed_attempt` (qualquer um desses significa "já existe uma correção conhecida pra esse par, não duplique"). Se encontrar uma com `status == 'needs_review'`, só incremente `occurrences` e atualize `timestamp`/`execution_id`/`step_id`. Se encontrar com qualquer um dos OUTROS status listados, NÃO crie nova entrada. Se não encontrar nenhuma, crie uma nova entrada seguindo exatamente este schema: `{'id': 'healing_<execution_id>_<step_id>', 'timestamp': <iso8601 agora>, 'execution_id': <self.execution_id ou getattr equivalente>, 'step_id': step_id, 'action': action, 'failed_selector': selector, 'root_cause': None, 'proposed_fix': None, 'qa_insight': None, 'healing_method': healing_method, 'occurrences': 1, 'status': 'needs_review'}`. Adicione um throttle simples: se já foi escrito para o MESMO `(action, failed_selector)` nos últimos 30 segundos desta mesma execução (guarde um dict em memória na instância), pule a escrita em disco. **CRÍTICO:** Envolva `_register_healing_for_review` inteiramente num try/except que só loga a falha (print ou logging) e NÃO levanta — o sensor F1 jamais pode derrubar uma transação por I/O ou erro de escrita de arquivo. Isso é uma função não-fatal por design. Não altere nenhum outro comportamento de `_log_step` nem dos métodos que já chamam HEALED além do descrito. Não faça refatoração, renomeação nem melhoria fora deste objetivo.
  >
  > Depois, adicione casos de teste em `aegis_runner/test_runner_integration.py` (siga o estilo de `unittest.mock` já usado no arquivo) cobrindo: (a) uma primeira falha HEALED cria a entrada `needs_review` corretamente com `healing_method` correto; (b) uma segunda falha HEALED no mesmo `(action, failed_selector)` incrementa `occurrences` em vez de duplicar; (c) se já existe uma entrada `pending` ou `applied` ou `failed_attempt` pro mesmo par, nenhuma entrada nova é criada; (d) `select_option_resilient` resolvido via fallback de coordenada loga `HEALED` (não `SUCCESS`)."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` — todos os testes (antigos e novos) passam
  - [x] `python -c "import py_compile; py_compile.compile('aegis_runner/runner.py', doraise=True)"` — sem erro de sintaxe

---

### [SUBAGENTE 02] - Cockpit: contar needs_review no endpoint de status de correções
> ✅ CONCLUÍDO
- **🎯 Objetivo:** O endpoint `/correcoes-status` passa a retornar também a contagem de entradas com `status == "needs_review"`, sem alterar as contagens existentes.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_cockpit/cockpit.py:629-665` (bloco do endpoint `/correcoes-status`)
  - Modificar: `aegis_cockpit/cockpit.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_cockpit/cockpit.py`, dentro do handler do endpoint que termina com `/correcoes-status` (bloco entre as linhas 629 e 665), adicione uma variável `needs_review_count` calculada com o mesmo padrão das existentes (`pending_count`, `applied_count`, etc. — linhas 642-655): `len([c for c in corrections if c.get('status') == 'needs_review'])`. Inclua essa nova chave `'needs_review': needs_review_count` no dicionário de resposta JSON (perto de `'pending'`, `'applied'`, `'failed_attempt'`, `'resolved'`, linhas 661-664). Não altere nenhuma outra contagem, rota ou comportamento existente. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -c "import py_compile; py_compile.compile('aegis_cockpit/cockpit.py', doraise=True)"` — sem erro de sintaxe
  - [x] Iniciar o Cockpit (`python aegis_cockpit/cockpit.py`) e chamar `GET /api/projects/<projeto>/tests/<teste>/correcoes-status` num projeto real com pelo menos uma entrada `needs_review` em `correcoes_acumuladas.json` — confirmar que a chave `needs_review` aparece no JSON de resposta com o valor correto

---

### [SUBAGENTE 03] - Cockpit UI: exibir contagem needs_review
> ✅ CONCLUÍDO
- **🎯 Objetivo:** A tela de correções do Cockpit exibe visualmente a contagem de itens `needs_review` retornada pelo endpoint (Subagente 02), do mesmo jeito que já exibe `pending`/`applied`/`resolved`.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_cockpit/static/index.html:4549-4650` (bloco de renderização da tabela/contadores de correções)
  - Modificar: `aegis_cockpit/static/index.html`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_cockpit/static/index.html`, na área que renderiza os contadores de status de correções (perto das linhas 4549-4650, onde já existem badges/contadores para `pending`/`applied`/`failed_attempt`/`resolved` vindos do endpoint `/correcoes-status`), adicione um badge/contador equivalente para a chave `needs_review` que o backend agora retorna. Siga exatamente o mesmo padrão visual (mesma estrutura HTML/CSS) dos contadores já existentes ali perto, só trocando o rótulo para algo como 'Precisa Revisão' e a cor para se destacar como pendência de investigação (não reutilize a cor de 'pending', que já significa outra coisa no fluxo). Não altere nenhuma outra parte da tela, não renomeie variáveis existentes, não refatore o restante do arquivo."
- **🧪 Critério de Validação (DoD):**
  - [x] Iniciar o Cockpit (`python aegis_cockpit/cockpit.py`), abrir a tela de correções de um teste com pelo menos uma entrada `needs_review` em `correcoes_acumuladas.json`, e confirmar visualmente no navegador que o novo badge aparece com o valor correto
  - [x] Verificar no console do navegador que não há erro JS novo ao carregar a tela

---

### [SUBAGENTE 04] - Sanitizer: preservar campo flaky do plano ao regenerar
> ✅ CONCLUÍDO
- **🎯 Objetivo:** `_write_execution_plan` ganha um campo `flaky` no schema de cada step e, ao regenerar `plano_execucao.json`, preserva `flaky=true` de steps que já existiam no plano anterior, casando por `(type, selector)` — NÃO por `step_id`, que é posicional e desloca a cada regeração.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/sanitizer.py:925-1055` (método `_write_execution_plan` completo: montagem dos `steps`, whitelist de serialização nas linhas 1030-1044 — onde `step_id` é gerado posicionalmente na 1032 — e a escrita final)
  - Modificar: `aegis_sanitizer/sanitizer.py`
  - Criar: `aegis_sanitizer/test_sanitizer_execution_plan.py` (não existe teste hoje para este módulo — seguir o estilo `unittest` de `aegis_runner/test_runner_integration.py`)
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_sanitizer/sanitizer.py`, no método `_write_execution_plan` (linha 925): (1) ANTES de montar a lista `steps` nova, leia o `plano_execucao.json` antigo em `plan_path` se ele já existir (mesmo `os.path.join(self.telemetry_dir, 'plano_execucao.json')` da linha 927) e monte `old_flaky_keys = {(s.get('type'), s.get('selector')) for s in <steps do plano antigo> if s.get('flaky')}` — proteja com try/except para o caso do arquivo antigo não existir ou estar malformado (nesse caso, conjunto vazio, sem quebrar a geração). A chave é `(type, selector)` de propósito: `step_id` é regenerado posicionalmente (`f'st_{i+1:03d}'` na linha 1032) e steps inseridos/removidos deslocariam a marcação para o passo errado. (2) Na compreensão que serializa os steps finais (linhas 1030-1044), adicione a chave `'flaky': (s['type'], s.get('selector', '')) in old_flaky_keys` a cada step (ou `**({'flaky': True} if ... else {})` para incluir só quando true, seguindo o padrão das outras chaves opcionais — escolha UM dos dois estilos e aplique de forma consistente; o runner vai ler com `s.get('flaky', False)`, então ambos funcionam). Se dois steps novos tiverem o mesmo par `(type, selector)`, ambos herdam a marcação — comportamento aceito pelo design (colisão é risco menor que deslocamento posicional). Não mude a lógica de geração de nenhum outro campo, não remova o Padrão Q existente (linhas 931-956), não reordene nada além do necessário para inserir a leitura do plano antigo antes da escrita do novo. Não faça refatoração, renomeação nem melhoria fora deste objetivo.
  >
  > Crie `aegis_sanitizer/test_sanitizer_execution_plan.py` com testes `unittest` cobrindo: (a) gerar um plano pela primeira vez sem plano antigo — nenhum step sai com `flaky` verdadeiro; (b) gerar um plano quando já existe um `plano_execucao.json` anterior com um step `flaky: true` — o novo plano preserva `flaky: true` no step com o mesmo `(type, selector)`, **inclusive quando a posição/`step_id` desse step mudou** entre o plano antigo e o novo (ex.: um step novo inserido antes dele — este teste é a prova de que o merge não é posicional); (c) um step que tinha `flaky: true` no plano antigo mas cujo `(type, selector)` não existe mais nos eventos novos simplesmente não propaga nada (sem erro); (d) plano antigo malformado (JSON inválido) não quebra a geração — o plano novo sai normalmente sem `flaky` herdado."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_sanitizer/test_sanitizer_execution_plan.py` — todos os testes passam
  - [x] `python -c "import py_compile; py_compile.compile('aegis_sanitizer/sanitizer.py', doraise=True)"` — sem erro de sintaxe

---

### [SUBAGENTE 05] - Runner: FlakyStepFailure e leitura do mapa flaky
> ✅ CONCLUÍDO
- **🎯 Objetivo:** `TransactionRunner` deriva um mapa `step_id → flaky` do `plano_execucao.json` já carregado em `self.execution_plan`, define a exceção `FlakyStepFailure`, e os **6 métodos resilientes** (`click_resilient`/`click_chained` via `_handle_click_failure`, `fill_chained`, `fill_resilient`, `select_option_native_resilient`, `select_option_resilient`) levantam `FlakyStepFailure` em vez da exceção original quando o step é flaky E a tentativa atual da linha é ≤ 3 — e **liberam o self-healing normalmente** (sem levantar nada) quando o step é flaky E a tentativa atual é ≥ 4 — sem nenhuma mudança de assinatura em `execute_scenario_default` nem no bot compilado.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py:1441-1449` (carregamento de `self.execution_plan`, já existente), `:386-478` (`_handle_click_failure`, branch `if strict:` na linha 475), `:1113-1116` (`fill_chained`), `:1192-1198` (`fill_resilient`), `:767-820` (`select_option_native_resilient`, branch `if strict:` na linha 806), `:551-765` (`select_option_resilient` — atenção: formato diferente, ver prompt)
  - Modificar: `aegis_runner/runner.py`
  - Modificar (testes): `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_runner/runner.py`: (1) Defina uma nova exceção `class FlakyStepFailure(Exception)` no topo do módulo, com construtor recebendo `(step_id, selector, original_exception)` e guardando os três como atributos (a exceção original precisa continuar acessível para log/investigação). (2) Logo após o carregamento de `self.execution_plan` (linhas 1441-1449), adicione `self.flaky_step_ids = {s['step_id']: s.get('flaky', False) for s in self.execution_plan['steps']} if self.execution_plan else {}`. (3) Adicione um atributo de instância `self.current_row_flaky_attempt = 1` inicializado no mesmo bloco (valor default de segurança; outro subagente vai resetá-lo por linha dentro de `run()`).
  >
  > (4) Nos **4 pontos padrão** `if strict:` (linhas 475 em `_handle_click_failure`, 806 em `select_option_native_resilient`, 1115 em `fill_chained`, 1195 em `fill_resilient` — os números podem ter deslocado ligeiramente por edições anteriores, localize pelo texto '[STRICT] Falha definitiva'), substitua a lógica atual por EXATAMENTE este padrão (adapte só o `action`/selector/mensagem de log de cada método, mantendo o resto idêntico):
  > ```python
  > is_flaky_step = self.flaky_step_ids.get(step_id, False)
  > flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4
  > if strict and not flaky_healing_unlocked:
  >     if is_flaky_step and self.current_row_flaky_attempt <= 3:
  >         self._log_step(step_id=step_id, action=<mesma action de hoje>, selector=<mesmo selector de hoje>, target_description=target_description, status="FAILED", error_msg=str(e))
  >         raise FlakyStepFailure(step_id, selector, e)
  >     print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ...")  # mensagem de log já existente no método
  >     self._log_step(step_id=step_id, action=<mesma action de hoje>, selector=<mesmo selector de hoje>, target_description=target_description, status="FAILED", error_msg=str(e))
  >     raise e
  > # senão (strict=False de verdade, OU passo flaky já na 4ª+ tentativa): cai no
  > # fallback de self-healing que já existe logo abaixo, SEM NENHUMA MUDANÇA.
  > ```
  > É CRÍTICO que quando `flaky_healing_unlocked` for `True`, o código NÃO levante nenhuma exceção aqui — ele precisa continuar para o código de self-healing que já existe abaixo desse bloco no método (é assim que a 4ª tentativa de um passo flaky ganha acesso ao self-healing, exatamente como um passo com `strict=False` teria hoje).
  >
  > (5) `select_option_resilient` (def na linha 551) tem formato DIFERENTE — dois pontos, nenhum deles um `if strict: raise` clássico: (5a) na linha 738, o `if not option_clicked and strict:` hoje só imprime e pula o branch do cognitive. Ajuste a condição para que um passo flaky com `flaky_healing_unlocked=True` NÃO pule o cognitive (ou seja, o cognitive roda como se strict fosse False nessa 4ª tentativa). (5b) no bloco final `else` (linhas 761-765), onde hoje há `raise RuntimeError(msg)`: quando o step for flaky e `self.current_row_flaky_attempt <= 3` e `strict=True`, levante `FlakyStepFailure(step_id, selector, RuntimeError(msg))` no lugar do RuntimeError (mantendo o `_log_step(status='FAILED')` que já existe ali); nos demais casos, mantenha o `raise RuntimeError(msg)` atual. Isso garante que dropdown custom flaky dispara restart em vez de falha definitiva.
  >
  > Não mexa em nenhum outro comportamento dos 6 métodos, não altere a assinatura pública de nenhum deles, não toque em `execute_scenario_default` nem em nenhum bot compilado. Não implemente aqui o laço que incrementa `self.current_row_flaky_attempt` nem a captura de `FlakyStepFailure` em `run()` — isso é outra tarefa. Não faça refatoração, renomeação nem melhoria fora deste objetivo.
  >
  > Adicione testes em `aegis_runner/test_runner_integration.py` cobrindo, para pelo menos `click_resilient`/`click_chained` e `select_option_resilient`: (a) step marcado flaky, `current_row_flaky_attempt=1`, falha com `strict=True` → levanta `FlakyStepFailure` (não a exceção original); (b) mesmo step, `current_row_flaky_attempt=3` → ainda levanta `FlakyStepFailure`; (c) mesmo step, `current_row_flaky_attempt=4` → NÃO levanta `FlakyStepFailure` nem a exceção original — cai no self-healing (mock deve confirmar que o caminho de self-healing foi chamado); (d) step NÃO flaky com `strict=True` continua levantando a exceção original independente da tentativa."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` — todos os testes passam
  - [x] `python -c "import py_compile; py_compile.compile('aegis_runner/runner.py', doraise=True)"` — sem erro de sintaxe

---

### [SUBAGENTE 06] - Runner: laço de restart por linha em run()
> ✅ CONCLUÍDO
- **🎯 Objetivo:** `TransactionRunner.run()` reseta `self.current_row_flaky_attempt = 1` no início de cada linha do dataset, captura `FlakyStepFailure` e reinicia a transação daquela linha (nova página/contexto isolado + reset do histórico de steps) até 3 vezes; a 4ª tentativa roda sem restart posterior (o self-healing já foi liberado internamente pelo Subagente 05). Outras exceções continuam falhando a linha imediatamente, sem restart.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py:1461-1600` (laço principal de `run()`: criação da página por linha na `:1477`, inicialização do `steps_history` com PENDING nas `:1493-1508`, chamada do cenário na `:1550`, e o tratamento de exceção/registro de falha definitiva logo abaixo)
  - Modificar: `aegis_runner/runner.py`
  - Modificar (testes): `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_runner/runner.py`, dentro de `run()`, no laço que já itera cada linha do dataset: no INÍCIO do processamento de cada linha, adicione `self.current_row_flaky_attempt = 1` e envolva o corpo da transação num laço `while self.current_row_flaky_attempt <= 4:`. É CRÍTICO o que fica DENTRO do while: a criação da página/contexto novo (hoje na linha ~1477, incluindo o fechamento da página anterior), a inicialização do `steps_history` com PENDING (linhas ~1493-1508) e a chamada do cenário (linha ~1550) — o restart é da transação COMPLETA da linha, não só do cenário. Em caso de sucesso do cenário, `break` e o fluxo pós-sucesso segue idêntico ao de hoje. Em caso de `except FlakyStepFailure`: se `self.current_row_flaky_attempt < 4`, incremente e `continue` (restart); senão, registre a falha definitiva da linha exatamente como uma exceção normal faria hoje e `break` — **adicione um comentário** explicando que este branch é defensivo e inalcançável por design (o Subagente 05 garante que `FlakyStepFailure` só é levantada quando `current_row_flaky_attempt <= 3`; na 4ª tentativa o passo flaky cai no self-healing em vez de relançar), mas fica como rede de segurança. Qualquer outro `except Exception` mantém o comportamento atual: registra falha definitiva da linha imediatamente, sem restart. Para linhas que nunca levantam `FlakyStepFailure`, o fluxo observável deve ser IDÊNTICO ao de hoje (uma única iteração do while). Não toque nos métodos resilientes (isso já foi feito em outra tarefa). Não faça refatoração, renomeação nem melhoria fora deste objetivo.
  >
  > Adicione um teste de integração em `aegis_runner/test_runner_integration.py` (mockando `self.scenarios` e Playwright como os testes existentes já fazem) que simula: 1ª e 2ª tentativas de uma linha levantam `FlakyStepFailure`, 3ª tentativa tem sucesso — confirme que a linha é registrada como sucesso e que o cenário foi chamado exatamente 3 vezes para aquela linha (prova de que o restart completo aconteceu, não um retry parcial). Adicione também um teste em que a linha levanta uma exceção comum (não-flaky) na 1ª tentativa — o cenário deve ter sido chamado exatamente 1 vez (sem restart)."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` — todos os testes passam
  - [x] `python -c "import py_compile; py_compile.compile('aegis_runner/runner.py', doraise=True)"` — sem erro de sintaxe

---

### [SUBAGENTE 07] - Cockpit: UI para marcar/desmarcar flaky por passo
> ✅ CONCLUÍDO
- **🎯 Objetivo:** A tela de Passos do Cockpit ganha um checkbox por passo para marcar/desmarcar `flaky` em `plano_execucao.json`, com um novo endpoint backend que persiste essa mudança.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_cockpit/static/index.html:3653-3770` (função `renderSteps`, onde os steps do `executionPlan` já são lidos e renderizados — ponto de inserção do checkbox); `aegis_cockpit/cockpit.py:339` (onde `plano_execucao.json` já é lido via `load_json` para servir ao frontend — usar como referência de caminho do arquivo)
  - Modificar: `aegis_cockpit/cockpit.py`, `aegis_cockpit/static/index.html`
- **🤖 Prompt para o Claude Code:**
  > "Claude, implemente marcação manual de `flaky` por passo: (1) Em `aegis_cockpit/cockpit.py`, adicione um novo endpoint (siga o padrão de rotas já existente no arquivo, ex.: `POST /api/projects/<projeto>/tests/<teste>/steps/<step_id>/flaky`) que recebe um corpo JSON `{'flaky': true|false}`, localiza `plano_execucao.json` do teste (mesmo caminho já usado na leitura da linha 339), encontra o step com o `step_id` recebido na lista `steps`, atualiza seu campo `flaky` com o valor recebido, e reescreve o arquivo inteiro de volta (leitura-modificação-escrita simples, sem necessidade de lock pois é operação do Cockpit via UI, não concorrente com o runtime). Retorne sucesso/erro em JSON. (2) Em `aegis_cockpit/static/index.html`, na função `renderSteps` (linha 3653 em diante, onde os steps do `executionPlan` são exibidos), adicione um checkbox por linha de passo ligado ao campo `flaky` do step, que ao mudar de estado chama o novo endpoint via `fetch` (siga o padrão de chamadas fetch já usado em outras partes do arquivo para ações do Cockpit) e atualiza o estado local sem precisar recarregar a tela inteira. Não adicione nenhum aviso, confirmação ou trava extra ao marcar/desmarcar (decisão explícita do design: sem preocupação de idempotência bloqueando a UI). Não altere nenhuma outra parte de `renderSteps` nem do restante do arquivo. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -c "import py_compile; py_compile.compile('aegis_cockpit/cockpit.py', doraise=True)"` — sem erro de sintaxe
  - [x] Iniciar o Cockpit, abrir a tela de Passos de um teste com `plano_execucao.json` existente, marcar um passo como flaky pela UI, e confirmar (lendo o arquivo em disco) que `flaky: true` foi persistido para o `step_id` correto; desmarcar e confirmar que volta a `false`

---

### [SUBAGENTE 08] - Playbook: documentar Padrão R (flaky retry)
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Documentar o novo comportamento de restart automático por linha para passos flaky como um padrão de resiliência nomeado no playbook usado pelo Code Generator, mantendo o playbook como fonte única da lógica de resiliência do projeto.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_mentor/skills/rpa-copilot-coder.md` (estrutura existente dos "Padrões" já documentados, para seguir o mesmo formato); `.specs/plans/self-healing-tracking-e-flaky-retry.design.md` (seção "Feature 2", já implementada nos Subagentes 04/05/06)
  - Modificar: `aegis_mentor/skills/rpa-copilot-coder.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_mentor/skills/rpa-copilot-coder.md`, adicione um novo padrão de resiliência ao catálogo existente (siga exatamente o mesmo formato/estrutura dos padrões já documentados no arquivo — título, problema, solução, exemplo se aplicável), nomeado 'Padrão R: Passos Flaky com Restart Automático por Linha'. Descreva: passos marcados `flaky: true` no `plano_execucao.json` (marcação feita via Cockpit) fazem o runner reiniciar a transação inteira daquela linha do dataset (nova página/contexto) até 3 vezes; na 4ª tentativa, o self-healing (coordenada/IA) é liberado como último recurso, exatamente como já acontece para qualquer passo hoje. O bot compilado não precisa de nenhuma lógica nova — o comportamento é inteiramente decidido pelo `TransactionRunner` em runtime, lendo o campo `flaky` do plano. Deixe claro que o Code Generator (LLM) NÃO precisa gerar nenhum código diferente para steps flaky — é uma responsabilidade só do runner. Não altere nenhum outro padrão já documentado no arquivo, não reescreva nem reformate seções existentes. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [x] Ler o arquivo modificado e confirmar visualmente que o novo padrão segue a mesma estrutura Markdown dos padrões vizinhos (sem quebrar nenhuma seção existente)
  - [x] `grep -c "^## " aegis_mentor/skills/rpa-copilot-coder.md` antes/depois — confirmar que só aumentou (nenhum cabeçalho existente foi removido/mesclado)

---

## 🔧 ADENDO PÓS-ACEITAÇÃO (2026-07-06) — F2 morta em produção: `strict=False` é o default universal

**Contexto (achado do close-backlog, validado por plan-critic):** o teste E2E de aceitação no cenário 001 do Portal Segura provou que a F2 nunca dispara. Causa raiz: a premissa do design ("o bot compilado continua passando `strict=True` estático de sempre") é **falsa** — `grep -c "strict=True"` retorna **0** em todos os `bot_producao.py` do repo e no `code_generator.py`. `strict` tem default `False` em todos os métodos resilientes, então a condição `if strict and not flaky_healing_unlocked:` nunca avalia `is_flaky_step` — F2 é código morto para qualquer bot já compilado. Além disso, em `select_option_resilient`, o fallback de coordenada gravada (`runner.py:874-892`) roda **incondicionalmente** (nem `strict` o bloqueia) e "cura" o passo antes de qualquer chance de `FlakyStepFailure`. Fix aprovado pelo plan-critic com 5 ações (ver blocos 09 e 10).

---

### [SUBAGENTE 09] - Runner: flaky dispara por si só, independente de strict
> ✅ CONCLUÍDO
- **🎯 Objetivo:** A marcação `flaky: true` no plano passa a disparar `FlakyStepFailure` (tentativas 1-3) e liberar self-healing (4ª tentativa) por si só, sem depender do parâmetro `strict` que os bots compilados nunca passam como `True`. Cobre os 4 pontos clássicos + os 3 pontos do `select_option_resilient` (incluindo o fallback de coordenada que hoje cura antes do raise).
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (pontos exatos, linhas atuais confirmadas: `_handle_click_failure` `:628-636`; `select_option_resilient` fallback de coordenada `:874-892`, guard cognitive `:898-901`, raise final `:928-934`; `select_option_native_resilient` `:975-983`; `fill_chained` `:1289-1295`; `fill_resilient` `:1374-1382`)
  - Modificar: `aegis_runner/runner.py`
  - Modificar (testes): `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `aegis_runner/runner.py`, o mecanismo de flaky-retry existe mas nunca dispara em produção porque todos os bots compilados chamam os métodos resilientes com `strict=False` (default). Corrija em 3 partes, SEM alterar nenhum comportamento de passos não-flaky:
  >
  > (1) **4 pontos clássicos** — nas linhas ~630 (`_handle_click_failure`), ~977 (`select_option_native_resilient`), ~1291 (`fill_chained`) e ~1376 (`fill_resilient`), a condição hoje é `if strict and not flaky_healing_unlocked:` (em `select_option_native_resilient`/`fill_resilient`/`fill_chained` pode ser `if strict and ...` dentro de `except`). Troque APENAS a condição externa para `if (strict or is_flaky_step) and not flaky_healing_unlocked:`. O corpo interno já está correto (flaky + tentativa ≤3 levanta `FlakyStepFailure`; senão print [STRICT] + `raise e`) — MAS atenção: o branch do print `[STRICT]` + `raise e` agora só pode ser alcançado quando `strict=True` e não-flaky, então nada muda nele. Verifique que um passo flaky com `strict=False` e tentativa ≤3 levanta `FlakyStepFailure`, e que com tentativa ≥4 cai no self-healing (bloco `elif`/código abaixo) como se nada tivesse acontecido.
  >
  > (2) **`select_option_resilient` — 3 pontos:** (2a) o fallback de coordenada gravada (linhas ~874-892, `if not option_clicked and original_coords_option ...`) hoje roda incondicionalmente. Adicione à condição `and not (self.flaky_step_ids.get(step_id, False) and self.current_row_flaky_attempt <= 3)` — um passo flaky nas tentativas 1-3 NÃO pode ser curado por coordenada, precisa falhar e reiniciar. NÃO toque no fallback `_click_by_live_geometry` (linha ~865-866) — geometria viva é determinística, não é healing, continua sempre ativa. (2b) o guard do cognitive (linha ~900, `if not option_clicked and strict and not flaky_healing_unlocked:`) → troque `strict` por `(strict or is_flaky_step)`. (2c) o raise final (linhas ~932-933, `if strict and is_flaky_step and self.current_row_flaky_attempt <= 3:`) → remova o `strict and`, deixando `if is_flaky_step and self.current_row_flaky_attempt <= 3:`.
  >
  > (3) Não altere assinaturas, não mexa em `run()`, não toque no sensor de healing (`_register_healing_for_review`) nem em nenhum bot compilado. Não faça refatoração, renomeação nem melhoria fora deste objetivo.
  >
  > Adicione testes em `aegis_runner/test_runner_integration.py` (siga o estilo mock existente da classe `TestFlakyStepRestart`): (a) passo flaky com `strict=False` (o caso real de produção) e tentativa 1 → `click_resilient` levanta `FlakyStepFailure`; (b) mesmo cenário com tentativa 4 → NÃO levanta, cai no self-healing (mock confirma chamada); (c) `select_option_resilient` com passo flaky `strict=False`, coordenada gravada VÁLIDA (mock de `page.evaluate` retornando o texto esperado) e tentativa 1 → levanta `FlakyStepFailure` SEM usar a coordenada (prova de que o fallback de coordenada foi pulado); (d) mesmo cenário com tentativa 4 → coordenada é usada e o passo é `HEALED`; (e) passo NÃO flaky com `strict=False` → comportamento atual intocado (self-healing roda normalmente, nenhuma `FlakyStepFailure`)."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` — todos os testes (antigos e novos) passam
  - [x] `python -c "import py_compile; py_compile.compile('aegis_runner/runner.py', doraise=True)"` — sem erro de sintaxe

---

### [SUBAGENTE 10] - Docs: corrigir premissa falsa "strict=True estático" no playbook e no design
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Corrigir o texto do Padrão R no playbook (que alimenta o prompt do Code Generator LLM — texto errado ali pode induzir a LLM a emitir `strict=True` em todos os passos, desligando self-healing globalmente) e a premissa correspondente no design doc.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_mentor/skills/rpa-copilot-coder.md` (Padrão R, linhas ~303-315, especificamente as afirmações "com o mesmo `strict=True` estático de sempre" nas linhas ~306-307); `.specs/plans/self-healing-tracking-e-flaky-retry.design.md` (Decisão 1, linha ~97, e pseudocódigo/prosa que afirmam que o bot passa `strict=True`)
  - Modificar: `aegis_mentor/skills/rpa-copilot-coder.md`, `.specs/plans/self-healing-tracking-e-flaky-retry.design.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, corrija uma premissa falsa em dois documentos. Fato verificado no repo: nenhum bot compilado passa `strict=True` (grep retorna 0 em todos os `projects/**/bot_producao.py` e no `code_generator.py`); `strict` tem default `False` e só é emitido `True` no caso estreito do Padrão Q (ambiguidade de `has_text` sem fragmento estável). O runner foi corrigido para a marcação `flaky` disparar por si só.
  >
  > (1) Em `aegis_mentor/skills/rpa-copilot-coder.md`, no Padrão R (linhas ~303-315): substitua as afirmações de que o bot 'continua passando o mesmo `strict=True` estático de sempre' por: o comportamento flaky é disparado exclusivamente pela marcação `flaky: true` no `plano_execucao.json`, **independente do valor de `strict`** que o bot passa (que continua sendo o default `False` na maioria dos passos, ou `True` apenas no caso residual do Padrão Q). Deixe explícito que o Code Generator NÃO deve passar a emitir `strict=True` por causa deste padrão — a regra de quando usar `strict=True` continua sendo exclusivamente a do Padrão Q. Adicione uma nota curta de custo: marcar `flaky` num passo estruturalmente quebrado (não intermitente) custa ~3 execuções extras completas da linha antes do self-healing entrar na 4ª tentativa. Não altere nenhum outro padrão nem reformate o arquivo.
  >
  > (2) Em `.specs/plans/self-healing-tracking-e-flaky-retry.design.md`: na Decisão 1 (linha ~97) e em qualquer outra passagem que afirme que o bot compilado 'continua passando strict=True', adicione uma correção datada (2026-07-06) explicando o fato verificado acima e que a implementação final usa `(strict or is_flaky_step)` nos pontos de decisão, mais o gate do fallback de coordenada em `select_option_resilient`. Estilo: as correções datadas já existentes no próprio documento. Não reescreva seções inteiras — adenda cirúrgica.
  >
  > Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [x] `grep -c "^### " aegis_mentor/skills/rpa-copilot-coder.md` antes/depois — inalterado (nenhum padrão removido/adicionado)
  - [x] Ler os trechos modificados dos dois arquivos e confirmar que nenhuma afirmação "bot passa strict=True estático" sobrou sem correção
