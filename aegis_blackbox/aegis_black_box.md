# 🛡️ Aegis BlackBox - Gravador de Voo (Fase 1)

O módulo `aegis_blackbox` é o componente responsável pela **Fase 1 (Gravação de Sessão)** do pipeline do Aegis RPA Suite. Ele atua como um "Gravador de Voo", capturando de forma discreta e transparente todas as interações de um usuário humano com uma aplicação web (cliques, preenchimentos, seletores físicos, payloads de rede, etc.). 

Esses dados de telemetria bruta servem de base para as fases seguintes de sanitização, compilação semântica e geração de código de robôs resilientes.

---

## 1. Arquitetura Geral e Fluxo de Dados

A arquitetura do BlackBox Recorder baseia-se em um modelo híbrido e bidirecional de execução que conecta um processo Python (utilizando Playwright) a um agente de monitoramento em JavaScript injetado diretamente no contexto de renderização do navegador.

```
+-----------------------------------------------------------------------------------+
|                            Aegis RPA Host (Python)                                |
|                                                                                   |
|  +--------------------+      +--------------------+      +---------------------+  |
|  |   AegisRecorder    | <--> | start_control_srv  | <--> |  CognitiveGateway   |  |
|  | (Playwright Engine)|      |  (HTTP REST Port)  |      |   (Audio Transcr)   |  |
|  +--------------------+      +--------------------+      +---------------------+  |
+------------^---------------------------^----------------------------^-------------+
             |                           |                            |
  Playwright | Bidirecional              | REST HTTP API              | ctypes / MCI
  Context    | (expose_function)         | (localhost:9900)           | WaveAudio
             v                           v                            v
+-----------------------------------------------------------------------------------+
|                         Microsoft Edge Headed Browser                             |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | JS Agent (JS_MINIMAL_LISTENERS)                                             |  |
|  |                                                                             |  |
|  | - Event Listeners (click, change, blur)   - Selection Cascade (Aegis V4)    |  |
|  | - Anti-Bot Detector (monkey-patch)        - UI Indicator (Shadow DOM LED)   |  |
|  +-----------------------------------------------------------------------------+  |
|                                                                                   |
|                              DOM (Página Alvo)                                    |
+-----------------------------------------------------------------------------------+
```

### Mecanismo de Comunicação Bidirecional
1. **Injeção do Agente JS (`JS_MINIMAL_LISTENERS`)**: O script de monitoramento é injetado no contexto global de todas as abas e frames por meio do método `add_init_script` do Playwright.
2. **Exposição de Callbacks Python**: O Python expõe três funções nativas ao escopo do browser por meio do método `expose_function`:
   - `pythonRecordAction(event_json)`: Recebe eventos de clique, preenchimento e varreduras de campos.
   - `pythonToggleVoice()`: Gerencia o estado de gravação de voz e aciona o hardware de áudio do sistema operacional.
   - `pythonAddAnnotation(text)`: Registra anotações de negócio enviadas pela interface web.
3. **Fluxo de Entrada de Dados**: Ações no DOM disparam listeners em fase de captura no JavaScript, que geram seletores, normalizam os dados e os enviam de volta para o processo Python.

---

## 2. O Agente JavaScript Injetado (`JS_MINIMAL_LISTENERS`)

O agente JavaScript é o "coração" do monitoramento em tempo de execução no navegador. Suas principais responsabilidades técnicas e heurísticas incluem:

### 2.1. Normalização de Elementos (`resolveAegisTargetElement`)
Evita ruídos comuns de gravação causados por cliques em elementos internos não interativos (ex: tags `path` de SVGs, ícones `mat-icon`, ou spans internos de formatação).
- **Redirecionamento de SVG**: Se o clique ocorrer em um elemento `path`, o alvo é redirecionado para a raiz `<svg>`.
- **Escalada para Interativo**: Tenta localizar o ancestral interativo mais próximo (`closest`) usando um seletor restrito a botões, links, abas, checkboxes, dropdowns (`mat-option`, `.mat-menu-item`, etc.).
- **Atributos de Teste**: Se não houver elemento interativo explícito, busca o ancestral mais próximo que possua um atributo estável de testes (ex: `data-testid`, `data-qa`).

### 2.2. Motor de Seletores Aegis V4 (Cascata de Prioridade)
Ao interagir com um elemento, o agente calcula um seletor primário executando uma cascata de 5 estratégias ordenadas de forma estrita em `AEGIS_SELECTOR_STRATEGY_PROVIDERS`:

1. **`data-testid`**: Atributo ideal de testes. Busca sequencialmente por `data-testid`, `data-test-id`, `data-test` e `data-qa`.
2. **`id` Estável**: Captura ids estáveis do DOM. Ignora ativamente ids dinâmicos contendo padrões numéricos longos (ex: `/\\d{8,}/`) ou gerados automaticamente por frameworks (ex: `mat-input-`, `mat-select-`).
3. **Texto Visível Semântico**: Se o elemento for um botão, link ou possuir um `role` interativo, captura seu texto interno limpo limitando-o a 45 caracteres, gerando seletores com a pseudo-classe do Playwright `:has-text(...)` (ex: `button:has-text('Confirmar')`).
4. **Universal Form Field Solver**: Se for um campo de entrada (`input`, `textarea`, `select`), tenta associar o campo ao seu rótulo (`label`) correspondente na página de 5 formas:
   - Rótulo explícito via atributo `for` casado com o `id` do elemento.
   - Rótulo implícito (elemento aninhado em uma tag `<label>`).
   - Rótulo irmão direto (tag `<label>` imediatamente anterior no DOM).
   - Componentes Angular Material (`mat-form-field` contendo `.mat-form-field-label`).
   - Rótulo estrutural de grupos de formulário do Bootstrap ou Tailwind (`.form-group`, `.field`, etc.).
5. **Tag Genérica**: Fallback final baseado no nome da tag em caixa baixa (ex: `input`).

### 2.3. Algoritmo de Unicidade e Climbing de Ancestrais (`makeAegisSelectorUnique`)
Após gerar o seletor base com uma das estratégias acima, o agente valida se ele é único no escopo do documento (ou do Shadow Root).
- Se `queryLength(selector) > 1` (o seletor é ambíguo), o algoritmo sobe a árvore DOM (até o limite de 5 níveis) anexando prefixos de ancestrais estáveis (IDs estáveis, tags estruturais como `form`, `table`, `article`, ou classes estruturais como `.card`, `.container`, `.grid`).
- Se o climbing falhar em garantir a unicidade, o gravador emite um aviso silencioso no console e marca o evento com a propriedade `selector_ambiguous: true`.

### 2.4. Seletores Encadeados (Chained Locators) e getAegisParentData
Quando um elemento interativo possui um seletor inerentemente ambíguo que não pode ser resolvido apenas subindo tags simples, o método `getAegisParentData` entra em ação:
- Ele detecta a ambiguidade e sobe a hierarquia em busca de um ancestral estável (ex: um container estrutural de linha de tabela ou card).
- Retorna um dicionário `{ selector: parent_selector, has_text: text_inside_parent }` que permite ao robô final ancorar sua busca na estrutura hierárquica do DOM (ex: `locator(parent).locator(child)`), que é muito mais resiliente do que caminhos absolutos XPath.

### 2.5. Geração de Múltiplos Candidatos (Fallback Selectors)
O método `getAegisSelectorCandidates` gera até 3 candidatos de seletores baseados em estratégias distintas (ex: candidato 1 usando `id`, candidato 2 usando rótulo/texto, candidato 3 usando tag). 
- O candidato no índice `[0]` é sempre o seletor primário.
- Os candidatos seguintes são validados como estritamente únicos na página no momento da captura e gravados no array `fallback_selectors`. Em tempo de execução, se o seletor primário falhar, o robô consome essa lista determinística para autocorreção automática.

### 2.6. Lazy-Baseline (Deduplicação de Inputs Flashing)
Diferente de gravadores ingênuos que capturam cada tecla digitada (gerando centenas de eventos parciais), o Aegis BlackBox utiliza uma estratégia preguiçosa (lazy):
- Captura o valor final do campo apenas nos eventos de `change`, `blur`, `click` de navegação ou `beforeunload`.
- **Baseline Preguiçosa**: A primeira vez que um campo recebe foco ou é escaneado, o seu valor atual vira uma baseline oculta. O evento de alteração real só é emitido se o valor final for modificado em relação a essa baseline. Isso evita capturar valores pré-preenchidos pelo servidor ou hidratados de forma assíncrona por SPAs.

### 2.7. Interface Visual (Micro-LED Indicator via Shadow DOM)
O gravador injeta uma pequena interface visual discreta no canto superior direito do navegador.
- **Shadow DOM Fechado**: Injetado dentro de um `ShadowRoot` com modo `closed` para que as folhas de estilo da página alvo (CSS global) não quebrem o layout do indicador, e para evitar que seletores do próprio robô interceptem o indicador.
- **LED Indicador**: Exibe `AEGIS REC` pulsando vermelho quando a gravação está ativa, e `PAUSADO` em verde quando desativada.

---

## 3. Detecções Inteligentes de Fluxo

### 3.1. Anti-Bot Detector (Detecção de Cadência Humana)
Muitos sites financeiros e governamentais utilizam scripts de telemetria anti-bot (como Zone.js ou Angular Material) que registram eventos de escuta de teclado (`keydown`/`keyup`) para monitorar a digitação. 
- O BlackBox realiza um monkey-patch na propriedade prototype de `EventTarget.prototype.addEventListener`.
- Sempre que a página alvo tenta registrar um listener de `keydown` ou `keyup` em um campo de texto, o seletor do campo é armazenado no cache `window.__aegis_keydown_fields__`.
- Durante a persistência dos dados, os campos presentes nesse cache recebem o atributo `"fill_strategy": "HUMAN_LIKE"` no dicionário. Isso instrui o robô final a simular a digitação caractere por caractere (com delay variável aleatório), contornando bloqueios automáticos de segurança.

### 3.2. Varredura Cooperativa (Periodic DOM Scan)
Para capturar dados de campos que foram preenchidos pelo usuário mas não acionaram diretamente os eventos clássicos do DOM de clique/blur (ou que foram autocompletados por gerenciadores de senhas), o processo Python roda uma varredura paralela a cada 3 segundos:
- Executa a função `scan_fields_python` via Playwright.
- Mapeia todos os inputs visíveis na viewport, extrai seus valores e emite eventos sintéticos do tipo `scan_field` para preencher as lacunas da gravação.

---

## 4. Anotações de Negócio e Transcrição de Voz (MCI)

### 4.1. Anotações de Negócio (`Ctrl+Shift+A`)
Pressionar `Ctrl+Shift+A` exibe uma modal escura e estilizada sobreposta na página (Anotação de Negócio Aegis).
- Permite ao desenvolvedor documentar decisões de negócio ou regras de validação para passos específicos diretamente na telemetria.
- **Detecção de Extrações (Outputs)**: Anotações com a sintaxe `extract:<selector>:<semantic_key>` (ex: `extract:.proposta-codigo:numero_proposta`) são interpretadas e cadastradas diretamente no dicionário de saídas (`schema_outputs`), gerando campos que o robô lerá para extrair dados da tela após a execução do fluxo.

### 4.2. Gravação de Voz Inteligente (`Ctrl+Shift+V`)
Facilita o mapeamento de processos legados ao permitir que o usuário grave observações narradas enquanto executa as tarefas no navegador.
- **Gravação de Áudio Nativa (MCI)**: No Windows, o Aegis interage diretamente com as APIs de multimídia do sistema operacional via `ctypes.windll.winmm`. 
- Grava áudio em formato waveaudio codificado em 16-bit, 16kHz, Mono (configuração otimizada para modelos de IA como Whisper).
- Ao finalizar a gravação (pressionando `Ctrl+Shift+V` novamente), o arquivo `.wav` é salvo na pasta de destino do projeto e submetido ao `CognitiveGateway` (`aegis_runner/cognitive_fallback`) para transcrição. A transcrição resultante é acoplada ao evento da telemetria sob a chave `voice_annotation`.

---

## 5. API de Controle REST HTTP

O gravador embarca um servidor HTTP leve (`AegisControlHandler` herdado de `BaseHTTPRequestHandler`) rodando em uma thread daemon separada na porta `9900` (ou superior caso a porta esteja em uso). Esta API permite o controle remoto total da gravação pelo Cockpit Orchestrator ou scripts externos.

### Endpoints Disponíveis

| Endpoint | Método | Parâmetros | Descrição |
|---|---|---|---|
| `/api/status` | GET | Nenhum | Retorna o status atual da gravação (pausada/ativa, contagem de eventos, etc.) |
| `/api/pause` | GET | Nenhum | Pausa o monitoramento de eventos na página (muda indicador para verde) |
| `/api/resume` | GET | Nenhum | Resume o monitoramento de eventos na página (muda indicador para vermelho) |
| `/api/scenario`| GET | `name` | Altera o cenário de testes ativo na gravação |
| `/api/annotation` | GET | `text` | Adiciona uma anotação de negócio/regra ao fluxo atual |
| `/api/voice/start` | GET | Nenhum | Dispara o início da gravação de voz pelo microfone |
| `/api/voice/stop` | GET | Nenhum | Para a gravação de voz e retorna a transcrição de texto obtida via LLM |
| `/api/scan` | GET | Nenhum | Força uma varredura imediata do DOM para ler campos ativos |
| `/api/finish` | GET | Nenhum | Encerra a gravação de forma limpa, compilando os arquivos no disco |

---

## 6. Persistência de Dados e Fusão Inteligente de Schemas

Ao finalizar uma sessão (via API, atalho console `f` ou fechamento do browser), o gravador consolida a telemetria em disco por meio de seu pipeline de limpeza e fusão:

```
[Events Buffer] ──> [Filtro de Redundâncias] ──> [Fusão com Dicionário Anterior] ──> [Escrita em Disco]
                                                        (dicionario.json)
                                                                 │
                                                                 └──> gravacao.json
                                                                 └──> dicionario.json
                                                                 └──> dataset_inicial.json
                                                                 └──> template.csv
```

### 6.1. Filtro de Redundâncias
Varre o buffer de eventos de trás para frente para eliminar preenchimentos redundantes. Se um campo foi preenchido múltiplas vezes antes de uma ação de navegação (clique em botão avançar, submit, etc.), apenas o último valor final do campo é preservado.

### 6.2. Algoritmo de Auto-Preservação (Fusão de Dicionários)
Para evitar que uma regravação de fluxo delete traduções semânticas de campos feitas anteriormente por revisores de código ou pelo Sanitizer (ex: se o seletor `#usr-01` já foi mapeado como `usuario_login` no `dicionario.json` existente):
1. O gravador carrega o `dicionario.json` existente do projeto e mapeia a relação `selector -> chave_semantica_antiga`.
2. Durante a geração do novo dicionário, se o seletor físico do elemento gravado bater exatamente com o seletor antigo, a chave semântica amigável é preservada.
3. Se houver desvios ou campos sem casamento (porque o site mudou sua estrutura ou um elemento novo foi injetado), o gravador gera chaves brutas normalizadas e emite um warning de atenção no terminal recomendando re-sanitização.

### 6.3. Artefatos de Saída Gerados

Tudo é gravado na pasta de destino definida no parâmetro `--output-dir` do projeto:

- `gravacao.json`: Arquivo contendo a linha do tempo bruta de cliques, preenchimentos, dados de rede (API AJAX interceptada) e anotações ordenadas por timestamp.
- `dicionario.json`: Mapeamento estruturado de cada campo (inputs e outputs) contendo seus seletores físicos, estratégias de preenchimento, pontuação de confiança de seletores (`confidence`) e regras básicas de validação.
- `dataset_inicial.json`: Dataset inicial no formato JSON contendo uma linha com todos os dados digitados pelo usuário durante a gravação (mapeados sob suas chaves semânticas).
- `template.csv`: Arquivo CSV de entrada estruturado com os cabeçalhos das chaves do dicionário para preenchimento de lotes pelo usuário.
- `browser_console.log`: Histórico técnico completo de saídas de console e erros capturados do navegador web para diagnósticos forenses de execução.

---

## 7. Simulador E2E Legado (`run_auto_simulation`)

O arquivo `recorder.py` mantém uma função legada chamada `run_auto_simulation` utilizada para validar o funcionamento do gravador de forma autônoma:
- **Preenchimento Reativo Local**: Simula a entrada de textos disparando manualmente eventos `'input'` e `'change'` no DOM para disparar reatividade de frameworks como Angular e React.
- **Abertura Resiliente de Dropdowns**: Contorna a latência de carregamento de overlays CDK Angular clicando no trigger, aguardando a renderização no portal da sobreposição, varrendo as opções visíveis e selecionando a correta sem depender de coordenadas físicas.
- **Validação de Token SMS**: Simula o preenchimento de tokens SMS de segurança e lida com retentativas de validações falhas comuns em portais corporativos.
