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
            print("[ERRO] O módulo cognitivo de IA não está ativo ou configurado no projeto.")
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
8. **Espera de transições (Padrão J):**
   Sempre use esperas explícitas (`page.locator(...).wait_for(...)`) ao transicionar entre etapas. Evite `time.sleep` estático cego, a não ser que seja para aguardar a conclusão de animações ou requisições AJAX assíncronas específicas descritas nas notas.
9. **Proibição de Hardcode (Segurança):**
   Não coloque credenciais ou tokens em texto fixo. Use as variáveis do `.env` carregadas pelo `TransactionRunner` ou passadas no dataset.
10. **Saída:**
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis RPA Code Generator (Fase 4)")
    parser.add_argument("--project-dir", required=True, help="Diretório do projeto isolado")
    args = parser.parse_args()

    service = CodeGeneratorService(args.project_dir)
    success = service.generate()
    if not success:
        sys.exit(1)
