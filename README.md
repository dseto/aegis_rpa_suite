# 🛡️ Aegis RPA Suite: Guia de Instalação e Operação

O **Aegis RPA Suite** é um ecossistema portátil de desenvolvimento e resiliência de robôs RPA baseados em Python + Playwright. Este manual descreve como transferir, instalar e utilizar o framework em outro computador, opcionalmente assistido por uma ferramenta de codificação com IA (como Gemini Antigravity, Claude Code ou similares).

---

## 📂 Estrutura do Pacote Portátil

O projeto está estruturado de forma desacoplada seguindo a segregação de responsabilidades entre interface, orquestração física de projetos, gerenciamento de processos de background e lógicas de negócios:

```
aegis_rpa_suite/
├── aegis_blackbox/              # Gravador de Voo (BlackBox Recorder)
│   └── recorder.py              # Classe AegisRecorder para capturar eventos reativos
├── aegis_sanitizer/             # Compactador, Dicionário de Dados e Firewall
│   ├── sanitizer.py             # Classe SanitizerService (relatórios de telemetria)
│   ├── dataset_validator.py     # Classe DatasetValidatorService (firewall de dados)
│   └── code_generator.py        # Classe CodeGeneratorService (geração cognitiva via IA)
├── aegis_runner/                # Camada e helpers de execução resiliente
│   ├── runner.py                # TransactionRunner com suporte a injeção do gateway
│   └── cognitive_fallback.py    # Gateway cognitivo (LiteLLM/OpenRouter)
├── aegis_cockpit/               # Painel gráfico orquestrador e managers
│   ├── cockpit.py               # Entrypoint HTTP do servidor Cockpit
│   ├── project_manager.py       # Classe ProjectManager (gerência do workspace)
│   ├── process_manager.py       # Classe ProcessManager (controle assíncrono de processos)
│   └── static/                  # Frontend estático da interface SPA
│       └── index.html           # UI do Cockpit (HTML/CSS/JS segregado)
├── aegis_mentor/                # Skills de copilot e guias de resiliência
│   ├── plugin.json              # Metadados do plugin
│   └── skills/                  # Skills de assistente IA (Mapeamento & Padrões)
│       ├── rpa-copilot-analyst.md
│       └── rpa-copilot-coder.md
├── projects/                    # [Área Externa] Pasta de RPAs específicos
│   └── <nome_projeto>/          # Ex: faturamento_portal
│       ├── .env                 # Configurações de IA e browser do projeto
│       ├── project.json         # Metadados do Projeto
│       ├── skills/              # Skills reutilizáveis do projeto
│       │   └── <slug_skill>/    # Ex: login_portal (gravacao, dicionario, skill.json)
│       └── tests/               # Cenários de teste isolados
│           └── <slug_cenario>/  # dataset, bot, dicionário, logs, executions/
├── telemetry_data/              # [Área Externa] Logs de telemetria e datasets
├── requirements.txt             # Dependências Python do ecossistema
└── README.md                    # Este manual de operação
```

---

## 🔒 Regras de Isolamento de RPAs e Proteção do Framework (Aegis Blindado)

1. **Não Geração de Arquivos na Raiz:** Não devem ser gerados arquivos na raiz do projeto (como screenshots, relatórios ou CSVs temporários), exceto em casos de extrema necessidade técnica.
2. **Isolamento de Diretórios de Processos (Projects):** Todos os scripts, simuladores, testes e logs específicos de um sistema alvo devem ficar confinados exclusivamente sob subpastas de `projects/`, nunca dentro de pastas internas do Aegis.
3. **Core Framework Blindado:** A estrutura de pastas internas do Aegis (`aegis_runner`, `aegis_blackbox`, `aegis_cockpit`, `aegis_sanitizer`, `aegis_mentor`) é um motor de execução genérico e blindado.
4. **Desacoplamento de `projects/` e `telemetry_data/`:** Devem ser tratadas como áreas completamente externas à suite core do Aegis, mantendo o framework 100% reutilizável e desacoplado.
5. **Múltiplos Cenários de Teste por Projeto:** Cada cenário é isolado em um subdiretório `tests/<slug_cenario>/` dentro do projeto, contendo suas próprias telemetrias, datasets, scripts gerados, arquivos `.env`, histórico de passos e histórico de execuções.

---

## 🧩 Módulo de Skills Reutilizáveis (Aegis Modular Skills)

As **Aegis Modular Skills** são blocos funcionais reutilizáveis de automação (como autenticação/login, preenchimento de endereço padrão ou rotinas de logout) projetados para serem extraídos e compartilhados por múltiplos cenários de teste de um mesmo projeto.

### ⚙️ Como as Skills são Consumidas e Executadas

1. **Ação `call_skill` na Telemetria:** O cenário consumidor referencia uma Skill declarando uma ação estruturada de tipo `call_skill` com `skill_slug` e `parameters`.
2. **Compilação Modular (`skills_lib.py`):** Durante a Fase 4, o **Code Generator** compila a Skill em uma função Python síncrona `def run_skill_<slug>(page, runner, **parametros):`.
3. **Chamada no Robô:** O `bot_producao.py` importa e executa a função do `skills_lib.py` na posição correta do fluxo.
4. **Mapeamento e Auditoria:** O Cockpit renderiza os passos da Skill inline com o prefixo `[Skill: nome_da_skill]`.

---

## 🚀 Guia de Instalação em outro Computador

### Passo 1: Descompactar o Framework
1. Transfira o arquivo `aegis_rpa_suite.zip` para a máquina de destino.
2. Extraia o conteúdo em um diretório de trabalho de sua preferência (ex: `C:\workspace\aegis_rpa_suite`).

### Passo 2: Configurar o Ambiente Python
```powershell
cd C:\workspace\aegis_rpa_suite
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### Passo 3: Assistente de Codificação IA (Opcional)
As skills de copilot em `aegis_mentor/skills/` fornecem contexto de domínio RPA para ferramentas como Gemini Antigravity ou Claude Code.

---

## 🕹️ Aegis Cockpit (Painel Orquestrador)

```powershell
python aegis_cockpit/cockpit.py
```

### Configurações (`aegis_config.json` na raiz)
```json
{
    "projects_dir": "C:\\Projetos\\aegis_rpa_suite\\projects",
    "telemetry_dir": "C:\\Projetos\\aegis_rpa_suite\\telemetry_data",
    "port": 8075
}
```

### 🖥️ Fluxo de Navegação Dual-State
1. **Portal de Projetos (Visão Global):** Grid responsivo de projetos com pesquisa em tempo real.
2. **Workspace do Projeto (Visão Detalhada):** Foco no projeto selecionado com gerenciamento de cenários de teste na barra lateral.

### 🎨 Melhorias de Layout e Usabilidade (Pipeline Flex)
* **Estrutura Adaptável (Fases 1 a 4):** As etapas de preparação e geração de robô foram organizadas em um grid auto-ajustável (`.prep-grid` com `.step-card` de largura mínima de `180px`), eliminando amontoamentos em telas menores e se empilhando de forma fluida.
* **Fase 1 Integrada:** O campo de URL de Gravação e o botão de acionamento do gravador de voo foram unificados de forma limpa dentro do card da Fase 1.
* **Fase 5 Expandida:** A etapa do Aegis Runner foi promovida a um card de largura total (`.runner-card`), organizando as opções de execução (checkboxes) de forma horizontal e elegante.
* **Checkboxes Personalizados:** Substituição dos checkboxes nativos por controles personalizados de alta fidelidade visual com capitalização em texto natural (evitando a coerção do estilo em maiúsculas).
* **Painel e Terminal de Execução com Scroll:** A coluna central agora suporta rolagem vertical nativa com scrollbars personalizados no tom estético violeta. O Terminal de Execução possui altura mínima garantida de `300px` para evitar que suma da tela.
* **Edição de Títulos e Metadados com IA:** Os nomes de projetos e cenários, bem como suas descrições e resultados esperados, podem ser editados após a criação por meio de modais dedicados (ícone ✏️ na barra lateral) e do painel contextual central. Cada painel de edição dispõe do botão **✨ Enriquecer com IA**, que consulta a LLM para detalhar e qualificar as descrições em linguagem natural baseada em melhores práticas de QA.
* **Resolução Dinâmica de Caminhos:** O Cockpit substituiu fallbacks rígidos/estáticos para caminhos locais (antigo `C:\Projetos\Lab\...`) por caminhos dinâmicos gerados em tempo de execução relativos à raiz do framework (`PROJECT_ROOT`). Isso garante funcionamento imediato sem quebras de diretórios em máquinas limpas.
* **Salvamento Seguro de Configuração (Merge):** O processo de atualização do arquivo de workspace (`aegis_config.json`) foi refatorado para realizar uma fusão (merge) de chaves em vez de sobrescrita destrutiva, preservando portas e parâmetros do SO durante o reinício.
* **Carregamento Robusto do Módulo Cognitivo:** O parser do arquivo `.env` global foi aprimorado para suportar varreduras multi-diretórios (lendo da raiz do framework e do CWD atual) e sanitização automática de aspas simples/duplas para chaves de API, mitigando erros de autenticação na LLM.

### 📊 Gestão de Dataset (Aba Dataset)

* **Visualização e Edição Inline:** Todos os registros do `dataset_inicial.json` são exibidos em tabela editável diretamente na interface.
* **Adição Manual de Registros:** Botão **+ Novo Registro** para adicionar linhas ao dataset com ID sequencial automático.
* **Clonagem de Registros:** Botão 📋 na coluna de Ações para duplicar um registro existente com um clique, gerando um novo ID sequencial único e inserindo o clone logo abaixo do original — ideal para criar variações de casos de teste.
* **Exclusão Individual:** Botão 🗑️ para remover registros específicos do dataset.
* **Importação via CSV:** Botão **📂 Importar CSV** para carregar dados de um arquivo `.csv` externo, fundindo os registros importados ao dataset existente com normalização automática de cabeçalhos.
* **Validação de Dataset:** Botão **✔ Validar Dataset** que executa o Firewall Validator (Fase 3) contra **todos** os registros do dataset.
* **Seleção de Registros para Execução:** Checkboxes individuais em cada linha e um checkbox mestre **Selecionar Todos** permitem escolher exatamente quais registros serão executados na próxima rodada.

### 🚀 Execução em Lote com Controle Granular (Fase 5)

* **Modo Headed/Headless:** Checkbox para executar o navegador em modo visível ou invisível.
* **Capturas de Tela por Passo (Evidências):** Checkbox **Screenshots** para ativar captura automática de screenshot a cada passo bem-sucedido (`AEGIS_STEP_SCREENSHOTS=true`). Arquivos salvos em `step_<row_id>_<n>_<action>_<selector>.png`.
* **Logs em Tempo Real vs. Acumulado:** Checkbox **Logs em Tempo Real** para controlar emissão de linhas `[AEGIS_STEP]` em tempo real — útil para datasets grandes onde o volume de logs pode saturar o terminal.
* **Grid de Progresso de Transações:** Painel de acompanhamento exibe o status individual de cada registro (`⏳ Executando`, `✓ Sucesso`, `❌ Falhou`) com barra de progresso percentual em tempo real.
* **Resiliência Total no Loop:** O runner cria uma página Playwright isolada por transação. Erros, travamentos ou diálogos JavaScript em um registro são automaticamente descartados sem interromper os demais. O loop sempre percorre até o último registro.

### 🤖 Acompanhamento e Auditoria de Passos (Tempo Real)

* **Mapeamento Prévio e Expansão de Skills Inline:** O painel carrega a lista de eventos de `gravacao.json` e renderiza Skills inline com prefixo `[Skill: nome_da_skill]`.
* **Algoritmo de Pareamento FIFO:** Correlaciona logs com passos mesmo quando seletores são otimizados ou alterados pelo self-healing.
* **Vínculo de Registro do Dataset por Passo:** Cada passo exibido mostra qual linha (`Registro #N`) do dataset foi utilizada, garantindo rastreabilidade completa.
* **Status em Runtime:** `⏳ Executando`, `✓ Sucesso`, `✨ Healed` (self-healing IA), `❌ Falhou`, `⏹ Parado`.
* **Trilha de Auditoria Persistida por Execução:** O `historico_passos.json` completo (com todos os passos de todas as transações) é preservado na pasta `executions/run_<timestamp>/` de cada execução. O arquivo armazena o `row_id` em cada passo para permitir filtragem precisa por registro no histórico.
* **Zerar Status:** Permite redefinir os passos de volta ao estado `Pendente` e remover o histórico salvo.

### 📋 Histórico de Execuções (Aba Histórico)

Navegação em dois níveis para evitar sobrecarregar a tela em datasets com muitos registros:

* **Taxa de Sucesso (Pass Rate):** A lista exibe a porcentagem e proporção exata de sucesso por execução (ex: `80% (4/5)`) em vez de um status binário.
* **Nível 1 — Transações Executadas:** Ao clicar em uma execução, exibe a lista de todos os registros com status individual (`✓ Sucesso`, `❌ Falhou`), duração e cenário.
* **Nível 2 — Passos Auditados por Registro:** Ao clicar em um registro específico, exibe os passos auditados exclusivos daquele `row_id`. Botão `⬅ Voltar` retorna ao Nível 1.
* **Visualizador de Screenshots:** Passos com evidências visuais exibem botão 📸 que carrega o screenshot no painel.
* **Retrocompatibilidade:** Execuções antigas sem relatório transacional renderizam os passos diretamente em modo legado.

---

## 🎙️ Anotações Semânticas em Tempo Real (Texto & Voz)

O **Aegis Blackbox** permite documentar a intenção funcional do processo de negócio diretamente no browser durante a gravaçãoheaded:
* **Anotações de Texto (`Ctrl+Shift+A`):** Abre um modal integrado com Shadow DOM na página web sob gravação para digitação da intenção funcional do passo atual (salvo via `pythonAddAnnotation`).
* **Anotações de Voz (`Ctrl+Shift+V`):** Inicia a captura de áudio do microfone em background (utilizando API nativa MCI no Windows, sem dependências externas). Ao pressionar novamente, salva o arquivo `.wav` de 16kHz e realiza a transcrição semântica automática via LLM/Whisper no `CognitiveGateway` (exibindo toast reativo na tela).
* **Sanitização Semântica:** O `sanitizer.py` consome essas anotações e reescreve descrições mecânicas em linguagem de negócio no `relatorio.md` e `gravacao.json`.

---

## 🔗 Módulo Aegis DevOps (REST API v7.1)

O módulo `aegis_devops/` fornece integração nativa com o **Azure DevOps** utilizando estritamente a API REST v7.1 (autenticação por PAT):

* **Painel DevOps Independente (Nova Tela):** Interface gráfica dedicada e apartada no Cockpit para configuração centralizada de pipelines. Permite selecionar o projeto do workspace, configurar credenciais globais e selecionar múltiplos cenários de teste para compor a matriz do pipeline.
* **Configurações Persistentes por Projeto:** Parametrizações do DevOps são salvas localmente em `projects/{project_slug}/devops_config.json` com mascaramento automático de chaves (PAT/API Key) na UI e algoritmo de merge que impede a sobrescrita acidental de tokens válidos.
* **Publicação Assíncrona em Background (`publish_pipeline.py`):** O processo de push e registro de pipeline é executado em segundo plano sob o `ProcessManager` do Cockpit, permitindo que o usuário acompanhe o progresso detalhado de cada fase em tempo real por um console de terminal integrado.
* **Matriz de Execução Concorrente:** A publicação consolida a execução paralela de múltiplos cenários de teste no arquivo `azure-pipelines.yml` gerado automaticamente, otimizando o tempo de execução no agente Azure DevOps.
* **Governança Segura de Segredos:** Quando o Variable Group cognitivo (`aegis-llm-group`) já existe no Azure DevOps, a publicação preserva intactos os segredos editados manualmente pelo usuário na UI do Azure DevOps (como chaves da API de LLM), evitando sobrescritas acidentais com strings vazias.
* **Git Push REST (`publisher.py`):** Realiza commits atômicos de arquivos, scripts do core do runner e cenários diretamente no Azure Repos sem depender do binário local `git`.
* **Mapeamento Granular no Azure Test Plans:**
  * **Test Plan** $\rightarrow$ Projeto Aegis (`project_slug`).
  * **Test Suite** $\rightarrow$ Cenário Aegis (`test_slug`).
  * **Test Case** $\rightarrow$ Registro individual do Dataset (um caso de teste criado e documentado por linha do dataset, com cada campo mapeado como step do Test Case).
  * **Test Run** $\rightarrow$ Publica os resultados individuais da execução em lote (Passed, Failed) diretamente atrelados aos seus respectivos Test Cases.
* **JUnit XML Reporter (`junit_reporter.py`):** Traduz o relatório CSV de execução do robô para o formato JUnit XML, integrado à task `PublishTestResults@2` do pipeline YAML, permitindo gráficos detalhados de sucesso/falha e vinculação automática de logs e screenshots às falhas no painel de QA.

---

## 🔄 Fluxo de Desenvolvimento Resiliente (Aegis Pipeline)

### 1. Fase 1: Gravação (Aegis BlackBox)
```powershell
python aegis_blackbox/recorder.py --url "https://mestres.ai" --output-dir "projects/seu_projeto" --control-port 9900
```
* **DOM Scanner & Anti-Bot:** Varre o DOM a cada 3 segundos. Detecta campos com listeners de teclado para configurar `"fill_strategy": "HUMAN_LIKE"`.
* **Priorização do `data-testid`:** Prioriza atributos de testes estruturados (`data-testid`, `data-test-id`, `data-test`, `data-qa`).
* **Auditoria de Confiabilidade de Seletores:** Seletores com score < 70% disparam alertas `[⚠️ AEGIS RECORDER ALERT]`.
* **Graceful Shutdown:** Salva telemetrias pendentes via `HTTP /api/finish` antes de encerrar.

### 2. Fase 2: Sanitização/Tratamento (Aegis Sanitizer)
```powershell
python aegis_sanitizer/sanitizer.py --project-dir projects/seu_projeto
```
* Consolida cliques duplos, remove preenchimentos duplicados, descarta cliques em overlays genéricos, filtra autocompletes redundantes.
* Gera `relatorio.md` e reescreve `gravacao.json` sanitizado.

### 3. Fase 3: Validação de Dataset (Firewall Validator)
```powershell
python aegis_sanitizer/dataset_validator.py --dataset projects/seu_projeto/dataset_inicial.json --project-dir projects/seu_projeto
```
* Validação tolerante — bloqueia apenas erros críticos estruturais (ausência de `id`, cenário não registrado).
* Analisa `expected_result` para diferenciar casos de teste de erro intencional de falhas inesperadas.
* Gera `relatorio_validacao.json` com blocos `"failures"` e `"warnings"`.

### 4. Fase 4: Geração Automática de Código (Aegis Code Generator)
```powershell
python aegis_sanitizer/code_generator.py --project-dir projects/seu_projeto
```
* Compila `bot_producao.py` e `skills_lib.py` usando IA (Gemini via OpenRouter).
* Valida sintaticamente o script gerado com `compile()` antes de salvar.
* Requer `.env` com `AEGIS_COGNITIVE_API_KEY`, `AEGIS_COGNITIVE_PROVIDER` e `AEGIS_COGNITIVE_MODEL`.

### 5. Fase 5: Execução de Produção (Aegis Runner)
```powershell
python projects/seu_projeto/bot_producao.py
```

| Variável de Ambiente | Padrão | Descrição |
|---|---|---|
| `AEGIS_BROWSER_HEADLESS` | `true` | `true` para modo invisível, `false` para headed (visível) |
| `AEGIS_STEP_SCREENSHOTS` | `false` | `true` para capturar screenshot a cada passo bem-sucedido |
| `AEGIS_STEP_LOGS_REALTIME` | `true` | `false` para suprimir `[AEGIS_STEP]` em tempo real (datasets grandes) |
| `AEGIS_EXECUTION_DIR` | `project_dir` | Pasta de saída da execução (definido automaticamente pelo Cockpit) |
| `AEGIS_EXECUTION_ID` | — | ID único da execução em lote (definido automaticamente pelo Cockpit) |

---

## 🛠️ Mecanismos de Resiliência Nativos (Aegis Runner)

O **Aegis Runner** (`aegis_runner/runner.py`) implementa algoritmos de resiliência de alto nível para lidar com as principais falhas de automação web em ambientes dinâmicos e SPAs:

1. **Priorização de `data-testid` e Normalização:** Isola o robô de variações e IDs dinâmicos de backend.

2. **Preenchimento Resiliente de Texto (`fill_resilient`):** Se o seletor falhar, localiza o elemento via simulação de teclado físico controlando foco e eventos Zone.js.

3. **Fallback Visual Cognitivo por Imagem (Último Caso):** Captura screenshot da viewport, dispara chamada cognitiva de visão à IA (Gemini) para localizar o elemento por descrição semântica e calcular coordenadas percentuais dinâmicas para clique físico.

4. **Heurística Estática de Links:** Em múltiplos candidatos, desprioriza âncoras locais (`#`) em favor de links de navegação externos (`http/https`).

5. **Validação Ativa de Transição (State Verification):** Quando `validate_navigation=True`, verifica se o clique resultou em alteração de URL. Em caso de falha, força navegação direta via `page.goto()`.

6. **Isolamento Total de Transações por Página:** Uma nova instância de página Playwright é criada por transação do dataset. Listener `page.on("dialog", lambda d: d.dismiss())` descarta todos os diálogos JavaScript automaticamente. Registros com falha sistêmica são marcados como `SYSTEM_FAILED` **sem interromper o lote**.

7. **Captura de Evidências Visuais por Passo:** Quando `AEGIS_STEP_SCREENSHOTS=true`, captura screenshot após cada passo `SUCCESS` ou `HEALED`, salvando com nome `step_<row_id>_<n>_<action>_<selector>.png`. Acessível no Cockpit via botão 📸 no histórico de passos.
