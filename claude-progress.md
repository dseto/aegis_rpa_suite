# Claude Progress

Contrato: `backlog-agentico-design-time`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | E1.1: marca de auditoria `generic_only_expected_missing` no runner (tiers de healing + identity), aditiva, sem mudança de control-flow, com registro Sensor F1 | pending |
| T-02 | E3: handler determinístico de overlay não mapeado na cadeia de recovery (dismiss Escape/botão canônico, discriminador expected_effect, disciplina _tier_baseline, HEALED + Sensor F1) | pending |
| T-03 | Regressão do runner: suíte completa de aegis_runner verde após T-01+T-02 (inclui test_runner_integration, test_unified_target, test_unified_target_wiring) | pending |
| T-04 | E2 núcleo: módulo testável `aegis_cockpit/healing_review.py` — varredura de needs_review, agrupamento por (action, failed_selector), resolução obrigatória de step_id, proposta determinística de promoção de seletor (anchor_geometry/fallback_selectors/parent_has_text_reduced, zero LLM) | pending |
| T-05 | E2 rota cognitiva: casos sem resolução estrutural → contexto (screenshot, healing_method, seletor falho/resolvido) → diagnose_failure do CognitiveGateway (mockado nos testes) → proposta estruturada de correção | pending |
| T-06 | E2 fiação: endpoint no cockpit.py expondo o fluxo (listar propostas, entregar diff, aprovar → correção pending no formato do fluxo surgical existente), lógica mantida em healing_review.py, handler HTTP fino | pending |
| T-07 | Fechamento: suíte completa do repo verde + lint (regressão zero sobre sanitizer/codegen/UTD) | pending |
| T-08 | Execução real (3x) do bot de referência Portal Segura (007-Portal Segura / 001-Cenário Principal, compilado, sem regeneração) contra site localhost:5173 — smoke live de que o runner alterado (T-01/T-02) não crasha em execução real headed. Exit 0 confirma só que as 3 execuções completaram sem exceção; comparação de métricas contra `.specs/plans/portal-segura.baseline-001.md` (taxa de sucesso, novo tipo de falha, needs_review, tempo) e veredito APROVADO/REPROVADO exigem leitura humana pós-execução via skill `aegis-regression-gate` — não é decidido por este verify_cmd. | pending |

## Última atualização

_(vazio — preenchido pelo agente durante a sessão)_
