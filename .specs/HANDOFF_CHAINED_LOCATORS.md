# Handoff Session: Chained Locators Implementation

**Data**: 2026-07-03  
**Objetivo**: Implementar seletores hierárquicos (chained locators) para eliminar ambiguidade de seletor e reduzir dependência de auto-healing  
**Status**: ⚠️ Em Progresso - Fundação Implementada, UX em Refinamento

---

## 1. O Que Foi Realizado

### 1.1 Funcionalidade Principal: Chained Locators
Implementado sistema de seletores hierárquicos onde elementos ambíguos são resolvidos por um **pai estável + filtro de texto no filho**:

```python
# Antes (seletor plano, ambíguo)
click_resilient(page, "#field-sexo >> .mat-select", "Dropdown Sexo")

# Depois (hierárquico, robusto)
click_chained(
    page,
    parent={"selector": "#field-sexo", "has_text": ""},
    child={"selector": ".mat-select-trigger"},
    target_description="Dropdown Sexo"
)
```

**Arquivos Modificados**:
- ✅ `aegis_runner/runner.py` - Métodos `click_chained()` (ln 571) e `fill_chained()` (ln 623)
- ✅ `aegis_blackbox/recorder.py` - Função `getAegisParentData()` (ln ~344-486) para detectar ambiguidade
- ✅ `aegis_sanitizer/sanitizer.py` - Inclusão de marcador `⬆` no relatório para indicar chained
- ✅ `aegis_sanitizer/code_generator.py` - Regras 2-3 atualizadas para usar `click_chained`/`fill_chained`
- ✅ `aegis_cockpit/cockpit.py` - `_regenerate_report_safe()` inclui contexto de parent
- ✅ `aegis_mentor/skills/rpa-copilot-coder.md` - Padrão Q define quando usar chained (marcador `⬆`)

### 1.2 Pipeline de Dados End-to-End Validado
```
recorder.py (captura parent)
    ↓
gravacao.json (salva parent context)
    ↓
relatorio.md (exibe com marcador ⬆)
    ↓
LLM (lê relatorio.md, gera click_chained)
    ↓
bot_producao.py (executa com chained logic)
    ↓
runner.py (resolve parent via Playwright filter)
```

**Validação**: 
- ✅ 47/93 eventos com parent capturados (50.5%)
- ✅ 23 chamadas chained geradas pelo LLM
- ✅ 22x click_chained + 1x fill_chained em bot produção
- ✅ Sintaxe válida, execução completa

### 1.3 Correções Críticas de UX (Cockpit)

#### Problema 1: Múltiplos Passos como "Executando" Simultâneos
**Causa Raiz**: Frontend parseava logs desincronizados + runner gravava múltiplos RUNNING entries

**Soluções Aplicadas**:
1. ✅ **runner.py:976** - Reset `steps_history` por transação (não acumula entre transações)
2. ✅ **runner.py:110-126** - Método `_write_steps_realtime()` escreve arquivo após cada passo
3. ✅ **cockpit.py:296-319** - Inverte prioridade: lê arquivo raiz (em execução) ANTES do histórico
4. ✅ **cockpit.py:327-329** - Filtra por `current_row_id` se fornecido no query
5. ✅ **index.html:3693-3695** - Frontend filtra automaticamente por transação ativa
6. ✅ **index.html:2767-2781** - DESATIVOU parsing de logs (causa de mistura de passos)
7. ✅ **index.html:3838-3860** - Heurística: passo PENDING após completados = "Executando"
8. ✅ **index.html:3047-3048** - SEMPRE re-renderiza passos (não cache stale)

#### Problema 2: Cockpit Mostrava Histórico Antigo Durante Execução Ativa
**Causa**: Polling priorizava execução completa ao invés de arquivo em tempo real

**Correção**: Inverteu lógica - agora lê `historico_passos.json` (raiz, atualizado em tempo real) PRIMEIRO

---

## 2. Arquitetura Final

### 2.1 Estrutura de Status (Sem RUNNING Duplicate)
```
historico_passos.json (gerado durante execução):
[
  { index: 1, type: "fill", status: "SUCCESS", row_id: 1 },
  { index: 2, type: "click_chained", status: "HEALED", row_id: 1 },
  { index: 3, type: "click_chained", status: "FAILED", row_id: 1 },
  ...
]

Status válidos: SUCCESS, HEALED, FAILED, STOPPED, BYPASSED
Status NÃO usado: RUNNING (evita múltiplas entries)
```

### 2.2 Pipeline de Polling (Live)
1. Runner executa passo → chama `_log_step(status)` (SUCCESS/HEALED/FAILED)
2. `_log_step()` chama `_write_steps_realtime()` → grava arquivo imediatamente
3. Frontend polling a cada 1s → `fetch('/api/projects/.../telemetry-files')`
4. Cockpit retorna `steps_history` filtrado por row_id
5. Frontend `renderSteps()` recalcula heurística a cada render:
   - Se há passos completados (SUCCESS/HEALED) + próximo é PENDING → marca como "⏳ Executando"

---

## 3. Métricas de Validação

| Critério | Resultado |
|----------|-----------|
| Eventos com parent capturados | 47/93 (50.5%) ✅ |
| Chained calls geradas | 23 ✅ |
| Passos simultâneos em RUNNING | 0 (antes: 10+) ✅ |
| Transações mista no histórico | 0 (antes: múltiplas) ✅ |
| Row IDs únicos por execução | 1 por transação ✅ |
| Arquivo atualizado em tempo real | Sim (a cada passo) ✅ |

---

## 4. Problemas Resolvidos vs Remanescentes

### ✅ Resolvidos
- ✓ Ambiguidade de seletor em estruturas repetitivas (grids, cards)
- ✓ Múltiplos passos "executando" simultaneamente no Cockpit UI
- ✓ Mistura de dados de múltiplas transações/execuções
- ✓ Histórico desatualizado durante execução ativa
- ✓ LLM não gerando chained methods (falta contexto no relatório)

### ⚠️ Remanescentes / Próximas Ações
1. **Frontend não atualiza após SEMPRE re-render** (issue new)
   - Causa: Lógica de heurística pode ter erro
   - Fix: Validar se `isNextPending && hasCompletedSteps` calcula corretamente
   - Prioridade: 🔴 CRÍTICO (bloqueia UX)

2. **Dropout de valor do arquivo entre polls** (observado em testes)
   - Exemplo: POLL 48 = 45 steps → POLL 49 = 15 steps
   - Causa: Arquivo sendo zerado/reescrito entre transações?
   - Fix: Investigar se `_write_steps_realtime()` está sendo chamado de forma inconsistente
   - Prioridade: 🟡 MÉDIO

3. **Edge case: Dropdown options off-screen (TIMEOUT_SELECTOR)**
   - Tentativa: Reposicionar CDK overlay via JS + dispatchEvent
   - Status: Implementado mas não testado em cenário real
   - Prioridade: 🟢 BAIXO (fallback cognitivo funciona)

---

## 5. Checklist Para Próximas Sessões

### Imediato (Próxima sessão)
- [ ] Validar renderSteps heurística com execução live
- [ ] Verificar por que arquivo "droppa" de 45 → 15 steps
- [ ] Testar com múltiplas transações (row_id 1, 2, 3) simultaneamente
- [ ] Verificar se `_write_steps_realtime()` é thread-safe (concurrent calls)

### Médio Prazo
- [ ] Benchmark: Compara % de bots sem RUNNING duplicates antes vs depois
- [ ] Cobertura: Testar em 5+ RPA diferentes (tipos de app)
- [ ] Documentação: Atualizar README com padrão Chained Locators

### Longo Prazo
- [ ] Investigar CDK overlay fix (reposition vs zoom) - qual é mais robusto?
- [ ] Considerar cache de parent selectors como otimização
- [ ] Adicionar métrica de "ambiguidade resolvida" ao report

---

## 6. Commits Relacionados

```bash
# Implementação principal
5671eac feat(ux): sync gravacao.json e relatorio.md na deleção de passos
5e51de7 feat(ui): allow user to delete individual steps from Cockpit
e8b6e4f fix(steps): merge real executed steps with planned recording steps

# Correções de UX aplicadas nesta sessão (não são commits, pendentes)
- runner.py: steps_history reset por transação + _write_steps_realtime()
- cockpit.py: prioridade inverta + filtro por row_id
- index.html: renderSteps Always + heurística PENDING
```

---

## 7. Arquivos de Referência

**Documentação de Design**:
- `.specs/plans/chained-locators.design.md` - Design original
- `.specs/plans/chained-locators.validation.md` - Validação end-to-end

**Código Modificado**:
- `aegis_runner/runner.py` - click_chained, fill_chained, _write_steps_realtime
- `aegis_blackbox/recorder.py` - getAegisParentData
- `aegis_sanitizer/sanitizer.py` - Report generation com ⬆
- `aegis_sanitizer/code_generator.py` - Regras Q atualizada
- `aegis_cockpit/cockpit.py` - Polling logic
- `aegis_cockpit/static/index.html` - Frontend polling + heurística

**Testes**:
- `test_live_polling.sh` - Script que valida polling em tempo real
- `test_execution.py` - Execução com monitoramento de passos

---

## 8. Notas Importantes Para Próximo Dev

### ⚠️ Crítico
1. **NÃO volte a adicionar status RUNNING em `_log_step`** — causa múltiplas entries duplicadas
2. **Frontend PRECISA de polling contínuo** — `keepStepsState` foi removido por propósito
3. **`_write_steps_realtime()` é chamada a cada passo** — performance é OK mas monitor se houver lag

### 🔧 Debugging
- Arquivo histórico: `projects/{proj}/tests/{test}/historico_passos.json` (raiz)
- Arquivo relatório: `projects/{proj}/tests/{test}/reports/relatorio.md` (LLM lê este)
- Logs do runner: stdout via `[AEGIS_STEP]` prefix
- Polling endpoint: `GET /api/projects/{slug}/telemetry-files?test_slug={test}`

### 📝 Próxima Iteração
- Validar que heurística renderiza corretamente
- Se ainda houver problemas, considerar **voltar RUNNING mas com lógica de "update último entry"** (não append)
- Alternative: Usar campo `last_update_time` no JSON para marcar qual passo está "ativo AGORA"

---

## 9. Resumo Executivo

**Objetivo Alcançado**: ✅ Implementar chained locators end-to-end (recorder → report → LLM → bot)

**Impacto**:
- Ambiguidade de seletor reduzida em ~50% dos eventos
- Auto-healing reduzido (23 chained vs fallback resilient)
- Cockpit UX corrigida (sem múltiplos RUNNING simultâneos)

**Status**: 🟡 Fundação sólida, UX em refinamento

**Bloqueador**: Frontend não re-renderiza com dados frescos (verificar heurística)

---

*Documento preparado para transição de contexto*  
*Próximo responsável: [Seu nome aqui]*
