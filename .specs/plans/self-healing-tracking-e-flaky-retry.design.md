# Self-Healing como Bug Rastreável + Retry-Antes-de-Healing para Passos Flaky — Design Document

**Status:** Backlog — pontos em aberto da Feature 2 discutidos e decididos em 2026-07-05 (ver seção "Decisões"); revisado em 2026-07-05 por avaliação técnica externa (contradição no pseudocódigo da F2, gap de persistência do `flaky`, chave de dedup divergente, premissa falsa sobre carregamento do plano — todas corrigidas no corpo do documento); segunda revisão em 2026-07-05 pós-critic do backlog (rótulos `select_option_resilient`×`select_option_native_resilient` corrigidos, gap de HEALED×SUCCESS no dropdown custom incorporado à F1, chave de merge do `flaky` trocada de `step_id` posicional para `(type, selector)`); ainda não implementado
**Data:** 2026-07-05
**Risco:** Médio — toca `runner.py` (execução), schema de `plano_execucao.json` e `correcoes_acumuladas.json`. `code_generator.py` **não precisa mudar** (decisão abaixo).
**Origem:** Pedido explícito do usuário após uma sessão de debugging onde self-healing por coordenada mascarou pelo menos 2 falhas reais (ver `.specs/handoff-autocomplete-select-nao-verificavel.md`) e flakiness documentada no playbook (`Padrão J — regra estendida`) continuou aparecendo de forma imprevisível.

---

## Motivação (evidência real desta sessão)

1. **Self-healing mascarando bug real, não só "salvando o dia"**: no bug de autocomplete marca/modelo (ver handoff), o clique por coordenada reportou `HEALED` (sucesso) mas não disparou o listener real do app-alvo, deixando `state.formValues.modeloVeiculo` vazio. O sintoma só apareceu 3 telas depois. Hoje, `HEALED` é só uma linha no `historico_passos.json` e um contador no resumo do Cockpit ("Healed: N") — ninguém é forçado a investigar *por que* aquele passo precisou de healing.
2. **Flakiness já catalogada, mas sem tratamento automático**: `aegis_mentor/skills/rpa-copilot-coder.md` (Padrão J, regra estendida) já documenta um bug real e nomeado ("st_034 do portal_segura — dropdown condicional não tinha renderizado a tempo em ~1 a cada N execuções"). Isso significa que a equipe **já sabe** que certos passos são inerentemente instáveis — mas hoje não existe lugar nenhum pra marcar isso de forma estruturada nem para reagir de forma diferente quando esse passo falha.

---

## Feature 1: Self-Healing vira automaticamente um item de backlog rastreável

### Problema

`_log_step(status="HEALED", ...)` em `aegis_runner/runner.py` grava o resultado no `historico_passos.json` e segue em frente. Não existe elo entre "esse passo precisou de healing" e o sistema de correções (`correcoes_acumuladas.json`) que já existe pro resto do framework. Um passo pode precisar de healing em 100% das execuções, silenciosamente, pra sempre — sem nunca virar um item de revisão.

### Solução

Sempre que qualquer caminho de self-healing tiver sucesso (`status="HEALED"` em qualquer `_log_step`), o runner grava automaticamente uma entrada em `correcoes_acumuladas.json` com um status novo: `"needs_review"`.

**Correção de escopo (2026-07-05, revisão de conformidade):** os pontos reais que hoje emitem `status="HEALED"` são `runner.py:488`/`:504` (dentro de `_handle_click_failure`, compartilhado por `click_resilient` E `click_chained`), `:816` (`select_option_native_resilient` — `<select>` HTML nativo, action `select_native`; versões anteriores deste doc rotulavam errado como `select_option_resilient`), `:1124` (`fill_chained`) e `:1207`/`:1292` (`fill_resilient`) — confirmado por grep. `click_by_coordinates` (`runner.py:358-384`) **não** está nessa lista: é um método determinístico usado como estratégia primária para Shadow DOM fechado (não um fallback de self-healing) e sempre reporta `status="SUCCESS"` quando bem-sucedido, nunca `"HEALED"`. Hookar `_log_step` naturalmente já ignora `click_by_coordinates` sem nenhuma ação extra — não precisa (nem deve) ser listado como coberto por esta feature.

**Gap encontrado na revisão do backlog (2026-07-05, confirmado por leitura direta do código):** `select_option_resilient` (dropdown custom Angular/Material, def `runner.py:551` — o método do st_034/st_052, motivação central deste design) hoje loga `status="SUCCESS"` na linha `:759` MESMO quando quem resolveu foi o fallback de coordenada gravada (`:715-728`) ou o cognitive/IA visual (`:740-751`). Ou seja: a fonte de healing mais relevante do framework é invisível para o sensor da Feature 1. Parte do escopo da F1 é ajustar esse método para emitir `HEALED` (com `healing_method` correto) quando um desses dois fallbacks resolveu, mantendo `SUCCESS` só para clique direto por seletor/geometria viva.

**Por que um status novo, e não reaproveitar `"pending"`**: `"pending"` hoje significa "correção proposta, com `proposed_fix` pronto, aguardando o Code Generator aplicar" — é isso que o filtro em `code_generator.py:347` reinjeta automaticamente na próxima geração. Uma entrada de healing NÃO tem `proposed_fix` nenhum ainda (ninguém investigou a causa) — injetar isso cegamente na próxima geração seria pedir pra IA "adivinhar" um fix sem causa raiz identificada, reproduzindo exatamente o problema que gerou o caos da Fase 4 nesta sessão (ver `.specs/handoff-*` desta mesma sessão sobre numeração de plano). `"needs_review"` fica **de fora** do filtro de reinjeção automática — só vira `"pending"` depois que um humano (ou QA) escreve o `proposed_fix` de verdade, do mesmo jeito que já acontece hoje no fluxo normal do Cockpit.

### Esquema da entrada

```json
{
    "id": "healing_<execution_id>_<step_id>",
    "timestamp": "<iso8601>",
    "execution_id": "<id da execução>",
    "step_id": "st_XXX",
    "action": "click_chained",
    "failed_selector": "<selector que precisou de healing>",
    "root_cause": null,
    "proposed_fix": null,
    "qa_insight": null,
    "healing_method": "coordinate | js_evaluate | visual_ai",
    "occurrences": 1,
    "status": "needs_review"
}
```

`healing_method` distingue qual camada de fallback resolveu (coordenada gravada, `page.evaluate` direto, ou IA visual) — ajuda a priorizar: healing por coordenada é o mais arriscado (não confirma efeito colateral real, ver Feature raiz desta sessão), healing por IA visual já reporta uma justificativa própria.

### Deduplicação

**Revisão (2026-07-05, avaliação externa):** a chave original deste design era `(step_id, failed_selector)`. O Cockpit já tem uma chave de dedup pro resto do fluxo de correções — `(action, failed_selector)`, sem `step_id` (ver `cockpit.py:608-610`, `:1454` e `index.html:4554`/`:4593`, todos agrupando por `` `${action}||${failed_selector}` ``). Usar uma chave diferente faria uma entrada `needs_review` da Feature 1 não reconciliar com uma `pending`/`failed_attempt` já existente pro mesmo par, duplicando o item na visão do QA.

Antes de criar uma entrada nova, checa se já existe uma `needs_review` (ou `pending`/`applied`/`resolved`/`failed_attempt` — qualquer status que signifique "já tem correção conhecida pra isso", incluindo `applied` pelo mesmo motivo que o próprio Cockpit já trata `applied`+`pending` juntos em `cockpit.py:607`) pro mesmo `(action, failed_selector)` — mesma chave que o Cockpit já usa. Se existir e for `needs_review`, só incrementa `occurrences` e atualiza `timestamp`/`execution_id`/`step_id` mais recente — não precisa virar uma lista crescente de N entradas idênticas por N execuções. `step_id` continua gravado na entrada (útil pra navegação/exibição), só não faz parte da chave de dedup.

### Onde implementar

- `aegis_runner/runner.py`, dentro de `_log_step()` (ponto único onde todo status é gravado) — adicionar um branch: `if status == "HEALED": self._register_healing_for_review(step_id, selector, action, healing_method)`.
- Novo método `_register_healing_for_review` precisa saber o caminho do `correcoes_acumuladas.json` do teste atual — `TransactionRunner` já resolve `project_dir`/`test_dir` pra outros artefatos (`historico_passos.json`), reaproveitar o mesmo caminho.
- Cockpit (`aegis_cockpit/cockpit.py`, `/correcoes-status` e telas de correções) precisa aprender a listar/contar `needs_review` separado de `pending`/pendentes de aprovação — hoje o contador só sabe `pending/applied/failed/resolved` (ver `pending_count`/`applied_count`/etc. em `cockpit.py`).

### Risco / cuidado

- **Não pode disparar durante execução em massa sem limite**: se um teste roda 500 linhas de dataset e o MESMO passo precisa de healing em todas, a dedupe (occurrences++) evita 500 entradas, mas ainda assim escreve o arquivo 500 vezes (I/O). Considerar um throttle (só grava a cada N execuções, ou só na 1ª ocorrência de cada dia).
- **Escrita a partir do runtime é responsabilidade nova (confirmado por grep: `runner.py` hoje tem zero referências a `correcoes_acumuladas.json` — só `cockpit.py` e `code_generator.py`/`step_validator.py` mexem nesse arquivo, sempre em fluxo design-time)**. Isso introduz risco real de concorrência: Fase 5 rodando (escrevendo healing) ao mesmo tempo que um QA edita correções pelo Cockpit. Mecanismo decidido: **read-modify-write com lock de arquivo** (`msvcrt.locking`/`portalocker` ou equivalente multiplataforma) no método `_register_healing_for_review` — abre o arquivo, adquire lock exclusivo, lê o estado atual, aplica dedupe/incremento, escreve, libera lock. Combinar com o throttle do item acima (não é opcional: sem throttle, um dataset de 500 linhas tenta 500 locks sequenciais no mesmo arquivo só pra um único passo flaky). Mesmo padrão de risco que já existe hoje pro `historico_passos.json` (que o runner já escreve concorrentemente por linha) — reusar a mesma estratégia de I/O já validada ali, se houver uma.

---

## Feature 2: Passos marcados como "flaky" tentam restart completo (até 3x) antes de acionar self-healing

### Problema

Hoje, todo passo tem a MESMA política de resiliência: tentativas normais → self-healing (coordenada/IA) → falha definitiva. Isso é ótimo pra falhas genuinamente estruturais (selector mudou, elemento não existe), mas ruim pra falhas **conhecidas como intermitentes** (Padrão J regra estendida: "dropdown condicional não tinha renderizado a tempo em ~1 a cada N execuções") — nesses casos, a ação certa não é "adivinhar via coordenada", é **tentar de novo do zero**, porque na maioria das vezes a re-execução simplesmente não bate na janela de corrida de novo.

### Solução proposta

1. **Marcação do passo como flaky** — novo campo booleano no `plano_execucao.json`:
   ```json
   { "step_id": "st_034", "type": "click", ..., "flaky": true }
   ```
   Quem marca: humano/QA via Cockpit (checkbox na tela de Passos, análogo ao fluxo de correções).

   **Escopo inicial reduzido (2026-07-05, avaliação externa):** a marcação automática por `occurrences >= N` (Feature 1 → Feature 2) fica **fora do escopo inicial**. Motivo: acopla F1↔F2 e herda o gap de persistência do `flaky` no Sanitizer (ver "Onde implementar" abaixo) — automatizar uma marcação em cima de um campo que ainda pode ser apagado silenciosamente na próxima sanitização é automação sobre estado instável. Entregar primeiro F1 (sensor) + marcação **manual** de `flaky` via Cockpit; auto-marcação por threshold vira um incremento futuro, só depois que (a) a persistência do campo estiver resolvida com merge no Sanitizer e (b) houver dados reais de `occurrences` de produção pra calibrar o valor de N.

2. **Runner respeita a marcação, com política invertida**: para um passo com `flaky=true`, o bot compilado passa `strict=True` (já existe esse parâmetro em `click_resilient`/`fill_resilient`/`click_chained`/`fill_chained`/`select_option_resilient` — hoje serve pra pular self-healing e falhar rápido) **nas primeiras 3 tentativas daquela linha do dataset**, deixando a exceção propagar. Isso é capturado num nível ACIMA do passo individual — no laço de execução da transação (`TransactionRunner.run()`), não dentro do passo. Outras linhas do dataset seguem seu fluxo normal, sem qualquer relação com as tentativas desta linha.

3. **Restart completo, não retry pontual**: como o app-alvo mantém estado cumulativo (wizard multi-tela — não dá pra "voltar" só um passo sem redigitar tudo de novo, confirmado nesta sessão), o restart precisa ser da **transação inteira daquela linha do dataset**: fecha a página/context atual, abre uma nova (mesmo padrão de isolamento que já existe — 1 página por linha), roda o `execute_scenario_default(page, row, runner)` completo de novo desde o passo 1.

4. **4ª tentativa libera self-healing**: se as 3 tentativas completas (com `strict=True` nos passos flaky) falharem TODAS no mesmo passo flaky, a 4ª tentativa roda com `strict=False` pra esse(s) passo(s) especificamente — aí sim self-healing entra como último recurso, do jeito que já funciona hoje.

### Decisões (discutidas com o usuário em 2026-07-05)

1. **Sinalização flaky vs. falha normal — decidido**: `TransactionRunner` passa a carregar `plano_execucao.json` na inicialização e monta um mapa `step_id → flaky`. O bot compilado **não muda em nada** — continua passando `strict=True` do jeito estático que já existe hoje para qualquer step. Toda a decisão dinâmica ("essa falha dispara restart ou é definitiva?") fica centralizada dentro do runner, que interpreta o `strict=True` recebido de forma diferente dependendo de (a) o `step_id` estar marcado `flaky` no plano e (b) qual é a tentativa atual daquela linha do dataset. Código gerado pela LLM nunca precisa saber de "tentativa atual" — evita adicionar mais uma lógica condicional à superfície que a IA tem que acertar (lição desta sessão: cada padrão novo no código gerado é mais uma chance de regressão).

   **Correção de premissa falsa (2026-07-06):** o texto acima ("bot compilado continua passando `strict=True` do jeito estático que já existe hoje para qualquer step") está errado e foi verificado por grep no repo: nenhum bot compilado em `projects/**/bot_producao.py` passa `strict=True`, e `code_generator.py` também não emite isso — `strict` tem default `False` nas assinaturas de `runner.py` e só é passado como `True` no caso residual do Padrão Q (ausência de fragmento estável de `has_text` em `click_chained`/`fill_chained`). A afirmação correta é: o gatilho do restart-por-linha é exclusivamente a marcação `flaky: true` no `plano_execucao.json`, **independente do valor de `strict`** que o bot passa naquela chamada (que continua sendo `False` na esmagadora maioria dos passos). A implementação final em `runner.py` usa `(strict or is_flaky_step)` nos pontos de decisão (ver `_handle_click_failure`, `fill_chained`, `fill_resilient`, `select_option_native_resilient`, `select_option_resilient`), mais um gate equivalente para o fallback de coordenada em `select_option_resilient`. O `code_generator.py` não deve passar a emitir `strict=True` por causa da Feature 2 — a única regra de quando usar `strict=True` continua sendo a do Padrão Q.
2. **`code_generator.py` não muda — decidido, consequência do item 1**: como o bot gerado é idêntico seja o passo flaky ou não, não há necessidade de nenhuma alteração no gerador de código nem no prompt de geração além da já existente entrada `flaky` no plano (que o gerador nem precisa ler).
3. **Escopo do restart — decidido, corrigindo suposição inicial deste design**: o restart é da **transação de UMA ÚNICA linha do dataset** (a que sofreu a falha flaky), nunca do lote inteiro. Isso já era a intenção original do design (seção "Restart completo, não retry pontual" abaixo), mas ficou como preocupação em aberto por engano — não é. Como o blast radius é sempre 1 linha, o custo extra (até 4 tentativas daquela linha) é desprezível frente ao tempo total do lote, mesmo em datasets grandes — as outras linhas seguem seu fluxo normal, sem qualquer bloqueio ou espera. **Não é necessário nenhum teto de tempo total** — 3 tentativas + fallback de healing já limita o pior caso por linha.
4. **Idempotência no app-alvo — decidido, fora de escopo**: não é uma preocupação a ser tratada pelo framework. Assumido que reiniciar uma transação do zero é seguro para os apps-alvo em questão (sem necessidade de aviso, confirmação ou trava adicional no Cockpit para marcar `flaky=true`).

   **Pressuposto explícito (2026-07-05, avaliação externa):** essa decisão assume que a transação é idempotente no sistema-alvo. Apps que persistem/gravam algo a cada tentativa (o próprio `portal_segura` gera um número de proposta em runtime a cada submissão — ver Padrão Q, `PRO-80935`) podem acumular registros duplicados no sistema-alvo a cada restart de linha. Isso é aceito como fora de escopo do framework por decisão do usuário, não porque o risco não exista — registrado aqui pra não virar surpresa em produção quando `flaky=true` for usado num passo que já passou de um ponto de submissão irreversível no fluxo.

### Arquitetura necessária (revisada 2026-07-05 — avaliação externa encontrou contradição na versão anterior)

**Correção crítica:** a versão anterior deste pseudocódigo chamava `execute_scenario_default(page, row, runner, strict_flaky=strict_para_flaky)` — um 4º parâmetro passado AO cenário. Isso contradiz a própria Decisão 1 ("bot compilado não muda em nada") e é **impossível hoje de qualquer forma**: o runner invoca o callback posicionalmente como `self.scenarios[scenario](page, row, self)` (`runner.py:1548-1552`, via `inspect.signature`), e `step_validator.py::_validate_scenario_function_signature` valida via AST que `execute_scenario_default` tem **exatamente** `(page, row, runner)` — qualquer parâmetro a mais quebra o gate `INVALID_SCENARIO_SIGNATURE`/`WRONG_SCENARIO_PARAM_ORDER` antes mesmo do bot rodar. O modelo correto é **state-based**, do jeito que a Decisão 1 já descrevia em prosa — o pseudocódigo abaixo foi reescrito pra bater com isso:

```
TransactionRunner.run()
  para cada row do dataset (linhas continuam independentes entre si):
    self.current_row_flaky_attempt = 1   # estado no runner, não parâmetro do cenário
    while self.current_row_flaky_attempt <= 4:
        page = novo contexto isolado (fecha o anterior se existir) — SÓ desta linha
        try:
            execute_scenario_default(page, row, runner)   # assinatura IDÊNTICA à de hoje, sem mudança
            break  # sucesso, sai do while — segue pra próxima linha do dataset normalmente
        except FlakyStepFailure as e:
            if self.current_row_flaky_attempt == 4:
                registra falha definitiva desta linha (como hoje)
                break
            self.current_row_flaky_attempt += 1
            continue  # restart completo, só desta linha
        except Exception:
            # falha NÃO relacionada a passo flaky — comportamento atual, sem restart
            registra falha definitiva desta linha
            break
```

Dentro dos métodos resilientes (que já recebem `step_id` e `strict` do bot compilado, sem nenhuma mudança de assinatura), a lógica de decisão entra nos pontos reais confirmados por leitura do código — **correção de rótulo (2026-07-05, revisão do backlog):** versões anteriores diziam "`select_option_resilient` em `:806`", mas `:806` pertence a `select_option_native_resilient` (def `:767`, `<select>` nativo). O dropdown custom `select_option_resilient` (def `:551`) tem **dois** pontos de decisão strict, com formato diferente dos demais:

- `_handle_click_failure` em `runner.py:475` (compartilhado por `click_resilient` e `click_chained`);
- `fill_chained` em `:1115`;
- `fill_resilient` em `:1195`;
- `select_option_native_resilient` em `:806`;
- `select_option_resilient` em `:738` (`if not option_clicked and strict:` — hoje só imprime e pula o cognitive, sem raise) e `:761-765` (o `raise RuntimeError` final — é aqui que a `FlakyStepFailure` do passo flaky precisa substituir o RuntimeError quando tentativa ≤ 3).

Nos quatro primeiros, a lógica fica assim:

```
# dentro do método resiliente, no ponto onde hoje é só "if strict: raise <exceção original>"
is_flaky_step = self.flaky_step_ids.get(step_id, False)   # mapa carregado do plano, ver abaixo

# CORREÇÃO CRÍTICA (2026-07-05, revisão de conformidade): uma versão anterior
# deste pseudocódigo tinha "elif strict: raise <exceção original>" incondicional,
# o que fazia a 4ª tentativa de um passo flaky continuar levantando a exceção
# original em vez de liberar o self-healing — contradizendo a Decisão/Solução
# item 4 ("a 4ª tentativa roda com strict=False pra esse(s) passo(s)
# especificamente — aí sim self-healing entra como último recurso"). A correção:
# a 4ª tentativa (e além) de um passo flaky precisa CAIR NO FALLBACK de
# self-healing abaixo, não relançar a exceção. O bot continua passando o
# `strict` que já passaria de qualquer forma — na prática `False` na maioria
# dos passos, `True` só no residual do Padrão Q (ver correção de premissa
# falsa, 2026-07-06, na Decisão 1 acima: nenhum bot compilado passa
# `strict=True` "estático de sempre" — isso nunca foi verdade). Quem decide
# se esse `strict` "vale" ou é ignorado nesta chamada específica é o runner,
# via este estado interno, combinando `strict OR is_flaky_step`.
flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4

if strict and not flaky_healing_unlocked:
    if is_flaky_step and self.current_row_flaky_attempt <= 3:
        raise FlakyStepFailure(step_id, selector, e)   # restart completo da linha, ver run()
    raise e   # comportamento de hoje, inalterado — step não-flaky com strict=True
# senão (strict=False de verdade, OU passo flaky já na 4ª+ tentativa): segue
# pro fallback de self-healing existente logo abaixo, SEM NENHUMA MUDANÇA —
# é o mesmo código que já roda hoje quando strict=False.
```

`FlakyStepFailure(Exception)` — nova exceção levantada pelos métodos resilientes citados, carregando `(step_id, selector, exceção_original)` como argumentos (não uma string formatada solta — mantém a exceção original acessível para quem for investigar/logar o restart). O bot compilado **não sabe** dessa exceção nem da tentativa atual — ele só passa `strict=True` do jeito estático que já faz hoje; toda a interpretação de "essa falha é retry-ável, definitiva, ou deve liberar self-healing" vive dentro do runner, lendo seu próprio estado (`self.current_row_flaky_attempt`) e o mapa carregado do plano (`self.flaky_step_ids`).

### Onde implementar (arquivos afetados)

- `aegis_sanitizer/sanitizer.py` — schema de `plano_execucao.json` ganha campo opcional `flaky`. **Tarefa de código, não só schema**: `_write_execution_plan` (`sanitizer.py:925`) regera o arquivo inteiro do zero a cada Fase 2, sem merge — confirmado lendo o método (monta `steps` só a partir de `events`/`dataset_rows`, nunca lê o `plano_execucao.json` antigo). Um `flaky=true` setado manualmente pelo Cockpit seria apagado silenciosamente na próxima re-gravação/re-sanitização. Precisa: antes de escrever o novo plano, ler o `plano_execucao.json` antigo (se existir) e reaplicar `flaky=true` nos steps novos correspondentes (mesmo padrão de preservação que já existe pra `devops_config.json`/`aegis_config.json`). **Chave de correspondência revisada (2026-07-05, revisão do backlog):** NÃO usar `step_id` como chave do merge — `step_id` é gerado posicionalmente a cada sanitização (`f"st_{{i+1:03d}}"` por `enumerate`, `sanitizer.py:1032`), então qualquer step inserido/removido desloca TODOS os ids seguintes e o `flaky` migraria silenciosamente pra um passo errado. Usar `(type, selector)` como chave (ambos estão no schema serializado, `sanitizer.py:1030-1044`); se houver colisão (dois steps com mesmo par), aceitar que ambos herdam a marcação — risco menor que o do deslocamento posicional. Também é preciso adicionar `flaky` à whitelist de serialização do schema (`sanitizer.py:1030-1044`), que hoje não inclui o campo. Sem isso tudo, a Feature 2 fica inútil já na segunda iteração do ciclo grava→sanitiza.
- `aegis_cockpit/` — UI pra marcar/desmarcar `flaky` por passo (tela de Passos), sem aviso/trava adicional (decisão 4).
- `aegis_runner/runner.py` — **`TransactionRunner` já carrega `plano_execucao.json` na inicialização hoje** (`runner.py:1441-1449`, em `self.execution_plan`, iterado em `:1494-1496` — confirmado por leitura direta, correção de uma suposição errada de rascunhos anteriores deste design que diziam "não faz isso hoje"). Falta só: derivar `self.flaky_step_ids = {s["step_id"]: s.get("flaky", False) for s in self.execution_plan["steps"]}` a partir do que já está em memória — trivial, nenhum carregamento novo necessário; `run()` ganha o laço de restart por linha e o estado `self.current_row_flaky_attempt`; nova exceção `FlakyStepFailure`; os **6 métodos resilientes** (`click_resilient`/`click_chained` via `_handle_click_failure`, `fill_chained`, `fill_resilient`, `select_option_native_resilient`, e `select_option_resilient` — os dois selects incluídos porque ambos já têm `strict` hoje e ambos são fontes de healing da Feature 1; ver correção de rótulo na seção "Arquitetura necessária") ganham o branch de decisão acima no lugar do `if strict: raise` atual (no caso do `select_option_resilient`, nos seus dois pontos `:738`/`:761-765`, com o formato próprio descrito acima).
  **Nota sobre o laço de `run()`:** com a correção do branch acima, `FlakyStepFailure` só é levantada quando `current_row_flaky_attempt <= 3` — ou seja, o `if self.current_row_flaky_attempt == 4` dentro do `except FlakyStepFailure` do pseudocódigo de `run()` (seção "Arquitetura necessária") nunca é de fato alcançado (na 4ª tentativa o passo flaky cai no self-healing, não relança `FlakyStepFailure`). Implementar como está é seguro (código defensivo inofensivo), mas documentar isso no comentário do código pra não confundir quem for mexer depois.
- `aegis_sanitizer/code_generator.py` — **sem alterações** (decisão 2).
- `aegis_mentor/skills/rpa-copilot-coder.md` — documentar o novo comportamento como um padrão de resiliência (ex.: "Padrão R: Passos Flaky com Restart Automático por Linha"), pra manter o playbook como fonte única da lógica de resiliência do projeto.

---

## Como as duas features se conectam

Feature 1 (rastreio de healing) é o **sensor** — detecta automaticamente "esse passo é suspeito" sem precisar de um humano notar. Feature 2 (flaky retry) é a **reação automática** — mas precisa de uma marcação explícita (`flaky=true`) que, na prática, viria muitas vezes DA análise de uma entrada `needs_review` da Feature 1 depois que um humano confirma "sim, isso é intermitência, não bug estrutural" (distinção importante: nem toda falha que precisa de healing é flakiness — pode ser bug real, tipo o do autocomplete desta sessão, que healing não devia mascarar, e sim falhar rápido pra alguém investigar).

**Ordem de implementação sugerida**: Feature 1 primeiro (mais simples, self-contida em `runner.py` + schema de `correcoes_acumuladas.json`) — dá visibilidade real de quais passos SÃO flaky de fato, com dados de produção, antes de construir a máquina de restart da Feature 2 em cima de suposições.
