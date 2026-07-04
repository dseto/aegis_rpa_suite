# Handoff: Ralph Loop Anti-Hallucination Hardening

**Data:** 2026-07-03
**Objetivo da sessão:** garantir que o Ralph Loop (code_generator.py) gere código limpo, compilável, sem erros de referência/sintaxe/alucinação, e que o bot gerado execute até o final sem erros causados pelo código. Verificação exigida via **execução real ao vivo**, não testes estáticos/históricos.

**Projeto de teste usado para verificação:** `projects/portal_segura/tests/004_teste_novo_pipeline` (alvo local `http://localhost:5173/`).

**Resultado final:** bot gerado executa **18/18 passos com sucesso** (`[AEGIS RUNNER] ✅ Execução em lote finalizada com sucesso total!`), confirmado em `reports/historico_passos.json` — todos os passos `SUCCESS` ou `HEALED`, nenhum `FAILED`/`STOPPED`.

---

## Bugs encontrados e corrigidos (nesta sessão + sessão anterior compactada)

### 1. `extract_step_ids_from_code()` usava `ast.walk()` (BFS, não ordem-fonte)
**Arquivo:** `aegis_sanitizer/step_validator.py`
Chamadas de passo dentro de ramos `if/elif/else` em profundidades diferentes saíam fora de ordem, gerando `STEP_ID_MISMATCH` falsos em código já correto. Este era o motivo real do "Ralph Loop nunca converge" da sessão anterior (diagnóstico anterior estava errado).
**Fix:** coleta `(lineno, col_offset, step_id)` e ordena explicitamente por posição; colapsa `step_id` duplicado consecutivo (ramos mutuamente exclusivos de um mesmo passo lógico).

### 2. `reorder_steps_to_match_plan()` abortava sempre (no-op silencioso)
Abortava se qualquer statement top-level não tivesse `step_id` extraível (ex: `cpf_atual = page.locator(...).input_value()`, comum em bots reais).
**Fix:** agrupa statements sem `step_id` junto ao próximo statement que tiver um; só aborta se restarem statements órfãos ao final.

### 3. Hallucinação de nomes de campo do dataset
Bot usava `row.get("email_acesso")`, `row.get("nome_completo")` etc. quando as chaves reais em `dicionario.json` eram `email_login`, `nome_cliente` etc. Falharia silenciosamente em produção (string vazia, sem exceção).
**Fix:** novo validador `validate_dataset_field_names()` — AST walk em `row.get("...")`, compara contra `dicionario.json["fields"].keys()`.

### 4. `dry_run_bot()` não executava o bloco `if __name__ == "__main__":`
Sandbox testava só `execute_scenario_default(...)`. Kwargs alucinados em `register_scenario()`/`run()`/`TransactionRunner()` (ex: `scenario_id=` em vez de `scenario_name=`) só quebravam na execução real.
**Fix:** segunda passada de `exec()` com `if __name__ == "__main__":` substituído por `if True:`, contra um `_FakeRunner` com assinaturas reais (não `*a, **kw` genérico).

### 5. LLM repetia o mesmo erro de kwarg por 10 tentativas seguidas
`TypeError` puro do Python não sugere nome correto para kwargs não relacionados (ex: `start_page_url`).
**Fix:** hints de assinatura correta injetados na mensagem de erro do dry run para `register_scenario`, `run`, `TransactionRunner`, `fill_resilient`, `click_resilient`, `select_option_resilient`.

### 6. `project_dir` não subia da pasta `code/`
Bot usava `Path(__file__).parent`, resolvendo para `<test_dir>/code/` — mas `dataset_inicial.json` fica em `<test_dir>/`. Invisível a todos os gates porque `dry_run_bot()` não carrega dataset real.
**Fix:** novo validador estrutural `_validate_project_dir_resolution()` — exige que a linha `project_dir = ...` dentro do bloco `__main__` contenha a lógica de subida de pasta (`os.path.basename(current_dir) == "code"`).

### 7. Alucinação de conversão de formato de data
Bot gerava `datetime.strptime(row.get("data_nascimento_cliente"), "%Y-%m-%d")` assumindo ISO, quando o valor real do dataset já estava no formato `dd/mm/aaaa` (igual ao `observed_value` do dicionário) — `ValueError` em runtime.
**Fix duplo:**
- Regra de prompt em `code_generator.py`: proíbe conversão de formato de data sem evidência explícita do `dicionario.json`.
- `dry_run_bot()` passou a carregar a **primeira linha real** de `dataset_inicial.json` (antes usava `{}` vazio — `row.get()` sempre retornava `""` e nunca exercitava `strptime`). Agora esse tipo de bug é pego no sandbox, não na execução real.

### 8. `plano_execucao.json` intercalava passo não-relacionado entre abertura e seleção de dropdown
Passo "abrir dropdown Estado Civil" (st_014) → "preencher e-mail" (st_015, não relacionado) → "selecionar opção Casado(a)" (st_016). No browser real (sem pausas humanas da gravação), clicar no campo de e-mail fechava o overlay do Angular Material antes da opção ser selecionada — falha de negócio, não do código gerado.
**Fix:** `_reorder_dropdown_pairs()` em `aegis_sanitizer/sanitizer.py` — detecta pares abertura/opção com passos intercalados e move o(s) passo(s) intercalado(s) para depois da seleção.

### 9. Seletor ambíguo do campo de Data de Nascimento
`label:has-text('Data de Nascimento') ~ input` casava múltiplos elementos no DOM real, causando fallback para self-healing visual que às vezes não preenchia o input real — bloqueando validação de negócio de passos seguintes (dropdown "Sexo" recusava seleção com data vazia).
**Fix:** seletor trocado para `#field-nascimento input` (escopado pelo container com ID estável) em `dicionario.json`, `plano_execucao.json` e `gravacao.json` do projeto de teste.

---

## Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `aegis_sanitizer/step_validator.py` | Fix ordem BFS→source-order; fix reorder no-op; `validate_dataset_field_names()` novo; `dry_run_bot()` com dataset real + assinaturas reais de todos os métodos do runner + hints de erro; `_validate_project_dir_resolution()` novo |
| `aegis_sanitizer/code_generator.py` | Wiring dos novos validadores no Ralph Loop; regra de prompt anti-alucinação de formato de data; auto-reorder de `STEP_ID_MISMATCH` puro sem gastar tentativa |
| `aegis_sanitizer/sanitizer.py` | `_reorder_dropdown_pairs()` novo, chamado antes de escrever `plano_execucao.json` |
| `README.md` | Nova seção 4.1 documentando o pipeline determinístico de passos |
| `projects/portal_segura/tests/004_teste_novo_pipeline/{dicionario,plano_execucao,gravacao}.json` | Seletor de data corrigido (projeto de teste específico) |

## Regressão

Todas as mudanças em `step_validator.py`/`sanitizer.py` foram re-testadas contra os 3 bots previamente válidos (`001_teste`, `002_teste02`, `003_teste_sem_id`) após cada alteração — zero falsos positivos introduzidos.

## Pendências / não cobertas nesta sessão

- `aegis_runner/test_runner_integration.py` não foi atualizado para a API `step_id` (mencionado em handoff anterior, fora do escopo desta sessão).
- A correção do seletor de data (#9) foi aplicada apenas ao projeto de teste `004_teste_novo_pipeline`. Se outros projetos tiverem o mesmo padrão de seletor ambíguo por `label:has-text(...) ~ input` em campos com container de ID estável, precisam de correção manual equivalente — não há detecção automática genérica desse padrão ainda.
- `_reorder_dropdown_pairs()` usa heurística simples (clique mais próximo anterior que não seja outra opção); não cobre casos com múltiplos dropdowns entrelaçados de forma mais complexa.
