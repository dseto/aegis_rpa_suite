# Handoff: Pipeline de Passos Determinístico

**Data**: 2026-07-03
**Sessão**: Brainstorm + Planejamento + Implementação
**Branch**: main

---

## Objetivo

Criar correlação precisa entre passos planejados e executados no Aegis RPA Suite, garantindo que o robô execute exatamente o que foi planejado, na ordem correta, com rastreabilidade completa.

## O que foi feito

### 4 arquivos modificados + 1 novo

| Arquivo | Mudança |
|---------|---------|
| `aegis_sanitizer/sanitizer.py` | Adicionado `_write_execution_plan()` — gera `plano_execucao.json` ao final da sanitização |
| `aegis_runner/runner.py` | `step_id` obrigatório em 6 métodos, carregamento do plano, estados PENDING/RUNNING/SUCCESS/FAILED/STOPPED, `_mark_remaining_stopped()`, `[AEGIS_STEP]` com step_id |
| `aegis_sanitizer/code_generator.py` | Prompt exige `step_id`, Ralph Loop com validação AST (máx 3 tentativas), `_surgical_correct_with_reflection()`, `_extract_failing_snippets()`, gateway armazenado como `self.gateway` |
| `aegis_sanitizer/step_validator.py` | **NOVO** — Validador AST: `extract_step_ids_from_code()` e `validate_bot_against_plan()` |

### Não mexido (fora do escopo)

- `aegis_cockpit/` — integração com `plano_execucao.json` é follow-up
- `aegis_mentor/skills/` — catálogo de resiliência inalterado
- Skills (call_skill) — TODO para futuro
- `test_runner_integration.py` — precisa ser atualizado para nova API com step_id

---

## Como funciona

### Fluxo completo

```
Sanitizer
  └─→ gera plano_execucao.json (step_id st_001, st_002, ...)

Code Generator
  └─→ lê plano, injeta no prompt LLM
  └─→ gera bot_producao.py com step_id em cada chamada
  └─→ valida via AST (step_validator.py)
  └─→ se falhar: Ralph Loop com reflexão (máx 3x)
  └─→ se passar: escreve bot

Runner
  └─→ carrega plano_execucao.json
  └─→ inicializa steps_history com PENDING
  └─→ executa bot, atualiza status in-place
  └─→ escreve historico_passos.json com todos os estados
```

### Novo arquivo: plano_execucao.json

```json
{
  "version": "1.0",
  "test_dir": "001_teste",
  "generated_at": "2026-07-03T16:06:46",
  "total_steps": 93,
  "steps": [
    {
      "step_id": "st_001",
      "type": "fill",
      "selector": "#username",
      "description": "Preencher o e-mail de login"
    }
  ]
}
```

### Bot gerado esperado

```python
runner.fill_resilient(
    selector="#email",
    target_description="Preencher email",
    step_id="st_001",
    value=row.get("email", "")
)
```

### Estados de passo

| Estado | Significado |
|--------|-------------|
| PENDING | No plano, ainda não iniciado |
| RUNNING | Em execução |
| SUCCESS | Executado com sucesso |
| HEALED | Executado via auto-healing |
| FAILED | Falhou |
| STOPPED | Não alcançado (transação abortou) |

---

## Decisões de design

- **step_id**: `st_001`, `st_002`, ... (3 dígitos zero-padded)
- **Validação**: AST estática (compara step_id, ordem, contagem — não compara tipo de método)
- **Correção**: Ralph Loop com auto-reflexão (LLM vê histórico de erros anteriores)
- **Modelo**: `AEGIS_COGNITIVE_CODER_MODEL` (o mais poderoso)
- **Cenários**: cada test folder = 1 robô independente, 100% linear
- **Backward compat**: bots antigos descartados, sem migração
- **Skills**: fora do escopo (TODO)

---

## Verificação

Testes executados:
- ✅ `step_validator.py`: 6 testes passaram (extract, validate, missing, wrong order, no plan, no steps)
- ✅ `sanitizer.py`: gerou `plano_execucao.json` com 93 passos do projeto `portal_segura/001_teste`
- ✅ Todos os 4 arquivos: sintaxe Python válida
- ✅ Importações cross-module: funcionando

## Pendências

1. Atualizar `aegis_runner/test_runner_integration.py` para nova API com `step_id` obrigatório
2. Integrar Cockpit (`cockpit.py` + `index.html`) para ler `plano_execucao.json` como fonte dos passos
3. Implementar expansão de Skills (call_skill → passos inline no plano)
4. Testar end-to-end: sanitize → codegen → run com um projeto real