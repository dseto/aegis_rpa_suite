# 🛡️ Aegis DevOps - Documentação Técnica e Funcional

Este documento detalha o funcionamento técnico e arquitetural do módulo **Aegis DevOps** (`aegis_devops`), responsável pelo ciclo de integração contínua (CI), publicação automática de pipelines de execução e sincronização de dados de testes com o Azure DevOps. O público-alvo são arquitetos e desenvolvedores de infraestrutura RPA.

---

## 📖 1. Visão Geral e Propósito

O módulo **Aegis DevOps** estende o framework para fora da máquina local do desenvolvedor, permitindo que robôs gerados sejam empacotados, versionados no Git e orquestrados de forma automatizada. Ele utiliza APIs REST oficiais do Azure DevOps (v7.1) para automatizar a criação de pipelines e planos de testes a partir de definições estáticas do projeto local.

```
┌────────────────────────┐
│ 1. Aegis Cockpit       │
│  (Orquestração Local)  │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ 2. Aegis DevOps        │
│   (Módulo de Push)     │
└───────────┬────────────┘
            │
            ├─────────────── Git Push REST API ────────────────► [ Azure Repos ]
            │                                                      • core + scripts compilados
            │
            ├────────────── Variable Groups API ───────────────► [ Azure Pipelines ]
            │                                                      • variáveis + token mascarado
            │
            └────────────── Test Plans REST API ───────────────► [ Azure Test Plans ]
                                                                   • suite + registros do dataset
```

---

## 🏗️ 2. Arquitetura de Arquivos

O diretório do módulo está estruturado com os seguintes arquivos:

* [__init__.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/__init__.py): Inicialização do módulo.
* [azure-pipelines-template.yml](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/azure-pipelines-template.yml): Template base em formato YAML contendo as etapas do pipeline (instalação de dependências do Python, execução do runner Playwright, captura de evidências e geração de relatório de erros).
* [junit_reporter.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/junit_reporter.py): Conversor de logs de execução para o formato JUnit XML.
* [publish_pipeline.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publish_pipeline.py): CLI orquestradora que lê configurações DevOps locais e dispara a publicação.
* [publisher.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py): Cliente de baixo nível contendo a classe [AzureDevOpsPublisher](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L7) que gerencia as chamadas de API do Azure DevOps.

---

## ⚙️ 3. Análise Detalhada dos Componentes

### A. Tradutor de Testes ([junit_reporter.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/junit_reporter.py))
Este script converte os relatórios de execução do robô (`relatorio_execucao.csv`) em relatórios no formato JUnit XML (`test-results.xml`).

* **Método [convert_csv_to_junit](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/junit_reporter.py#L6):** 
  - Lê linha a linha os resultados das transações.
  - Para cada falha detectada (`FAILED` ou `ERROR`), anexa uma tag `<failure>` descrevendo o campo falho (`failed_field`) e a mensagem de erro do sistema (`error_message`), registrando uma stacktrace.
  - O XML gerado é consumido pelas tarefas nativas de publicação de teste do Azure DevOps, permitindo exibir gráficos de sucesso/falha e falhar a build se houver erros na massa de dados.

### B. O Publicador DevOps ([publish_pipeline.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publish_pipeline.py))
CLI acionada para empacotar e enviar o projeto para a nuvem. Ela realiza as seguintes fases sequenciais:

1. **Leitura da Configuração:** Carrega os dados DevOps do projeto (slug, organização, projeto, repositório, branch, token PAT e cenários a incluir) gerenciados por [ProjectManager](file:///c:/Projetos/aegis_rpa_suite/aegis_cockpit/project_manager.py).
2. **Gerenciamento do Variable Group:** Verifica a existência do grupo de variáveis (`aegis-llm-group`) no Azure DevOps. Se não existir, cria-o com campos de integração cognitiva vazios, forçando a segurança e impedindo o vazamento de chaves locais do desenvolvedor.
3. **Empacotamento de Arquivos:** Agrupa em memória todo o core do framework (`aegis_runner/` e `junit_reporter.py`), os códigos compilados do bot (`bot_producao.py`, `skills_lib.py`) e arquivos de dados (`dicionario.json`, `dataset_inicial.json`).
4. **Mascaramento de Credenciais:** Lê o arquivo `.env` local e substitui valores de chaves de API secretas por variáveis tokenizadas da pipeline (ex: `AEGIS_COGNITIVE_API_KEY=$(AEGIS_COGNITIVE_API_KEY)`).
5. **Geração do YAML Consolido:** Popula a matriz de execução dinamicamente no YAML de pipeline com base nos cenários incluídos.
6. **Git Push REST API:** Dispara um commit atômico enviando todos os arquivos preparados para o Azure Repos.
7. **Registro de Pipeline:** Registra ou atualiza a pipeline no Azure DevOps baseando-se no arquivo YAML gerado.
8. **Sincronização com Azure Test Plans:** Itera sobre a massa de dados (`dataset_inicial.json`) e cria uma hierarquia de testes correspondente.

### C. Cliente de API DevOps ([publisher.py](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py))
Centraliza as chamadas REST utilizando autenticação Basic baseada em Personal Access Token (PAT).

* **Classe [AzureDevOpsPublisher](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L7):**
  - **[push_files](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L41):** Obtém o ID do repositório, busca o head da branch (`objectId`) e realiza um git commit remoto via API Git Pushes, criando ou atualizando arquivos texto/base64 de forma atômica.
  - **[create_or_update_variable_group](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L105):** Cria ou atualiza Variable Groups demarcando automaticamente quais chaves são do tipo `isSecret` para ocultá-las na UI do DevOps.
  - **[create_or_update_pipeline](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L152):** Cria ou obtém a Build Definition do pipeline YAML.
  - **[sync_test_suite_from_dataset](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L293):** Gerencia a sincronização de datasets de forma hierárquica nos planos de teste (Plan → Suite → Test Case). Cada linha do dataset vira um Test Case Work Item estruturado no Azure Boards contendo passos parametrizados em HTML ([create_test_case_work_item](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L244)).
  - **[publish_run_results_from_csv](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/publisher.py#L363):** Cria uma execução de Test Run na nuvem, traduz status do Aegis (`SUCCESS`/`HEALED`/`FAILED`) para status oficiais do Azure DevOps (`Passed`/`Failed`), e publica os resultados finais atrelando-os aos respectivos Test Case IDs.

---

## 🚀 4. Fluxo de Execução da Pipeline DevOps (CI/CD)

O arquivo [azure-pipelines-template.yml](file:///c:/Projetos/aegis_rpa_suite/aegis_devops/azure-pipelines-template.yml) implementa as seguintes etapas de automação em nuvem:

```
┌────────────────────────────────────────────────────────┐
│ 1. Inicializa Agente VM (ex: windows-latest)           │
│    • Vincula Variable Group $(vg_name)                │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. Setup do Python e Dependências                      │
│    • pip install -r requirements.txt                   │
│    • playwright install --with-deps                    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 3. Execução Paralela da Matriz (Scenarios)             │
│    • Roda o bot: python bot_producao.py                │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. Pós-Execução (JUnit Conversion)                     │
│    • python junit_reporter.py csv xml                  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 5. Publicação de Evidências                            │
│    • Publish Test Results (JUnit XML)                  │
│    • Upload Artifacts (screenshots, logs CSV e JSON)   │
└────────────────────────────────────────────────────────┘
```
