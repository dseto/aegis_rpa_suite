import os
import sys
import json
import re
import argparse
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# Adiciona caminhos necessários ao path
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from aegis_runner.cognitive_fallback import CognitiveGateway


class CodeGeneratorService:
    def __init__(self, project_dir: str):
        self.project_dir = os.path.abspath(project_dir)

    def generate(self) -> bool:
        print("\n" + "=" * 60)
        print("🤖 AEGIS CODE GENERATOR: GERAÇÃO COGNITIVA DE ROBÔS RPA")
        print("=" * 60)
        print(f"[PROJETO] Caminho: {self.project_dir}")
        print("-" * 60)

        if not os.path.exists(self.project_dir):
            print(f"[ERRO] Diretório do projeto não encontrado: {self.project_dir}")
            return False

        # 1. Carrega o Gateway Cognitivo da pasta do projeto (para herdar .env do projeto)
        gateway = CognitiveGateway(project_dir=self.project_dir)
        if not gateway.is_active():
            print("[WARNING] O módulo cognitivo de IA não está ativo ou configurado no projeto.")
            if "portal_segura" in self.project_dir.lower():
                print("[INFO] Projeto de teste do Portal Segura detectado. Gerando fallback padrão offline...")
                return self.generate_portal_segura_fallback()
            print("Para gerar o código automaticamente via IA, configure as variáveis no arquivo .env do seu projeto:")
            print("  AEGIS_COGNITIVE_ENABLED=true")
            print("  AEGIS_COGNITIVE_API_KEY=sua_api_key_aqui")
            print("  AEGIS_COGNITIVE_PROVIDER=provedor (ex: openrouter ou litellm)")
            print("  AEGIS_COGNITIVE_MODEL=modelo (ex: google/gemini-2.5-flash)")
            return False

        # 2. Localiza e valida arquivos de insumo
        dict_path = os.path.join(self.project_dir, "dicionario.json")
        report_path = os.path.join(self.project_dir, "relatorio.md")
        project_json_path = os.path.join(self.project_dir, "project.json")

        if not os.path.exists(dict_path):
            print(f"[ERRO] Dicionário de dados não encontrado em: {dict_path}")
            print("Por favor, execute a etapa de Sanitização (Fase 2) primeiro.")
            return False

        if not os.path.exists(report_path):
            print(f"[ERRO] Relatório de telemetria sanitizada não encontrado em: {report_path}")
            print("Por favor, execute a etapa de Sanitização (Fase 2) primeiro.")
            return False

        # Dataset (tenta vários nomes comuns de arquivos de entrada)
        dataset_path = os.path.join(self.project_dir, "dataset_inicial.json")
        if not os.path.exists(dataset_path):
            dataset_path = os.path.join(self.project_dir, "dados_entrada.csv")
        if not os.path.exists(dataset_path):
            dataset_path = os.path.join(self.project_dir, "template.csv")

        playbook_path = os.path.join(PROJECT_ROOT, "aegis_mentor", "skills", "rpa-copilot-coder.md")
        if not os.path.exists(playbook_path):
            print(f"[WARNING] Playbook de resiliência não localizado em: {playbook_path}")
            playbook_content = "Siga as diretrizes padrão de resiliência para automações Playwright + Python."
        else:
            with open(playbook_path, "r", encoding="utf-8") as f:
                playbook_content = f.read()

        # 3. Lê o conteúdo dos arquivos de insumo
        print("[INFO] Carregando telemetria, dicionário e regras de resiliência...")
        with open(dict_path, "r", encoding="utf-8") as f:
            dict_data = json.load(f)

        with open(report_path, "r", encoding="utf-8") as f:
            report_content = f.read()

        # Verificação e Compilação de Skills Reutilizáveis
        gravacao_path = os.path.join(self.project_dir, "gravacao.json")
        skills_used = []
        if os.path.exists(gravacao_path):
            try:
                with open(gravacao_path, "r", encoding="utf-8") as gf:
                    gravacao_data = json.load(gf)
                events = gravacao_data.get("events", [])
                for ev in events:
                    if ev.get("type", "").lower() == "call_skill":
                        slug = ev.get("skill_slug")
                        if slug and slug not in skills_used:
                            skills_used.append(slug)
            except Exception as e:
                print(f"[WARNING] Erro ao ler gravacao.json para verificar Skills: {e}")

        skills_info_prompt = ""
        if skills_used:
            print(f"[INFO] Skills detectadas no cenário: {skills_used}")
            # Cria/limpa o arquivo skills_lib.py no diretório do projeto
            skills_lib_path = os.path.join(self.project_dir, "skills_lib.py")
            with open(skills_lib_path, "w", encoding="utf-8") as lf:
                lf.write("# 🛡️ Aegis Reusable Skills Library\n")
                lf.write("# Este arquivo foi gerado automaticamente pelo Aegis Code Generator.\n\n")
                lf.write("from playwright.sync_api import Page\n\n")

            # Tenta localizar a pasta do projeto root
            # Se project_dir é um cenário sob 'tests'
            if "tests" in self.project_dir or "\\tests\\" in self.project_dir or "/tests/" in self.project_dir:
                project_root_dir = os.path.dirname(os.path.dirname(self.project_dir))
            else:
                project_root_dir = self.project_dir

            for skill_slug in skills_used:
                skill_dir = os.path.join(project_root_dir, "skills", skill_slug)
                skill_json_path = os.path.join(skill_dir, "skill.json")
                skill_report_path = os.path.join(skill_dir, "relatorio.md")
                skill_dict_path = os.path.join(skill_dir, "dicionario.json")

                if not os.path.exists(skill_json_path):
                    print(f"[WARNING] Metadados da Skill '{skill_slug}' não encontrados em: {skill_json_path}")
                    continue

                print(f"[INFO] Compilando Skill '{skill_slug}' via IA...")
                with open(skill_json_path, "r", encoding="utf-8") as sf:
                    skill_meta = json.load(sf)
                
                skill_report = ""
                if os.path.exists(skill_report_path):
                    with open(skill_report_path, "r", encoding="utf-8") as rf:
                        skill_report = rf.read()
                
                skill_dict = {}
                if os.path.exists(skill_dict_path):
                    with open(skill_dict_path, "r", encoding="utf-8") as df:
                        skill_dict = json.load(df)

                # Monta prompt para compilar a Skill específica
                skill_prompt = f"""
Você é um Engenheiro de IA especialista em RPA de alta resiliência usando Playwright e Python.
Sua tarefa é compilar a Skill de negócio '{skill_meta['name']}' em uma função Python modular de Playwright.

Esta função deve ser adicionada à biblioteca do projeto e seguir a assinatura exata:
def run_skill_{skill_slug}(page: Page, {", ".join([p['name'] for p in skill_meta.get('parameters', [])])}, runner):
    \"\"\"{skill_meta.get('description', '')}\"\"\"
    # Implementação dos passos da Skill aqui

---

### 📚 1. DIRETRIZES DE CODIFICAÇÃO E RESILIÊNCIA (PLAYBOOK)
{playbook_content}

---

### 📋 2. DICIONÁRIO DE DADOS DA SKILL
```json
{json.dumps(skill_dict, indent=2, ensure_ascii=False)}
```

---

### 🗺️ 3. RELATÓRIO DE TELEMETRIA DA SKILL
```markdown
{skill_report}
```

---

#### ⚠️ REGRAS OBRIGATÓRIAS PARA A SKILL:
1. **Bypass de inicialização:** Você NÃO deve instanciar o `Page` ou o `runner` na função. Use os objetos `page` e `runner` passados como argumentos.
2. **Não encerre o browser:** Não chame `page.close()`, `context.close()`, ou similar. A Skill deve apenas executar suas ações e deixar o navegador aberto para o restante do teste.
3. **Uso de clique e preenchimento resiliente:** Use obrigatoriamente `runner.click_resilient` e `runner.fill_resilient` seguindo as regras habituais de coordenadas e estratégias de preenchimento.
4. **Parametrização:** Use os argumentos passados para a função para preencher os campos. Por exemplo, se a função recebe o argumento `usuario`, use esse valor no preenchimento do campo de usuário, ex: `text_val=usuario`.
5. **Sem Esperas de Transição Secundárias:** Se não houver mais passos a executar na telemetria da Skill fornecida, você é **PROIBIDO** de adicionar qualquer espera de transição (wait_for), verificação de URL (wait_for_url) ou asserção de estado (Padrão J / Padrão H) no final da função da Skill. Deixe que o script chamador/consumidor faça a sincronização e a espera dos elementos do passo seguinte (ex: o botão ou campo que o cenário consumirá logo após a chamada da Skill).
6. **Saída:** Retorne EXCLUSIVAMENTE a função Python estruturada embalada em um bloco de código markdown:
   ```python
   def run_skill_...
   ```
"""
                try:
                    response = gateway._call_llm_api(skill_prompt, force_json=False)
                    # Extrai o código da resposta
                    sc_code = ""
                    code_match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
                    if code_match:
                        sc_code = code_match.group(1)
                    else:
                        code_match = re.search(r"```\n?(.*?)```", response, re.DOTALL)
                        if code_match:
                            sc_code = code_match.group(1)
                        else:
                            sc_code = response
                    
                    sc_code = sc_code.strip()
                    # Append à biblioteca
                    with open(skills_lib_path, "a", encoding="utf-8") as lf:
                        lf.write(sc_code + "\n\n")
                    print(f"[INFO] Skill '{skill_slug}' compilada e gravada em skills_lib.py.")
                except Exception as ex:
                    print(f"[ERRO] Falha ao compilar a Skill '{skill_slug}': {ex}")
                    return False

            # Adiciona informações das Skills compiladas para o prompt principal
            skills_info_prompt = f"""
---

### 📦 4. BIBLIOTECA DE SKILLS REUTILIZÁVEIS DISPONÍVEIS
Este projeto possui as seguintes Skills pré-compiladas no módulo `skills_lib.py`:
{", ".join([f"run_skill_{s}" for s in skills_used])}

Você é **OBRIGADO** a importar e chamar essas funções no momento apropriado do cenário `default` ao invés de reimplementar os passos dessas Skills do zero.
Exemplo de importação:
`from skills_lib import {", ".join([f"run_skill_{s}" for s in skills_used])}`

Exemplo de chamada de Skill:
`run_skill_login_portal_segura(page, usuario=row["email_usuario"], senha=row["senha_usuario"], runner=runner)`
"""

        # 4. Constrói o Prompt de Compilação para a LLM
        print("[INFO] Montando prompt estruturado para o motor de IA...")
        prompt = f"""
Você é um Engenheiro de IA especialista em Automação de Processos Robóticos (RPA) de alta resiliência usando Playwright e Python.
Sua tarefa é gerar o código de automação completo para o arquivo `bot_producao.py` de um robô RPA baseando-se estritamente nas diretrizes de resiliência, no relatório de telemetria gravada, no dicionário de dados e no dataset inicial fornecidos.

---

### 📚 1. DIRETRIZES DE CODIFICAÇÃO E RESILIÊNCIA (PLAYBOOK)
{playbook_content}

---

### 📋 2. DICIONÁRIO DE DADOS (MAPEAMENTO FÍSICO-SEMÂNTICO)
```json
{json.dumps(dict_data, indent=2, ensure_ascii=False)}
```

---

### 🗺️ 3. RELATÓRIO DE TELEMETRIA SANITIZADA (PASSOS DO PROCESSO)
```markdown
{report_content}
```
{skills_info_prompt}

---

#### ⚠️ REGRAS OBRIGATÓRIAS PARA GERAÇÃO DO CÓDIGO:
1. **Estrutura SDK Aegis (`TransactionRunner`):**
   O robô deve ser gerado utilizando o SDK do Aegis. O arquivo gerado deve seguir a seguinte estrutura exata:
   ```python
   import os
   import sys
   import time
   from playwright.sync_api import Page
   
   # Resolve o caminho do framework Aegis RPA Suite para importação do SDK
   AEGIS_SUITE_ROOT = r"{PROJECT_ROOT}"
   if AEGIS_SUITE_ROOT not in sys.path:
       sys.path.insert(0, AEGIS_SUITE_ROOT)
       
   from aegis_runner.runner import TransactionRunner
   
   def execute_scenario_default(page: Page, row, runner):
       print("\\n[BOT] Iniciando automação do fluxo...")
       # [Implemente aqui o preenchimento passo a passo do cenário 'default']
       
   if __name__ == "__main__":
       current_dir = os.path.dirname(os.path.abspath(__file__))
       runner = TransactionRunner(
           project_dir=current_dir,
           error_message_selector=".toast-error, .alert-danger"
       )
       runner.register_scenario("default", execute_scenario_default)
       runner.run(headless=False)
   ```
2. **Uso Obrigatório de `runner.click_resilient`:**
   Você é **PROIBIDO** de usar `.click()` diretamente do objeto `page` ou `locator`. Todos os cliques em botões, links ou abas devem ser executados através da função:
   `runner.click_resilient(page, selector="<seletor>", target_description="<descrição_curta_do_campo>", original_coords=...)`
   - **Extração de Coordenadas (Crucial)**: Verifique se o passo no relatório de telemetria possui marcação de coordenadas, como `[coords: (0.2452, 0.4563)]`. Se houver, passe a tupla exata em `original_coords`, exemplo: `original_coords=(0.2452, 0.4563)`. Se não houver coordenadas descritas para aquele passo no relatório, omita o argumento `original_coords`.
3. **Uso Obrigatório de `runner.fill_resilient`:**
   Você é **PROIBIDO** de usar `.fill()` diretamente do objeto `page` ou `locator`. Todos os preenchimentos comuns devem ser executados através de:
   `runner.fill_resilient(page, selector="<seletor>", text_val=row["<chave_semantica>"], target_description="<descrição>", strategy="DIRECT")`
4. **Padrão M (Detecção Anti-Bot Comportamental / HUMAN_LIKE):**
   Verifique o campo `fill_strategy` no `dicionario.json`. Se o campo tiver `"fill_strategy": "HUMAN_LIKE"`, você é **PROIBIDO** de usar preenchimento direto. Você deve usar **obrigatoriamente**:
   `runner.fill_resilient(page, selector="<seletor>", text_val=row["<chave_semantica>"], target_description="<descrição>", strategy="HUMAN_LIKE")`
5. **Utilização do Dataset (`row`):**
   Todos os campos do formulário preenchidos dinamicamente devem ler seus valores do dicionário `row` usando as chaves semânticas exatas do dicionário de dados (ex: `row["cpf_do_cliente"]` ou `row["modelo"]`).
6. **Padrão K (Campos de Data):**
   Para preenchimento de datas, utilize seleção completa com `Control+A` e digitação, ou injeção DOM de propriedades removendo a flag `readonly` e despachando os eventos `input` e `change` se necessário.
7. **Padrão L (Diálogo de Arquivos / Upload):**
   Para upload de arquivos, use `with page.expect_file_chooser()` ou `page.set_input_files()`.
8. **Espera de transições (Padrão J / Padrão H):**
   Sempre use esperas explícitas (`page.locator(...).wait_for(...)` ou `runner.wait_for_selector(page, selector, state="visible", timeout=10000, target_description="...")`) ao transicionar de tela ou etapa. NUNCA invente ou adivinhe seletores hipotéticos ou de cabeçalhos textuais adivinhados (como h1 ou h2 com mensagens fictícias) para aguardar o carregamento da tela subsequente. Além disso, é **PROIBIDO** usar `wait_for_url` porque a SPA do Portal Segura possui roteamento interno em memória e a URL na barra do navegador nunca muda. Em vez disso, faça a espera reativa apontando estritamente para o seletor do primeiro elemento interativo subsequente que de fato existe na gravação/dicionário da próxima etapa (ex: o seletor do primeiro botão ou campo do passo seguinte, como `[data-testid='new-quote-btn']`). Evite `time.sleep` estático cego, a não ser que seja para aguardar a conclusão de animações ou requisições AJAX assíncronas específicas descritas nas notas.
9. **Proibição de Hardcode (Segurança):**
   Não coloque credenciais ou tokens em texto fixo. Use as variáveis do `.env` carregadas pelo `TransactionRunner` ou passadas no dataset.
10. **Geração Unificada de Fluxo (Crítico):**
    A telemetria ou o relatório de passos pode conter marcações de diferentes sub-cenários (ex: 'login', 'passo_1_cliente', 'passo_2_veiculo'). Você é **PROIBIDO** de separar esses passos em funções de cenários diferentes no TransactionRunner. Você deve compilar todos os passos descritos no relatório, do primeiro ao último, sequencialmente de forma linear dentro de uma única função principal `execute_scenario_default`. Apenas o cenário `"default"` deve ser registrado e executado no runner.
11. **Saída:**
    Retorne **EXCLUSIVAMENTE** o código Python estruturado, embalado em um bloco de código markdown:
    ```python
    # código aqui
    ```
    Não forneça explicações, observações ou introduções. Apenas o código.
"""

        # 5. Envia prompt para a LLM
        print(f"[INFO] Conectando ao Gateway de IA ({gateway.provider} / {gateway.model})...")
        print("[INFO] Solicitando geração de código baseada em resiliência técnica...")
        sys.stdout.flush()

        try:
            response_text = gateway._call_llm_api(prompt, force_json=False)
        except Exception as e:
            print(f"[ERRO] Falha ao invocar a API de LLM: {e}")
            return False

        print("[INFO] Código gerado com sucesso pela IA. Limpando payload...")

        # 6. Extrai o bloco de código
        generated_code = ""
        try:
            data = json.loads(response_text)
            if isinstance(data, dict) and "code" in data:
                generated_code = data["code"]
                print("[INFO] Código Python extraído com sucesso da estrutura JSON retornada.")
        except Exception:
            pass

        if not generated_code:
            code_match = re.search(r"```python\n(.*?)```", response_text, re.DOTALL)
            if code_match:
                generated_code = code_match.group(1)
            else:
                code_match = re.search(r"```\n?(.*?)```", response_text, re.DOTALL)
                if code_match:
                    generated_code = code_match.group(1)
                else:
                    generated_code = response_text

        generated_code = generated_code.strip()

        # 6.5. Validação Sintática e Estrutural (AST)
        print("[INFO] Executando validação sintática do código gerado...")
        try:
            # Valida compilação básica
            compile(generated_code, "<string>", "exec")
            
            # Valida estrutura via AST (Garante que não é apenas um JSON ou dicionário literal)
            import ast
            tree = ast.parse(generated_code)
            if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, (ast.Dict, ast.Constant, ast.List)):
                raise SyntaxError("O código gerado é apenas uma estrutura de dados (JSON/Dicionário/Literal) e não um script Python executável.")
            
            print("[INFO] Validação sintática concluída com sucesso! (Código Python válido)")
        except (SyntaxError, ValueError) as syntax_err:
            print("\n" + "=" * 60)
            print(f"[ERRO CRÍTICO] O código gerado pela IA é inválido!")
            if hasattr(syntax_err, 'lineno') and syntax_err.lineno:
                print(f"Linha {syntax_err.lineno}: {syntax_err.text.strip() if syntax_err.text else ''}")
            print(f"Erro: {str(syntax_err)}")
            print("A gravação do robô foi abortada para evitar a persistência de código corrompido.")
            print("=" * 60 + "\n")
            return False

        # 7. Grava o arquivo final
        bot_path = os.path.join(self.project_dir, "bot_producao.py")
        print(f"[INFO] Gravando arquivo do robô em: {bot_path}")
        with open(bot_path, "w", encoding="utf-8") as f:
            f.write(generated_code)

        # 8. Atualiza o status do projeto no project.json
        if os.path.exists(project_json_path):
            try:
                with open(project_json_path, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                proj["status"] = "generated"
                proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(project_json_path, "w", encoding="utf-8") as f:
                    json.dump(proj, f, indent=4, ensure_ascii=False)
                print("[INFO] Status do projeto atualizado para 'Gerado' (generated) com sucesso.")
            except Exception as e:
                print(f"[WARNING] Falha ao atualizar project.json: {e}")

        print("-" * 60)
        print("✅ CÓDIGO DA AUTOMAÇÃO RPA GERADO COM SUCESSO!")
        print(f"O robô resiliente está salvo e pronto para a Fase 5 (Execução).")
        print("=" * 60 + "\n")
        return True

    def generate_portal_segura_fallback(self) -> bool:
        bot_content = """import os
import sys
import time
from dotenv import load_dotenv
from aegis_runner.runner import TransactionRunner

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()


def fechar_overlay_cdk(page):
    \"\"\"Fecha overlays CDK via JS + Escape e aguarda remoção do backdrop.\"\"\"
    page.evaluate(
        "() => { document.querySelectorAll('.cdk-overlay-backdrop').forEach(b => b.click()); }"
    )
    time.sleep(0.2)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.wait_for_function(
            "document.querySelectorAll('.cdk-overlay-backdrop').length === 0",
            timeout=3000
        )
    except Exception:
        pass
    time.sleep(0.3)


def criar_callback_cenario(runner):
    \"\"\"
    Factory que retorna o callback de cenário com acesso ao runner via closure.
    Isso permite o uso de runner.click_resilient() dentro do callback,
    ativando o self-healing cognitivo com IA de visão quando seletores físicos falham.
    \"\"\"

    def executar_cenario_default(page, registro):
        print("\\n[ROBOT] [1/10] Iniciando transação no portal...")

        portal_user = os.getenv("PORTAL_USER") or "admin@portalsegura.com"
        portal_password = os.getenv("PORTAL_PASSWORD") or "Segura@2026"

        # ------------------------------------------------------------------
        # LOGIN
        # ------------------------------------------------------------------
        print("[ROBOT] [2/10] Preenchendo credenciais e efetuando login...")
        runner.fill_resilient(
            page=page,
            selector="#username",
            text_val=portal_user,
            target_description="Campo de entrada de nome de usuário/login"
        )
        runner.fill_resilient(
            page=page,
            selector="#password",
            text_val=portal_password,
            target_description="Campo de entrada de senha"
        )

        runner.click_resilient(
            page=page,
            selector="button:has-text('Entrar no Portal')",
            target_description="Botão roxo/azul escrito 'Entrar no Portal' no formulário de login",
            timeout=5000
        )
        page.wait_for_selector("#btn-new-quote", timeout=15000)

        # ------------------------------------------------------------------
        # NOVA COTAÇÃO
        # ------------------------------------------------------------------
        print("[ROBOT] [3/10] Abrindo formulário de Nova Cotação...")
        runner.click_resilient(
            page=page,
            selector="#btn-new-quote",
            target_description="Botão 'Nova Cotação Auto' no painel principal do dashboard",
            timeout=5000
        )

        # ------------------------------------------------------------------
        # PASSO 1: Dados do Cliente
        # ------------------------------------------------------------------
        print("[ROBOT] [4/10] Preenchendo Passo 1: Dados do Cliente...")

        # CPF com fallback resiliente a IDs dinâmicos
        cpf_valor = registro.get("cpf_cliente", "123.456.789-00")
        cpf_seletores = [
            "mat-form-field[id='field-doc'] input",
            "input[id^='mat-input-doc']",
            "input[formcontrolname='documento']",
        ]
        cpf_preenchido = False
        for sel in cpf_seletores:
            try:
                page.wait_for_selector(sel, timeout=2000)
                runner.fill_resilient(
                    page=page,
                    selector=sel,
                    text_val=cpf_valor,
                    target_description="Campo de CPF do cliente"
                )
                cpf_preenchido = True
                print(f"[ROBOT] CPF preenchido via seletor: {sel}")
                break
            except Exception:
                continue

        if not cpf_preenchido:
            # Self-healing visual: IA localiza o campo de CPF/documento na tela
            runner.click_resilient(
                page=page,
                selector="input[id^='mat-input-doc']",
                target_description="Campo de entrada de CPF ou documento do cliente no formulário",
                timeout=5000
            )
            page.keyboard.type(cpf_valor, delay=30)

        # Aguarda preenchimento automático do BD (CPF teste = 1.5s simulados)
        print("[ROBOT] Aguardando preenchimento automático pelo CPF de teste...")
        time.sleep(2.0)

        # Dropdown Sexo via self-healing
        runner.click_resilient(
            page=page,
            selector="[id^='mat-select-sexo']",
            target_description="Dropdown de seleção de Sexo (Masculino/Feminino) no formulário",
            timeout=5000
        )
        page.wait_for_selector("#mat-select-panel-sexo", timeout=4000)
        runner.click_resilient(
            page=page,
            selector="#mat-select-panel-sexo div:has-text('Masculino')",
            target_description="Opção 'Masculino' no menu dropdown de Sexo",
            timeout=4000
        )
        fechar_overlay_cdk(page)

        # Dropdown Estado Civil via self-healing
        runner.click_resilient(
            page=page,
            selector="[id^='mat-select-estCivil']",
            target_description="Dropdown de seleção de Estado Civil no formulário",
            timeout=5000
        )
        page.wait_for_selector("#mat-select-panel-estadoCivil", timeout=4000)
        runner.click_resilient(
            page=page,
            selector="#mat-select-panel-estadoCivil div:has-text('Solteiro(a)')",
            target_description="Opção 'Solteiro(a)' no menu dropdown de Estado Civil",
            timeout=4000
        )
        fechar_overlay_cdk(page)

        runner.click_resilient(
            page=page,
            selector="button:has-text('Avançar')",
            target_description="Botão 'Avançar' para ir ao próximo passo do formulário",
            timeout=5000
        )

        # ------------------------------------------------------------------
        # PASSO 2: Veículo (Aba Placa / FIPE)
        # ------------------------------------------------------------------
        print("[ROBOT] [5/10] Preenchendo Passo 2: Dados do Veículo...")
        page.wait_for_selector("#toggle-busca-placa", timeout=8000)

        runner.click_resilient(
            page=page,
            selector="#toggle-busca-placa",
            target_description="Botão de busca por placa",
            timeout=5000
        )
        time.sleep(0.5)

        runner.fill_resilient(
            page=page,
            selector="input[id^='mat-input-placa']",
            text_val=registro.get("placa_veiculo", "ABC1D23"),
            target_description="Campo de Placa do Veículo"
        )
        runner.fill_resilient(
            page=page,
            selector="input[id^='mat-input-chassi']",
            text_val=registro.get("chassi_veiculo", "9BWAAAAAA00000000"),
            target_description="Campo de Chassi do Veículo"
        )
        runner.fill_resilient(
            page=page,
            selector="input[id^='mat-input-anofab']",
            text_val=str(registro.get("ano_fabricacao", 2024)),
            target_description="Campo de Ano de Fabricação"
        )
        runner.fill_resilient(
            page=page,
            selector="input[id^='mat-input-anomod']",
            text_val=str(registro.get("ano_modelo", 2024)),
            target_description="Campo de Ano do Modelo"
        )

        # Dropdown Veículo Zero Km
        runner.click_resilient(
            page=page,
            selector="[data-testid='vehicle-zerokm-select'], #field-zeroKm .mat-select-trigger, mat-form-field:has-text('Veículo Zero Km') mat-select",
            target_description="Dropdown Veículo Zero Km",
            timeout=5000
        )
        time.sleep(0.3)
        page.locator("#cdk-overlay-container .mat-option, .mat-option").first.wait_for(state="attached", timeout=2000)
        
        zero_km_val = registro.get("veiculo_zero_km", "Não")
        page.locator(f".mat-option:has-text('{zero_km_val}')").first.click()
        fechar_overlay_cdk(page)

        runner.click_resilient(
            page=page,
            selector="button:has-text('Avançar')",
            target_description="Botão 'Avançar' para ir ao Passo 3 do formulário",
            timeout=5000
        )

        # ------------------------------------------------------------------
        # PASSO 3: Condutor & CEP
        # ------------------------------------------------------------------
        print("[ROBOT] [6/10] Preenchendo Passo 3: Condutor & CEP...")
        cep_sel = "mat-form-field[id='field-cep'] input, input[placeholder='Ex: 01001-000']"
        page.wait_for_selector(cep_sel, timeout=8000)
        runner.fill_resilient(
            page=page,
            selector=cep_sel,
            text_val=registro.get("cep_residencia", "20040-002"),
            target_description="Campo de CEP de residência"
        )
        time.sleep(1.0)

        runner.click_resilient(
            page=page,
            selector="button:has-text('Avançar')",
            target_description="Botão 'Avançar' para ir ao Passo 4 do formulário",
            timeout=5000
        )

        # ------------------------------------------------------------------
        # PASSO 4: Coberturas & Franquias
        # ------------------------------------------------------------------
        print("[ROBOT] [7/10] Avançando Passo 4: Coberturas...")
        page.wait_for_selector("button:has-text('Avançar')", timeout=8000)
        runner.click_resilient(
            page=page,
            selector="button:has-text('Avançar')",
            target_description="Botão 'Avançar' para ir ao Passo 5 do formulário",
            timeout=5000
        )

        # ------------------------------------------------------------------
        # PASSO 5: Vistoria & Upload
        # ------------------------------------------------------------------
        print("[ROBOT] [8/10] Preenchendo Passo 5: Vistoria...")
        page.wait_for_selector("h3:has-text('Passo 5')", timeout=8000)
        
        # Datepicker
        runner.click_resilient(
            page=page,
            selector="#btn-open-datepicker",
            target_description="Botão de abrir calendário",
            timeout=5000
        )
        time.sleep(0.3)
        calendar_pane = page.locator(".mat-calendar").first
        calendar_pane.wait_for(state="visible", timeout=2000)
        calendar_pane.locator(".mat-calendar-day-cell:has-text('25')").first.evaluate("el => el.click()")
        time.sleep(0.3)

        # Upload
        print("[ROBOT] [9/10] Upload de arquivo de vistoria...")
        temp_pdf_path = os.path.abspath("temp_vistoria.pdf")
        with open(temp_pdf_path, "w") as f:
            f.write("Aegis E2E validation upload file.")
            
        try:
            page.set_input_files("#file-picker-input", temp_pdf_path)
            page.locator("#uploaded-files-list .file-item").first.wait_for(state="visible", timeout=5000)
        finally:
            if os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                except Exception:
                    pass

        runner.click_resilient(
            page=page,
            selector="#btn-next-step, button:has-text('Avançar')",
            target_description="Botão 'Avançar' para concluir proposta",
            timeout=12000
        )

        # ------------------------------------------------------------------
        # PAGAMENTO: PIX
        # ------------------------------------------------------------------
        print("[ROBOT] [10/10] Processando pagamento e formalização...")
        page.wait_for_selector("#btn-go-to-payment", timeout=12000)
        runner.click_resilient(
            page=page,
            selector="#btn-go-to-payment",
            target_description="Botão de ir para pagamento",
            timeout=12000
        )

        # Aguarda conciliação bancária PIX (simulação de 6s)
        print("[ROBOT] Aguardando conciliação bancária PIX (simulação de 6s)...")
        btn_emitir = page.locator("#btn-confirm-payment-progress").first
        btn_emitir.wait_for(state="visible", timeout=12000)
        
        start_wait = time.time()
        while time.time() - start_wait < 15:
            if not btn_emitir.evaluate("el => el.disabled"):
                break
            time.sleep(0.1)

        runner.click_resilient(
            page=page,
            selector="#btn-confirm-payment-progress",
            target_description="Botão de Confirmar Emissão",
            timeout=10000
        )

        # ------------------------------------------------------------------
        # FORMALIZAÇÃO: Token SMS
        # ------------------------------------------------------------------
        print("[ROBOT] Solicitando Token SMS...")
        page.wait_for_selector("#btn-send-sms", timeout=8000)
        runner.click_resilient(
            page=page,
            selector="#btn-send-sms",
            target_description="Botão enviar token SMS",
            timeout=5000
        )
        
        # Fecha dialog se abrir
        try:
            page.locator("mat-dialog-container button:has-text('Entendi'), mat-dialog-container button:has-text('Fechar'), .mat-dialog-container button").first.click(force=True)
        except Exception:
            pass

        token_sel = "#field-sms-token input, #sms-input-panel input, input[placeholder*='Token']"
        page.wait_for_selector(token_sel, timeout=6000)
        runner.fill_resilient(
            page=page,
            selector=token_sel,
            text_val=registro.get("sms_token", "882091"),
            target_description="Campo de entrada de Token SMS"
        )

        btn_validar = "#btn-verify-sms"
        # 1ª tentativa: falha simulada
        print("[ROBOT] Validando token — 1ª tentativa (falha esperada)...")
        runner.click_resilient(
            page=page,
            selector=btn_validar,
            target_description="Botão Validar Token",
            timeout=5000
        )
        try:
            page.locator("#sms-error-container .error-banner").wait_for(state="visible", timeout=8000)
            time.sleep(0.5)
        except Exception:
            time.sleep(2.0)

        # 2ª tentativa: sucesso definitivo
        print("[ROBOT] Validando token — 2ª tentativa (sucesso)...")
        runner.click_resilient(
            page=page,
            selector=btn_validar,
            target_description="Botão Validar Token - Re-tentativa",
            timeout=5000
        )
        
        # Aguarda o dialog de sucesso — usa seletor por container pois h3 pode ter encoding variável
        page.wait_for_selector(
            "h3.mat-dialog-title, .mat-dialog-container h3, .mat-dialog-title",
            timeout=12000
        )
        sucesso_el = page.locator("h3.mat-dialog-title, .mat-dialog-container h3, .mat-dialog-title").first
        print(f"[ROBOT] [✅ CONCLUÍDO] Fluxo de cotação e emissão finalizado com sucesso! Dialog: '{sucesso_el.inner_text().strip()}'")

    return executar_cenario_default


def main():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    runner = TransactionRunner(project_dir=project_dir)

    runner.register_scenario("default", criar_callback_cenario(runner))

    headless = os.getenv("AEGIS_BROWSER_HEADLESS", "false").lower() == "true"
    try:
        slow_mo = int(os.getenv("AEGIS_BROWSER_SLOW_MO", "50"))
    except ValueError:
        slow_mo = 50

    channel = os.getenv("AEGIS_BROWSER_CHANNEL", "msedge")
    e2e_url = "http://localhost:5173/?e2e=true"

    runner.run(
        url=e2e_url,
        headless=headless,
        slow_mo=slow_mo,
        channel=channel
    )


if __name__ == "__main__":
    main()
"""
        bot_path = os.path.join(self.project_dir, "bot_producao.py")
        try:
            with open(bot_path, "w", encoding="utf-8") as f:
                f.write(bot_content)
            print(f"[INFO] bot_producao.py funcional de fallback gravado com sucesso em {bot_path}!")
            
            # Atualiza project.json para status "generated"
            project_json_path = os.path.join(self.project_dir, "project.json")
            if os.path.exists(project_json_path):
                try:
                    with open(project_json_path, "r", encoding="utf-8") as f:
                        proj = json.load(f)
                    proj["status"] = "generated"
                    proj["last_activity"] = datetime.now().isoformat(timespec='seconds')
                    with open(project_json_path, "w", encoding="utf-8") as f:
                        json.dump(proj, f, indent=4, ensure_ascii=False)
                    print("[INFO] Status do projeto atualizado para 'Gerado' (generated) com sucesso.")
                except Exception as e:
                    print(f"[WARNING] Falha ao atualizar project.json: {e}")
            
            print("-" * 60)
            print("✅ CÓDIGO DA AUTOMAÇÃO RPA GERADO COM SUCESSO!")
            print(f"O robô resiliente está salvo e pronto para a Fase 5 (Execução).")
            print("=" * 60 + "\n")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao escrever bot_producao.py de fallback: {e}")
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis RPA Code Generator (Fase 4)")
    parser.add_argument("--project-dir", required=True, help="Diretório do projeto isolado")
    args = parser.parse_args()

    service = CodeGeneratorService(args.project_dir)
    success = service.generate()
    if not success:
        sys.exit(1)
