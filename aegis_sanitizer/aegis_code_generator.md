# 🛡️ Aegis Code Generator (Fase 4) - Documentação Técnica e Funcional

Este documento fornece uma especificação técnica e funcional detalhada do módulo **Aegis Code Generator** (`aegis_sanitizer/code_generator.py`). O público-alvo deste documento são arquitetos de soluções RPA, engenheiros de software e desenvolvedores que mantêm ou estendem o framework.

---

## 📖 1. Visão Geral e Propósito

O **Aegis Code Generator** é a quarta fase do pipeline do **Aegis RPA Suite**. Ele atua como um compilador cognitivo (baseado em Large Language Models) encarregado de traduzir a telemetria física compactada e as regras de negócio em scripts de automação Python/Playwright estáticos, robustos e altamente resilientes.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                                  FASE DE DESIGN                                │
│                                                                                │
│  ┌─────────────────┐     ┌───────────────────┐     ┌────────────────────────┐  │
│  │ 1. Aegis        │     │ 2. Aegis          │     │ 3. Dataset             │  │
│  │    BlackBox     ├────►│    Sanitizer      ├────►│    Validator           │  │
│  │   (Gravador)    │     │  (Sanitização)    │     │   (Validação Dados)    │  │
│  └─────────────────┘     └─────────┬─────────┘     └───────────┬────────────┘  │
│                                    │                           │               │
│                                    ▼                           ▼               │
│                            plano_execucao.json         dataset_inicial.json    │
│                            relatorio.md                dicionario.json         │
│                                    │                           │               │
│                                    └─────────────┬─────────────┘               │
│                                                  │                             │
│                                                  ▼                             │
│                                    ┌────────────────────────┐                  │
│                                    │ 4. Aegis Code          │                  │
│                                    │    Generator (Este)    │                  │
│                                    └─────────────┬──────────┘                  │
└──────────────────────────────────────────────────┼─────────────────────────────┘
                                                   ▼
                                    ┌────────────────────────┐
                                    │ bot_producao.py        │
                                    │ skills_lib.py          │
                                    └──────────────┬─────────┘
                                                   │
                                                   ▼
                                     FASE DE PRODUÇÃO (RUN-TIME)
                                    ┌────────────────────────┐
                                    │ 5. Aegis Runner        │
                                    │   (Execução Estática)  │
                                    └────────────────────────┘
```

### Filosofia de Design
* **Separação Design-Time vs. Run-Time:** A inteligência artificial (LLM) atua exclusivamente na fase de design para gerar e corrigir o código do robô. Em produção, o robô opera de forma determinística (estática) usando o SDK do Aegis (`TransactionRunner`), minimizando a latência de rede, custos de token e falhas de conexão.
* **Anti-Hallucination & Enforcements:** O gerador de código possui uma barreira rigorosa de validação via Árvore de Sintaxe Abstrata (AST) e execução experimental (Dry Run) em sandbox para garantir que a LLM nunca introduza erros de sintaxe ou desvios de arquitetura.
* **Alteração Cirúrgica (Karpathy Style):** No ciclo de correções, o gerador não reescreve o robô inteiro; ele edita apenas os blocos específicos de código associados aos passos falhos, eliminando a regressão de passos funcionais.

---

## 🏗️ 2. Arquitetura de Dados e Integração

O Code Generator é executado de forma standalone ou orquestrado pelo **Aegis Cockpit**. Ele consome cinco insumos essenciais do projeto e produz três saídas.

### Insumos (Inputs)
1. **`plano_execucao.json`:** Lista sequencial dos passos mapeados (ID, seletor, tipo de ação, propriedades físicas, coordenadas e regras).
2. **`dicionario.json`:** Dicionário de dados mapeando chaves semânticas às colunas de entrada, incluindo estratégias de preenchimento (`fill_strategy`).
3. **`relatorio.md`:** Relatório de telemetria humana detalhado gerado pelo Sanitizer.
4. **`dataset_inicial.json` (ou `.csv`):** Arquivo de dados de entrada que alimentará o loop transacional.
5. **`rpa-copilot-coder.md`:** O manual ou *playbook* contendo os 18 padrões de resiliência recomendados pelo Aegis para escrita de robôs.

### Saídas (Outputs)
1. **`code/bot_producao.py`:** Script Python principal do robô estruturado sob a classe `TransactionRunner`.
2. **`code/skills_lib.py`:** Biblioteca contendo as sub-rotinas e tarefas de negócio reutilizáveis (ex: login, navegação inicial) compiladas separadamente.
3. **`code/index_arquivos.json`:** Manifesto JSON listando a data de geração e metadados dos arquivos de código produzidos.

---

## ⚙️ 3. Recursos Principais e Modos de Operação

O comportamento do gerador é controlado pela classe `CodeGeneratorService`. Ele possui os seguintes modos e algoritmos de execução:

### A. Fluxo de Geração Nova (`_generate_new_code`)
Invocado quando o robô (`bot_producao.py`) não existe ou quando o projeto requer uma compilação do absoluto zero. Desde 2026-07 este fluxo é **híbrido por padrão** (`AEGIS_CODEGEN_HYBRID=true`) — ver Seção 3.5. A LLM só recebe o playbook completo, o plano de execução inteiro e a telemetria no caminho **full-LLM legado** (flag desligada, projeto com `skills_used`, plano ausente, ou fallback de tentativa); no caminho híbrido, ela só vê os *slots cognitivos* (Seção 3.5), nunca o arquivo inteiro.

### B. Fluxo de Correção Cirúrgica (`_surgical_correct`)
Quando o robô já existe e o sistema detecta que há correções pendentes (`correcoes_acumuladas.json`), o gerador ativa o modo de correção localizada.

1. **Detecção de Âncoras:** O gerador divide o script Python em blocos lógicos delimitados por comentários formatados como `# [PASSO X] Descrição`.
2. **Análise de Escopo (`_build_scoped_edit_plan`):** Mapeia quais `step_id`s do plano de execução precisam de alteração (seja por falha nas correções pendentes ou por erros de validação sintática da tentativa anterior).
3. **Substituição Cirúrgica (`_surgical_correct_scoped`):** Envia para a LLM apenas o trecho do código correspondente aos blocos problemáticos com um contexto mínimo (bloco anterior e posterior somente leitura). O retorno da LLM é reinserido cirurgicamente no código existente via substituição de linhas. O resto do arquivo permanece 100% inalterado.
4. **Fallback:** Caso as âncoras estejam ambíguas ou ausentes, o gerador recua automaticamente para a correção do arquivo inteiro.

### C. Compilação de Skills Reutilizáveis
Se a gravação original (`gravacao.json`) contiver eventos com a ação `call_skill`, o Code Generator:
1. Localiza a pasta da skill correspondente (`skills/<skill_slug>/`).
2. Lê seu `skill.json` (metadados e assinatura de parâmetros), `relatorio.md` e `dicionario.json`.
3. Invoca a LLM para compilar uma função Python independente com a assinatura `run_skill_<slug>(page, parameters..., runner)`.
4. Grava-a na biblioteca compartilhada `skills_lib.py` e injeta as regras de importação no prompt do robô principal.

---

## 🧬 3.5 Geração Híbrida (Determinística + Cognitiva) — default desde 2026-07

A LLM é o gargalo de custo/latência/alucinação da Fase 4 mesmo em passos 100% mecânicos (um `click` cujo seletor, tipo e binding de dataset já são deriváveis sem ambiguidade do próprio plano). O motor híbrido inverte a relação entre validador e gerador: em vez de a LLM escrever tudo e o `step_validator.py` cobrar o padrão depois, um novo módulo — `aegis_sanitizer/deterministic_emitter.py` — **emite** o padrão diretamente a partir do plano, e a LLM só é chamada para os passos onde resta julgamento real.

### A. Classificação por passo — linha de corte C1-C10 (`classify_step`)

Para cada step emitível do plano, `classify_step` decide `deterministic`, `cognitive` ou `omit` (`sup_`/`skip`, nunca vira código) aplicando dez condições conservadoras, na ordem:

| # | Condição | Efeito se disparar |
|---|---|---|
| C1 | Tipo de step fora de `{click, fill, select, select_native}` | `cognitive` |
| C2 | `execution_hint == "skip"` → `omit`; `execution_hint == "optional"` → decisão de emitir é da LLM | `omit` / `cognitive` |
| C3 | Padrão Q — `parent.has_text_original` presente ou `sanitization_notes` cita Padrão Q/`has_text` | `cognitive` |
| C4 | Binding ambíguo — `fill`/`select_native` sem exatamente 1 casamento de chave no dicionário via `selector`/`selector_original`; `select` sem exatamente 1 via `trigger_selector` | `cognitive` |
| C5 | `weak_selector: true` sem seletor encadeado/`has_text` para ancorar | `cognitive` |
| C6 | Padrão N — seletor de menu suspenso a dividir em `Pai >> Filho` | `cognitive` |
| C7 | Projeto tem `skills_used` não vazio — condição **global**, decidida pelo chamador (`_generate_new_code`) antes de invocar `build_skeleton`, não por `classify_step` | rota inteira cai para full-LLM |
| C8 | Step é alvo de `pending_corrections` (direto ou via `required_reopen.after_step_id`) | `cognitive` |
| C9 | `fill` cujo próximo step emitível é um `click` em painel de autocomplete (lookahead calculado pelo chamador, nunca pelo `classify_step`) | `cognitive` |
| C10 | Valor de negócio (`observed_value` do dicionário) embutido literalmente no seletor/`has_text` — anti-hardcode | `cognitive` |

Um step `deterministic` é escrito diretamente por `emit_step_block` (sem chamada de LLM); um `cognitive` vira um placeholder no arquivo:
```python
# [PASSO N] <descrição do passo>
# AEGIS_COGNITIVE_SLOT step_id="st_014" motivo="<razão da classificação>"
pass
```
`build_skeleton` monta o arquivo inteiro (todos os blocos determinísticos + placeholders) e o manifest de proveniência (Seção 3.6). A LLM recebe, numa única chamada, **só** os slots cognitivos da geração atual (`_render_hybrid_slots_context`), e responde no formato delimitado `# BEGIN_STEP st_XXX` / `# END_STEP st_XXX` — um par por `step_id` alvo, splicado de volta no esqueleto.

`AEGIS_CODEGEN_FORCE_LLM_STEPS` (CSV de `step_id`s) permite rebaixar manualmente qualquer step para cognitivo mesmo que `classify_step` o classificasse como determinístico — útil para depuração pontual sem mexer no plano.

### B. Padrão Q dinâmico (C3) — a regra anti-hardcode mais violada na prática

Quando um step cai em C3, o prompt do slot **prescreve** (não sugere) composição dinâmica: se o literal residual de `has_text` contém um ou mais `observed_value` do dicionário, a LLM DEVE compor via f-string com `row.get("<chave>", "")` para cada chave casada, preservando o texto estático residual (ex.: `"FIPE"`) como literal na mesma f-string — nunca reemitir o literal gravado tal como está. `step_validator.py` reforça isso com um erro dedicado: `HARDCODED_PARENT_HAS_TEXT` (distinto de `MISSING_PARENT_HAS_TEXT` — modo de falha oposto) dispara quando `parent.has_text_original` está presente e o `has_text` do plano contém um `observed_value` como substring, mas o código emitido usa o literal (match exato ou embutido no seletor) em vez de `row.get(...)` dinâmico. O `detail` do erro nomeia as chaves candidatas derivadas ou degrada para uma mensagem genérica quando o match é ambíguo (dois `observed_value` iguais, ex. `'2026'` podendo ser `ano_modelo` ou `ano_fabricacao`) ou vazio.

### C. Manifest de proveniência (`code/generation_manifest.json`)

Toda geração bem-sucedida (híbrida ou full-LLM) grava `code/generation_manifest.json` ao lado do bot:

```json
{
  "generator_version": "hybrid-1",
  "plan_checksum": "sha1...",
  "steps": {
    "st_010": {"provenance": "deterministic", "reason": "C1-C9 nenhuma disparou", "block_sha1": "..."},
    "st_062": {"provenance": "cognitive", "reason": "C3: Padrão Q"},
    "st_023": {"provenance": "cognitive_patched", "reason": "correção QA cirúrgica aplicada sobre bloco originalmente deterministic"}
  }
}
```

* `generator_version`: `"hybrid-1"` ou `"full-llm"` — a rota full-LLM **sempre sobrescreve** o manifest com `steps: {}`, então um manifest híbrido obsoleto nunca sobrevive a uma regeneração não-híbrida.
* `plan_checksum`: sha1 do plano usado nesta geração — uma re-sanitização que renumera `step_id`s degrada qualquer lógica dirigida por manifest a um no-op em vez de misfire contra um mapa obsoleto.
* `provenance` por step: `deterministic`, `cognitive`, ou `cognitive_patched` (quando uma correção cirúrgica QA posterior toca um bloco originalmente emitido determinístico).
* `CognitiveGateway.is_active()` continua exigido no início de toda geração, mesmo quando o plano vai resolver para zero slots cognitivos — o híbrido economiza chamadas de LLM, não a exigência de API key/gateway.

### D. Política anti-drift no Ralph Loop (`_restore_deterministic_blocks`)

Dentro de cada tentativa do Ralph Loop, blocos `deterministic` que caem **fora** do escopo da correção/reflection atual são re-splicados na sua forma canônica (`_restore_deterministic_blocks` + `_compute_restore_target_scope`) antes de revalidar — isso impede que uma reflection full-file "melhore" (ou corrompa) silenciosamente um bloco que já estava correto por construção. Falhas de conteúdo em um bloco recém-restaurado são fail-fast; falhas de ordem/contagem (`STEP_ID_MISMATCH` etc.) não interrompem a restauração.

**Guard de `lineno` órfão:** se um erro do diff atual tem `lineno`/`linenos` mas nenhum bloco `# [PASSO N]` conhecido cobre essa linha (ex.: erro na assinatura de `execute_scenario_default`, que fica fora de qualquer bloco de passo), o cálculo de escopo sinaliza `scope_incomplete=True` e força fallback de **arquivo inteiro** nessa tentativa — em vez de ficar preso reenviando só os `step_id`s conhecidos para sempre sem nunca corrigir o erro real (achado durante o gate H8, retry 3 do backlog híbrido).

---

## 🛡️ 4. O Ciclo de Auto-Reflexão e Validação (Ralph Loop)

Para garantir resiliência e integridade do robô final, o Code Generator opera em um loop de retroalimentação ativa de até **N** tentativas (configurado em `AEGIS_CODEGEN_MAX_RETRIES`, padrão `5`), conhecido como **Ralph Loop**.

```
   ┌──────────────────────────────────────────────────────────┐
   │ 1. Obter Prompt de Geração / Correção                    │
   └──────────────────────────┬───────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ 2. Chamada da API de LLM (CognitiveGateway)              │
   └──────────────────────────┬───────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ 3. Validação Sintática (Python Compile + AST Check)       │
   └──────────────────────────┬───────────────────────────────┘
                              │ Falhou (Erro Sintático)
                              ├──────────────────────────────────────┐
                              │ Passou                               │
                              ▼                                      │
   ┌──────────────────────────────────────────────────────────┐      │
   │ 4. Normalização Determinística de Boilerplate            │      │
   └──────────────────────────┬───────────────────────────────┘      │
                              │                                      │
                              ▼                                      │
   ┌──────────────────────────────────────────────────────────┐      │
   │ 5. Validação Estrutural (Proíbe classes/asyncio/open)    │      │
   └──────────────────────────┬───────────────────────────────┘      │
                              │ Falhou (Erro Estrutural)             │
                              ├──────────────────────────────────────┤
                              │ Passou                               │
                              ▼                                      │
   ┌──────────────────────────────────────────────────────────┐      │
   │ 6. Validação de Plano e Padrões (Wait, Select, Chained)  │      │
   └──────────────────────────┬───────────────────────────────┘      │
                              │ Falhou (Desvio do Plano)             │
                              ├──────────────────────────────────────┤
                              │ Passou                               │
                              ▼                                      │
   ┌──────────────────────────────────────────────────────────┐      │
   │ 7. Dry Run Executivo (Compilação & Import em Sandbox)    │      │
   └──────────────────────────┬───────────────────────────────┘      │
                              │ Falhou (Erro Runtime/Imports)        │
                              ├──────────────────────────────────────┤
                              │ Passou                               │
                              ▼                                      │
               ┌──────────────────────────────┐                      │
               │   SUCESSO! Grava o Bot       │                      │
               └──────────────────────────────┘                      │
                                                                     │
   ┌──────────────────────────────────────────────────────────┐◄─────┘
   │ 8. Reflection Engine (_surgical_correct_with_reflection) │
   │    • Coleta mensagens de erro                            │
   │    • Extrai recortes do código falho                     │
   │    • Incrementa tentativa e refaz prompt                 │
   └──────────────────────────┬───────────────────────────────┘
                              │
                              ▼
               Retorna ao passo 2 (Max 5 vezes)
```

### Mecanismos de Validação do Ralph Loop

1. **Validação Sintática (`_validate_syntax`):**
   * Executa o interpretador em modo de compilação rápida `compile(code, "<string>", "exec")`.
   * Realiza um *AST parsing* para garantir que o retorno não seja uma estrutura de dados literal (ex: dicionário ou JSON cru encapsulado em markdown).
2. **Validação Estrutural (`validate_bot_structure`):**
   * Proíbe a criação de classes customizadas de runner (ex: `class ResilientRunner`).
   * Proíbe o uso de chamadas de loop assíncrono como `async def` e `asyncio.run()`.
   * Proíbe o gerenciamento manual do browser e do Playwright.
   * Restringe imports espúrios do namespace `aegis_runner`.
3. **Validação de Conformidade do Plano (`validate_bot_against_plan`):**
   * Garante que todos os `step_id` definidos como obrigatórios no plano de execução estejam instanciados no código do robô.
   * Enforça a ordenação linear dos passos de acordo com o plano original.
4. **Validação de Nomes de Campos (`validate_dataset_field_names`):**
   * Rastreia expressões `row.get("campo")` ou `row["campo"]` via análise AST e confere se a chave declarada existe no dicionário semântico do projeto.
5. **Validação de Padrões de Resiliência (`validate_resilience_patterns`):**
   * Enforça a substituição de `.click()` e `.fill()` nativos do Playwright pelos métodos resilientes do SDK (`runner.click_resilient`, `runner.fill_resilient`).
   * Enforça a utilização de seletores encadeados (`_chained`) ou filtros de ancoragem textual (`:has-text(...)`) para passos marcados com `weak_selector: true`.
   * Garante a declaração obrigatória de coordenadas físicas (`original_coords`) se documentadas na telemetria.
6. **Validação de Invariantes de Feedback (`validate_required_wait_patterns` etc.):**
   * Verifica se as esperas de transição e reabertura explícitas especificadas no histórico de falhas (`correcoes_acumuladas.json`) foram corretamente incorporadas ao código gerado.
7. **Dry Run Executivo (`dry_run_bot`):**
   * Executa o robô em um processo sandbox isolado com um stub do Playwright. Este teste estático/dinâmico de runtime valida a presença de variáveis indefinidas (`NameError`), falhas de tipagem (`TypeError`) ou falhas ocultas de importação de submódulos.

---

## 🛠️ 5. Correções Determinísticas Automáticas

Determinadas correções mecânicas não requerem uma nova iteração da LLM, o que economiza tempo de processamento e reduz o risco de novas alucinações. O Code Generator intercepta o código e aplica correções via AST/texto:

* **Correção de Métodos Alucinados:** Se a LLM chamar um método inexistente no runner (ex: `runner.select_native_resilient`), mas houver apenas um candidato próximo no SDK (ex: `runner.select_option_native_resilient`), o gerador substitui a chamada diretamente usando análise de similaridade (`difflib.get_close_matches`).
* **Instanciações Espúrias:** Se a LLM instanciar múltiplos `TransactionRunner` dentro do escopo de funções (o que geraria erro de inicialização), o método `_strip_stray_transaction_runner_calls` varre a AST e remove os nós duplicados.
* **Reordenação de Passos:** Se os passos gerados possuírem os IDs corretos, mas estiverem fora da sequência do plano de execução, o método `reorder_steps_to_match_plan` reordena as instruções no nível da AST.
* **Assinatura de `execute_scenario_default`:** Se `_validate_scenario_function_signature` reportar `INVALID_SCENARIO_SIGNATURE`/`WRONG_SCENARIO_PARAM_ORDER` e os nomes de parâmetro da LLM forem exatamente `{page, row, runner}` (só a ordem errada, sem `*args`/`**kwargs`/defaults), `_rewrite_scenario_signature_to_canonical` reescreve a assinatura via AST para `(page, row, runner)` sem nova chamada de LLM. Nomes alienígenas (a LLM inventou outro nome) não disparam o autofix — cai para o fluxo normal de correção.

---

## 📝 6. Padrões de Normalização de Boilerplate

Para manter o robô compatível com a orquestração externa e com execuções manuais locais, o gerador sobrescreve as seções estáticas do script através do método `_normalize_boilerplate`.

Imports e bootstraps de sistema são injetados de forma padronizada no cabeçalho do arquivo:
```python
import os
import sys
import time
from playwright.sync_api import Page

current_dir = os.path.dirname(os.path.abspath(__file__))
AEGIS_SUITE_ROOT = current_dir
while AEGIS_SUITE_ROOT and not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):
    parent = os.path.dirname(AEGIS_SUITE_ROOT)
    if parent == AEGIS_SUITE_ROOT:
        break
    AEGIS_SUITE_ROOT = parent

if not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):
    global_path = r"C:\Projetos\aegis_rpa_suite"
    if os.path.exists(global_path):
        AEGIS_SUITE_ROOT = global_path

if AEGIS_SUITE_ROOT not in sys.path:
    sys.path.insert(0, AEGIS_SUITE_ROOT)

from aegis_runner.runner import TransactionRunner
```

O bloco principal de execução (`__main__`) é reconstruído dinamicamente na parte inferior do arquivo, lendo seletores de erros personalizados configurados no `project.json` do robô:
```python
if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) == "code" else current_dir

    runner = TransactionRunner(project_dir=project_dir, error_message_selector=".toast-error, .alert-danger")
    runner.register_scenario(scenario_name="default", callback=execute_scenario_default)
    runner.run()
```

---

## ⚙️ 7. Manual de Operação e Variáveis de Configuração

### Variáveis do Sistema (.env)
O gerador de código requer as seguintes variáveis configuradas no ambiente do projeto ou do framework para ativação do motor de IA:

* `AEGIS_COGNITIVE_ENABLED`: Define se a geração de código via IA está ativa (`true`).
* `AEGIS_COGNITIVE_API_KEY`: Chave de autenticação do provedor de LLM.
* `AEGIS_COGNITIVE_PROVIDER`: Identificador do provedor (ex: `openrouter` ou `litellm`).
* `AEGIS_COGNITIVE_MODEL`: Modelo principal de IA (ex: `google/gemini-2.5-flash`).
* `AEGIS_COGNITIVE_CODER_MODEL` (Opcional): Modelo focado especificamente na escrita de código.
* `AEGIS_CODEGEN_MAX_RETRIES` (Opcional): Limite de tentativas no Ralph Loop (padrão `5`).
* `AEGIS_DEBUG_DUMP_BOT` (Opcional): Caminho do arquivo para salvar dumps de depuração durante tentativas falhas.
* `AEGIS_CODEGEN_HYBRID` (Opcional, padrão `true`): ativa a geração híbrida determinística+cognitiva (Seção 3.5). `false` força o fluxo full-LLM legado (arquivo inteiro sempre por LLM).
* `AEGIS_CODEGEN_FORCE_LLM_STEPS` (Opcional): CSV de `step_id`s a rebaixar manualmente para cognitivo mesmo que `classify_step` os classificasse como determinísticos.

### Interface de Linha de Comando (CLI)
Para compilar o código de um robô manualmente pelo terminal, execute:
```powershell
python aegis_sanitizer/code_generator.py --project-dir <caminho_do_projeto>
```
* **Exemplo:** `python aegis_sanitizer/code_generator.py --project-dir projects/portal_segura/tests/001_teste`

---

## 🔍 8. Diagnóstico de Falhas Comuns e Soluções

A tabela abaixo compila as principais falhas identificadas no processo de geração, sua origem e o procedimento de correção recomendado.

| Erro Apresentado | Causa Provável | Procedimento de Correção |
|---|---|---|
| **`SyntaxError: O código gerado é apenas uma estrutura de dados...`** | A LLM retornou um JSON ou dicionário bruto no lugar do script Python executável. | Ajuste o prompt ou reduza a temperatura/parâmetros do modelo no gateway cognitivo. |
| **`FAIL: HALLUCINATED_RUNNER_METHOD`** | A LLM inventou um método que não pertence ao SDK (ex: `runner.input_text`). | Verifique se o método pretendido possui equivalência na lista `RUNNER_METHODS` e atualize o playbook de resiliência. O framework corrige digitações leves automaticamente. |
| **`FAIL: STEP_ID_MISMATCH`** | Os IDs de passos no código diferem do `plano_execucao.json` ou a ordem linear está desalinhada. | O gerador reordena os passos automaticamente. Caso o passo esteja ausente, o Ralph Loop reitera informando o ID esperado. |
| **`FAIL: MISSING_REQUIRED_WAIT`** | A LLM removeu um `time.sleep` ou espera explícita requerida por uma correção pendente anterior. | O gerador injetará o erro no próximo prompt do Ralph Loop e o modo cirúrgico atuará diretamente no passo falho para reinserir a espera. |
| **`ValueError: time data ... does not match format`** | A LLM inventou uma formatação ou parse de data sem evidência. | O playbook enforça o uso do `observed_value` bruto sem conversões. Certifique-se de que os dados do dataset correspondem ao formato do formulário. |
| **`FAIL: EXTRA_STEPS`** | A LLM adicionou interações extras baseando-se em colunas extras do dataset. | Delete o bloco extra. O gerador proíbe a criação de passos não mapeados originalmente no `plano_execucao.json`. |
| **`FAIL: HARDCODED_PARENT_HAS_TEXT`** | Um step de Padrão Q (C3) foi emitido com o literal gravado em `parent.has_text` em vez de composição dinâmica `row.get(...)` — regride para valor de negócio fixo (mesmo bug em qualquer regeneração com dataset de 2+ linhas). | O `detail` do erro nomeia as chaves candidatas; a correção cirúrgica reenvia o slot com a prescrição Q-a (Seção 3.5-B). |
| **`EXTRA_STEPS` inesperado num ciclo cirúrgico após um `required_reopen` já resolvido** | A tolerância de `EXTRA_STEPS` a um step `*_reopen` (`step_validator.py`, `planned_set_for_reopen`) só vale enquanto a correção `required_reopen` que o originou está em `pending_corrections`. Assim que ela é marcada `applied`/`resolved`, o bloco reopen sai da lista de exceções e qualquer ciclo QA subsequente mirando OUTRO step falha imediatamente. Gap conhecido, fora do escopo do gerador híbrido (achado no gate H8, retry8). | Evitar rodar ciclo cirúrgico QA com um reopen `applied` ainda no arquivo; ou re-derivar a tolerância a partir dos blocos de fato presentes no bot em vez do status da correção (correção estrutural não implementada). |
