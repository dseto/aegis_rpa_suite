# BACKLOG DE EXECUÇÃO - CLAUDE CODE

> Origem: `.specs/plano-cauda-longa-verificada.md` — **somente a Fase F1** (Seção 5 da tabela de fases).
> F2 (pós-condição gravada / recorder / sanitizer / emitter) e F3 (calibração) estão FORA deste backlog.
> Plano aprovado após 3 rodadas (plan-critic Fable, plan-critic Opus, verificação focada Opus) — sem emendas pendentes.
> **RESET (2026-07-15):** SUB01-08 foram implementados e gateados com sucesso em 2026-07-14, mas as mudanças em `aegis_runner/runner.py`/`cognitive_fallback.py` nunca foram commitadas e foram perdidas por colisão com sessão concorrente (ver `close-backlog` run, commit `11aa1b2` de outra sessão no mesmo checkout). Re-executando do zero a partir daqui, com commit imediatamente após cada gate fechar. **Achado**: os arquivos de teste (`test_runner_integration.py`/`test_cognitive_fallback.py`) são gitignored e SOBREVIVERAM ao checkout da outra sessão — a suíte completa original (118+7 testes, todas as classes de SUB01-07) continua no disco, servindo de especificação exata pra reimplementação.

> SUB01 recommitado em `f8a82c2` (2026-07-15). SUB02 recommitado em `3045df8` (2026-07-15). SUB03 recommitado em `3cd2a80` (2026-07-15). SUB04 recommitado em `64fbec6` (2026-07-15). SUB05 recommitado em `901c8f4` (2026-07-15). SUB06 recommitado em `1dd5099` (2026-07-15). SUB07 recommitado em `c5d6909` (2026-07-15) — **reimplementação completa, suíte 118+7 testes 100% verde, tudo commitado localmente (nada pushed).** SUB08 (validação/relatório, sem código core) permanece válido — sua evidência ao vivo continua correta contra a implementação atual (mesma lógica, recriada a partir da suíte de teste sobrevivente que serviu de spec).

> 🏁 **DEMANDA FECHADA — 2026-07-15.** Aceitação macro (close-backlog): suíte completa reexecutada do zero (118/118 + 7/7, exit 0), objetivo do plano (Seção 1) confirmado por inspeção direta do código (não só do backlog marcado como concluído) — `_verify_action_effect`/`_hit_test_plausible`/`VERIFY_REJECTED` (pré/pós) cobrindo os 6 call sites de `self_healing_click`/`propose_fill_target` (`runner.py:1475,2076,2174,2659,2794,2893`), coordenada gravada verificada movida pra antes do LLM em `_handle_unrecoverable_click`, T1/T2 e `strict` re-semantizados conforme prometido. Doc técnica (`aegis_runner/aegis_runner.md` Seções 1-3, `CLAUDE.md` raiz) conferida contra o código real e commitada em `e05f5be` (docs-only, sobre os 7 commits de implementação `f8a82c2..c5d6909`). Nada pushed. Tarefas A e B em `.specs/plano-cauda-longa-verificada.backlog.pending.md` seguem deliberadamente fora de escopo (B já resolvida por `11aa1b2`; A pendente, não bloqueadora).

## ⚠️ Avisos globais para TODO subagente (leia antes de qualquer tarefa)

1. **Números de linha do plano estão DEFASADOS.** O plano foi escrito num checkout anterior; o código
   já drifou. Âncore-se SEMPRE por **nome de função / método**, nunca por número de linha do plano.
   Referências reais confirmadas neste checkout (2026-07-14):
   - `aegis_runner/cognitive_fallback.py`: `self_healing_click` na linha ~247; os 3 `return True`
     cegos com `page.mouse.click` estão em ~262-263, ~311-312, ~330-331.
   - `aegis_runner/runner.py` (âncoras por nome): `_verify_action_effect` (a CRIAR),
     `_capture_click_effect_snapshot`, `_click_effect_signals_changed`, `_register_healing_for_review`,
     `_handle_unrecoverable_click`, `_handle_click_failure`, `select_option_resilient`,
     `select_option_native_resilient`, `fill_chained`, `fill_resilient`, `fill_human_like`, `_log_step`.
   - **Os 6 call sites de `self.cognitive.self_healing_click(...)` em `runner.py`** (confirmados por grep):
     linha ~933 (`_handle_unrecoverable_click`), ~1514 (`select_option_resilient`),
     ~1594 (`select_option_native_resilient`), ~2061 (`fill_chained`), ~2171 (`fill_resilient`),
     ~2254 (`fill_human_like`). Reconfirme por grep antes de editar.

2. **Doutrina F1 (uma frase):** a régua deixa de ser "LLM sim/não" e vira "verificado sim/não".
   Nenhum tier (determinístico, geometria, coordenada, LLM) pode reportar sucesso sem uma
   **pós-condição observável** confirmando o efeito. Ação cega de qualquer origem morre.

3. **Working Agreement #1 (MANDATÓRIO, do CLAUDE.md):** nenhuma tarefa que altere lógica de
   seletor/DOM/timing é DoD-completa só com a suíte MOCKADA verde. Toda tarefa que muda comportamento
   de runtime precisa passar pelo gate de browser real — via skill **`aegis-regression-gate`**
   (retrocompat: roda o bot de referência compilado N vezes vs baseline, veredito APROVADO/REPROVADO)
   e/ou **`aegis-live-pilot`** (validação de sabotagem contra site real). Isso está nos DoDs abaixo;
   não pule. Tarefas de fundação que apenas ADICIONAM um método sem call site alcançável ainda não têm
   superfície de runtime — o gate de browser delas roda nas tarefas que as fiam (SUB 03/04) e no SUB 08.

4. **Comandos de teste reais deste repo** (Python puro, sem pytest runner — rode o arquivo direto):
   - `python aegis_runner/test_runner_integration.py`
   - `python aegis_runner/test_cognitive_fallback.py`
   - Requisito de versão do projeto: Python >= 3.8.

5. **Escopo estrito.** Cada tarefa lista os arquivos que pode tocar. Fora disso é território proibido.
   Proibido refatorar, renomear ou "melhorar" o que não está no objetivo. F1 **NÃO toca** recorder,
   sanitizer nem emitter (isso é F2).

6. **Preservação byte-a-byte da mecânica flaky:** o gate `(strict or is_flaky_step) and not
   flaky_healing_unlocked` continua sendo avaliado ANTES de entrar na cadeia de tiers, exatamente como
   hoje. Passo flaky em tentativa ≤3 continua levantando `FlakyStepFailure` e reiniciando a linha SEM
   tocar em tier 3/4. Nenhuma tarefa pode alterar isso.

---

### [SUBAGENTE 01] - Fundação A1: verificador universal `_verify_action_effect`
> ✅ CONCLUÍDO (2026-07-14) — método em `runner.py:644`, 26 testes novos, 83/83 OK, zero call sites de produção (aditivo confirmado por grep).
- **🎯 Objetivo:** Criar em `runner.py` o método único `_verify_action_effect(page, before_snapshot, expected=None) -> bool` que generaliza a verificação de efeito já existente, COM a ressalva obrigatória de overlay e pós-condições type-aware de fill. Apenas ADICIONA o método + testes unitários; não fia nenhum call site ainda.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (métodos `_capture_click_effect_snapshot`, `_click_effect_signals_changed`, `fill_chained` — a comparação `actual != text_val`, e a detecção de `input_type`), `.specs/plano-cauda-longa-verificada.md` (Seção 4.A1)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie em `aegis_runner/runner.py` um novo método `_verify_action_effect(self, page, before_snapshot, expected=None) -> bool` na classe do runner. Ele generaliza a verificação de efeito, NÃO substitui o que já existe — reutilize `_click_effect_signals_changed` como base dos sinais genéricos. Regras obrigatórias:
  > 1. **Sinais genéricos (sempre):** delegue a `_click_effect_signals_changed` (URL/domSize/overlay/className).
  > 2. **Ressalva de overlay (DEPENDÊNCIA DURA, não cosmética):** quando o snapshot `before` indicar que havia um painel aberto (presença de `.cdk-overlay-pane` ou `[role='listbox']` no estado `before`), sinais genéricos SOZINHOS NÃO bastam — fechar um painel via clique no backdrop CDK muda os MESMOS sinais sem confirmar o clique certo (falso-positivo já documentado no próprio código). Nesse caso exija a pós-condição específica (painel fechou E valor apareceu no trigger/opção); nunca aceite só genéricos.
  > 3. **Pós-condições específicas por gesto** (quando aplicável, via `expected` ou tipo de gesto): **fill** → leia `input_value()` do elemento que DE FATO recebeu a digitação (o alvo proposto / `document.activeElement`, NÃO o seletor original que falhou) e compare **type-aware**: para campos numéricos/mascarados (input_type numérico já detectado pelo runner, ou chave semântica CPF/CNPJ/CEP conhecida pelo `_ASYNC_GUARD_KEY_RE`) compare só dígitos; para texto livre (nome, endereço) compare exato ou normalizando só whitespace — NUNCA faça strip de pontuação (mascararia fill errado em 'José D''Ávila' ou 'Rua X, 123'); tolere a conversão de formato de data que o runner já faz. **select** → painel fechou E valor apareceu no trigger. **clique de trigger** → painel abriu. **navegação** → URL mudou. Use as primitivas de confirmação que já existem no arquivo como referência, generalizando — não copie `actual != text_val` literalmente (é igualdade estrita; a base a generalizar).
  > 4. Quando `expected` vier preenchido (Fase 2, ainda não usado agora), ele é critério primário; sem ele, use os genéricos com a ressalva de overlay.
  > Escreva testes unitários novos em `test_runner_integration.py` cobrindo: sinais genéricos passam/reprovam; ressalva de overlay (com painel no `before`, genéricos sozinhos NÃO aprovam); fill type-aware numérico (só dígitos) vs texto livre (exato, sem strip de pontuação). NÃO fie este método em nenhum call site ainda — isso é tarefa de outro subagente. Não toque em nenhuma outra função."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (inclui os novos testes de `_verify_action_effect`) — 83/83 OK
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde (sem regressão) — 7/7 OK
  - [x] Método é ADITIVO: nenhuma função pré-existente teve comportamento alterado (grep confirma que `_verify_action_effect` ainda não tem chamador de produção) — 0 call sites confirmado
  - [x] Browser real: N/A nesta tarefa (método ainda sem call site alcançável; gate roda no SUB 03/04/08)

---

### [SUBAGENTE 02] - Fundação A4: gate de plausibilidade pré-clique `_hit_test_plausible`
> ✅ CONCLUÍDO (2026-07-14) — função em `runner.py:719`, modo soft Shadow DOM (`" >> "`), 91/91 testes OK, zero call sites de produção.
- **🎯 Objetivo:** Criar em `runner.py` a função de gate de plausibilidade pré-clique que generaliza o hit-test já usado no fallback de coordenada do select (`elementFromPoint` + match de texto), COM o modo soft para Shadow DOM. Apenas ADICIONA função + testes; não fia call site ainda.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (o hit-test existente dentro de `select_option_resilient` — bloco que usa `document.elementFromPoint(x, y)` e compara `textContent`), `.specs/plano-cauda-longa-verificada.md` (Seção 4.A4 + ressalva de Shadow DOM)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie em `aegis_runner/runner.py` uma função `_hit_test_plausible(self, page, x, y, target_description, original_selector=None) -> bool` que generaliza o hit-test já usado no fallback de coordenada do `select_option_resilient` (`document.elementFromPoint(x, y)` retornando `textContent`). A função roda `elementFromPoint(x, y)` na coordenada proposta e checa se `tagName`/`textContent`/`role` do elemento sob o ponto é compatível com `target_description`. Retorna True (plausível) ou False (implausível).
  > **Ressalva de Shadow DOM (obrigatória):** `elementFromPoint` no nível do `document` retorna o shadow HOST, não o elemento interno (event retargeting), e `textContent` do host não atravessa a fronteira do Shadow DOM. Quando `original_selector` contiver a substring `' >> '` (seletor de Shadow DOM sancionado, Padrão A), rode em **MODO SOFT**: logue a checagem mas NÃO bloqueie (retorne True), deixando a verificação PÓS-clique ser a única linha de defesa nesse caso. Não tente `shadowRoot.elementFromPoint`.
  > Esta função é PURA em termos de efeito: NÃO clica, NÃO muda estado da página — só inspeciona. Escreva testes unitários em `test_runner_integration.py`: elemento compatível → plausível; incompatível → implausível SEM nenhum clique físico (mock de `page.mouse.click` NÃO chamado); seletor com `' >> '` → modo soft retorna True mesmo com texto divergente. NÃO fie em nenhum call site ainda. Não toque em outra função."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (inclui testes de `_hit_test_plausible`, incl. modo soft Shadow DOM e "implausível não clica") — 91/91 OK
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde (sem regressão) — 7/7 OK
  - [x] Função é ADITIVA e sem efeito colateral (nenhum `page.mouse`/`page.keyboard` dentro dela)
  - [x] Browser real: N/A nesta tarefa (sem call site; gate roda no SUB 03/08)

---

### [SUBAGENTE 03] - B (ATÔMICO): contrato proposto→verificado + migração dos 6 call sites + migração dos testes existentes
> ✅ CONCLUÍDO (2026-07-14) — contrato dict/None, 6 call sites migrados, testes migrados (91+7 OK). Gate de browser real: APROVADO com exceção anotada — ver `.specs/plans/cauda-longa-verificada.baseline-001.md` Seção 2 (queda de métrica explicada: falso-HEALED real capturado ao vivo em `st_022`, não regressão).
- **🎯 Objetivo:** Inverter o contrato de `self_healing_click` (de `bool` que clica → `dict|None` que PROPÕE), adicionar `propose_fill_target`, dar intenção ao prompt, e — NO MESMO COMMIT — migrar os 6 call sites em `runner.py` para o fluxo `propor → gate(A4) → clicar/focar → verificar(A1) → agir`, E migrar os testes existentes que quebram. **Esta é UMA mudança de contrato indivisível.** Não pode ser fatiada em tarefas paralelas.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/cognitive_fallback.py` (todo `self_healing_click`), `aegis_runner/runner.py` (os 6 call sites: `_handle_unrecoverable_click`, `select_option_resilient`, `select_option_native_resilient`, `fill_chained`, `fill_resilient`, `fill_human_like`; e os métodos `_verify_action_effect` e `_hit_test_plausible` criados nos SUB 01/02), `.specs/plano-cauda-longa-verificada.md` (Seção 4.B integral + Seção 3)
  - Modificar: `aegis_runner/cognitive_fallback.py`, `aegis_runner/runner.py`, `aegis_runner/test_cognitive_fallback.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, execute esta mudança de contrato como UMA unidade atômica, na ordem abaixo, sem deixar o repo em estado intermediário quebrado.
  >
  > **PASSO 1 — `cognitive_fallback.py` (B1+B2):** transforme `self_healing_click` de ação final em PROPOSTA. Ele deve retornar `{'x': int, 'y': int, 'reason': str, 'confidence': float}` quando a IA avista o alvo, ou `None` quando não avista / módulo inativo / exceção. REMOVA os 3 `return True` cegos e os `page.mouse.click(x, y)` embutidos (o caso módulo-inativo, o caso sucesso-IA, e o caso exceção/timeout) — coordenada é tier do RUNNER agora, não do gateway. Preserve a intenção do design atual em que IA que responde 'não encontrei' retorna `None` (não vira clique cego). No prompt, ADICIONE contexto de intenção (`expected_effect` textual derivado do tipo de gesto — ex.: 'após o clique, um painel deve abrir' / 'a URL deve mudar' / 'o campo deve habilitar'). Adicione o método análogo `propose_fill_target(...)` (mesma forma de retorno dict|None) para os fills. NÃO altere `diagnose_failure`, `compare_visual_similarity`, `transcribe_audio`, `call_llm`/`parse_json_response` — grep confirma que só `self_healing_click` faz clique físico no arquivo.
  >
  > **PASSO 2 — migrar os 6 call sites em `runner.py`** para o fluxo `propose → gate(A4) → click/focus → verify(A1) → agir`. Reconfirme por grep os call sites de `self.cognitive.self_healing_click(`. São 6, com severidade diferente (trate todos, mas ciente do risco):
  >   - `_handle_unrecoverable_click` (~933) e `select_option_resilient` (~1514): hoje produzem falso-HEALED puro (`return True` cego). Após propor, rode `_hit_test_plausible`; se implausível → logue `VERIFY_REJECTED` (pré-clique, custo zero) e siga pro próximo tier SEM clicar; se plausível → clique, depois `_verify_action_effect`; só vira HEALED se verificar.
  >   - `fill_chained` (~2061), `fill_resilient` (~2171), `fill_human_like` (~2254): hoje o padrão `if clicked: <digita em document.activeElement>` passaria a digitar SEM foco garantido (dict é truthy) → corrupção silenciosa. `2171`/`2254` são as rotas de fill DEFAULT (HUMAN_LIKE) — prioridade máxima. Use `propose_fill_target` → gate → focar o alvo proposto → digitar → `_verify_action_effect` (pós-condição de fill type-aware). Sem verificação, NÃO reporte HEALED.
  >   - `select_option_native_resilient` (~1594): degrada sem corromper (o retry re-executa `select_option` real, auto-verificável) — migre igual, mas é a menor classe de risco.
  > Todo tier resolvido por healing continua registrando `needs_review` via `_register_healing_for_review` (Sensor F1), como hoje. `VERIFY_REJECTED` NUNCA levanta `FlakyStepFailure` — é só um tier esgotado, cai pro próximo/FAILED. Preserve o gate flaky ANTES da cadeia (aviso global #6).
  >
  > **PASSO 3 — migrar os testes existentes que quebram com o contrato bool→dict** (mesmo commit, é migração esperada, não regressão):
  >   - `test_cognitive_fallback.py`: `test_self_healing_click_success` (assere `mouse.click.assert_called_once_with` — deixa de valer; reescreva para assertar o dict de proposta e que `mouse.click` NÃO foi chamado). `test_self_healing_click_not_found` (hoje passa por acidente com `assertFalse(None)`; reescreva para assertar `None` explícito).
  >   - `test_runner_integration.py`: os métodos com `@patch(...self_healing_click, return_value=True)` que alcançam o call site pós-migração quebram duro — ajuste os mocks para retornar um dict de proposta (`{'x':.., 'y':.., 'reason':.., 'confidence':..}`) e ajuste as asserções de fluxo: `test_click_resilient_fallback_success`, `test_click_chained_non_strict_falls_back_to_self_healing`, `test_click_resilient_flaky_attempt_4_unlocks_self_healing`, `test_select_option_resilient_flaky_attempt_4_unlocks_self_healing`, `test_click_resilient_flaky_strict_false_attempt_4_unlocks_self_healing`, `test_click_resilient_non_flaky_strict_false_self_healing_untouched`, `test_fill_chained_falls_back_to_cognitive_when_no_unique_reduction`. Os 2 com `return_value=False` que sobrevivem por serem falsy devem virar `return_value=None` por semântica: `test_select_option_resilient_coordinate_fallback_logs_healed`, `test_click_no_effect_genuine_failure_raises_after_all_recovery_layers_fail`.
  > NÃO corte o wrapper de compat aqui (isso é o SUB 08). NÃO reordene a coordenada do click (isso é o SUB 04). NÃO mexa em T1/T2 (SUB 05). Faça só a mudança de contrato + migração dos call sites + migração dos testes."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde (testes de proposta migrados: retorna dict/None, não clica) — 7/7 OK
  - [x] `python aegis_runner/test_runner_integration.py` verde (todos os 9 métodos listados migrados; nenhum vermelho por `TypeError` de dict-como-bool) — 91/91 OK
  - [x] Grep confirma ZERO `page.mouse.click` remanescente dentro de `self_healing_click`
  - [x] Grep confirma os 6 call sites migrados para o fluxo propose→gate→verify (nenhum `if clicked:` que digite/selecione sem verificação)
  - [x] **Browser real (Working Agreement #1):** skill `aegis-regression-gate` → **APROVADO com exceção anotada** contra o baseline `TesteFimm/006-Fimm` — 3/3 execuções consistentes (SUCCESS 19→17, HEALED 6→4, ponto de falha st_026→st_022), investigado e explicado: `st_022` era falso-HEALED na Seção 1 (IA clicava cego num painel errado, digitava sem confirmar, reportava sucesso incondicional); pós-SUB03 o gate de plausibilidade rejeita a proposta ANTES do clique (zero ação), corretamente. Não é regressão — é a doutrina funcionando. Achado incidental fora de escopo: `input[type='range']` de `st_022` está `disabled` no DOM (gap do plano/geração deste projeto, não do runtime).

---

### [SUBAGENTE 04] - A2: reorder coordenada-antes-do-LLM no click + snapshot `before` para fill/select + rota de verificação
> ✅ CONCLUÍDO (2026-07-14) — coordenada gravada verificada movida pra antes do cognitivo em `_handle_unrecoverable_click`; 93/93 + 7/7 testes OK. Gate browser real: APROVADO sem exceção, 3/3 execuções idênticas ao pós-SUB03 (17/4/2/25, mesmo ponto de falha, `needs_review` estável em 9) — mudança não regrediu nada. `st_007` (autocomplete de banco, flagado pelo usuário) continua HEALED sem verificação como esperado — é T1, escopo do SUB05.
- **🎯 Objetivo:** Completar o rewire da cadeia da Seção 3 que não está no SUB 03: mover a coordenada gravada para ANTES do LLM no click (`_handle_unrecoverable_click`), estender a captura do snapshot `before` para os gestos de fill/select, e garantir que TODO retorno positivo de tier passe por `_verify_action_effect` antes de virar HEALED.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (`_handle_unrecoverable_click` e o comentário "Último Recurso" sobre staleness de coordenada; `select_option_resilient` que JÁ tem coordenada antes do cognitivo — usar como referência da ordem-alvo; `_capture_click_effect_snapshot`; `_verify_action_effect`), `.specs/plano-cauda-longa-verificada.md` (Seção 3 + Seção 4.A1/A2)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, complete o rewire da cadeia de tiers conforme a Seção 3 do plano, SEM refazer o que o SUB 03 já fez (contrato do gateway e migração dos call sites já estão prontos).
  > 1. **Reorder do click:** em `_handle_unrecoverable_click`, hoje a ordem é geometria-ao-vivo → cognitivo → coordenada gravada (coordenada é 'Último Recurso' por staleness). Mude para: identidade/geometria → **coordenada gravada COM `_verify_action_effect`** → LLM verificado. ATENÇÃO: isto é mudança REAL de comportamento num caminho que funciona hoje, não no-op. Só é seguro porque a ressalva de overlay do `_verify_action_effect` (SUB 01) está ativa — a coordenada gravada, se obsoleta e caindo no backdrop CDK, dispararia o falso-positivo genérico documentado; a verificação com ressalva de overlay é o que impede isso. A coordenada gravada roda com verificação de efeito ANTES do LLM. O `select_option_resilient` JÁ está nessa ordem — não o altere, use como referência.
  > 2. **Snapshot `before` para fill/select:** hoje o snapshot antes/depois já é capturado para o click (sensor de CLICK_NO_EFFECT). Estenda a captura de `before` (uma vez, no início do gesto) para os gestos de fill e select, para que `_verify_action_effect` tenha o baseline.
  > 3. **Rota de verificação universal:** garanta que todo retorno positivo de tier (identidade, coordenada) passe por `_verify_action_effect` (ou pela pós-condição específica) antes de virar HEALED. Proposta de tier rejeitada pela verificação → logue `VERIFY_REJECTED` e siga pro próximo tier; nunca aborte por proposta ruim, só quando esgotar.
  > Preserve o gate flaky ANTES da cadeia (aviso global #6). NÃO mexa em T1/T2 (SUB 05), nem na semântica de `strict` (SUB 06), nem na telemetria agregada (SUB 07). Adicione/ajuste testes de integração mockada da cadeia click/select com coordenada aceita e rejeitada."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (cadeia click com coordenada-antes-do-LLM; verificação em tier de coordenada) — 93/93 OK
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde — 7/7 OK
  - [x] Grep/inspeção confirma que nenhum tier de coordenada/identidade reporta HEALED sem passar por `_verify_action_effect`
  - [x] **Browser real (Working Agreement #1):** skill `aegis-regression-gate` → **APROVADO** (3/3 execuções idênticas ao baseline pós-SUB03, sem exceção)

---

### [SUBAGENTE 05] - A3: T1/T2 (multi-candidato e `.first`) entram na doutrina de verificação
> ✅ CONCLUÍDO (2026-07-14) — 99/99+7/7 OK, T1/T2 verificados com `_verify_action_effect`. Gate browser real: APROVADO, 3/3 idêntico ao pós-SUB04 (17/4/2/25, `needs_review`=9). **Achado incidental durante o gate**: `st_007` (autocomplete de banco, flagado pelo usuário como painel-nunca-fecha-mas-HEALED) NÃO passa por T1/T2 — passa por `fallback_selectors` (Nível 2.9, código M5 pré-existente), que usa `_effect_confirmed` chamando `_click_effect_signals_changed` DIRETO, sem a ressalva de overlay do `_verify_action_effect`. Bug real, mas FORA do escopo desta tarefa e do backlog original (SUB01-08 nunca tocam `_attempt_deterministic_click_recovery`). Reportado ao usuário; decisão pendente sobre adicionar tarefa nova (SUB05b) pra cobrir Níveis 2.5/2.75/2.9.
- **🎯 Objetivo:** Fazer os tiers T1 (heurística multi-candidato) e T2 (strict-violation → `.first`) só aceitarem com verificação de efeito, logando `HEALED`/`healing_method="ambiguous_candidate_verified"` + Sensor F1, em vez do SUCCESS silencioso de troca de alvo.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (o ponto da heurística multi-candidato no fluxo de click; os pontos de "strict mode violation"/"resolved to" que clicam/preenchem `.first` no click e no fill; `_verify_action_effect`; `_register_healing_for_review`), `.specs/plano-cauda-longa-verificada.md` (Seção 4.A3)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, coloque os tiers T1 e T2 sob a doutrina de verificação. Hoje: (a) a heurística multi-candidato troca de alvo silenciosamente e loga SUCCESS; (b) uma 'strict mode violation'/'resolved to' clica o `.first` (no click) ou preenche o `.first` (no fill) e loga SUCCESS. Mude ambos para: só aceitar o resultado se `_verify_action_effect` confirmar o efeito; quando confirmado, logar `HEALED` com `healing_method='ambiguous_candidate_verified'` e registrar `needs_review` via `_register_healing_for_review` (Sensor F1) — NÃO mais SUCCESS silencioso. Se a verificação reprovar, logue `VERIFY_REJECTED` e a cadeia segue. Localize esses pontos por grep de 'strict mode violation'/'resolved to' e da heurística multi-candidato — os números de linha do plano estão defasados. Preserve o gate flaky. NÃO mexa no reorder do click (SUB 04) nem na semântica de `strict` (SUB 06). Adicione testes de que T1/T2 logam HEALED verificado (não SUCCESS) e criam entrada `needs_review`."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (T1/T2 logam HEALED verificado + `needs_review`) — 99/99 OK (6 testes novos)
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde — 7/7 OK
  - [x] Grep confirma que os pontos multi-candidato e `.first` não têm mais caminho de SUCCESS sem verificação
  - [x] **Browser real (Working Agreement #1):** skill `aegis-regression-gate` → **APROVADO** (3/3 idêntico, sem regressão). Achado incidental fora de escopo documentado acima (`fallback_selectors`/M5).

---

### [SUBAGENTE 06] - A5: re-semantização de `strict` ("apenas tiers 1-2")
> ✅ CONCLUÍDO (2026-07-14) — 101/101+7/7 OK. Achado e corrigido: `select_option_resilient` tinha 2 fallbacks de coordenada que nunca consultavam `strict` (só a mecânica flaky), contradizendo o contrato "tiers 1-2 apenas" que já funcionava certo em click/fill. Gate browser real: APROVADO, 3/3 idêntico (17/4/2/25), `needs_review`=9.
- **🎯 Objetivo:** Re-semantizar `strict=True` para significar "apenas tiers 1-2" (sem coordenada nem LLM) — modo homologação/replay-literal —, mantendo `strict=False` como default de produção (NÃO aplicar nenhum flip global de default).
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (todos os pontos que hoje consultam `strict` para bloquear tiers — click, fill, select; a interação com `flaky_healing_unlocked`), `.specs/plano-cauda-longa-verificada.md` (Seção 4.A5 + Seção 7)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, re-semantize o parâmetro `strict` do runner. Novo contrato: `strict=True` = 'apenas tiers 1-2' (identidade/geometria; SEM tier de coordenada verificada e SEM tier LLM) — modo de homologação/replay-literal. `strict=False` PERMANECE o default de produção — NÃO aplique nenhum flip de default global (o plano anterior propunha `strict=True` default; este plano o CANCELA). Garanta que, sob `strict=True`, a cadeia pule do tier 2 direto pro FAILED limpo, sem coordenada nem LLM. Preserve a composição com a mecânica flaky exatamente como hoje (aviso global #6): o gate `(strict or is_flaky_step) and not flaky_healing_unlocked` continua avaliado antes da cadeia. Localize os pontos por grep de `strict` — linhas do plano defasadas. NÃO mexa em T1/T2 (SUB 05) nem no reorder (SUB 04) além do necessário para o corte de tier sob strict. Ajuste/adicione testes: sob `strict=True`, coordenada e LLM NÃO são alcançados; sob `strict=False`, cadeia completa roda."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (testes de `strict` refletindo "tiers 1-2 apenas"; default `strict=False` intacto) — 101/101 OK
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde — 7/7 OK
  - [x] **Browser real (Working Agreement #1):** skill `aegis-regression-gate` → **APROVADO** (3/3 idêntico, sem regressão)

---

### [SUBAGENTE 07] - E: telemetria/observabilidade (`VERIFY_REJECTED` pré/pós + tier resolver + taxa por tier)
> ✅ CONCLUÍDO (2026-07-14) — 118/118+7/7 OK, aditivo confirmado. Gate browser real: APROVADO, 3/3 idêntico (17/4/2/25), `needs_review`=9. `reports/telemetria_resolucao.json` validado com dado real: `identity=17, fallback_selector=1, parent_has_text_reduced=2, coordinate=1, verify_rejected pre_click=1` — bate exatamente com a investigação manual de `st_007`/`st_022` feita nesta sessão.
- **🎯 Objetivo:** Registrar por passo, em `historico_passos.json`, o tier resolvedor e o `verify_result` (sinais que passaram), e a contagem de `VERIFY_REJECTED` separada por pré-clique e pós-clique; mais a métrica agregada por execução de taxa de resolução por tier.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (`_log_step` e a escrita de `historico_passos.json`; os pontos onde `VERIFY_REJECTED` passou a ser logado pelos SUB 03/04/05), `.specs/plano-cauda-longa-verificada.md` (Seção 4.E)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, estenda a telemetria do runner (aditivo, sem quebrar o schema atual de `historico_passos.json`). Por passo, registre: tier resolvedor, `verify_result` (quais sinais de verificação passaram), e contagem de `VERIFY_REJECTED` separada em pré-clique (gate de plausibilidade, nenhuma ação ocorreu) vs pós-clique (verificação de efeito reprovou após clicar). Adicione uma métrica agregada por execução: taxa de resolução por tier (quanto da cauda longa o tier 4/LLM realmente resolve; taxa de rejeição pré vs pós-clique). Isso é o número que valida a adesão à tendência e informa a F3. Mudança ADITIVA — passos/execuções sem os campos novos continuam válidos. NÃO altere a lógica de decisão de tier (isso já foi feito nos SUB 03-05); só instrumente. Adicione testes de que os campos novos aparecem no histórico e que a contagem pré/pós é separada."
- **🧪 Critério de Validação (DoD):**
  - [x] `python aegis_runner/test_runner_integration.py` verde (campos de telemetria novos + contagem pré/pós separada) — 118/118 OK
  - [x] `python aegis_runner/test_cognitive_fallback.py` verde — 7/7 OK
  - [x] Mudança confirmadamente aditiva (histórico antigo sem os campos continua parseável)
  - [x] **Browser real (Working Agreement #1):** skill `aegis-regression-gate` → **APROVADO** — `telemetria_resolucao.json` inspecionado, dados corretos e batendo com investigação manual

---

### [SUBAGENTE 08] - Validação final de browser real (sabotagem) + reconfirmação de B4 (zero chamadores diretos)
> ✅ CONCLUÍDO (2026-07-14) — Parte B feita diretamente (grep no bot real `TesteFimm`: zero chamadores diretos de `self_healing_click`/`CognitiveGateway` — B4 reconfirmado). Parte A: 3 cenários de sabotagem confirmados ao vivo contra site real, evidência re-verificada diretamente nos logs brutos (não só self-report do subagente): (1) LLM resolve com verificação — `st_005`, `resolver_tier="visual_ai"`, `verify_result.passed=true`; (2) rejeição pós-clique — `[VERIFY_REJECTED]...(pos-clique)` → FAILED limpo, nunca HEALED; (3) rejeição pré-clique — já demonstrado organicamente 21x (`st_022`) + reconfirmado. **Achado incidental durante os testes**: 1ª tentativa do cenário 1 expôs gap real — o 4º sinal de verificação (`siblingClassFingerprint`) re-resolve o seletor ORIGINAL morto em vez da coordenada realmente clicada, ficando cego a troca de aba via classe CSS pura mesmo quando a IA acertou o alvo. Reportado como tarefa separada (fora de escopo desta tarefa, que é só medição). Relatório completo: `.specs/relatorio-piloto-cauda-longa-verificada-sub08.md`.
- **🎯 Objetivo:** Provar em site real que a doutrina F1 funciona ponta-a-ponta (via cenários de sabotagem do plano, Seção 4.F), e reconfirmar empiricamente a premissa de B4 ("zero chamadores diretos de `self_healing_click` fora do runner") contra bots reais em produção antes de tratar como fato. Esta tarefa NÃO modifica código de framework core.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py`, `aegis_runner/cognitive_fallback.py` (apenas para o grep de reconfirmação), `.specs/plano-cauda-longa-verificada.md` (Seção 4.F + Seção 4.B4 + ressalva da Rodada 3), `CLAUDE.md` (descrição das skills `aegis-live-pilot`/`aegis-regression-gate`)
  - Modificar: nenhum arquivo de framework core. Pode gravar o relatório de piloto onde a skill `aegis-live-pilot` grava (`.specs/relatorio-piloto-<slug>.md`).
- **🤖 Prompt para o Claude Code:**
  > "Claude, faça a validação final da Fase F1 em browser real e a reconfirmação de B4. Duas partes:
  > **Parte A — sabotagem (skill `aegis-live-pilot`, requer URL real fornecida pelo usuário — NÃO invente URL):** rode os 3 cenários da Seção 4.F do plano: (1) seletor sabotado → confirmar que o tier 4/LLM resolve COM verificação (HEALED verificado, não falso-HEALED); (2) efeito sabotado (elemento clicável mas inerte) → confirmar `VERIFY_REJECTED` pós-clique → FAILED limpo, ZERO falso-HEALED; (3) posição sabotada (coordenada aponta pra elemento errado plausível-parecendo) → confirmar que o gate pré-clique (`_hit_test_plausible`) rejeita quando o hit-test não bate com `target_description`. Para exercitar o tier 4 é preciso `AEGIS_COGNITIVE_ENABLED=true` (com chave). Documente os resultados no relatório de piloto.
  > **Parte B — reconfirmação de B4:** faça grep por chamadores DIRETOS de `self_healing_click` / `.cognitive.self_healing_click` / uso de `CognitiveGateway` fora de `aegis_runner/runner.py`, incluindo os bots compilados reais em `projects/*/tests/*/bot_producao.py`. ATENÇÃO: `projects/` é gitignored e pode estar VAZIO neste checkout — se estiver, rode o grep contra o diretório `projects/` real da máquina de implementação (onde os bots estão populados). O objetivo é reconfirmar 'zero chamadores diretos' contra bots reais, não herdar a contagem '186' do plano (não reproduzível aqui). Se confirmado zero, o corte do wrapper (B4) está justificado por evidência; se aparecer algum chamador direto, reporte — o erro de assinatura seria trivial de corrigir mas precisa ser sabido. NÃO modifique código de framework core nesta tarefa; ela mede e valida."
- **🧪 Critério de Validação (DoD):**
  - [x] Cenários de sabotagem executados contra site real (`TesteFimm`, `http://localhost:6174`): cenário 1 = HEALED verificado (`resolver_tier="visual_ai"`); cenário 2 = `VERIFY_REJECTED` pós-clique + FAILED limpo (zero falso-HEALED); cenário 3 = gate pré-clique rejeita posição errada
  - [x] Relatório de piloto gravado (`.specs/relatorio-piloto-cauda-longa-verificada-sub08.md`)
  - [x] Grep de reconfirmação de B4 executado contra bot real (`TesteFimm/tests/cenario_principal/code/bot_producao.py`); zero chamadores diretos confirmado ⇒ B4 justificado
  - [x] Nenhum arquivo de `aegis_*` core modificado nesta tarefa
