# Plano de Refatoração — "Simulador Humano Fiel"

> Status: **AGUARDANDO APROVAÇÃO** — nenhum arquivo de código modificado.
> Data: 2026-07-13. Objetivo: robô rigorosamente fiel a usuário humano — falha rápida (strict), digitação cadenciada (HUMAN_LIKE), execução visível (headed) por padrão.
> Revisado em 2 rodadas independentes (plan-critic via Opus 4.8 + checagem de fidelidade à intenção via Fable) — ver Seção "Histórico de Revisão" no fim. Este documento já incorpora os 4 refinamentos resultantes.
> **SUPERSEDIDO (2026-07-14):** o default `strict=True` proposto neste plano foi revertido por `.specs/plano-cauda-longa-verificada.md` (Seção 7) — `strict=True` vira modo opt-in de homologação, não default de produção. Os demais itens (HUMAN_LIKE, headless=False, hover físico, emissão limpa, allowlist `time.sleep`, Cockpit) permanecem válidos.

## Correções de premissa (vs. diretrizes recebidas)

1. **Não há `.tpl`** — não existe pasta `templates/` no repo. Os "templates físicos" são funções emissoras em `aegis_code_generator/deterministic_emitter.py` (`_emit_click`, `_emit_fill`, etc., via f-strings). Único parâmetro redundante emitido hoje é `strategy=` no `_emit_fill` (linhas 235, 246, 258).
2. **`validate_bot_structure` não lança exceção** — contrato existente acumula dicts de erro (`{"type": ..., "detail": ...}`) e retorna `{"status": "FAIL", "errors": [...]}`; é o que o Ralph Loop consome. Não existe `BotValidationError` no código. Proposta: seguir o contrato (dict com `type: "FORBIDDEN_TIME_SLEEP"`), não lançar exceção — lançar quebraria o loop de correção.
3. **Dois furos que a diretriz não cobre** (necessários ao objetivo "falhar em vez de adivinhar"):
   - `fill_human_like` (`runner.py:2044`) não tem parâmetro `strict` e possui fallback cognitivo próprio (`runner.py:2110`) sem gate. Com HUMAN_LIKE default global, quase todo fill passa por esse caminho — strict seria contornado.
   - No `select_option_resilient`, fallback de coordenadas (`runner.py:1484`) roda ANTES do check de strict (linha 1508) e não é gateado por ele — coordenada histórica é "adivinhação" tanto quanto IA visual (comentário em `runner.py:1187` reconhece isso no caminho de click).
4. **Geometria DOM ao vivo (Nível 3) NÃO é adivinhação — é revisão de posição do mesmo alvo gravado.** `_click_by_live_geometry` resolve o elemento pelo literal `:has-text('...')` extraído do próprio seletor gravado (`_extract_has_text_literal`); só a *posição* é resolvida em tempo real (overlays CDK reancoram o painel a cada abertura — a coordenada percentual gravada fica obsoleta). Identidade do alvo = 100% da gravação. Categoria idêntica a `fallback_selectors` (caminho alternativo pro mesmo elemento gravado, também sobrevive a strict). Portanto: **Nível 3 continua ativo sob strict** em ambos os caminhos (`click`/`select`) — só os tiers que *inventam* alvo (IA visual, coordenada cega) são cortados. Ver Seção A e "Histórico de Revisão".

## Proposed Changes

### A. `aegis_runner/runner.py` — novos defaults globais

| Método | Linha | Mudança |
|---|---|---|
| `click_resilient` | 462 | `strict=False` → `strict=True` |
| `click_chained` | 1757 | `strict=False` → `strict=True` |
| `select_option_resilient` | 1319 | `strict=False` → `strict=True`; gate `and not strict` no fallback de **coordenadas** da opção (1484) e no cognitivo (1508, já gateado) |
| `select_option_native_resilient` | 1544 | `strict=False` → `strict=True` |
| `fill_chained` | 1839 | `strategy="DIRECT"` → `"HUMAN_LIKE"`; `strict=False` → `strict=True` |
| `fill_resilient` | 1930 | `strategy="DIRECT"` → `"HUMAN_LIKE"`; `strict=False` → `strict=True`; propagar `strict` na delegação para `fill_human_like` (1963, hoje não propaga) |
| `fill_human_like` | 2044 | adicionar `strict: bool = True` e gatear tier cognitivo (2110) com a mesma regra strict/flaky dos demais métodos |
| `run` | 2257 | `headless=True` → `headless=False` (override via `AEGIS_BROWSER_HEADLESS` preservado — Cockpit continua mandando) |

**Reposicionamento do gate de strict em `_handle_unrecoverable_click` (runner.py:856-924):** hoje o gate (linha 880, `if (strict or is_flaky_step) ... raise e`) dispara ANTES do Nível 3 (geometria ao vivo, linha 888+), cortando um tier determinístico junto com os de adivinhação. Mudança: mover o `raise` de strict para depois do bloco do Nível 3 — ordem final passa a ser (1) Nível 3 geometria por `live_text` (sobrevive a strict, sempre tenta se `live_text` disponível), (2) *então* o gate de strict decide se Nível 3.5 (cognitivo IA) e Nível 4 (coordenada gravada) rodam. Sem `live_text` (chamador não é `click_chained`), comportamento não muda — cai direto no gate.

**Auditoria da geometria ao vivo no select (`select_option_resilient`, runner.py:1470-1476):** hoje esse tier já roda sem gate de strict, mas em caso de sucesso não seta `healed_via_fallback` (só `"coordinate"` e `"visual_ai"` são setados, linhas 1498/1521) — loga `SUCCESS` silencioso em vez de `HEALED`, sem registrar `needs_review` via Sensor F1. Fix: setar `healed_via_fallback = "live_geometry"` quando a linha 1476 resolver o clique, para o desvio do seletor gravado ficar auditável (linha 1531-1532 já loga `HEALED` + Sensor F1 automaticamente uma vez que `healed_via_fallback` esteja setado — nenhuma outra mudança necessária ali).

**Hover físico:** remover curto-circuito `if not page.locator(selector).first.is_visible(timeout=500):` (`runner.py:483-484`) — loop de hover sequencial nos ancestrais roda sempre que seletor contém `" >> "`. Mantém `is_visible` por nível intermediário (não dá para hover em pai invisível) e try/except.

Não mexer: `flaky_step_ids`/desbloqueio na 4ª tentativa (mecânica ortogonal, composição com strict já verificada), tier `fallback_selectors` (determinístico, já roda sob strict por design), `time.sleep` internos do runner (validador cobre só código de bot, não o SDK).

### B. `aegis_code_generator/deterministic_emitter.py` — emissão limpa

- `_emit_fill`: remover variável `strategy` (linha 235) e as duas linhas `strategy="{strategy}"` (246, 258). Código emitido fica limpo; default `HUMAN_LIKE` da assinatura governa.
- Consequência assumida: campos hoje `fill_strategy=DIRECT` no dicionário passam a digitar cadenciado — regra global pedida. `DIRECT` continua alcançável via kwarg explícito (correção cirúrgica pode emitir).
- `_emit_click`/`_emit_select*` já não emitem nada redundante — sem mudança.
- `_emit_async_guard` (linha 323-336, emite `time.sleep(2.0)  # Aguarda validação assíncrona do campo` para campos CPF/CNPJ/CEP) **não muda** — é a forma canônica sancionada que a allowlist do validador (Seção C1) precisa reconhecer literalmente.

### C. `aegis_code_generator/step_validator.py`

1. **`FORBIDDEN_TIME_SLEEP` com allowlist** (não ban absoluto) em `validate_bot_structure` (linha 79+): walk AST detectando todo `time.sleep(...)`/`from time import sleep` + `sleep(...)`. Duas formas ficam isentas por comparação estrutural:
   - a linha canônica exata que `_emit_async_guard` produz (`time.sleep(2.0)` imediatamente após uma chamada `runner.fill_*` em campo CPF/CNPJ/CEP — mesma adjacência que o re-splice anti-drift já garante byte-idêntica);
   - o Padrão P do playbook (`time.sleep(0.5)` entre um `runner.fill_*`/`runner.click_*` e o próximo `runner.click_*` — janela de renderização de autocomplete, sem seletor determinístico disponível para essa espera, conforme documentado no próprio playbook).

   Qualquer `time.sleep` fora dessas duas formas → erro. Dict de erro **com `lineno`** — obrigatório pelo Working Agreement #5 do CLAUDE.md (erro sem `step_id`/`lineno` fica invisível à correção cirúrgica; mapeamento lineno→`# [PASSO X]` já existe no `code_generator.py`). Detail orienta: usar Padrão J (`runner.wait_for_selector`) ou, se for validação assíncrona/renderização real, usar exatamente uma das duas formas canônicas.
2. **`MISSING_HUMAN_LIKE_STRATEGY`** (`step_validator.py:1186-1198`): hoje exige kwarg explícito `strategy="HUMAN_LIKE"` via `kwarg_equals`. Com emissão limpa o kwarg some e o check falharia todo bot que tenha campo marcado `human_like_selectors` no dicionário. Ajuste: passa se kwarg ausente (default agora HUMAN_LIKE) ou `"HUMAN_LIKE"`; falha só com `strategy="DIRECT"` explícito em campo anti-bot.
3. **Hints de erro** (`step_validator.py:1859-1863`, strings literais mostradas ao LLM no Ralph Loop): atualizar assinaturas citadas para os novos defaults (`headless=False`, `strategy="HUMAN_LIKE"`, `strict=True`) — senão o hint mente pro modelo durante correção cirúrgica. (Os stubs `_FakeRunner`, linhas 1717-1729, só validam nomes de kwarg no dry-run, não valores default — atualizar é higiene, não requisito funcional.)

### D. `aegis_code_generator/code_generator.py` — prompts (caminho full-LLM/cognitivo)

- Boilerplate no prompt (linha 1230): `runner.run(headless=False)` → `runner.run()` (canônico de `_normalize_boilerplate` já é `runner.run()`, linha 103 — só o prompt está dessincronizado).
- Instruções de fill (1267-1272, Padrão M): remover `strategy="DIRECT"` dos exemplos; instruir a omitir `strategy` (default HUMAN_LIKE) e nunca emitir `strict=`/`headless=`.
- Reforçar no prompt que `time.sleep` só é aceitável nas duas formas do Padrão P/Regra 8 (já existentes no prompt) — **não** proibir totalmente no texto do prompt, para não contradizer a Regra 8 (linha 1284) que manda emitir o async guard. O validador (Seção C1) é o gate real; o prompt só precisa parar de sugerir sleeps fora dessas duas formas.

### E. Cockpit (Fase 5)

- `aegis_cockpit/static/index.html:1161`: remover `checked` do `#chk-run-headless` — UI abre com execução visível por padrão.
- `aegis_cockpit/cockpit.py:1318`: `body.get('headless', True)` → `body.get('headless', False)` (chamadas de API sem a flag também viram headed).
- `project_manager.py:313` já escreve `AEGIS_BROWSER_HEADLESS=false` no `.env` default — sem mudança.

### F. Testes (atualização de asserts, não rollback — Working Agreement #3)

- `test_deterministic_emitter.py` (166-184, 304-334): asserts de `strategy="DIRECT"`/`"HUMAN_LIKE"` viram asserts de **ausência** do kwarg.
- `test_restore_deterministic_blocks.py` (203, 207): strings canônicas com `strategy="DIRECT"` atualizadas para nova forma canônica (crítico: re-splice anti-drift compara forma canônica byte a byte).
- `test_runner_integration.py`: casos que dependem do default `strict=False`/`DIRECT` passam a declarar kwarg explicitamente ou têm expectativa atualizada. Novo caso: `_handle_unrecoverable_click` com `strict=True` + `live_text` setado → Nível 3 tentado, tier cognitivo/coordenada NÃO tentado se geometria resolver.
- Novo teste: `select_option_resilient` — geometria ao vivo bem-sucedida sob `strict=True` loga `HEALED`/`healing_method="live_geometry"` (não `SUCCESS` silencioso).
- Novo teste: `FORBIDDEN_TIME_SLEEP` — positivo (sleep arbitrário, `lineno` correto), negativo x2 (forma canônica do async guard passa; forma canônica do Padrão P passa).

## Riscos declarados

1. **Gap H8 amplificado**: `fill_human_like` faz `blur` incondicional que fecha painel de autocomplete recém-aberto (Seção 8 do `.specs/plano-codegen-hibrido-deterministico.md`). HUMAN_LIKE global aumenta exposição a esse bug conhecido (opt-in → opt-out). Fora de escopo cirúrgico — declarado, não corrigido aqui. Piloto obrigatório (Verification Plan #4) deve exercitar uma cadeia de autocomplete dependente real (ex.: Marca→Modelo) pra confirmar se o gap se manifesta sob os novos defaults.
2. ~~Bots já compilados mudam de comportamento sem regeneração~~ — **não é risco**: usuário confirmou que não há necessidade de manter retrocompatibilidade com bots já compilados. Baseline do `aegis-regression-gate` (portal_segura) diverge por design; novo baseline é simplesmente gravado pós-mudança, sem preocupação de preservar o comportamento antigo.
3. **Execução mais lenta** (60ms/tecla) e headed exige display — CI/lote devem setar `AEGIS_BROWSER_HEADLESS=true` explicitamente.
4. Menos entradas Sensor F1 (`needs_review`) nos tiers de adivinhação (IA/coordenada) — esperado, é o objetivo. Geometria ao vivo continua gerando `needs_review` (agora também no caminho select, ver Seção A) — não é uma perda de observabilidade, é redistribuição correta.

## Verification Plan

1. **Suites mockadas**: `python aegis_runner/test_runner_integration.py`, `test_deterministic_emitter.py`, `test_restore_deterministic_blocks.py`, `test_error_selector_config.py`, `test_weak_selector_enforcement.py`, `test_dryrun_multirow.py`, `test_sanitizer_execution_plan.py`.
2. **Validador**: bot sintético com `time.sleep(2)` solto → FAIL `FORBIDDEN_TIME_SLEEP` + `lineno` correto; bot com `time.sleep(2.0)` na forma canônica pós-CPF → PASS; bot com `time.sleep(0.5)` na forma canônica Padrão P → PASS; bot com `wait_for_selector` → PASS.
3. **Regeneração**: rodar Fase 4 num projeto existente; inspecionar `bot_producao.py` — zero `strategy=`, zero `strict=`, zero `headless=` explícitos; `generation_manifest.json` coerente.
4. **Browser real (obrigatório — Working Agreement #1)**: mudança toca seletor/DOM/timing (hover, HUMAN_LIKE, strict, geometria). Rodar bot de referência `portal_segura/tests/001_teste` via skill `aegis-regression-gate`, esperar divergência controlada do baseline, validar: janela visível, digitação cadenciada visível, falha rápida (sem tier cognitivo/coordenada) em seletor sabotado sem `live_text`, recuperação via geometria ao vivo (com log `HEALED`) em seletor de opção sabotado com `live_text`/dropdown, hover sequencial em passo com `" >> "`. Se houver cadeia de autocomplete dependente no cenário, exercitar (Risco 1). Gravar novo baseline.
5. **Cockpit**: abrir UI, confirmar checkbox desmarcado; disparar execução sem tocar no checkbox → processo recebe `AEGIS_BROWSER_HEADLESS=false`.

## Histórico de Revisão

**Rodada 1 — plan-critic via Opus 4.8.** Verificou as ~25 citações de linha do plano original contra o código real (todas corretas). Veredito: "Redesenho escopado". Achados aplicados neste documento:
- `[CRÍTICO]` `FORBIDDEN_TIME_SLEEP` como ban absoluto contradiz `_emit_async_guard`, Regra 8 do prompt e Padrão P do playbook — geraria deadlock no Ralph Loop pra bots com CPF/CNPJ/CEP. → Resolvido na Rodada 2 (allowlist, não remoção total — ver abaixo).
- `[ALTO]` `strict=True` também desligava o Nível 3 (geometria ao vivo, determinístico), que corrige uma cascata real de produção (st_024→st_025 Portal Segura). → Aplicado: gate de strict reposicionado (Seção A).
- `[MÉDIO]` Amplificação do gap H8 (blur incondicional). → Declarado como Risco 1, não corrigido (fora de escopo cirúrgico).
- Achado descartado por decisão consciente: alavanca `AEGIS_FORCE_HUMAN_LIKE` como via mais leve — rejeitada porque a intenção pede mudança de regra de negócio do motor, não configuração de ambiente (confirmado na Rodada 2).

**Rodada 2 — checagem de fidelidade à intenção via Fable**, avaliando se o plano + recomendações da Rodada 1 ainda cumprem "trocar velocidade e flexibilidade solta por execução rigorosa e 100% aderente ao voo físico gravado". Conclusão: sim, com um refinamento:
- Remover `FORBIDDEN_TIME_SLEEP` do escopo (recomendação literal da Rodada 1) deixaria o caminho LLM/cognitivo sem gate contra sleeps cegos — reabre a "flexibilidade solta" que a intenção quer eliminar, e contradiz a própria Seção D do plano ("validador é o gate real"). Refinamento aplicado: **allowlist de 2 formas canônicas**, não remoção (Seção C1).
- "Nível 3 sobrevive a strict" (achado ALTO da Rodada 1) é fidelidade real, não tolerância: geometria ao vivo re-localiza o mesmo alvo gravado (por `:has-text()` extraído da própria gravação), nunca inventa alvo — categoria idêntica a `fallback_selectors`, que o plano já mantinha ativo sob strict. Achado adicional da Rodada 2: gap de auditoria pré-existente no caminho select (geometria bem-sucedida logava `SUCCESS` silencioso) — corrigido na Seção A (`healed_via_fallback="live_geometry"`).
- Gap H8 (blur): confirmado como risco pré-existente declarado, não como furo de fidelidade — mantido fora de escopo.
