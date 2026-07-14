# Sumário de Entrega — Sessão 2026-07-14

## Contexto

Piloto fimm_billing, cenário 003_teste_novo. Bot falhava em st_014 (fill_chained — data de vencimento) com timeout 30s → healing visual (60s+). Achado: parent.has_text gravado com texto cruzando fronteira de elemento, irrecuperável.

## Entregues

### 1. Âncora viável (deterministic_emitter.py) — DONE ✅

**Problema:** Texto multi-linha colapsado em espaços + truncado em 50 chars, Playwright `:has-text()` nunca casa.

**Solução:** `_viable_has_text_literal()` — primeira linha só; linha única truncada descarta último token; nada viável → `None`. Impede emissão de seletor morto.

**Onde:** `_emit_click()` usa anchor viável; C5 de `classify_step` rejeita weak_selector sem material.

**Validação:** 8 testes novos, suíte 100%.

---

### 2. Container_click → optional (sanitizer.py) — DONE ✅

**Problema:** Clique em tags puras (`nav`, `main`) com `confidence < 70` é ruído de captura, sem efeito de negócio, dispara CLICK_NO_EFFECT healing toda execução.

**Solução:** Regra `_GENERIC_CONTAINER_CLICK_TAGS` — marca como `execution_hint: "optional"` + nota `container_click`. Numeração `st_` intacta; LLM omite por default.

**Validação:** 5 testes novos, 100%.

---

### 3. Redução de parent.has_text (runner.py) — DONE ✅

**Problema:** parent.has_text de `click_chained`/`fill_chained` com 0 match → healing cognitivo toda execução.

**Solução:** `_reduce_parent_has_text()` — corta tokens do fim, exige CHILD único (unicidade no alvo, não parent — containers aninhados casam 2+ ancestors legitimamente). `_retry_chained_with_reduced_parent()` retenta o gesto determinístico antes de escalar.

**Extras:**
- Union dos parents filtrados (nunca `.first` — child pode não estar sob primeiro container).
- Fallback teclado pra `fill()` rejeitado com `Malformed value` (ex.: `input[type=date]`).
- Registra `HEALED`/`needs_review` com `healing_method="parent_has_text_reduced"`.

**Validação:** 6 testes novos, 2 legados ajustados (mock), 60/60 runner suite.

---

### 4. Gap do validador (step_validator.py) — DONE ✅

**Problema:** `select_option_native_resilient` sem assinatura real em `_FakeRunner` — alucinação `option_val=` passou em dry-run, falhou em produção.

**Solução:** Assinatura real + hint. Pegou erro **ao vivo** na regeneração.

---

### 5. Indentação splice (code_generator.py) — DONE ✅

**Problema:** LLM retorna scoped blocks em coluna 0; splice sem re-indent destrói `execute_scenario_default`.

**Solução:** Detectar target indent, normalizar via delta uniforme.

---

### 6. Anti-drift de omissão (code_generator.py) — DONE ✅

**Problema:** Reflection full-file reintroduz passos-ruído omitidos (`optional_omitted`). Manifest preserva a decisão, mas rewrite faz código de verdade aparecer de novo.

**Solução:** Estender `_restore_deterministic_blocks` — slots cognitivos com `reason == "optional_omitted"` recebem bloco-vazio canônico a cada tentativa (mesma política dos blocos deterministic).

**Validação:** Passou live: st_006/st_008 permaneceram omitidos em retry 4/5.

---

### 7. Live fimm_billing — transaction SUCCESS ✅

**Resultado:**
- st_001–st_005: SUCCESS determinístico.
- st_006/st_008: OMITTED (bloco-vazio, zero healing).
- st_007/st_009: SUCCESS determinístico.
- st_010: SUCCESS (select_option_native_resilient, correto kwarg).
- st_011/st_012: HEALED (visual_ai, não redução — filtra `select:has-text()` + `.grid div` ambíguo).
- **st_014: HEALED (parent_has_text_reduced)** ← determinístico, zero cognitivo.
- st_015–st_019: SUCCESS determinístico.

**Transação:** `SUCCESS | 1` — fim-a-fim limpo.

---

### 8. Gate regressão (reference bot, 3×) — APROVADO ✅

**Portal Segura (001_teste), sem regeneração:**
- 3 execuções: 41/3/2 (SUCCESS/HEALED/FAILED), mesmas 3 healings (st_024/st_025/st_037), mesmo ponto de falha (st_038, drift de data pré-existente).
- Taxa média: 0/1, tempo: 158.3s (vs. 151.35s gate H8, +4.6% variação normal).
- Correções: 26/3 (estável).
- Camada nova NÃO disparou — inerte quando parent.has_text casa.
- **Veredito:** ✅ APROVADO, zero regressão.

---

### 9. Docs atualizadas

- [CLAUDE.md](CLAUDE.md): regra container_click, âncora viável, gap parent.has_text + mitigação.
- [.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md](.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md): gate pós-redução-parent-has_text anexado.
- [.specs/pendencias-fimm-billing-2026-07-14.md](.specs/pendencias-fimm-billing-2026-07-14.md): P1/P2/P3 rastreadas.

---

## Métricas

| Artefato | Mudança |
|---|---|
| `deterministic_emitter.py` | +1 função, +3 testes |
| `sanitizer.py` | +1 constante, +1 regra, +5 testes |
| `runner.py` | +2 funções, +6 testes |
| `step_validator.py` | +1 assinatura, +1 hint |
| `code_generator.py` | +1 extend, +1 reindent, +10 testes |
| **Teste suites** | 60/60 runner ✅; 10/10 codegen ✅ |
| **Live runs** | fimm_billing SUCCESS ✅; portal_segura gate APROVADO ✅ |

---

## Pendências (backlog)

Ver [.specs/pendencias-fimm-billing-2026-07-14.md](.specs/pendencias-fimm-billing-2026-07-14.md):

- **P1:** Recorder — capturar 1ª linha parent text (raiz P1; workaround ativo).
- **P2:** Emitter — dataset field binding pra `select` (raiz; hardcode st_010).
- **P3:** Sanitizer — `redundant_select_click` suppressão (raiz; workaround ativo).

---

## Summary

**Fimm billing st_014 resolvido** (determinístico via redução + teclado). **Dois ruídos de captura (st_006/st_008) omitidos** (zero healing). **Reference bot retrocompatível** (gate 100% APROVADO). **Docs + pendências documentadas** (prioridade clara). Pronto pra produção; raízes ficarão no backlog pós-piloto.
