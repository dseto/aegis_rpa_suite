# Gap: recuperação ENABLE_TIMEOUT não registra `healing_method`

**Status:** 🏁 FECHADO — 2026-07-10. Implementado em `aegis_runner/runner.py` (`click_resilient`, ambos call sites de `_recover_via_recent_fills`), teste de regressão em `aegis_runner/test_runner_integration.py::TestEnableTimeoutSensor::test_successful_recovery_registers_needs_review_with_enable_timeout_recovered`, doc atualizada em `CLAUDE.md` ("Enable-Timeout Detection"). Task avulsa (`task_debf8458`), não passou por `plan-critic` (gap pontual, escopo trivial demais para justificar o ciclo completo).
**Origem:** achado durante `/reflect` no fechamento de `sensor-enable-timeout-recuperacao-fill.backlog.md` (2026-07-10).

## Problema

Em `aegis_runner/runner.py`, o sensor `ENABLE_TIMEOUT` (`_recover_via_recent_fills`, ~linha 991), quando recupera um clique com sucesso (o alvo habilita após re-fill dos campos recentes), cai direto em `_finalize_click_success` (~linha 561/655) sem nunca chamar `_register_healing_for_review` com um `healing_method` próprio (ex. `"enable_timeout_recovered"`).

Hoje o passo só fecha como `HEALED` se o sensor `CLICK_NO_EFFECT` (mecanismo diferente — snapshot de URL/DOM/overlay) coincidentemente também detectar mudança. Caso contrário fecha como `SUCCESS` comum, indistinguível de um clique que nunca teve problema.

Isso contradiz o princípio já documentado em `CLAUDE.md`: "Every tier that resolves a step via healing... auto-registers a `needs_review` entry in `correcoes_acumuladas.json` (Sensor F1)". A recuperação via `ENABLE_TIMEOUT` é uma camada de healing real (o bot preencheu campo cedo demais, precisou re-preencher) mas não deixa rastro em `correcoes_acumuladas.json`/`needs_review`, diferente de todas as outras camadas de healing (`visual_ai`, `coordinate`, `fallback_selector`, `click_no_effect_recovered`).

## Evidência

`projects/portal_segura/tests/001_teste/executions/run_20260710_084455/reports/execution.log`, linhas 77-99: `ENABLE_TIMEOUT` dispara em `st_018`, recuperação roda, passo fecha `HEALED` — mas sem `healing_method="enable_timeout_recovered"` seguindo o padrão dos outros tiers.

## Tarefa

Adicionar chamada a `_register_healing_for_review` com `healing_method="enable_timeout_recovered"` quando `_recover_via_recent_fills` tiver sucesso (retornar `True`), seguindo o mesmo padrão já usado nos outros tiers de healing em `runner.py` (ver linhas 723, 878, 894, 1124, 1393, 1459, 1772, 1858, 1883 para o padrão de chamada).

Adicionar teste de regressão em `aegis_runner/test_runner_integration.py` confirmando que uma recuperação bem-sucedida via `ENABLE_TIMEOUT` registra `needs_review` corretamente.

Rodar suíte completa (`test_runner_integration.py` + `test_cognitive_fallback.py`) antes de considerar pronto.

Mudança cirúrgica — não mexer em mais nada além disso.
