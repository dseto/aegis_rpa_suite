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
Invocado quando o robô (`bot_producao.py`) não existe ou quando o projeto requer uma compilação do absoluto zero. A LLM recebe o playbook completo, o plano de execução, os metadados do dicionário e a telemetria, sintetizando a lógica linear das interações na função `execute_scenario_default`.

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
