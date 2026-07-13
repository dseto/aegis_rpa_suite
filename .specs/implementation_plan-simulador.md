# Plano de Implementação: Motor de Simulação Humana Fiel (Revisado & Anotado)

Este plano detalha as alterações cirúrgicas necessárias para adotar a simulação humana no Aegis RPA Suite, incorporando as revisões técnicas exigidas. As alterações estão demarcadas com tags `[AJUSTADO - CRÍTICA ITEM X]` para evidenciar onde e como cada gap da versão anterior foi mitigado.

---

## Proposed Changes (Proposed Changes)

### 1. Módulo Core: `aegis_runner`

#### [MODIFY] [runner.py](file:///c:/Projetos/aegis_rpa_suite/aegis_runner/runner.py)
Ajuste de assinaturas e defaults na inicialização e nos helpers de interação física:

- **Defaults das Assinaturas de Interação:**
  - Alterar as assinaturas padrão de `click_resilient`, `fill_resilient`, `click_chained`, `fill_chained` e `select_option_native_resilient` para assumirem `strict=True` por padrão:
    ```python
    def click_resilient(self, page, selector, target_description, timeout=5000, validate_navigation=False, original_coords=None, step_id=None, strict=True)
    def fill_resilient(self, page, selector, text_val, target_description, strategy="HUMAN_LIKE", delay_ms=60, timeout=5000, step_id=None, strict: bool = True)
    def click_chained(self, page, parent: dict, child: dict, target_description: str, timeout: int = 5000, original_coords: tuple = None, step_id=None, strict: bool = True)
    def fill_chained(self, page, parent: dict, child: dict, text_val: str, target_description: str, strategy: str = "HUMAN_LIKE", delay_ms: int = 60, timeout: int = 5000, step_id=None, strict: bool = True)
    def select_option_native_resilient(self, page, selector, option_text, target_description, timeout=5000, step_id=None, strict: bool = True)
    ```
- **Forçar Execução Visível (`headless=False`):**
  - Mudar a assinatura do método `run` para que a renderização headed seja o padrão inicial:
    ```python
    def run(self, url=None, headless=False, slow_mo=50, channel="msedge")
    ```
  - Tratar a leitura da variável de ambiente de forma consistente para assumir `False` se a variável não estiver definida:
    ```python
    env_headless = os.environ.get("AEGIS_BROWSER_HEADLESS", "false")
    headless = env_headless.lower() in ("true", "1", "yes")
    ```
- **Fidelidade de Hover Físico Padrão:**
  - Em `click_resilient`, se o seletor for composto contendo `" >> "`, forçar a execução real do hover nos elementos pais intermediários incondicionalmente, removendo a verificação que pulava o hover caso o filho parecesse visível para o Playwright.
- **Leitura do `AEGIS_FORCE_HUMAN_LIKE`:**
  - Alterar a checagem da variável de ambiente para assumir `"true"` por padrão:
    ```python
    force_human_like = os.environ.get("AEGIS_FORCE_HUMAN_LIKE", "true").lower() in ("true", "1", "yes")
    ```

---

### 2. Módulo de Geração de Código Híbrida: `aegis_sanitizer`

#### `[AJUSTADO - CRÍTICA ITEM 2]` - Remoção de Ambiguidade (Defaults vs Verbosity)
- **Instrução de Emissão Limpa:**
  - O `Code Generator` e o prompt da LLM **NÃO DEVERÃO** injetar explicitamente `strict=True`, `strategy="HUMAN_LIKE"` ou `strategy="DIRECT"` nas chamadas geradas. 
  - Como a assinatura padrão dos métodos no core do `runner.py` foi alterada para `strict=True` e `strategy="HUMAN_LIKE"`, o gerador de código gerará instruções concisas e sem parâmetros redundantes:
    - *Exemplo de Geração Esperada (Limpa):*
      `runner.fill_resilient(page, selector="#username", text_val=row.get("usuario", ""), target_description="Preencher usuário", step_id="st_001")`
  - Toda menção de injeção explícita de `strategy="DIRECT"` ou `strategy="HUMAN_LIKE"` nos prompts de codificação do LLM (`code_generator.py`) será removida, forçando o motor a herdar o comportamento de simulação humana fiel de forma transparente.

#### `[AJUSTADO - CRÍTICA ITEM 1]` - Adequação à Geração Híbrida (Deterministic Engine)
- **Modificação nos Templates Determinísticos Físicos (`templates/step_click.py.tpl`, `templates/step_fill.py.tpl`, etc.):**
  - Mudar as strings e molduras estáticas dos templates determinísticos de código físico para se adequarem à nova política.
  - Remover parâmetros redundantes como `strategy="DIRECT"` dos blocos determinísticos. As novas linhas emitidas pelo motor deterministic para interações físicas herdarão diretamente as assinaturas enxutas do runner, garantindo simulação humana real em todas as execuções.
  - Eliminar qualquer wait estático contido nos templates que pudesse utilizar `time.sleep()`.

---

### 3. Validador AST: `aegis_sanitizer`

#### `[AJUSTADO - CRÍTICA ITEM 3]` - Validação AST Estrutural (Banimento do `time.sleep`)
- **Rigidez em `validate_bot_structure` em `step_validator.py`:**
  - Em vez de orientar apenas o LLM através do manual `rpa-copilot-coder.md`, a validação estrutural será física e defensiva.
  - Modificar a função `validate_bot_structure` para realizar uma varredura AST (`ast.walk`) e buscar por nós `ast.Call` que executem chamadas a `time.sleep()` ou imports diretos de `sleep`.
  - Caso detectado o uso de `time.sleep` estático, o validador rejeitará o código gerado com erro `FORBIDDEN_TIME_SLEEP`.
  - Isso força o *Ralph Loop* (geração cirúrgica com reflexão) a corrigir autonomamente o código e adotar waits de estado baseados no DOM (Padrão J: `wait_for(state="visible")` ou `runner.wait_for_selector`), sob risco de falha na compilação.

- **Atualização do Mock do Dry Run:**
  - Atualizar os mock methods em `dry_run_bot` em `step_validator.py` (linhas 1600 e 1602) para espelharem as assinaturas modificadas com `strict=True` e `strategy="HUMAN_LIKE"` por padrão.

---

### 4. Módulo Cockpit & Interface: `aegis_cockpit`

#### `[AJUSTADO - CRÍTICA ITEM 4]` - Cobertura do Aegis Cockpit (Fase 5)
- **default Headless no Servidor Backend (`cockpit.py`):**
  - No método `/api/run-bot` do `aegis_cockpit/cockpit.py` (linha 1318), alterar o default de obtenção do parâmetro `headless` enviado nas chamadas HTTP para `False`:
    ```python
    headless = body.get('headless', False)
    ```
    Isso assegura que se nenhuma flag for transmitida explicitamente na requisição da API (Fase 5), o robô executará visivelmente.
- **Checkbox Headless na UI Estática (`static/index.html`):**
  - Na interface web do Cockpit (`aegis_cockpit/static/index.html`, linha 1161), alterar o input do checkbox de controle do headless para inicializar desmarcado por padrão, removendo o atributo `checked`:
    ```html
    <input type="checkbox" id="chk-run-headless" />
    ```
    Garantindo consistência entre a visualização da UI, a API do Cockpit e o padrão headed configurado no core do Runner.

---

## Verification Plan

### Automated Tests
1. **Validação AST (Banimento de sleep):**
   - Adicionar asserções de teste em `step_validator.py` injetando fragmentos de código com `time.sleep` e garantindo o disparo da falha `FORBIDDEN_TIME_SLEEP`.
2. **Auto-teste de compilação:**
   - Executar `python aegis_sanitizer/code_generator.py` para rodar o smoke test `_self_test()` e certificar-se de que a validação estrutural AST e a compilação do bot estão íntegras.
3. **Testes de Integração do Runner:**
   - Executar `pytest aegis_runner/test_runner_integration.py` para certificar-se de que os testes internos toleram e validam os novos defaults das assinaturas com `strict=True`.

### Manual Verification
1. **Validar Estado Padrão da UI:**
   - Iniciar o Cockpit (`python aegis_cockpit/cockpit.py`), acessar o dashboard em localhost e validar se o checkbox "Executar Headless (Sem Janela)" na tela de execução do cenário de teste está desmarcado por padrão.
2. **Verificar Código Gerado Limpo:**
   - Gerar o bot em um cenário real. Confirmar no arquivo `bot_producao.py` gerado:
     - Ausência de `strict=True` e `strategy="HUMAN_LIKE"` explícitos nas chamadas de `click_resilient` e `fill_resilient` (chamadas limpas).
     - Ausência de loops contendo `time.sleep()` fixos sem validação de DOM.
3. **Verificar Comportamento em Execução:**
   - Rodar o robô gerado a partir do Cockpit. Garantir que:
     - O browser Microsoft Edge inicia de forma headed (janela visível).
     - O movimento de hover no elemento pai ocorre antes do clique no submenu.
     - A digitação cadenciada tecla por tecla ocorre em todos os campos de texto.
4. **Verificar Falha Determinística:**
   - Alterar manualmente um seletor crítico e verificar se o runner falha deterministicamente (`[STRICT] Falha definitiva...`), sem tentar fazer a adivinhação da IA cognitiva visual.
