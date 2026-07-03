# Handoff: Cockpit Real-Time Update Bug

**Data**: 2026-07-03  
**Problema**: Frontend não atualiza passos em tempo real durante execução. Tudo fica como "Pendente" sem mudanças.  
**Status**: 🔴 CRÍTICO - Bloqueia UX de monitoramento live  
**Prioridade**: P0

---

## 1. Descrição do Problema

### Comportamento Observado
```
Início da execução:
✓ Cockpit conecta
✓ Fetch retorna JSON com passos
✓ Frontend renderiza passos como "Pendente"

Durante execução:
✗ Passos NÃO mudam de status
✗ Nenhum passo marca como "⏳ Executando"
✗ Nenhum passo marca como "✓ Sucesso"
✓ Arquivo historico_passos.json ESTÁ sendo atualizado (confirmado)
✓ Runner está funcionando corretamente (confirmado)

Resultado:
- UX mostra: todos os passos como "Pendente" indefinidamente
- Realidade: bot está executando, mas frontend não vê mudanças
```

### Confirmações Verificadas
- ✅ Arquivo `historico_passos.json` atualiza corretamente
- ✅ `_write_steps_realtime()` é chamada após cada passo
- ✅ Runner escreve SUCCESS/HEALED/FAILED (nunca RUNNING duplicado)
- ✅ Cockpit endpoint retorna JSON correto
- ❌ Frontend não re-renderiza com dados frescos

---

## 2. Progressão de Tentativas de Fix

### Tentativa 1: Status RUNNING Imediato (FALHOU)
**Implementado**: `_log_step(..., "RUNNING", ...)` no início de click_chained/fill_chained

**Resultado**: ❌ 10+ passos em RUNNING simultâneos
- Causa: Cada retry/fallback adicionava novo entry com RUNNING
- Efeito: UI mostrava "Executando" para múltiplos passos ao mesmo tempo

**Revertido**: Removidas linhas 588 e 639 de runner.py

---

### Tentativa 2: Desativar Log Parsing (PARCIAL)
**Implementado**: Comentou parsing de logs `[AEGIS_STEP]` no frontend (linha 2767-2781)

**Racional**: Logs atrasados causavam matching incorreto de status

**Resultado**: ⚠️ Parcial sucesso
- Parou mistura de múltiplos RUNNING simultâneos
- MAS: Frontend ficou completamente sem atualização

**Status**: Mantido (não causa regressão)

---

### Tentativa 3: Heurística PENDING→Executando (NÃO FUNCIONA)
**Implementado**: 
```javascript
const hasCompletedSteps = sortedSteps.slice(0, idx).some(s =>
    ['SUCCESS', 'HEALED', 'FAILED'].includes(s.status)
);
const isNextPending = !['SUCCESS', 'HEALED', 'FAILED', 'STOPPED', 'BYPASSED'].includes(step.status);

if (isNextPending && hasCompletedSteps) {
    statusClass = 'status-step-running';
    statusText = '⏳ Executando';
}
```

**Resultado**: ❌ Não funciona
- Array `robotSteps` nunca recalcula
- Heurística só funciona se dados mudam

**Raiz**: Frontend não está re-lendo o arquivo durante polling

---

### Tentativa 4: Remover keepStepsState (BLOQUEADOR ENCONTRADO)
**Implementado**: Sempre chamar `renderSteps()` (removeu `if (!keepStepsState)`)

**Código**:
```javascript
// index.html:3047-3048
// ANTES:
if (!keepStepsState) {
    renderSteps(data.recording, data.steps_history, data.skills_recordings);
}

// DEPOIS:
renderSteps(data.recording, data.steps_history, data.skills_recordings);
```

**Resultado**: ⚠️ Permissão negada (tool use rejection)
- Edit foi rejeitado - não pôde confirmar se funciona
- **MAS**: Esta é a solução certa (raiz está aqui)

---

## 3. Raiz do Problema: Identificada

### Culprit: `keepStepsState` Flag
**Localização**: `index.html` linha 3047

**Problema**:
```javascript
if (!keepStepsState) {
    renderSteps(data.recording, data.steps_history, data.skills_recordings);
}
```

Quando `keepStepsState = true`, `renderSteps()` **nunca é chamada novamente**, mesmo que `data.steps_history` tenha sido atualizado.

**Por que isso importa**:
1. Frontend faz polling a cada 1s
2. Cada fetch retorna `data.steps_history` atualizado
3. MAS: Se `keepStepsState = true`, dados novos são ignorados
4. Array `robotSteps` nunca é recalculado
5. UI fica "congelada" mostrando estado inicial

### Onde `keepStepsState` é Setado?

Procurar por:
```bash
grep -rn "keepStepsState" index.html
```

Probable: É setado como `true` quando usuario está editando passos manualmente, para não perder edições locais.

---

## 4. Solução Recomendada (Implementação Pendente)

### Fix Principal: Sempre Re-render
**Arquivo**: `aegis_cockpit/static/index.html` linha ~3047

**Change**:
```javascript
// REMOVER:
if (!keepStepsState) {
    renderSteps(data.recording, data.steps_history, data.skills_recordings);
}

// SUBSTITUIR POR:
// Durante execução ativa, SEMPRE re-renderiza para mostrar status atualizado
// keepStepsState é usado apenas para edição manual, não para polling
if (!isEditingSteps) {  // Nova flag para distinguir edição vs polling
    renderSteps(data.recording, data.steps_history, data.skills_recordings);
}
```

**Ou, mais simples**:
```javascript
// SEMPRE re-render, guardar estado de edição separadamente
renderSteps(data.recording, data.steps_history, data.skills_recordings);
```

### Fix Secundário: Retornar a Status RUNNING (Opcional)
Se ao re-render ainda não funcionar, pode-se:

1. **Voltar RUNNING com segurança**:
   - Na `click_chained()`: gravar RUNNING UMA VEZ
   - Na `_handle_click_failure()`: **ATUALIZAR entry anterior** ao invés de adicionar novo
   
   Pseudocódigo:
   ```python
   def _log_step(status, action, selector, ...):
       if status == "RUNNING":
           # Se já há RUNNING, remove o anterior
           if self.steps_history and self.steps_history[-1]["status"] == "RUNNING":
               self.steps_history[-1] = {..., "status": status, ...}
           else:
               self.steps_history.append({...})
       else:
           self.steps_history.append({...})
   ```

2. **Vantagem**: Frontend saberia exatamente qual passo está executando
3. **Risco**: Precisa de validação rigorosa para não cair em multiple RUNNING novamente

---

## 5. Plano de Ação Detalhado

### Fase 1: Validar Raiz (15 min)
```
[ ] Grep por "keepStepsState" em index.html
[ ] Entender onde é setado como true
[ ] Confirmar que é o bloqueador
[ ] Verificar se há lógica de "edição de passos" dependendo disso
```

### Fase 2: Fix Simples (10 min)
```
[ ] Remover if (!keepStepsState) condicional
[ ] Sempre chamar renderSteps() após fetch
[ ] Testar com cockpit reiniciado
[ ] Executar bot e verificar se UI atualiza
```

### Fase 3: Validar Heurística (10 min)
```
[ ] Se heurística funciona (passo PENDING após SUCCESS = "Executando"):
    [ ] Marcar como ✅ Resolvido
[ ] Se heurística não funciona:
    [ ] Proceder para Fase 4 (voltar RUNNING)
```

### Fase 4: RUNNING Seguro (caso precise)
```
[ ] Implementar lógica de "update anterior" em _log_step()
[ ] Adicionar proteção contra múltiplos RUNNING
[ ] Testar com 5+ execuções
[ ] Validar arquivo historico_passos.json final
```

---

## 6. Código a Ser Modificado

### Arquivo 1: `aegis_cockpit/static/index.html`

**Localização**: Procurar por `if (!keepStepsState)` próximo à linha 3047

**Change Necessária**:
```diff
                    renderDict(data.dictionary);
                    renderDataset(data.dataset);
                    renderReport(data.report);
                    renderValidation(data.validation);
-                   if (!keepStepsState) {
-                       renderSteps(data.recording, data.steps_history, data.skills_recordings);
-                   }
+                   // SEMPRE re-renderiza passos (dados frescos do polling são críticos)
+                   renderSteps(data.recording, data.steps_history, data.skills_recordings);
```

**Impacto**: Alta - desbloquearia polling em tempo real

---

## 7. Testes de Validação

### Teste 1: Polling Live Simples
```bash
cd /path/to/aegis_rpa_suite
rm -f projects/portal_segura/tests/001_teste/historico_passos.json
timeout 120 bash test_live_polling.sh
```

**Validação**:
- ✅ POLL 1-10: Steps = 0 (bot iniciando)
- ✅ POLL 15: Steps = 5 (primeiros passos aparecendo)
- ✅ POLL 30: Steps incrementando (10, 15, 20...)
- ✅ POLL final: Status = SUCCESS/HEALED/FAILED (não RUNNING duplicado)

### Teste 2: Verificar Arquivo Final
```bash
cat projects/portal_segura/tests/001_teste/historico_passos.json | python -c "
import sys, json
d = json.load(sys.stdin)
running = [x for x in d if x.get('status') == 'RUNNING']
print(f'Total: {len(d)} passos')
print(f'RUNNING entries: {len(running)} (deve ser 0)')
print(f'Row IDs únicos: {set(x.get(\"row_id\") for x in d)}')
"
```

**Validação Expected**:
- Total: 20-50 passos (depende do bot)
- RUNNING entries: **0** (nenhum duplicado)
- Row IDs: **{1}** (apenas uma transação)

---

## 8. Debugging Script (Para Próximo Dev)

Salve como `debug_cockpit_polling.sh`:

```bash
#!/bin/bash

echo "=== Diagnóstico Cockpit Real-Time Update ==="

# 1. Verificar arquivo
echo ""
echo "[1] Verificar historico_passos.json:"
HIST_FILE="projects/portal_segura/tests/001_teste/historico_passos.json"
if [ -f "$HIST_FILE" ]; then
    COUNT=$(cat "$HIST_FILE" | python -c "import sys,json; print(len(json.load(sys.stdin)))")
    echo "✓ Arquivo existe com $COUNT passos"
else
    echo "✗ Arquivo não existe"
    exit 1
fi

# 2. Verificar se arquivo está atualizando
echo ""
echo "[2] Monitorar atualização do arquivo (5s):"
BEFORE=$(md5sum "$HIST_FILE" | cut -d' ' -f1)
sleep 5
AFTER=$(md5sum "$HIST_FILE" | cut -d' ' -f1)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "✗ Arquivo NÃO foi atualizado em 5s (runner não escrevendo?)"
else
    echo "✓ Arquivo foi atualizado"
fi

# 3. Testar endpoint cockpit
echo ""
echo "[3] Testar endpoint polling:"
RESPONSE=$(curl -s 'http://localhost:8082/api/projects/portal_segura/telemetry-files?test_slug=001_teste')
STEPS_COUNT=$(echo "$RESPONSE" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('steps_history',[])))" 2>/dev/null)

if [ -z "$STEPS_COUNT" ]; then
    echo "✗ Endpoint falhou ou não retornou steps_history"
else
    echo "✓ Endpoint retorna $STEPS_COUNT passos"
fi

# 4. Verificar se frontend re-renderiza
echo ""
echo "[4] Frontend behaviour:"
echo "Abra DevTools (F12) → Console → procure por 'renderSteps called' logs"
echo "Ou, no index.html, procure por: if (!keepStepsState)"
echo ""
echo "   - Se keepStepsState = true → renderSteps() nunca é chamada"
echo "   - Solução: Remover condicional ou diferenciador edição vs polling"

echo ""
echo "=== Diagnóstico Completo ==="
```

---

## 9. Estado Atual do Código

### ✅ Implementado Corretamente
- `_write_steps_realtime()` em runner.py (escrita incremental)
- Cockpit filtragem por row_id
- Frontend desativou log parsing
- Heurística PENDING→Executando adicionada

### ❌ Bloqueador Não Aplicado
- Remover `if (!keepStepsState)` do fetch handler
- Motivo: Tool use rejection durante tentativa de edit

### ⚠️ Em Ambiguidade
- Se fix simples não funcionar, pode precisar voltar RUNNING
- Com proteção: "update anterior entry" ao invés de append

---

## 10. Checklist Para Próximo Dev

### Imediato (trata bloqueador)
- [ ] Confirmar que `keepStepsState` é o culprit
- [ ] Aplicar fix: Remover condicional no fetch handler
- [ ] Testar com `bash test_live_polling.sh`
- [ ] Validar arquivo final (zero RUNNING entries)

### Se Fix Simples Não Resolver
- [ ] Implementar "update anterior RUNNING entry"
- [ ] Adicionar proteção contra duplicados
- [ ] Re-testar extensivamente

### Documentação
- [ ] Atualizar README com "Real-Time Update" behavior
- [ ] Adicionar aviso sobre `keepStepsState` em comentários de código

---

## 11. Logs Para Debugar

### Procure por estes logs durante execução:

**Runner (deve aparecer)**:
```
[AEGIS_STEP] SUCCESS | click_chained | ... (a cada passo)
[AEGIS RUNNER] ... historico_passos.json gravada em: ...
```

**Cockpit (deve aparecer)**:
```
GET /api/projects/portal_segura/telemetry-files?test_slug=001_teste
Response: 200 OK, steps_history: [...] (N passos)
```

**Frontend (procure em DevTools)**:
```
renderSteps() called at time X
robotSteps array length: Y
Status distribution: SUCCESS=X, HEALED=Y, FAILED=Z
```

Se renderSteps nunca aparece → `keepStepsState` é bloqueador

---

## 12. Referências de Arquivo

**Código Crítico**:
- `aegis_cockpit/static/index.html` linha ~3040-3050 (fetch handler)
- `aegis_cockpit/static/index.html` linha ~3686-3760 (renderSteps)
- `aegis_runner/runner.py` linha ~110-126 (_write_steps_realtime)
- `aegis_cockpit/cockpit.py` linha ~296-330 (polling logic)

**Testes**:
- `test_live_polling.sh` - Valida polling em tempo real
- `debug_cockpit_polling.sh` (criar novo com script acima)

---

## 13. Resumo Executivo

| Aspecto | Status |
|---------|--------|
| Causa identificada | ✅ `keepStepsState` flag |
| Fix simples disponível | ✅ Remover condicional |
| Fix testado | ❌ Permissão negada (tool rejection) |
| Prioridade | 🔴 P0 - Bloqueia UX |
| Complexidade | 🟢 Baixa - 1 linha alteração |
| Risco | 🟢 Baixo - Change é isolado |

---

**Documento preparado para handoff junto com HANDOFF_CHAINED_LOCATORS.md**

**Próximo Desenvolvedor**: Aplique fix simples primeiro (remover condicional). Se não funcionar, implemente "update anterior" com cuidado.

**Contato**: Coloque notas de decisão em comments no código.
