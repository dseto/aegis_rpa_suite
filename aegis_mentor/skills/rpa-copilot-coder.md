---
name: rpa-copilot-coder
description: "Expert RPA Coder for resilient, static, headed, and zero-LLM web/desktop automations. ACTIVATE this skill when you need to write, refactor, debug, or optimize Playwright (Python) scripts, resolve selector timeouts, handle deadlocks, or apply resilience design patterns."
---

# 💻 Antigravity RPA Coder: Engenharia e Padrões de Resiliência RPA

Este documento define os padrões arquiteturais de desenvolvimento, o catálogo de resiliência técnica e as regras de codificação baseadas em Playwright + Python para imunizar robôs contra intermitências de interface e erros de sistemas complexos.

---

## 🎨 1. Catálogo de Padrões de Resiliência (Zero-LLM Runtime)

Ao gerar ou refatorar scripts de automação, utilize os padrões abaixo no código-fonte Python para garantir que a execução seja 100% resiliente:

### 🧬 Padrão A: Piercing Nativo de Shadow DOM
* **Problema:** Elementos encapsulados em barreiras Shadow DOM que não respondem a seletores globais comuns.
* **Solução:** Use o operador nativo `>>` do Playwright no próprio seletor para penetrar a árvore do Shadow DOM de forma limpa, sem usar trechos redundantes de JS.
* **Exemplo:**
  ```python
  page.click("#shadow-filters-host >> input[value='CSV']")
  ```

### 📁 Padrão B: Interceptador de APIs de Rede (Network Mappings)
* **Problema:** Dropdowns reativos (Angular/React) que exibem labels legíveis ao usuário na tela, mas requerem a passagem de IDs de backend misteriosos na automação, sem APIs públicas para tradução imediata.
* **Solução:** Crie um listener de eventos de rede síncrono para interceptar a resposta JSON da API do portal em memória e realizar a tradução dinâmica no dicionário antes de interagir com a interface.
* **Exemplo:**
  ```python
  domain_mappings = {}
  def handle_response(response):
      if "api/v1/options-list.json" in response.url:
          data = response.json()
          for item in data:
              domain_mappings[item["id"]] = item["nome_exibicao"]
  page.on("response", handle_response)
  # Interação:
  target_label = domain_mappings.get("827", "Fallback")
  page.click(f".mat-option:has-text('{target_label}')")
  ```

### 🚦 Padrão C: Sequência Cognitiva de Desvio de Deadlock
* **Problema:** Formulários reativos onde o preenchimento de um campo bloqueia permanentemente os inputs vizinhos caso a validação do campo pai não seja disparada formalmente.
* **Solução:** Aplique a ordem estrita de desvio: limpe os campos dependentes, force o acionamento de eventos de mudança do campo pai (como `blur` ou cliques de validação) e só então preencha o novo campo liberado.
* **Exemplo:**
  ```python
  page.fill("#input-dependent", "") # Limpa campo dependente
  page.click("#btn-validate-parent") # Dispara validação do campo pai
  page.fill("#input-new-field", "Valor") # Preenche campo liberado
  ```

### 👁️ Padrão D: Clique Forçado via Viewport Evaluation
* **Problema:** Menus de CDK Overlay posicionados absolutamente que estouram os limites físicos visíveis da tela (viewport bounds), gerando exceções de scroll no Playwright.
* **Solução:** O `TransactionRunner` já implementa uma cascata automática de 4 estratégias no método `select_option_resilient`:
  1. **Playwright click** (`force=True`) — se o elemento estiver no viewport
  2. **Scroll overlay no viewport** (`scrollIntoView`) + retry
  3. **JS evaluate** (`el.click()`) — ignora viewport completamente
  4. **Zoom 70%** (`document.body.style.zoom`) + retry — para portais com CDK overlay mal posicionado
* **Exemplo de código gerado (nenhuma ação necessária — o runner já trata automaticamente):**
  ```python
  runner.select_option_resilient(page, dropdown_label="...", option_text=row.get("...", ""), ...)
  ```

### ⏱️ Padrão E: Sincronização Assíncrona de Loaders Globais
* **Problema:** Spinners flutuantes que bloqueiam cliques mesmo com os elementos de destino já visíveis, provocando intermitência (flakiness).
* **Solução:** Crie rotinas de espera explícita para que o elemento do loader passe para o estado oculto antes de prosseguir com interações.
* **Exemplo:**
  ```python
  page.wait_for_selector("#global-loader", state="hidden", timeout=7000)
  ```

### 🔁 Padrão F: Clique Reativo com Checagem de Efeito Colateral
* **Problema:** Botões carregados no DOM antes que seus listeners de eventos Javascript (Angular/React bindings) estejam ativos, resultando em cliques "perdidos" que não avançam o estado da aplicação.
* **Solução:** Implemente um loop curto de repetição estruturado que monitora um efeito colateral (mudança de URL ou visibilidade de um novo elemento de destino) antes de parar de clicar.
* **Exemplo:**
  ```python
  start = time.time()
  while time.time() - start < 10:
      try:
          page.click("#btn-next", force=True)
      except:
          pass
      time.sleep(0.5)
      if page.locator("#step-2-indicator").is_visible(timeout=200):
          break
  ```

### 🥪 Padrão G: Modais Empilhados Ambíguos
* **Problema:** Sobreposição de múltiplos diálogos modais CDK simultâneos que geram seletores ambíguos ou cliques invisíveis nas janelas sob a camada de topo.
* **Solução:** Adicione o modificador `.last` nos seletores dos modais no Playwright para interagir estritamente com o modal ativo do topo do CDK.
* **Exemplo:**
  ```python
  dialog_topo = page.locator(".mat-dialog-container").last
  dialog_topo.locator("button:has-text('Confirmar')").click(force=True)
  ```

### 🛡️ Padrão H: Proteção de Estado e Asserção de Transição (State Guarding)
* **Problema:** Um erro não capturado no início do formulário impede o avanço real da tela, mas o robô prossegue cegamente tentando preencher os passos posteriores, gerando múltiplos timeouts secundários em cascata.
* **Solução:** Adicione validações assertivas explícitas logo após transições de etapa. Aborte a execução imediatamente com um erro técnico específico se a transição não ocorrer no tempo programado.
* **Exemplo:**
  ```python
  page.click("#btn-submit-step-1")
  try:
      page.locator("#step-2-container").wait_for(state="visible", timeout=4000)
  except:
      raise RuntimeError("Erro crítico: falha cadastral no Passo 1 impediu avanço.")
  ```

### ⏱️ Padrão J: Sincronização de Transições Assíncronas de API (Async Step Transitioning)
* **Problema:** Transições de wizard que realizam chamadas lentas de backend antes de renderizar a interface de destino, gerando erros se a interação prosseguir imediatamente.
* **Solução:** Nunca insira sleeps estáticos fixos pós-clique de transição. Utilize a espera explícita `wait_for` apontando para um elemento visual exclusivo e invariável da tela subsequente.
* **Exemplo:**
  ```python
  page.click("#btn-calculate")
  page.locator("h2:has-text('Resultado Calculado')").wait_for(state="visible", timeout=15000)
  ```
* **Regra estendida — checkbox/toggle que revela campo condicional na MESMA tela:** O mesmo risco existe quando um clique em checkbox/toggle/radio faz o Angular (ou framework equivalente) renderizar um campo dependente (ex.: marcar "Possui Blindagem?" faz aparecer o dropdown "Nível da Blindagem"), mesmo sem navegação de página. Chamar `select_option_resilient`/`click_resilient`/`fill_resilient` para esse campo dependente **imediatamente** após o clique do checkbox é uma falha intermitente conhecida (bug real confirmado: st_034 do portal_segura — dropdown condicional não tinha renderizado a tempo em ~1 a cada N execuções, mesma tela funcionando normalmente no retry). **Sempre** insira um polling `wait_for`/loop de espera (contagem de `page.locator(...).count() > 0`, timeout generoso ~10-15s) pelo campo dependente ANTES de chamar o runner para interagir com ele — não confie que o helper resiliente absorve essa espera sozinho, pois seus timeouts internos por seletor são curtos e não acumulam entre tentativas.

### 📅 Padrão K: Manipulação de Objetos Tipo Calendário (Date Pickers)
* **Problema:** Calendários reativos ou fechados em modais que barram ou dificultam o preenchimento manual via teclado e exigem navegações extensas de mês/ano, gerando timeouts.
* **Solução:** Sempre priorize o preenchimento direto via teclado limpando e selecionando tudo com `Control+A` antes de digitar. Caso o campo esteja bloqueado com a flag `readonly` ou ignore eventos normais do teclado, contorne-o usando injeção direta de javascript (`evaluate`) para setar o valor no nó DOM e disparar manualmente os eventos `input` e `change`.
* **Exemplo:**
  ```python
  # Abordagem 1: Preenchimento direto com seleção total (Keyboard Bypass)
  input_selector = "input[name='data_nascimento']"
  page.click(input_selector)
  page.press(input_selector, "Control+A")
  page.fill(input_selector, "25/05/2026")
  page.press(input_selector, "Tab") # Confirma o evento change

  # Abordagem 2: Remoção de flag readonly e injeção (DOM Property Evaluation)
  page.evaluate("""() => {
      const el = document.querySelector("input[name='data_nascimento']");
      el.removeAttribute("readonly");
      el.value = "2026-05-25";
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
  }""")
  ```

### 📤 Padrão L: Upload de Arquivos via File Chooser e Injeção DOM
* **Problema:** Botões de upload e drag-and-drop customizados que ocultam o elemento `<input type="file">` ou dependem da abertura de diálogos nativos do sistema operacional, os quais o Playwright não consegue clicar diretamente.
* **Solução:** Capture o disparador nativo de arquivos usando o gerenciador de contexto `page.expect_file_chooser()` ou atue diretamente injetando os caminhos dos arquivos no locator do input nativo oculto (`set_input_files`).
* **Exemplo:**
  ```python
  # Abordagem 1: Interceptando o File Chooser do Navegador
  with page.expect_file_chooser() as fc_info:
      page.click("#custom-drag-drop-area") # Botão ou área que abre o diálogo
  file_chooser = fc_info.value
  file_chooser.set_files("C:/workspace/comprovante.pdf")

  # Abordagem 2: Atribuição Direta em Input do tipo file (oculto)
  page.set_input_files("input[type='file']", "C:/workspace/comprovante.pdf")
  ```

### 🧠 Padrão M: Digitação Cadenciada em Campos com Detecção Anti-Bot Comportamental
* **Problema:** Portais modernos (Angular Zone.js, React Hook Forms, sistemas bancários e governamentais) monitoram eventos `keydown` e calculam o intervalo médio entre teclas. Se o robô usar `.fill()` ou `keyboard.type()` sem delay, o campo registra `keystrokes = 0` ou `avgInterval < 8ms` e marca o campo como não confiável — mantendo o botão Avançar/Submit **desabilitado indefinidamente**, mesmo com o formulário preenchido corretamente. Funciona manualmente, quebra no robô — sem mensagem de erro.
* **Detecção automática:** O Recorder do Aegis detecta campos com listeners `keydown`/`keyup` ativos via interceptação de `addEventListener` e marca `"fill_strategy": "HUMAN_LIKE"` no `dicionario.json`. O Sanitizer reporta `ANTI-BOT COMPORTAMENTAL DETECTADO` no `relatorio.md`.
* **Regra OBRIGATÓRIA de geração de código:**
  > ⚠️ **CRÍTICO:** Ao ler o `dicionario.json` para gerar o script do robô, você DEVE verificar o campo `fill_strategy` de cada entrada. Se o valor for `"HUMAN_LIKE"`, você é PROIBIDO de usar `.fill()`, `keyboard.type()` ou `evaluate()` direto nesse campo. Use EXCLUSIVAMENTE `runner.fill_human_like()` ou `runner.fill_resilient(..., strategy="HUMAN_LIKE")`. Esta regra é inegociável e tem prioridade sobre qualquer outra otimização de velocidade.
* **Solução:** Use `runner.fill_human_like()` do `TransactionRunner`, que digita tecla por tecla com `time.sleep()` real entre cada keystroke, garantindo que o `performance.now()` do browser registre intervalos reais (≥ 60ms).
* **Exemplo de código gerado corretamente:**
  ```python
  # ✅ CORRETO — campo com fill_strategy: HUMAN_LIKE no dicionario.json
  # O avgInterval medido pelo Zone.js será ~60ms > threshold de 8ms
  runner.fill_human_like(
      page=page,
      selector="[data-testid='client-document-input']",
      text_val=row.get("cpf_do_cliente", ""),
      delay_ms=60
  )

  # Aguarda o AJAX do backend preencher campos dependentes (ex: nome auto-fill)
  time.sleep(2.0)

  # ✅ CORRETO — verifica se o nome foi preenchido pelo AJAX antes de digitar
  nome_atual = page.locator("[data-testid='client-name-input']").input_value()
  if not nome_atual or nome_atual.strip() == "":
      # Só digita se o AJAX não preencheu — redigitar reseta o trust state!
      runner.fill_human_like(
          page=page,
          selector="[data-testid='client-name-input']",
          text_val=row.get("nome_do_cliente", ""),
          delay_ms=60
      )
  ```
* **Exemplo de código gerado INCORRETAMENTE (nunca faça isso para campos HUMAN_LIKE):**
  ```python
  # ❌ ERRADO — .fill() não dispara keydown → keystrokes = 0 → botão bloqueado
  page.fill("[data-testid='client-document-input']", cpf_val)

  # ❌ ERRADO — keyboard.type() sem time.sleep() → avgInterval < 1ms → bloqueado
  page.locator("[data-testid='client-document-input']").click()
  page.keyboard.type(cpf_val)

  # ❌ ERRADO — evaluate() bypassa eventos de teclado completamente
  page.evaluate(f"document.querySelector('...').value = '{cpf_val}'")
  ```
* **Regra de ouro para campos de identidade (mesmo sem dicionario.json disponível):**
  - CPF, CNPJ, RG, Senha, Token SMS → **sempre** `fill_human_like()` em portais corporativos/gov
  - Após AJAX auto-fill (nome preenchido pelo backend) → **não redigitar** o campo preenchido automaticamente
  - `delay_ms` recomendado: **60ms** (confortável e acima de todos os thresholds conhecidos)

### 🪟 Padrão N: Detecção de Menus Suspensos / Dropdowns (Hover-to-Reveal)
* **Problema:** Itens de menu ocultos em dropdowns (especialmente com classes como `.sub-menu`, `.dropdown-menu`, ou similares na telemetria) que precisam de um evento hover no menu pai para se tornarem visíveis e clicáveis.
* **Solução:** O compilador de IA deve automaticamente identificar quando um seletor pertence a um submenu e dividi-lo em duas partes usando o operador de encadeamento ` >> ` (ex: `Pai >> Filho`), para que o `TransactionRunner.click_resilient` execute o hover automático no elemento pai antes de clicar no filho.
* **Exemplo:**
  - Seletor original na telemetria: `#menu-item-28904 .sub-menu #menu-item-141846 a`
  - Seletor compilado resiliente: `#menu-item-28904 >> #menu-item-141846 a`

### 🔽 Padrão O: Interação com Custom Selects / Dropdowns Customizados
* **Problema:** Portais modernos (Angular Material, Vuetify, Bootstrap Vue, etc.) não usam `<select>` nativo HTML. Em vez disso, usam `<div>` ou `<span>` customizados como trigger do dropdown. Na gravação, o clique no trigger gera um seletor genérico como `div` (com texto "Selecione" ou vazio), que casa com N elementos na página, tornando a automação frágil.
* **Detecção:** Na telemetria, identifique pares de eventos consecutivos onde:
  - Evento N: clique em `div`/`span` genérico com texto "Selecione" ou similar.
  - Evento N+1: clique em `[role='option']:has-text('...')` ou `.mat-option:has-text('...')`.
  Estes pares representam a abertura e a seleção de um custom dropdown.
* **Solução:** Use `runner.select_option_resilient()` que encapsula ambos os passos (abrir + selecionar):
  ```python
  runner.select_option_resilient(
      page,
      dropdown_label="Sexo",
      option_text=row.get("sexo_cliente", ""),
      original_coords_trigger=(0.4531, 0.6782),
      original_coords_option=(0.4617, 0.7420)
  )
  ```
* **Regra OBRIGATÓRIA:** Quando a telemetria apresentar um clique em seletor `div` com texto "Selecione" (ou similar) seguido imediatamente de um clique em uma opção (`[role='option']:has-text(...)` ou `.mat-option`), você DEVE substituir ambos os passos por uma única chamada a `runner.select_option_resilient()`. Nunca use `runner.click_resilient(page, selector="div", ...)` para abrir dropdowns customizados.

### 🔍 Padrão P: Correção de Inversão de Eventos em Autocomplete
* **Problema:** Em campos de busca com autocomplete (Angular Material, etc.), o recorder pode registrar o clique na opção da lista (`#mat-autocomplete-panel-... div`) *antes* de registrar o preenchimento do input (`fill` na busca). Isso ocorre porque o evento de `blur` ou `change` do input que coleta o valor de digitação só dispara após o clique na opção que remove o foco do input.
* **Detecção:** Na telemetria, se houver um clique em uma opção de autocomplete (`#mat-autocomplete-panel-...` ou similar) seguido imediatamente por um preenchimento (`FILL`) de um input de busca com o mesmo valor ou valor correspondente.
* **Solução:** O compilador deve **inverter** a ordem de execução desses dois passos no script Python. A automação deve sempre:
  1. Preencher o input de busca (usando `runner.fill_resilient` com estratégia DIRECT ou HUMAN_LIKE conforme o dicionário).
  2. Aguardar brevemente (ex: `time.sleep(0.5)`) para que a lista de opções seja renderizada/filtrada.
  3. Clicar na opção correspondente usando `runner.click_resilient`.
* **Exemplo de código correto:**
  ```python
  # Primeiro: Preenche o campo de busca
  runner.fill_resilient(page, selector="input[placeholder='Pesquisar Marca...']", text_val=row.get("marca_veiculo", ""), target_description="Campo 'Pesquisar Marca...'", strategy="DIRECT")
  time.sleep(0.5) # Aguarda renderização
  # Segundo: Clica na opção correspondente que apareceu
  runner.click_resilient(page, selector="#mat-autocomplete-panel-marca div:has-text('Hyundai')", target_description="Opção 'Hyundai'", original_coords=(0.0984, 0.7614))
  ```

### 🧬 Padrão Q: Locator Encadeado por Hierarquia (Chained Scope)
* **Problema:** Seletores genéricos (`.mat-select-grid-trigger`, `button:has-text('Comprar')`) que casam com múltiplos elementos em estruturas repetitivas como tabelas, grids e cards, gerando erros de strict mode violation ou cliques no elemento errado.
* **Detecção automática:** O Recorder Aegis detecta ambiguidade no seletor base e armazena o ancestral estável como um objeto `parent` estruturado no evento do `gravacao.json`. No `relatorio.md`, a presença do parent é indicada pelo prefixo **`⬆`** na coluna "Seletor Resiliente Sugerido". Exemplo:
  ```
  | Passo | Tipo | Elemento | Seletor Resiliente Sugerido | Valor / Ação |
  | 5 | `CLICK` | `div` | ⬆ `.mat-row[RCV - Danos Corporais 150.000,00]` ➜ `div` | Clique em: '150.000,00' |
  ```
* **Regra OBRIGATÓRIA de geração de código:**
  > ⚠️ Ao ler o `relatorio.md` para gerar o script do robô, você DEVE verificar se a coluna "Seletor Resiliente Sugerido" de cada passo contém o prefixo `⬆`. Se sim, use EXCLUSIVAMENTE `runner.click_chained()` ou `runner.fill_chained()`. Se não, use os métodos planos (`click_resilient`/`fill_resilient`). Esta regra é binária — zero ambiguidade. Para construir os dicionários `parent` e `child`, extraia o seletor do pai (entre `⬆` e `➜`) e o seletor do filho (após `➜`).
* **Solução:** Use `runner.click_chained()` com os dicionários `parent` e `child`. O runner resolve o pai com Playwright `.filter(has_text=...)` nativo e encadeia o filho.
* **Regra ANTI-HARDCODE para `has_text` (causa raiz — aplicar ANTES de cogitar `strict`):** O `has_text` gravado pelo Recorder é o texto LITERAL capturado na sessão de gravação. Se esse texto contém um valor gerado pelo sistema-alvo em runtime (ex.: número de proposta/protocolo/pedido criado dinamicamente pelo próprio portal, que muda a cada execução e NUNCA existe no dataset de entrada) misturado com valores ESTÁVEIS do dataset (nome do cliente, CPF, placa), você NÃO PODE copiar o texto gravado verbatim — isso viola a regra de Zero Hardcodes e faz o `parent_locator` nunca resolver em execuções futuras (o valor dinâmico gravado nunca se repete). Nesse caso, reconstrua `has_text` usando SOMENTE os fragmentos estáveis, montados a partir do dataset via `row.get(...)`, removendo o trecho dinâmico. Exemplo do bug real encontrado em produção: gravado `"PRO-80935 daniel setttt 22401666818 FIPE"` (prefixo `PRO-80935` = código de proposta gerado pelo portal a cada execução) → correto é `has_text=f"{row.get('nome_cliente', '')} {row.get('cpf_cliente', '')}"` (só os campos estáveis, suficientes para identificar a linha sem depender do código dinâmico).
* **Regra `strict=True` (rede de segurança, não substitui o fix acima):** Mesmo reconstruindo o `has_text` com valores estáveis, pode não existir NENHUM fragmento estável suficiente para identificar a linha (ex.: tabela sem nenhuma coluna vinda do dataset). Nesse caso residual, passe `strict=True` em `click_chained`/`fill_chained`. Motivo: quando o valor de identidade não bate, o `parent_locator` nunca resolve — o Self-Healing por IA visual então "adivinha" um elemento qualquer da tela (ex.: primeira linha da tabela) sem confirmar que é o registro certo, clicando/preenchendo o alvo ERRADO e reportando `HEALED` como se tivesse êxito (falso positivo confirmado em produção). Com `strict=True`, o runner pula os níveis de IA/coordenada e reporta `FAILED` de forma limpa e rastreável. Se o `has_text` já foi corrigido para usar só valores estáveis do dataset, mantenha `strict=False` (padrão) — a adivinhação nesse caso é aceitável como último recurso.
* **Exemplo de código gerado corretamente:**
  ```python
  # [PASSO X] Selecionar opção na linha da tabela
  runner.click_chained(
      page=page,
      parent={"selector": "tr", "has_text": "4.000,00"},
      child={"selector": ".mat-select-grid-trigger"},
      target_description="Dropdown de valor na linha R$ 4.000,00",
      original_coords=(0.45, 0.62)
  )
  ```
* **Exemplo a partir do relatório (⬆):**
  ```python
  # Ao ver: | ⬆ `.mat-row[RCV - Danos Morais 10.000,00]` ➜ `table tr button:has-text('Cláusulas')` |
  # Extrair parent.selector = "tr"
  # Extrair parent.has_text = "4.000,00" (primeiro texto curto da linha)
  # Extrair child.selector = "table tr button:has-text('Cláusulas')"
  runner.click_chained(
      page=page,
      parent={"selector": "tr", "has_text": "4.000,00"},
      child={"selector": "table tr button:has-text('Cláusulas')"},
      target_description="Botão Cláusulas na linha de Danos Morais",
      original_coords=(0.53, 0.71)
  )
  ```
* **Exemplo de fill encadeado:**
  ```python
  # [PASSO X] Preencher campo de valor na linha do produto
  runner.fill_chained(
      page=page,
      parent={"selector": "div.card", "has_text": "Seguro Auto Premium"},
      child={"selector": "input[name='valor']"},
      text_val=row.get("valor_premio", ""),
      target_description="Campo valor na linha Seguro Auto Premium",
      strategy="DIRECT"
  )
  ```

---

## 🎯 2. Diretrizes de Codificação RPA de Produção

* **Operação Offline em Runtime:** Os scripts gerados devem rodar puramente de forma estática com Playwright + Python, sem uso de LLMs ou conectores cognitivos em tempo de execução. Todo o conhecimento de interface deve estar embutido nos seletores CSS estáveis e lógica determinística.
* **Canal Heading Microsoft Edge:** Utilize o canal oficial do Edge corporativo (`channel="msedge"`) e a exibição headed (`headless=False`) em ambiente de produção/homologação local do usuário.
* **Manutenção do Estado de Sessão:** Sempre grave o estado de autenticação (cookies e storage) via `storage_state` do contexto após logins complexos ou autenticações MFA para economizar tempo de execução em rodadas subsequentes.
* **Proibição Absoluta de Hardcodes e Configurações Fixas:** NUNCA escreva credenciais, chaves de API, tokens, URLs de portais, rotas, caminhos de arquivos ou QUALQUER VALOR DE PREENCHIMENTO OU SELEÇÃO DE CAMPOS (como CPFs, CNPJs, nomes, datas, opções de dropdown) de forma fixa (hardcoded) no código-fonte final dos robôs. Todos os valores a serem preenchidos ou selecionados na interface devem ser obtidos dinamicamente em runtime a partir do dataset de entrada através da variável `row` (ex: `row.get("chave")` ou `row["chave"]`). É terminantemente proibido utilizar strings literais de teste no código gerado, mesmo que elas constem no relatório de telemetria (ex: 'Preencheu com: 123...'). Se um parâmetro de configuração global ou credencial obrigatória de ambiente não estiver definido, o script deve levantar imediatamente uma exceção clara (`ValueError`) detalhando a ausência da variável.
* **Isolamento de Projetos e Proteção do Framework (Aegis Suite Blindado):**
  * **Não Geração de Arquivos na Raiz:** Não devem ser gerados arquivos na raiz do projeto (exceto em casos de extrema necessidade, como atualizações do `requirements.txt` ou metadados de infraestrutura).
  * **Artefatos Específicos Isolados:** Artefatos específicos de um sistema (como logs de execução, capturas de tela, templates de CSV, datasets e relatórios temporários do portal de destino) só podem ser gerados e salvos dentro da sua própria estrutura de pastas do projeto (ex: subpastas em `projects/`), nunca dentro de pastas da suíte do Aegis.
  * **Separação Externa de Projetos:** Tudo o que for específico de um processo automatizado (RPA) ou de um projeto deve ser externo à pasta principal do Aegis. A estrutura do Aegis (como `aegis_runner`, `aegis_blackbox`, `aegis_cockpit`, `aegis_sanitizer`, `aegis_mentor`) é um motor blindado e deve ser protegida contra alterações específicas de robôs.
  * **Localização de Projects e Telemetry_Data:** As pastas `projects` (que armazena os códigos-fonte dos RPAs específicos) e `telemetry_data` (que armazena os dados transacionais de inputs/outputs dos testes e execuções) devem ficar localizadas externamente à suíte core do Aegis (no nível de projeto ou sob diretórios de integração dedicados), nunca misturadas ou aninhadas dentro das pastas internas de ferramentas do framework.
* **Uso Obrigatório do SDK Aegis (TransactionRunner):** NUNCA implemente loops de transação de lote, cliques simples (`page.click`) ou preenchimentos manuais (`page.fill`) de forma crua nos robôs. Todo script RPA deve importar a classe `TransactionRunner` da biblioteca `aegis_runner.runner` (`from aegis_runner.runner import TransactionRunner`), registrar suas rotinas de preenchimento específicas associadas aos cenários como callbacks (ex: `def execute(page, row, runner)`) e chamar `runner.run()`. Para interações de cliques, use obrigatoriamente `runner.click_resilient(page, selector, target_description, original_coords=...)` (passando as coordenadas extraídas do relatório se disponíveis). Para preenchimentos comuns, use `runner.fill_resilient(page, selector, text_val, target_description, strategy="DIRECT"|"HUMAN_LIKE")`. Isso garante que o robô seja curto, limpo e 100% integrado ao mecanismo de Self-Healing visual e fallback de coordenadas.
* **Leitura Obrigatória de `fill_strategy` no `dicionario.json` (Regra Anti-Bot):** Antes de gerar qualquer linha de código de preenchimento de campos, você DEVE ler o `dicionario.json` do projeto e verificar o atributo `fill_strategy` de cada campo. Campos com `"fill_strategy": "HUMAN_LIKE"` foram detectados pelo Recorder como possuidores de listeners `keydown`/`keyup` ativos — indicativo certo de detecção de cadência comportamental (Zone.js ou equivalente). Para esses campos, o código gerado deve usar **exclusivamente** `runner.fill_human_like()` ou `runner.fill_resilient(..., strategy="HUMAN_LIKE", delay_ms=60)`. O uso de `.fill()`, `keyboard.type()` sem delay, ou `evaluate()` de value nesses campos é uma falha crítica de geração e produzirá automação quebrada (botão de avanço permanece desabilitado mesmo com formulário completo). Aplique o **Padrão M** do catálogo.
* **Pipeline de Verificação Visual e Refinamento Contínuo:** Após gerar ou atualizar o script do robô, você DEVE acionar a validação visual executando o utilitário `verify_visual.py` (comando: `python aegis_runner/verify_visual.py --project-dir <caminho_do_projeto>`). O utilitário rodará o robô de forma headless, capturará `screenshot_script.png` no sucesso técnico e o comparará via IA multimodal com `screenshot_recorder.png`. Se o score de similaridade for inferior a 85% ou houver divergências listadas, você deve obrigatoriamente inspecionar as causas no relatório (`visual_verification_report.md`), refinar os seletores ou preenchimentos do script e re-executar a homologação até atingir aprovação automática.
