# Pendências — Piloto Fimm Finance Billing Engine (2026-07-14)

Achados durante a sessão de melhorias de precisão (st_006/st_008 omitidos, st_014 recuperado). Prioritário: raiz vs. workaround.

## P1: Recorder captura innerText de container cruzando fronteira de elemento

**Raiz:**  `recorder.substring(0, 40)` do parent.has_text grava texto multi-linha colapsado em espaços (ex.: `"Valor de Liquidação (R$) BRL Vencimento "`), irrecuperável a jusante. Playwright `:has-text()` nunca casa texto cruzando fronteira.

**Impacto:** st_014 fallback (`fill_chained` com parent.has_text=0 match) roda a cada execução. Com mitigação (redução de tokens), cai pra determinístico; sem ela, derruba pra cognitivo.

**Workaround (ativo):**  `_reduce_parent_has_text` + teclado fallback em runner.py (2026-07-14) — validado live fimm_billing, gate regressão aprovado, exigência CHILD único previne ambiguidade.

**Fix na origem:** Recorder (`aegis_blackbox/recorder.py`) — na captura de `parent.has_text`, extrair só primeira linha (antes do `\n` do innerText), sem truncamento.

**Impacto da correção:** Só vale pra re-gravações futuras; bots compilados antes continuam com texto multi-linha truncado. Após fix + re-gravação, `plano_execucao.json` novo usaria `execution_hint: "required"` (text viável), st_014 emitido deterministic (zero healing).

**Timing:** Pós-fimm, quando houver nova gravação piloto em site similar (fimm ou cliente novo).

---

## P2: Hardcoded option_text em st_010

**Achado:**  Code generator emitiu `option_text="1"` hardcoded em st_010 (`select_option_native_resilient`), devia ser `row.get("cliente_selecionado", "")`.

**Raiz:** Plano gravado com `text="1"` (o valor que o usuário selecionou durante gravação). Emitter (`deterministic_emitter.py`) não distingue valor gravado de dataset field — emite literal.

**Impacto:** Bot funciona só se dataset linha 1 tem `cliente_selecionado="1"`; qualquer outro valor falha.

**Fix:** Pós-sanitização, quando o passo de `select` tem `text` igual a um valor literal (números, valores de enum conhecidos), emitter deve:
1. Checar se existe field no dicionário com mesmo nome do `target_description` ou parte dele ("cliente" → "cliente_selecionado").
2. Se existe, emitir `row.get(field, "texto_default")` em vez do literal.
3. Se não existe, emitir o literal como warning em `sanitization_notes`.

**Timing:** Próxima geração (requer check novo em emitter ou step_validator).

---

## P3: st_011 e st_012 ruído de captura (healing contínuo)

**Achado:** 
- st_011: clique redundante em `<select>` pós-`select_native` (seletor `select:has-text('Selecione um cliente...')` — o placeholder quando select ainda tá vazio). Sempre falha em visibilidade/ação, healing visual consegue ~90% das vezes.
- st_012: clique em `div` dentro de `.grid` (seletor `.grid >> form .grid div`) — ambíguo (6+ matches no DOM), always healing, nunca determinístico.

**Raiz:** Recorder capturou passos que não têm efeito de negócio (UI ruído entre ações reais). Sanitizer classifica como `confidence < 70`, mas ainda emite como `required` porque o passo tem um selector/ação válida.

**Workaround (ativo):** st_011/st_012 marcados como `optional` no plano via regra container_click (baixa confiança em tags genéricas) ou check novo. LLM omite na geração de st_014 porque tem `container_click` em `sanitization_notes`.

**Fix (raiz):** Sanitizer — expandir a regra container_click ou criar regra novo `redundant_select_click` (clique em `select` logo após `select_option`/`select_option_native`, mesmo selector) para marcar como `sup_` (suppressão completa, não `optional`) com `step_role="redundant_select_click"`. Reduz plan noise pra gerador.

**Timing:** Próxima geração/re-sanitização que incluir esse projeto.

---

## Status de cada item

| # | Impacto | Workaround | Fix raiz | Prioridade | Timing |
|---|---|---|---|---|---|
| P1 | Alto (healing a cada execução de gravação velha) | ✅ Ativo (runner reduction layer) | Recorder — 1ª linha text | M | Re-gravação futura |
| P2 | Alto (bot falha com dataset ≠ valor capturado) | ❌ Nenhum (hardcode permanente) | Emitter/validator — dataset field binding | H | Próxima geração |
| P3 | Médio (healing ~90%, ainda caro) | ✅ Ativo (container_click rule omit) | Sanitizer — `redundant_select_click` suppressão | M | Próxima sanitização |

---

## Referências

- Achado P1 + workaround: [.specs/plano-execucao-st014-parent-has-text.md](.specs/plano-execucao-st014-parent-has-text.md) (probe + design)
- Workaround ativo (P1/P3): [aegis_runner/runner.py](aegis_runner/runner.py) `_reduce_parent_has_text()` + [aegis_sanitizer/sanitizer.py](aegis_sanitizer/sanitizer.py) `_GENERIC_CONTAINER_CLICK_TAGS`
- Gate regressão: [.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md](.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md) seção "Gate pós-redução-parent-has_text"

---

**Próxima ação:** Priorizar P2 (hardcode) se/quando houver re-geração de fimm ou novo piloto. P1 e P3 ficam em backlog de "raiz" — custo-benefício baixo enquanto workaround funciona.
