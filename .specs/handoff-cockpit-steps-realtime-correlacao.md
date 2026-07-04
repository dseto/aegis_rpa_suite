# Handoff: Correlação de Passos Planejados + Status em Tempo Real (Cockpit)

**Data**: 2026-07-03
**Status**: ✅ Resolvido nesta sessão
**Arquivos alterados**: `aegis_cockpit/static/index.html`

Continuação de `HANDOFF_COCKPIT_REALTIME_UPDATE_BUG.md` — aquele handoff resolveu a
escrita/leitura do `historico_passos.json`, mas deixou 3 problemas de UX que esta
sessão corrigiu.

---

## 1. Painel de passos do Cockpit não atualizava durante a execução

**Sintoma**: `renderSteps()` só era chamado a partir de `loadTelemetryData()`, e essa
função só era re-chamada quando `pollLogs()` detectava `data.running === false`
(fim do processo). Durante a execução (`data.running === true`), nada disparava
novo fetch — o painel de passos ficava congelado no snapshot inicial.

**Fix**: `pollLogs()` (linha ~2793) agora, enquanto `data.running === true`, chama
`loadTelemetryData(activeProjectSlug, true, currentSelectedVersion)` a cada 2 ticks
(~1.6s, throttle via `stepsPollCounter`) para reler o `historico_passos.json` fresco.

```js
let stepsPollCounter = 0;
// dentro de pollLogs():
if (data.running) {
    stepsPollCounter++;
    if (stepsPollCounter % 2 === 0 && activeProjectSlug) { ... loadTelemetryData(...) }
} else {
    stepsPollCounter = 0;
}
```

---

## 2. Aba Histórico mostrava `undefined` no lugar do ID do passo

**Causa raiz**: `historico_passos.json` grava o campo `step_id` (string, ex.
`"3"`), não `index`. O painel live (`renderSteps`) já tinha fallback silencioso
(`s.index || idx + 1` → posição no array), então "funcionava" por acidente
(número de posição, não o `step_id` real). O painel de Histórico
(`showHistoryTransactionSteps`, linha ~4356) lia `step.index` sem fallback →
`undefined`.

**Fix**: normalizado em 2 lugares para preferir `step_id` real:
- `renderSteps()` (linha ~3711): `const stepId = s.step_id ?? (s.index || idx+1)`
- `showHistoryTransactionSteps()` (linha ~4356): mesmo fallback na exibição.

---

## 3. Passos com `step_id` prefixado `auto_` apareciam como passo real

**Causa raiz**: `runner.py:_log_step()` faz fallback `step_id or f"auto_{n}"`
quando: (a) `step_id=None` é passado explicitamente (diagnóstico de falha sem
passo do plano associado, ex. `cognitive_fallback` diagnosticando erro genérico),
ou (b) o `step_id` informado não bate com nenhum passo do plano carregado (bug
potencial de dessincronia `plano_execucao.json` × `bot_producao.py`).

Essas entradas não são passos reais do fluxo e não devem contar/aparecer na UI.

**Fix**: filtradas na origem dos dados, antes de qualquer consumidor:
- `activeHistorySteps` (linha ~4782, alimenta aba Histórico)
- `stepsHistory` dentro de `renderSteps()` (linha ~3706, painel live)

```js
.filter(s => !(typeof s.step_id === 'string' && s.step_id.startsWith('auto_')))
```

**Nota para o futuro**: entradas `auto_*` continuam gravadas no
`historico_passos.json` em disco (não removidas do runner) — só ficam ocultas na
UI. Se o volume de `auto_*` por bug de dessincronia de plano crescer, vale a pena
fazer `runner.py` logar um aviso mais alto (`⚠️`) diferenciando os dois casos
(diagnóstico esperado vs. step_id não encontrado no plano) em vez de tratar os
dois igual.

---

## 4. Heurística "próximo passo executando" marcava TODOS os pendentes

**Sintoma**: após qualquer passo com status final, todo passo `PENDING`
subsequente (não só o próximo) era classificado como `⏳ Executando` — porque a
condição `isNextPending && hasCompletedSteps` era avaliada independentemente
para cada índice do loop, sem impedir múltiplos matches.

**Fix**: cálculo do índice do primeiro pendente movido para FORA do loop
(`updateStepsUI()`, linha ~3845) — `firstPendingAfterActivity` é calculado uma
única vez (primeiro passo pendente logo após o último com atividade
SUCCESS/HEALED/FAILED/RUNNING) e só esse índice recebe o status "Executando".

---

## Estado Final

- Painel Cockpit (execução ativa): atualiza a cada ~1.6s, mostra 1 único passo
  "Executando" por vez, numeração usa `step_id` real.
- Aba Histórico: numeração usa `step_id` real, sem `undefined`, sem entradas
  `auto_*` de diagnóstico.

## Não coberto nesta sessão

- `runner.py` ainda não diferencia nos logs o motivo do `auto_*` (diagnóstico vs.
  bug de dessincronia). Ver nota na seção 3.
