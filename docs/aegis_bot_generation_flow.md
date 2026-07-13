# 🛡️ Fluxo de Processo: Geração e Execução do Bot Aegis (Fase 4 e 5)

Este documento descreve detalhadamente o pipeline de processamento do **Aegis RPA Suite**, a partir do acionamento cognitivo via Large Language Model (LLM) até a execução estática do robô em produção.

---

## 🏗️ 1. Arquitetura Geral do Pipeline

O pipeline do Aegis é composto por fases bem definidas para garantir a estabilidade e a corretude do robô:

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
│                                    │    Generator (LLM)     │                  │
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

### Filosofia Core: Separação de Responsabilidades
* **Design-Time (Cognitivo/Não-determinístico):** A IA atua na fase de design compilando a telemetria em scripts de automação.
* **Run-Time (Determinístico/Estático):** Em produção, o robô opera de forma estática usando o SDK do Aegis (`TransactionRunner`), eliminando latências de rede e custos de IA.

---

## ⚙️ 2. O Ciclo do Aegis Code Generator (Fase 4)

Quando a geração de código é acionada:

### Passo A: Mapeamento de Entradas
O gerador lê:
1. `plano_execucao.json`: Seletores físicos e ações.
2. `dicionario.json`: Mapeamento de campos às chaves semânticas de dados.
3. `dataset_inicial.json`: Estrutura do payload de dados.
4. `rpa-copilot-coder.md`: O playbook com os 18 padrões de resiliência.

### Passo B: Determinação do Escopo
* **Nova Geração:** Gera todo o script `bot_producao.py` e bibliotecas `skills_lib.py` a partir do zero — hoje bifurcada entre o motor híbrido determinístico (padrão) e o fluxo full-LLM legado (fallback), ver Passo B.1.
* **Correção Cirúrgica (Karpathy Style):** Se o bot já existe e possui erros identificados, o gerador localiza os comentários `# [PASSO N]` e altera cirurgicamente apenas os blocos com falhas, preservando os passos corretos.

### Passo B.1: Geração Nova — Bifurcação Híbrido vs. Full-LLM

```
plano_execucao.json + dicionario.json carregados
                    │
                    ▼
   AEGIS_CODEGEN_HYBRID=false ?
   OU skills_used não vazio ?      ──── sim ────┐
   OU plano ausente ?                            │
                    │ não                        ▼
                    ▼                    FLUXO FULL-LLM (legado)
   classify_step(step) por step        arquivo inteiro pedido
   do plano — C1 a C10                 à LLM numa única chamada,
   (deterministic_emitter.py)          sem emissor determinístico
        │            │
        ▼            ▼
  "deterministic"  "cognitive" / "omit"
        │            │
        ▼            ▼
  emit_step_block   placeholder parseável
  (zero LLM)        # AEGIS_COGNITIVE_SLOT
        │            step_id="..." motivo="..."
        └──────┬─────┘
               ▼
     há slots cognitivos no skeleton?
     não → zero chamadas LLM
     sim → UMA chamada LLM cobrindo só os slots
               │
               ▼
     resposta não cobre todos os slots,
     ou splice inválido?
       sim → fallback full-LLM (mesma tentativa)
       não → segue
               │
               ▼
     code/generation_manifest.json gravado
     (provenance por step_id + plan_checksum)
               │
               ▼
     Passo C (Ralph Loop) — pipeline existente, inalterado
```

`aegis_code_generator/deterministic_emitter.py` é a inversão de `step_validator.py`: onde um validador só *rejeita* a ausência de um padrão de resiliência, o emissor *produz* esse padrão mecanicamente. `classify_step` aplica dez condições conservadoras por step — tipo suportado (`click`/`fill`/`select`/`select_native`), binding único e não-ambíguo no `dicionario.json`, ausência do token dinâmico do Padrão Q, `weak_selector` com material de ancoragem, fora da heurística de menu suspenso do Padrão N, sem correção pendente mirando o step, `fill` que não precede um autocomplete/painel de opção dinâmica, e nenhum valor de negócio do dicionário embutido no seletor — qualquer condição não satisfeita classifica o step como `cognitive` (dúvida sempre cai para a LLM). Steps `sup_`/`skip` são sempre `omit` (nunca viram código).

### Passo C: O Ciclo de Auto-Reflexão (Ralph Loop)
A LLM não pode introduzir bugs sintáticos ou desvios de arquitetura. O código proposto passa por validações antes de ser consolidado (limite de 5 tentativas):

1. **Validação Sintática:** Compilação com `compile()` + AST check.
2. **Validação Estrutural:** Proibição de classes customizadas, loops assíncronos (`asyncio`) e gerência manual de browsers.
3. **Validação de Conformidade:** Confirma que todos os `step_id` obrigatórios estão presentes em ordem linear.
4. **Validação de Campos:** Confirma que chamadas `row.get("campo")` possuem colunas válidas no dataset.
5. **Dry Run Executivo:** Execução estática/dinâmica em sandbox isolado com stub do Playwright.

> **Feedback de Erro (Reflection Engine):** Se qualquer validação falhar, o erro exato e a seção do código com problemas alimentam a próxima chamada da LLM.

> **Política anti-drift (bots híbridos):** antes de revalidar cada tentativa, uma etapa determinística restaura incondicionalmente a forma canônica de qualquer bloco `deterministic` (via `generation_manifest.json`) que esteja fora do escopo da correção corrente — impede que uma reescrita de arquivo inteiro na fase de reflection altere silenciosamente um bloco que já estava correto por construção.

### Passo D: Normalização Determinística AST e Gravação
1. **Substituição de Métodos:** Substitui nomes de métodos alucinados baseados em similaridade de strings.
2. **Injeção de Boilerplate:** Insere cabeçalhos padronizados de paths e importação do `TransactionRunner`.
3. **Bootstrap:** Escreve a função `if __name__ == "__main__"` configurando tratamento de exceções do cockpit.
4. **Persistência:** Grava `code/bot_producao.py`, `code/skills_lib.py` e (rota híbrida) `code/generation_manifest.json`.

---

## 🚀 3. Execução em Produção: Aegis Runner (Fase 5)

Uma vez gerado, o bot opera de forma autônoma:
1. **Inicialização:** O `TransactionRunner` lê a configuração de seletores de erro locais do `project.json`.
2. **Processamento em Loop:** Itera sobre as transações de `dataset_inicial.json`.
3. **Resiliência Nativa:** Utiliza o SDK embarcado para realizar cliques resilientes (`click_resilient`), preenchimentos humanos (`fill_human_like`), e auto-healing local de overlays de tela.
4. **Status Reporting:** Envia os status `SUCCESS` ou `BUSINESS_BLOCKED` para o console/cockpit para cada transação e salva screenshots em caso de erros no browser.
