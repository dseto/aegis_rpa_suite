# BACKLOG DE EXECUÇÃO - MOTOR DE SIMULAÇÃO HUMANA FIEL

Este backlog foi gerado a partir do plano de implementação revisado. Ele divide o trabalho em tarefas atômicas e isoladas que podem ser distribuídas para subagentes do Claude Code.

---

### [SUBAGENTE 01] - Refatoração do Runner Core (`aegis_runner`)
- **🎯 Objetivo:** Atualizar os defaults das assinaturas de métodos de interação e de orquestração no core do executor para simulação humana, headed e modo estrito, forçando também o hover físico.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py`
  - Modificar: `aegis_runner/runner.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é modificar o arquivo `aegis_runner/runner.py` para priorizar a simulação humana e a robustez estrita.
  > 
  > Realize as seguintes modificações:
  > 1. Altere a assinatura padrão e defaults de `click_resilient` para que `strict=True` seja o default.
  > 2. Altere as assinaturas padrão de `fill_resilient` e `fill_chained` para usar `strategy="HUMAN_LIKE"` e `strict=True` por padrão.
  > 3. Altere as assinaturas padrão de `click_chained` e `select_option_native_resilient` para usar `strict=True` por padrão.
  > 4. Altere a checagem da variável de ambiente `AEGIS_FORCE_HUMAN_LIKE` em `fill_resilient` para que seu fallback padrão seja `"true"` (caso não definida no ambiente).
  > 5. No método `run`, mude a assinatura para `headless=False` por padrão. Trate a variável de ambiente `AEGIS_BROWSER_HEADLESS` de modo que se estiver ausente, herde `headless=False` (headed).
  > 6. Em `click_resilient`, na seção de hover de seletores compostos (contendo `" >> "`), remova a verificação de visibilidade rápida (`is_visible`). Faça o hover sequencial nos elementos pais intermediários de forma incondicional para garantir a simulação humana fiel de navegação.
  > 
  > Restrinja-se a fazer apenas estas alterações. Não faça refatorações de código ou melhorias de estilo."
- **🧪 Critério de Validação (DoD):**
  - [ ] Validar a sintaxe do arquivo modificado: `python -m py_compile aegis_runner/runner.py`
  - [ ] Executar os testes de integração do runner e garantir que passem: `pytest aegis_runner/test_runner_integration.py`

---

### [SUBAGENTE 02] - Modificação do Validador AST (`aegis_sanitizer`)
- **🎯 Objetivo:** Implementar o banimento estrito de `time.sleep()` via AST em `validate_bot_structure` e atualizar as assinaturas mockadas de teste.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/step_validator.py`
  - Modificar: `aegis_sanitizer/step_validator.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é modificar o arquivo `aegis_sanitizer/step_validator.py` para banir estruturalmente esperas estáticas.
  > 
  > Realize as seguintes modificações:
  > 1. Na função `validate_bot_structure`, implemente uma varredura AST (utilizando `ast.walk`) para buscar qualquer nó `ast.Call` que execute a função `time.sleep(...)` ou `sleep(...)`.
  > 2. Se for detectada alguma chamada de sleep fixo, lance/adicione um erro de estrutura com o tipo `"FORBIDDEN_TIME_SLEEP"` e uma mensagem instruindo o uso de esperas de estado baseadas em DOM (Padrão J).
  > 3. Na função `dry_run_bot` (nas proximidades da linha 1600), atualize os mocks de `click_resilient` e `fill_resilient` do `TransactionRunner` para usarem os defaults atualizados (`strict=True` e `strategy="HUMAN_LIKE"`), evitando erros de dry-run.
  > 4. No auto-teste interno (`_self_test()`), adicione casos de teste com bots fictícios contendo `time.sleep(1)` ou `from time import sleep; sleep(1)` e certifique-se de que a validação barre esses robôs com erro `FORBIDDEN_TIME_SLEEP`.
  > 
  > Restrinja-se a fazer apenas estas alterações. Não faça outras modificações."
- **🧪 Critério de Validação (DoD):**
  - [ ] Validar a sintaxe do arquivo modificado: `python -m py_compile aegis_sanitizer/step_validator.py`
  - [ ] Executar o próprio módulo para rodar seu auto-teste: `python aegis_sanitizer/step_validator.py`

---

### [SUBAGENTE 03] - Limpeza do Gerador de Código e Templates (`aegis_sanitizer`)
- **🎯 Objetivo:** Ajustar o prompt da LLM no gerador e os templates físicos determinísticos para remover parâmetros redundantes de preenchimento e clique.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_sanitizer/code_generator.py`
  - Modificar: `aegis_sanitizer/code_generator.py`, `aegis_sanitizer/templates/*.tpl` (se existirem)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é limpar a geração de código de redundâncias de parâmetros.
  > 
  > Realize as seguintes modificações:
  > 1. No prompt da LLM em `code_generator.py` (dentro de `_generate_new_code`), remova todas as menções que sugeriam injetar explicitamente `strict=True`, `strategy="DIRECT"` ou `strategy="HUMAN_LIKE"`. O gerador deve produzir chamadas limpas (ex: `runner.fill_resilient(page, selector="...", text_val="...", target_description="...", step_id="...")`).
  > 2. Se existirem arquivos de template de geração física `.tpl` na pasta de templates de sanitização/geração (ex: `step_click.py.tpl`, `step_fill.py.tpl`), ajuste-os para remover os parâmetros `strict` e `strategy` redundantes e garantir que não utilizem `time.sleep()`.
  > 
  > Garanta que os testes de fumaça internos de compilação continuem passando."
- **🧪 Critério de Validação (DoD):**
  - [ ] Validar a sintaxe do arquivo modificado: `python -m py_compile aegis_sanitizer/code_generator.py`
  - [ ] Executar o auto-teste do gerador: `python aegis_sanitizer/code_generator.py`

---

### [SUBAGENTE 04] - Configuração e Default Headless no Cockpit (`aegis_cockpit`)
- **🎯 Objetivo:** Alterar o default da API do Cockpit para headed (`headless=False`) e remover o atributo `checked` na interface web.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_cockpit/cockpit.py`, `aegis_cockpit/static/index.html`
  - Modificar: `aegis_cockpit/cockpit.py`, `aegis_cockpit/static/index.html`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é alterar o cockpit para que os robôs rodem de forma visível por padrão.
  > 
  > Realize as seguintes modificações:
  > 1. Em `aegis_cockpit/cockpit.py` (no POST `/api/run-bot`, linha 1318), mude o default de obtenção do parâmetro `headless` para `False` (ficando: `headless = body.get('headless', False)`).
  > 2. Em `aegis_cockpit/static/index.html` (linha 1161), localize o checkbox `#chk-run-headless` e remova o atributo `checked` da tag HTML para que ele inicialize desmarcado por padrão na UI.
  > 
  > Não modifique outros endpoints ou layouts."
- **🧪 Critério de Validação (DoD):**
  - [ ] Validar a sintaxe do cockpit: `python -m py_compile aegis_cockpit/cockpit.py`
  - [ ] Iniciar temporariamente o Cockpit e validar a inicialização limpa: `python aegis_cockpit/cockpit.py --port 8077` (derrube após 2 segundos).

---

### [SUBAGENTE 05] - Homologação End-to-End & Verificação de Regressão
- **🎯 Objetivo:** Garantir retrocompatibilidade e validar o banimento do `time.sleep` em bots reais e a simulação humana headed.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py`, `aegis_sanitizer/step_validator.py`
  - Modificar: nenhum (tarefa de validação/teste pura).
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é validar se as mudanças de simulação humana não introduziram regressões.
  > 
  > Siga os passos de validação:
  > 1. Tente injetar manualmente a instrução `time.sleep(2)` em um bot de produção temporário e verifique se o validador `python aegis_sanitizer/step_validator.py` barra o bot exibindo a falha `FORBIDDEN_TIME_SLEEP`.
  > 2. Execute o bot de referência do repositório (`projects/portal_segura/tests/001_teste`) sem regenerar seu código e certifique-se de que a execução herde o modo headed (abrindo a janela) e a digitação humana de forma transparente.
  > 
  > Reporte os resultados obtidos."
- **🧪 Critério de Validação (DoD):**
  - [ ] Garantir que o bot de referência seja executado com sucesso: `python projects/portal_segura/tests/001_teste/code/bot_producao.py` (ou execute a ferramenta/skill de gate de regressão correspondente).
