# 🛡️ Aegis Mentor (rpa-copilot-plugin) - Documentação Técnica e Funcional

Este documento descreve as especificações funcionais e as diretrizes do módulo **Aegis Mentor** (`aegis_mentor`), estruturado como o plugin `rpa-copilot-plugin`. O público-alvo são arquitetos e desenvolvedores RPA responsáveis por mapear processos e implementar padrões de resiliência.

---

## 📖 1. Visão Geral e Propósito

O **Aegis Mentor** funciona como uma **Base de Conhecimento e Playbook Arquitetural** integrado ao framework. Ele não executa código de automação diretamente, mas serve como a fonte de verdade para boas práticas, guias de desenvolvimento e, crucialmente, é consumido pelo **Aegis Code Generator** ([code_generator.py](file:///c:/Projetos/aegis_rpa_suite/aegis_code_generator/code_generator.py)) para injetar regras e padrões de codificação nos prompts enviados às LLMs.

### Filosofia de Design
* **Centralização de Boas Práticas**: Evita que regras de resiliência fiquem espalhadas no código. Elas são descritas em arquivos markdown legíveis que orientam humanos (QA/Desenvolvedores) e agentes de IA.
* **Mapeamento Prévio e Análise**: Fornece um roteiro de perguntas e diagnósticos a serem feitos antes de iniciar qualquer desenvolvimento de robô.

---

## 🏗️ 2. Estrutura de Arquivos

O diretório do módulo está organizado da seguinte forma:

* [plugin.json](file:///c:/Projetos/aegis_rpa_suite/aegis_mentor/plugin.json): Manifesto do plugin declarando metadados, versão e descrição.
* **`skills/`**: Pasta contendo as diretrizes especializadas:
  1. [rpa-copilot-analyst.md](file:///c:/Projetos/aegis_rpa_suite/aegis_mentor/skills/rpa-copilot-analyst.md): Guia focado na fase de análise de DOM, telemetria de rede e diagnósticos iniciais.
  2. [rpa-copilot-coder.md](file:///c:/Projetos/aegis_rpa_suite/aegis_mentor/skills/rpa-copilot-coder.md): Catálogo técnico completo detalhando os 18 padrões de resiliência Aegis.

---

## 🕵️ 3. Mapeamento de Aplicações ([rpa-copilot-analyst.md](file:///c:/Projetos/aegis_rpa_suite/aegis_mentor/skills/rpa-copilot-analyst.md))

Direcionado para a Fase de Análise e Planejamento. Define diretrizes para:

### A. Pipeline Smart Recorder & Sanitizer
* **Voo Manual Instrumentado**: Utilização do gravador inteligente para registrar Shadow DOM, eventos reativos e requisições HTTP de backend.
* **Sanitização de Telemetria**: Procedimento de limpeza de cliques redundantes e deduplicação de logs para a geração do Golden Path.

### B. Protocolo de Diagnóstico Socrático
Protocolo de questionamento ativo para desvendar o comportamento de portais web instáveis:
* **Roteamento de URL**: Identificação de Single Page Applications (SPAs) e iframes ocultos.
* **Anatomia do DOM**: Investigação de IDs dinâmicos, Shadow DOM e elementos homônimos (ambiguidade).
* **Comportamento Assíncrono**: Análise de loadings, spinners e dependências reativas de campos do formulário.

### C. Segurança e Políticas de Isolamento
* **Mapeamento de Variáveis Externas**: Diretriz para mapear credenciais e URLs que obrigatoriamente devem residir em arquivos `.env` locais.
* **Proteção do Core Framework (Isolamento)**: Regra que proíbe a escrita de arquivos temporários, CSVs ou logs na raiz do framework Aegis. Todo artefato específico de um robô deve residir no subdiretório de seu respectivo projeto em `projects/`.

---

## 💻 4. Catálogo de Padrões de Resiliência ([rpa-copilot-coder.md](file:///c:/Projetos/aegis_rpa_suite/aegis_mentor/skills/rpa-copilot-coder.md))

Este arquivo documenta os **18 padrões técnicos de resiliência** que imunizam os robôs contra intermitências. Abaixo estão descritos os padrões mais críticos:

| Padrão | Nome | Problema Resolvido | Estratégia de Implementação |
|---|---|---|---|
| **A** | *Shadow DOM Piercing* | Elementos encapsulados em Web Components. | Utilização do operador nativo `>>` do Playwright no seletor para penetração limpa. |
| **B** | *Network Mappings* | Dropdowns reativos que usam IDs internos do backend no lugar de labels textuais visíveis. | Criação de listener síncrono no evento `"response"` para mapear a tabela de domínio em memória. |
| **C** | *Deadlock Bypass* | Formulários que bloqueiam inputs vizinhos se a validação do campo pai não for disparada. | Ordem de execução estrita: limpar campo dependente, disparar validação do pai e preencher o liberado. |
| **D** | *Forced JS Click* | Elementos em CDK Overlays fora do viewport gerando exceções de scroll. | Cascata automática no SDK: clique forçado → `scrollIntoView` → clique via injeção JS (`evaluate`). |
| **E** | *Loader Sincronização* | Overlays/spinners de carregamento invisíveis que interceptam cliques do robô. | Uso do método `wait_for_selector` com estado `state="hidden"`. |
| **F** | *Reactive Click* | Elementos clicáveis renderizados no DOM antes da ativação de seus bindings JS (cliques perdidos). | Loop de clique reativo curto monitorando alteração de estado ou de URL como condição de parada. |
| **G** | *Stacked Modals* | Sobreposição de múltiplos modais gerando seletores ambíguos. | Utilização do localizador `.last` para forçar interação com o topo do CDK. |
| **H** | *State Guarding* | Falhas silenciosas no início do formulário provocando timeouts em cascata nas etapas seguintes. | Asserções de transição explícitas que abortam a transação imediatamente com erro de negócio legível. |
| **J** | *Async Transitioning* | Wizards lentos com carregamento assíncrono ou toggles que renderizam campos dependentes. | Espera reativa por elementos exclusivos da próxima tela. Evita sleeps fixos. |
| **K** | *Date Pickers* | Calendários fechados que impedem digitação direta. | Seleção total (`Control+A`) + digitação ou injeção DOM direta via JS removendo a propriedade `readonly`. |
| **L** | *File Chooser* | Botões de upload customizados que abrem diálogos nativos do OS. | Uso do gerenciador de contexto `page.expect_file_chooser()` ou `set_input_files` no input nativo. |
| **M** | *Anti-Bot Cadenciado* | Bloqueio de submissão por monitoramento de intervalo entre teclas (avgInterval < 8ms). | Uso do método `runner.fill_human_like` com delay simulado de ~60ms entre caracteres. |
| **N** | *Hover Reveal* | Submenus ocultos que requerem hover no menu pai. | Concatenação de seletores (`Pai >> Filho`) para hover automático no ancestral. |
| **O** | *Custom Selects* | Trigger de dropdowns customizados que geram seletores ambíguos. | Uso do método unificado `runner.select_option_resilient` (abrir + selecionar). |
| **P** | *Autocomplete Order* | Inversão de eventos capturados devido à latência do `blur` do input. | Inversão algorítmica no gerador: digitação → sleep curto para renderização → clique no painel autocomplete. |
| **Q** | *Chained Locators* | Seletores idênticos em tabelas ou grids repetitivos (Strict Mode Violation). | Uso do método `runner.click_chained`/`fill_chained` parametrizados com `parent` (`has_text` dinâmico do dataset) e `child`. |
| **R** | *Flaky Restart* | Passos com intermitência de rede conhecida causando falhas determinísticas no pipeline. | Marcação `"flaky": true` no plano de execução para acionar o reinício completo da transação daquela linha (runner). |

---

## 🎯 5. Diretrizes de Codificação para Produção

O playbook define regras obrigatórias de desenvolvimento para robôs sob o framework Aegis:

1. **Uso Exclusivo do SDK**: Toda automação deve herdar a estrutura do `TransactionRunner` da biblioteca `aegis_runner.runner`, registrando callbacks estruturados e executando interações por meio dos métodos `.click_resilient` e `.fill_resilient`.
2. **Zero Hardcodes**: Proibição de valores literais de teste. CPFs, dados de entrada e parâmetros cadastrais devem ser lidos unicamente a partir do dicionário `row` em runtime.
3. **Tratamento de AJAX e AJAX Auto-fill**: Proibição de Sleeps estáticos cegos. Deve-se aguardar que os inputs dependentes tornem-se habilitados (`is_enabled()`) ou percam placeholders de carregamento antes de interagir.
4. **Homologação Visual**: Integração com a ferramenta de comparação visual `verify_visual.py` para contrastar as telas do robô com as capturas do gravador, exigindo uma similaridade mínima de 85% para a publicação.
