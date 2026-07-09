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
* **Controles de Colapso de Seções (Layout Expansível):** O header do Cockpit ganhou botões de recolhimento independentes para a coluna de Cenários (esquerda) e para o Painel de Operações/Console (centro). Ao recolher ambas as colunas, a seção da direita (Visualização / Dataset / Histórico) expande-se automaticamente para ocupar 100% da largura da tela, liberando espaço máximo para análise de evidências e datasets. O estado de cada coluna é persistido via `localStorage`.

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
* **Correlação por `step_id`:** Cada entrada do `historico_passos.json` carrega o `step_id` real do plano (`plano_execucao.json`/`# [PASSO X]`). O Cockpit usa esse campo — não mais posição no array nem heurística de matching por seletor — para numerar e ordenar os passos tanto no painel de execução quanto na aba Histórico.
* **Polling em Tempo Real Durante a Execução:** Enquanto o processo está rodando, o Cockpit relê o `historico_passos.json` a cada ~1.6s e re-renderiza o painel, refletindo status novos (`SUCCESS`, `HEALED`, `FAILED`) sem esperar o fim do lote.
* **Um Único Passo "Executando" por Vez:** A heurística de destaque identifica exatamente o próximo passo pendente após o último com atividade registrada — nunca marca múltiplos passos pendentes como executando simultaneamente.
* **Filtragem de Entradas de Diagnóstico (`auto_*`):** Passos com `step_id` gerado automaticamente (prefixo `auto_`) — registrados pelo Runner quando uma falha é diagnosticada sem estar associada a um passo do plano — são ocultados do painel e da aba Histórico, pois não representam um passo real do fluxo.
* **Vínculo de Registro do Dataset por Passo:** Cada passo exibido mostra qual linha (`Registro #N`) do dataset foi utilizada, garantindo rastreabilidade completa.
* **Status em Runtime:** `⏳ Executando`, `✓ Sucesso`, `✨ Healed` (self-healing IA), `❌ Falhou`, `⏹ Parado`, `⏭ Ignorado` (passos pulados/bypassados).
* **Ordenação por Ordem de Execução:** Permite alternar a ordenação do grid de passos clicando nos cabeçalhos `# ⇅` (ID original) ou `Ordem ⇅` (ordem de execução em tempo real).
* **Trilha de Auditoria Persistida por Execução:** O `historico_passos.json` completo (com todos os passos de todas as transações) é preservado na pasta `executions/run_<timestamp>/` de cada execução. O arquivo armazena o `row_id` em cada passo para permitir filtragem precisa por registro no histórico.
* **Zerar Status:** Permite redefinir os passos de volta ao estado `Pendente` e remover o histórico salvo.
* **Complemento de "Não Alcançado" a partir do Plano, não da Gravação Crua:** ao completar o painel com os passos planejados que não chegaram a ser executados, o Cockpit usa `plano_execucao.json` (já colapsado/deduplicado pelo Sanitizer, 1 `step_id` por ação real do bot) em vez de `gravacao.json` (telemetria bruta, com múltiplos eventos físicos por interação, ex.: vários cliques de exploração de dropdown). Usar a gravação crua fazia a contagem de "passos restantes" nunca bater com o total real do bot, gerando passos fantasma na UI (numeração solta, sem `st_XXX`, sem registro de dataset) que nunca existiram no fluxo compilado.

### 📋 Histórico de Execuções (Aba Histórico)

Navegação em dois níveis para evitar sobrecarregar a tela em datasets com muitos registros:

* **Taxa de Sucesso (Pass Rate):** A lista exibe a porcentagem e proporção exata de sucesso por execução (ex: `80% (4/5)`) em vez de um status binário.
* **Nível 1 — Transações Executadas:** Ao clicar em uma execução, exibe a lista de todos os registros com status individual (`✓ Sucesso`, `❌ Falhou`), duração e cenário.
* **Nível 2 — Passos Auditados por Registro:** Ao clicar em um registro específico, exibe os passos auditados exclusivos daquele `row_id`. Botão `⬅ Voltar` retorna ao Nível 1.
* **Visualizador de Screenshots:** Passos com evidências visuais exibem botão 📸 que carrega o screenshot no painel.
* **Retrocompatibilidade:** Execuções antigas sem relatório transacional renderizam os passos diretamente em modo legado.
* **Layout Redistribuído com Rolagem:** A aba Histórico ganhou rolagem vertical nativa em seu contêiner principal, deixando de ser limitada à altura da tela. A grade de Detalhes da Execução (Passos | Log | Screenshot) possui altura fixa garantida de `380px`. O painel de Insights & Propostas de Correção Cognitiva foi reorganizado em **2 colunas lado a lado**: à esquerda o campo de texto para o Analista QA e à direita a lista de correções sugeridas com rolagem interna dedicada.

### 🔧 Histórico de Problemas & Auto-Healing (Painel de Rastreabilidade de Bugs)

Novo painel permanente na aba **Histórico**, exibido logo após o painel de Evolução de Versões:

* **Grid de Bugs em Aberto:** Exibe todos os problemas com status diferente de `resolved` do arquivo `correcoes_acumuladas.json`, ordenados por prioridade: `❌ Falhou` → `⏳ Aguardando` → `🔧 Aplicado`. Bugs resolvidos saem automaticamente do grid e nunca mais aparecem na listagem.
* **Identificação do Passo (`# [PASSO X]`):** Cada bug exibe um badge roxo com o número do passo exato onde a falha ocorreu (ex: `Passo 69`), obtido do campo `index` do `historico_passos.json`. Registros aprovados antes desta funcionalidade exibem `sem nº` com tooltip explicativo. O campo `step_number` é persistido em `correcoes_acumuladas.json` a cada aprovação.
* **Badge de Resumo:** Contador ao lado do título mostra quantos bugs estão em aberto e quantos tiveram tentativas fracassadas repetidas, ou exibe `✅ Todos resolvidos` em verde quando a lista estiver limpa.
* **Coluna de Tentativas:** Cada linha exibe quantas vezes uma abordagem diferente foi tentada para o mesmo par `action + seletor` sem sucesso.
* **Indicador de Insight QA (🧠):** Bugs que já receberam diagnóstico humano exibem ícone 🧠 com tooltip do texto registrado.
* **Ação ✅ Resolver:** Marca o bug como `resolved` com **remoção otimista animada** (fade + slide em 250ms), sem aguardar a resposta do servidor. Se for o último bug em aberto, exibe mensagem verde de sucesso e atualiza o badge imediatamente. Em caso de falha na comunicação, o grid é restaurado automaticamente.
* **Ação 🔁 Reenviar (Modal):** Disponível para qualquer bug que não esteja em `pending` (aplicado, falhou ou resolvido). Abre modal dedicado exibindo o seletor, a causa raiz e o insight QA pré-existente para edição. Permite atualizar o **Diagnóstico QA** (pré-preenchido com o conteúdo anterior) e opcionalmente fornecer uma nova proposta de correção técnica. Ao confirmar, o bug volta a `pending` com o diagnóstico atualizado e os timestamps de falha limpos.
* **Auto-Invalidação de Correções Aplicadas:** Ao carregar os insights de uma nova execução com falhas, o Cockpit verifica automaticamente se algum seletor que falhou possuía uma correção com status `applied` ou `pending`. Se sim, o status é atualizado para `failed_attempt` com timestamp no `correcoes_acumuladas.json`, garantindo que a IA nunca repita uma abordagem já fracassada.
* **Atualização Automática:** O painel é recarregado automaticamente ao mudar para a aba Histórico e ao carregar novas execuções.

---

## 🎙️ Anotações Semânticas em Tempo Real (Texto & Voz)

O **Aegis Blackbox** permite documentar a intenção funcional do processo de negócio diretamente no browser durante a gravaçãoheaded:
* **Anotações de Texto (`Ctrl+Shift+A`):** Abre um modal integrado com Shadow DOM na página web sob gravação para digitação da intenção funcional do passo atual (salvo via `pythonAddAnnotation`).
* **Anotações de Voz (`Ctrl+Shift+V`):** Inicia a captura de áudio do microfone em background (utilizando API nativa MCI no Windows, sem dependências externas). Ao pressionar novamente, salva o arquivo `.wav` de 16kHz e realiza a transcrição semântica automática via LLM/Whisper no `CognitiveGateway` (exibindo toast reativo na tela).
* **Sanitização Semântica:** O `sanitizer.py` consome essas anotações e reescreve descrições mecânicas em linguagem de negócio no `relatorio.md` e `gravacao.json`.

---

## 💡 Ciclo de Retroalimentação & Evolução de Versões (Melhoria Contínua)

O ecossistema introduz um motor de melhoria contínua orientado por feedback visual e cognitivo para automatizar e auditar a evolução da estabilidade do robô:

* **Ciclo de Feedback Cognitivo (Retroalimentação):** Quando o robô apresenta falhas durante a execução (Fase 5), o módulo de visão computacional multimodal da IA analisa a tela, identifica a causa raiz e elabora propostas de correções (`proposed_fix`). Esses insights são apresentados na aba **Histórico** do Cockpit com miniaturas das telas dos erros. Cada insight carrega obrigatoriamente o **número do passo** (`step_number`) obtido do `historico_passos.json`, que é persistido em `correcoes_acumuladas.json` ao aprovar a correção.
* **Controle Humano (Aprovação de Insights):** O analista audita visualmente os erros e aprova as correções por meio de checkboxes. Durante a aprovação, o analista QA pode opcionalmente escrever um **Insight do Analista QA** (texto livre detalhando o diagnóstico humano da causa raiz e da solução). Uma vez aprovados, os insights automáticos da IA e a nota humana do QA são consolidados no arquivo `correcoes_acumuladas.json` com status `"pending"`.
* **Atualização de Diagnóstico em Qualquer Bug:** O endpoint `POST /api/projects/{slug}/tests/{test_slug}/correcoes/{id}/status` aceita os campos opcionais `qa_insight` e `proposed_fix` além do `status`. Isso permite ao QA atualizar o diagnóstico e a proposta de qualquer bug diretamente pelo modal de Reenvio, sem precisar de uma nova execução.
* **Retroalimentação na Geração de Código:** Ao rodar a Fase 4 (Gerador de Código), os insights aprovados pendentes são injetados no prompt da LLM. Se um **Insight do Analista QA** manual tiver sido preenchido, ele será destacado de forma contundente (caixa ASCII enfática no prompt) como instrução de **prioridade máxima** sobre o diagnóstico automático da IA. O gerador aplica as correções no código do `bot_producao.py` e atualiza o status das correções para `"applied"`, fechando o ciclo de melhoria contínua.
* **Histórico de Tentativas Fracassadas (Proibição de Repetição):** O fluxo de correção cirúrgica (`_surgical_correct`) coleta automaticamente todas as entradas com status `failed_attempt` para os mesmos pares `action + seletor` das correções pendentes. Esse histórico é injetado no prompt com uma caixa ASCII de aviso enfático, instruindo a LLM a criar uma **estratégia técnica completamente nova** sem repetir abordagens que já falharam anteriormente. A marcação de `failed_attempt` também ocorre **automaticamente** ao carregar os insights de uma nova execução com falhas — sem exigir ação do analista.
* **Reenvio de Bugs para Nova Tentativa:** Após uma correção ser aplicada e o robô ainda falhar, o analista pode usar o botão 🔁 **Reenviar** no painel de Histórico de Problemas para colocar o bug de volta na fila (`status: pending`) com um diagnóstico QA atualizado e, opcionalmente, uma nova proposta técnica. O modal é acessível a partir de qualquer status diferente de `pending` — incluindo `resolved`. Na próxima execução da Fase 4, toda a cadeia de tentativas anteriores é automaticamente carregada como contexto proibitivo, garantindo que o processo seja evolutivo e nunca fique em loop.
* **Evolução de Versões & Não Regressão:** Um painel de acompanhamento na aba **Histórico** exibe a linha do tempo evolutiva das versões geradas para o cenário de teste. O analista pode auditar métricas como taxa de sucesso de transações do lote, total de passos físicos concluídos, quantidade de auto-healing utilizado e status de estabilidade por versão, prevenindo regressões de código ao longo do tempo.

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
* **Descarte de Overlay CDK Genérico sem Derrubar Seleção Real:** a regra de limpeza de cliques em `#cdk-overlay-container` agora só descarta cliques em backdrop/container vazio de fato — clicks em uma opção específica dentro do overlay (selectors com `[role='option']` ou `has-text(...)`) são preservados, mesmo quando aninhados sob `cdk-overlay-container` (padrão comum em dropdowns/grids do Angular Material).
* **Correspondência de Autocomplete sem Depender de Idioma/Ordem de Campos:** a regra que descartava cliques em painel de autocomplete (`mat-autocomplete-panel-*`) sem um preenchimento correspondente comparava o nome do painel contra palavras fixas em inglês (`brand`/`model`/`version`), quebrando em qualquer app com seletores em outro idioma, e assumia preenchimento e seleção alternados 1:1 por campo — falso em fluxos onde múltiplos campos são preenchidos antes de qualquer seleção. Agora só descarta um clique de painel de autocomplete quando não houve preenchimento nenhum antes no fluxo (painel genuinamente órfão).
* **Padrão Q — Remoção Automática de Token Dinâmico em `has_text` (correção na origem):** quando o `has_text` de um `parent` gravado contém um token em formato de código/identificador (ex.: `PRO-80935`) que não aparece em nenhum valor do `dataset_inicial.json`, o sanitizer remove esse token diretamente do `plano_execucao.json` antes de chegar no Code Generator — em vez de só alertar no `relatorio.md` (mantido como auditoria complementar). Evita que um identificador gerado em runtime pelo app-alvo (protocolo, número de proposta) fique hardcoded no seletor do bot, o que o quebraria em toda execução seguinte.

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
* **Modelo Dedicado para Codificação (`AEGIS_COGNITIVE_CODER_MODEL`):** Variável de ambiente opcional que define um modelo de LLM específico e mais poderoso exclusivamente para geração e correção de código (Fase 4). Se não configurada, usa o modelo geral (`AEGIS_COGNITIVE_MODEL`).
* **Dois Fluxos Independentes (Karpathy Style):**
  * **Fluxo 1 — Geração Nova (`_generate_new_code`):** Invocado quando não há nenhum `bot_producao.py` existente. Gera o código completo do zero a partir do relatório de telemetria sanitizado, garantindo ausência total de hardcodes (fallbacks de `.get()` sempre com string vazia `""`).
  * **Fluxo 2 — Correção Cirúrgica (`_surgical_correct`):** Invocado quando já existe código e há correções pendentes aprovadas. A IA usa os comentários `# [PASSO X]` pré-existentes como âncoras para localizar e alterar **exclusivamente o bloco do passo problemático**, sem tocar em nenhuma linha funcionando.
* **Comentários de Rastreabilidade `# [PASSO X]` (Obrigatório):** Todo passo de automação gerado ou corrigido é obrigatoriamente precedido por um comentário no formato `# [PASSO X] Descrição do Passo`, onde `X` é o índice do passo na telemetria. Essa diretriz é imposta via prompt tanto na geração nova (regra 12) quanto na correção cirúrgica (regra 5), garantindo que código funcional nunca seja modificado acidentalmente em futuras rodadas de correção.
* **`error_message_selector` Customizável (`project.json`):** Campo opcional `"error_message_selector"` em `project.json` do projeto permite sobrescrever o seletor CSS de mensagens de erro usado pelo `TransactionRunner` no bloco `__main__` gerado (padrão histórico: `.toast-error, .alert-danger`). Útil quando o site alvo usa uma convenção de classe/toast diferente. Se o campo estiver ausente ou vazio, o Code Generator preserva o default atual (boilerplate byte-idêntico ao de projetos sem o campo).

### 4.1 Pipeline Determinístico de Passos (`plano_execucao.json`)

Fonte de verdade única que atravessa Sanitizer → Code Generator → Runner, garantindo rastreabilidade 1:1 entre o que foi planejado e o que o robô executa:

* **Geração pelo Sanitizer:** Ao final de `sanitize()`, gera `<test_dir>/plano_execucao.json` com a lista final de passos (`click`/`fill`/`filechooser`/`select`), cada um com `step_id` sequencial (`st_001`, `st_002`, ...), além de metadados de resiliência por passo (`parent`, `coords`) quando presentes na gravação.
* **Colapso de Pares Dropdown Abertura/Seleção:** `_reorder_dropdown_pairs()` detecta quando um passo que abre um dropdown/mat-select é seguido por um passo não relacionado antes da seleção da opção, e **colapsa** os dois num único step `type: "select"` (com `dropdown_label`, `option_text`, `coords_trigger`, `coords_option`) — a numeração de `step_id` reflete a contagem já colapsada, então `select_option_resilient()` (que só aceita um `step_id`) nunca conflita com a validação de contagem/ordem do plano. Evita que o overlay do Angular Material feche antes da opção ser clicada em produção.
* **`step_id` Obrigatório no Runner:** Toda chamada de ação (`click_resilient`, `fill_resilient`, etc.) exige o parâmetro nomeado `step_id`, usado para correlacionar log de execução (`[AEGIS_STEP]`) ao plano.
* **Validação AST Pós-Geração (`step_validator.py`):**
  * `validate_bot_structure()` — sintaxe, whitelist de imports/métodos do runner, ordem de parâmetros de `execute_scenario_default(page, row, runner)`, resolução correta de `project_dir` (deve subir da pasta `code/`).
  * `validate_bot_against_plan()` — compara `step_id`s do código com o plano (contagem, ordem, presença). Extração via AST ordenada explicitamente por posição no código-fonte (não por `ast.walk()`, que é BFS e pode devolver ordem errada em ramos `if/elif/else`).
  * `validate_resilience_patterns()` — por `step_id` do plano, exige o padrão de resiliência correspondente no código gerado: `click_chained`/`fill_chained` com `parent=`/`child=` como dict literal (não string) quando há `parent` gravado, `select_option_resilient` para passos `type: "select"`, `original_coords=` em `click_resilient`/`click_chained` quando há `coords` gravadas, e `strategy="HUMAN_LIKE"` (ou `fill_human_like()`) quando `dicionario.json` marca o campo com detecção anti-bot. O check `MISSING_PARENT_HAS_TEXT` aceita tanto `has_text` como valor literal quanto construído dinamicamente (ex.: `f"{row.get(...)}"`), rastreado separadamente via `dict_dynamic_keys` na extração AST — evita falso positivo quando o valor de `has_text` é parametrizado por campo do dataset em vez de fixo na gravação.
  * `reorder_steps_to_match_plan()` — corrige automaticamente divergências puras de ordem via manipulação de AST/fonte, sem gastar tentativa do Ralph Loop (reordenação é tarefa mecânica).
  * `validate_dataset_field_names()` — detecta `row.get("campo_alucinado")` que não existe em `dicionario.json`.
  * `dry_run_bot()` — executa o bot em sandbox real (incluindo o bloco `if __name__ == "__main__":`) contra um `_FakeRunner` com as assinaturas reais de todos os métodos do `TransactionRunner`, usando a **primeira linha real do dataset** (não um dict vazio) para exercitar conversões de formato (datas, regex) que só falham com dado real.
* **Ralph Loop com Reflexão:** `AEGIS_CODEGEN_MAX_RETRIES` tentativas de correção cirúrgica, cada uma alimentada com os erros exatos da tentativa anterior, até passar em todos os gates.
* **Normalização Determinística do Boilerplate:** `_normalize_boilerplate()` substitui o bloco `if __name__ == "__main__":` gerado pela LLM por uma versão fixa e canônica (`TransactionRunner(project_dir=..., error_message_selector=self.error_message_selector)`, `register_scenario`, `runner.run()` sem argumentos) logo após a validação de sintaxe — esse trecho é puramente mecânico e não deveria variar entre gerações. O valor de `error_message_selector` vem de `self.error_message_selector`, populado em `generate()` a partir do campo opcional `error_message_selector` de `project.json` (default `.toast-error, .alert-danger` quando ausente).

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
| `AEGIS_COGNITIVE_MODEL` | — | Modelo de LLM para uso geral (self-healing em runtime) |
| `AEGIS_COGNITIVE_CODER_MODEL` | — | Modelo de LLM dedicado para geração e correção de código (Fase 4). Sobrescreve `AEGIS_COGNITIVE_MODEL` apenas no Code Generator |

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

8. **Modo Estrito (`strict=True`) para Alvos Definitivamente Ausentes:** `click_resilient(..., strict=True)` pula os níveis 3 (self-healing cognitivo por visão) e 4 (fallback de coordenadas gravadas) quando o elemento não existe de fato na aplicação — cenário de "beco sem saída" no fluxo do app alvo, não uma falha de seletor. Sem `strict`, os fallbacks 3/4 "adivinham" um alvo próximo e arriscam clicar no elemento errado, corrompendo passos subsequentes; com `strict=True`, a exceção original do Playwright é relançada limpa e o passo é registrado como `FAILED`. Usado em correções cirúrgicas (`correcoes_acumuladas.json`) quando o diagnóstico confirma que o elemento recorrido não está disponível naquele ponto do fluxo e nenhuma correção é possível do lado do robô além de falhar de forma previsível.

9. **Espera Pré-Clique para Botões que Nascem `disabled` (`_wait_for_known_disabled_button`):** Alguns botões de confirmação (ex.: `#btn-confirm-payment-progress`) iniciam desabilitados e só habilitam após um timer/fetch assíncrono real do app (~6s). Como o clique físico do runner usa `force=True` internamente (necessário para outros seletores instáveis), ele ignora a checagem nativa de `enabled` do Playwright e clicaria cedo demais sem efeito algum. Antes de qualquer tentativa de clique, o runner faz polling limitado (`is_enabled()`, até 15s) para seletores conhecidos dessa família, sem adicionar latência nenhuma para os demais.

10. **Espera Pós-Clique para Transições Assíncronas de Wizard (`_wait_if_wizard_transition_button`):** Botões de avanço de wizard (`#btn-next-step`) podem disparar uma chamada assíncrona (ex.: cálculo de cotação) que desabilita o próprio botão de forma síncrona no clique e só libera a tela seguinte quando a resposta chega. Sem esperar isso, o passo seguinte do bot tenta interagir com uma tela ainda não renderizada. O runner faz polling limitado (até 15s) pelo botão voltar a ficar habilitado — ou pela sua identidade no DOM mudar (re-render trocou de tela) — antes de reportar o clique como concluído. Escopo restrito a esse seletor literal, sem impacto em outros cliques.

11. **Correção de Corrida em `fill_human_like()` (Digitação Cadenciada vs. Campo Bloqueado por Busca Assíncrona):** `fill_human_like()` usa `element.click(force=True)` para contornar falsos-negativos de estabilidade do Playwright em campos animados — efeito colateral: também ignorava um campo genuinamente desabilitado por uma busca assíncrona em andamento (ex.: auto-fill de nome disparado pelo preenchimento do CPF, que deixa o campo `disabled` por alguns segundos). O robô digitava no campo ainda bloqueado e o valor era descartado/sobrescrito quando a resposta assíncrona chegava. Agora há um polling limitado (`is_enabled()`, até 8s) imediatamente antes do clique forçado, sem reintroduzir o problema de estabilidade que o `force=True` resolve.

12. **Self-Healing vira Bug Rastreável Automaticamente:** Toda vez que qualquer caminho de self-healing resolve um passo (`status="HEALED"` em `_log_step`, incluindo os fallbacks de coordenada gravada e IA visual do dropdown customizado `select_option_resilient`), o runner grava automaticamente uma entrada `status="needs_review"` em `correcoes_acumuladas.json` (raiz do diretório do teste), com dedup por `(action, failed_selector)` e escrita atômica com lock de arquivo. Nenhum passo que precisou de healing fica invisível — o Cockpit conta e exibe essas entradas separadas de `pending`/`applied`/`resolved` no painel de Histórico de Problemas (badge **🔎 Precisa Revisão**) e no endpoint `/correcoes-status`. Um `needs_review` só vira `pending` (elegível para correção automática na próxima geração) depois que um humano investiga a causa raiz — nunca é reinjetado cegamente no Code Generator. **Dedup só suprime enquanto o par `(action, failed_selector)` está ATIVO** (`needs_review` ou `pending`) — um par já `resolved`/`applied`/`failed_attempt` volta a gerar entrada nova se falhar/curar de novo depois (regressão pós-resolução é sempre visível; corrigido após bug real onde um seletor marcado `resolved` uma vez nunca mais reaparecia no painel mesmo quebrando de novo em execuções futuras).

13. **Passos Flaky com Restart Automático por Linha (Padrão R):** Passos conhecidamente intermitentes (ex.: dropdown condicional que não renderiza a tempo em ~1 a cada N execuções) podem ser marcados `"flaky": true` no `plano_execucao.json` — manualmente pelo QA via checkbox na tela de Passos do Cockpit, tipicamente depois de confirmar que uma entrada `needs_review` (item 12) é intermitência, não bug estrutural. Para a linha do dataset que falha num passo marcado `flaky`, o runner reinicia a **transação inteira daquela linha** (nova página/contexto, do passo 1) até 3 vezes antes de liberar o self-healing como último recurso na 4ª tentativa — em vez de "adivinhar" via coordenada/IA na primeira falha. O gatilho é a marcação `flaky` em si, independente do valor de `strict` que o bot passa naquela chamada (que continua sendo o default estático de sempre). O bot compilado e o Code Generator não mudam em nada — toda a decisão de restart/liberação de healing vive centralizada no `TransactionRunner`.

14. **Sensor `CLICK_NO_EFFECT` (Passo Fantasma Visível):** `click_resilient` usa `click(force=True)` no clique físico principal, que pula a checagem de actionability do Playwright — um clique em elemento coberto por overlay "passa" e é logado `SUCCESS` mesmo sem efeito real, e a falha verdadeira só estoura N passos depois, com a correção cirúrgica mirando o passo errado. Antes do clique, o runner tira um snapshot barato via `page.evaluate()` (`url`, contagem de nós DOM com tolerância ±2, contagem de overlays `.cdk-overlay-container *, [role=dialog], .modal.show`); depois do clique bem-sucedido, faz polling com saída antecipada em ~100/300/800ms — qualquer sinal mudar, sai imediatamente (custo típico ~100ms). `document.activeElement` **não** entra como sinal de efeito: no engine Chromium (MS Edge) o próprio clique já move o foco, o que mascararia exatamente o caso-alvo (clique `force=True` sob overlay). Se nenhum sinal mudar até 800ms, loga `[AEGIS RUNNER] ⚠️ CLICK_NO_EFFECT | {step_id} | {selector}` — o passo continua retornando `True`/`SUCCESS`, é detecção-apenas, nunca bloqueio nem retry. Controlado por `AEGIS_CLICK_EFFECT_SENSOR` (default `true`; `false` desativa completamente, zero `evaluate()` extra) e excluído para `validate_navigation=True` e para os seletores literais das famílias do item 9/10 (já cobertos por espera dedicada). Fase inicial é **log-only**: só grava `needs_review` em `correcoes_acumuladas.json` (mesmo mecanismo do item 12, `healing_method="click_no_effect"`) quando `AEGIS_CLICK_EFFECT_REGISTER=true` — default `false` até calibrar falsos positivos em projeto piloto. O dedup do item 12 se aplica normalmente (só suprime enquanto o par está `needs_review`/`pending`).

15. **`fallback_selectors` — Recuperação Determinística de Seletor Morto (sem IA):** `getAegisSelectorCandidates()` (JS injetado do recorder) reaproveita a cascata de estratégias de seletor (`data-testid` → `id` → texto/rótulo → tag genérica) e, além do seletor primário, coleta até 3 candidatos de estratégias distintas, cada um validado único no DOM (`queryLength(sel) === 1`) no momento da captura. Os candidatos não-vencedores viram `fallback_selectors` no evento gravado — o `getAegisSelector()` original permanece um wrapper que retorna só `candidates[0]`, comportamento antigo intacto. O Sanitizer propaga `fallback_selectors` para o `plano_execucao.json` (aplicando Padrão Q e dedup contra o primário), e o Code Generator os remove de `_strip_internal_step_fields` antes do prompt — a LLM nunca vê o campo, só o runner. No `TransactionRunner`, `click_resilient`/`fill_resilient` ganham um novo nível ("Nível 2.9") entre a heurística determinística atual e o self-healing cognitivo: quando o seletor primário esgota as tentativas normais, o runner tenta cada `fallback_selector` gravado (timeout curto, ~2s); o primeiro que funcionar resolve o passo com `status="HEALED"` (`healing_method="fallback_selector"`), registrando `needs_review` via o mesmo Sensor F1 do item 12. Diferente do self-healing por IA/coordenada, esses candidatos são estratégias determinísticas alternativas para o mesmo elemento, validadas no momento da gravação — por isso o nível roda mesmo com `strict=True` (não é "adivinhação"; se o elemento genuinamente não existe, os fallbacks também falham e o Padrão R de restart de linha continua funcionando normalmente). Gravações antigas sem o campo mantêm a cadeia idêntica à anterior; bots já compilados funcionam sem regeneração (fallback resolvido pelo runner via plano, mesmo precedente do Padrão R).

16. **Correção Cirúrgica Escopada — Seleção do Passo Real, não do Diagnóstico Sintético:** o Code Generator (`_surgical_correct`) só consegue restringir a edição a um bloco `# [PASSO X]` específico quando a correção pendente tem um `step_id` que existe de verdade no bot compilado. O runner registra dois tipos de passo `FAILED` na mesma transação: o passo real que quebrou (`step_id` do plano, ex. `st_038`) e, logo depois, um diagnóstico sintético de fim-de-transação (`step_id` auto-gerado no formato `auto_N`, quando a IA de diagnóstico analisa a falha global). O Cockpit, ao montar a correção a partir do diagnóstico automático, agora prefere o último passo `FAILED` com `step_id` real sobre o sintético `auto_N` (que nunca existe como âncora no código gerado) — sem essa preferência, o escopo cirúrgico nunca encontrava o bloco e caía silenciosamente no modo full-file, reescrevendo o robô inteiro (e alucinando métodos) a cada correção. Além disso, QA pode marcar manualmente qualquer passo como falho — mesmo que o runner o tenha registrado como `SUCCESS` — via botão **🚩 Falho** na tela de Histórico de Execução do Cockpit (endpoint `POST .../steps/<step_id>/mark-failed`), útil quando o passo tecnicamente "funciona" (sem erro do Playwright) mas produz o resultado errado e nenhum diagnóstico automático seria acionado.
