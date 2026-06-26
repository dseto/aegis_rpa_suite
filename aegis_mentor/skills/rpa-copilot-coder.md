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
* **Solução:** Tente o clique nativo. Em caso de timeout ou falha de colisão, utilize injeção de JS (`evaluate`) direta na árvore do DOM para acionar a ação de clique do elemento.
* **Exemplo:**
  ```python
  opt = page.locator(".mat-option:has-text('Opção')")
  try:
      opt.click(force=True, timeout=1500)
  except Exception:
      opt.evaluate("el => el.click()")
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

---

## 🎯 2. Diretrizes de Codificação RPA de Produção

* **Operação Offline em Runtime:** Os scripts gerados devem rodar puramente de forma estática com Playwright + Python, sem uso de LLMs ou conectores cognitivos em tempo de execução. Todo o conhecimento de interface deve estar embutido nos seletores CSS estáveis e lógica determinística.
* **Canal Heading Microsoft Edge:** Utilize o canal oficial do Edge corporativo (`channel="msedge"`) e a exibição headed (`headless=False`) em ambiente de produção/homologação local do usuário.
* **Manutenção do Estado de Sessão:** Sempre grave o estado de autenticação (cookies e storage) via `storage_state` do contexto após logins complexos ou autenticações MFA para economizar tempo de execução em rodadas subsequentes.
* **Proibição Absoluta de Hardcodes e Configurações Fixas:** NUNCA escreva credenciais, chaves de API, tokens, URLs de portais, rotas ou caminhos de arquivos de forma fixa (hardcoded) no código-fonte final dos robôs. Todos esses parâmetros de configuração devem ser obtidos dinamicamente em runtime através de variáveis de ambiente (`os.getenv`) ou de arquivos de configuração externos (`.env`, `.json`, `.yaml`). Se um parâmetro de configuração obrigatório não estiver definido, o script deve levantar imediatamente uma exceção clara (`ValueError`) detalhando a ausência da variável, evitando valores padrão (fallbacks) que possam mascarar falhas de configuração ou expor credenciais padrão em produção.
* **Isolamento de Projetos e Proteção do Framework (Aegis Suite Blindado):**
  * **Não Geração de Arquivos na Raiz:** Não devem ser gerados arquivos na raiz do projeto (exceto em casos de extrema necessidade, como atualizações do `requirements.txt` ou metadados de infraestrutura).
  * **Artefatos Específicos Isolados:** Artefatos específicos de um sistema (como logs de execução, capturas de tela, templates de CSV, datasets e relatórios temporários do Portal Segura) só podem ser gerados e salvos dentro da sua própria estrutura de pastas do projeto (ex: subpastas em `projects/`), nunca dentro de pastas da suíte do Aegis.
  * **Separação Externa de Projetos:** Tudo o que for específico de um processo automatizado (RPA) ou de um projeto deve ser externo à pasta principal do Aegis. A estrutura do Aegis (como `aegis_runner`, `aegis_blackbox`, `aegis_cockpit`, `aegis_sanitizer`, `aegis_mentor`) é um motor blindado e deve ser protegida contra alterações específicas de robôs.
  * **Localização de Projects e Telemetry_Data:** As pastas `projects` (que armazena os códigos-fonte dos RPAs específicos) e `telemetry_data` (que armazena os dados transacionais de inputs/outputs dos testes e execuções) devem ficar localizadas externamente à suíte core do Aegis (no nível de projeto ou sob diretórios de integração dedicados), nunca misturadas ou aninhadas dentro das pastas internas de ferramentas do framework.
* **Uso Obrigatório do SDK Aegis (TransactionRunner):** NUNCA implemente loops de transação de lote ou gravação de logs transacionais repetitivos de forma manual nos robôs. Todo script RPA deve importar a classe `TransactionRunner` da biblioteca `aegis_runner.runner` (`from aegis_runner.runner import TransactionRunner`), registrar suas rotinas de preenchimento específicas associadas aos cenários como callbacks e chamar `runner.run()`, permitindo que os robôs sejam curtos, limpos e 100% independentes da pasta física do framework.
* **Leitura Obrigatória de `fill_strategy` no `dicionario.json` (Regra Anti-Bot):** Antes de gerar qualquer linha de código de preenchimento de campos, você DEVE ler o `dicionario.json` do projeto e verificar o atributo `fill_strategy` de cada campo. Campos com `"fill_strategy": "HUMAN_LIKE"` foram detectados pelo Recorder como possuidores de listeners `keydown`/`keyup` ativos — indicativo certo de detecção de cadência comportamental (Zone.js ou equivalente). Para esses campos, o código gerado deve usar **exclusivamente** `runner.fill_human_like()` ou `runner.fill_resilient(..., strategy="HUMAN_LIKE", delay_ms=60)`. O uso de `.fill()`, `keyboard.type()` sem delay, ou `evaluate()` de value nesses campos é uma falha crítica de geração e produzirá automação quebrada (botão de avanço permanece desabilitado mesmo com formulário completo). Aplique o **Padrão M** do catálogo.
* **Pipeline de Verificação Visual e Refinamento Contínuo:** Após gerar ou atualizar o script do robô, você DEVE acionar a validação visual executando o utilitário `verify_visual.py` (comando: `python aegis_runner/verify_visual.py --project-dir <caminho_do_projeto>`). O utilitário rodará o robô de forma headless, capturará `screenshot_script.png` no sucesso técnico e o comparará via IA multimodal com `screenshot_recorder.png`. Se o score de similaridade for inferior a 85% ou houver divergências listadas, você deve obrigatoriamente inspecionar as causas no relatório (`visual_verification_report.md`), refinar os seletores ou preenchimentos do script e re-executar a homologação até atingir aprovação automática.
