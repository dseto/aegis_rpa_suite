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
        if getattr(gateway, "coder_model", None):
            gateway.model = gateway.coder_model
        print(f"[INFO] Modelo de IA configurado para codificação: {gateway.model}")
        if not gateway.is_active():
            print("[WARNING] O módulo cognitivo de IA não está ativo ou configurado no projeto.")
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
            code_dir = os.path.join(self.project_dir, "code")
            os.makedirs(code_dir, exist_ok=True)
            skills_lib_path = os.path.join(code_dir, "skills_lib.py")
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
`run_skill_login(page, usuario=row["email_usuario"], senha=row["senha_usuario"], runner=runner)`
"""

        # Leitura das correções pendentes acumuladas do ciclo de feedback
        correcoes_acumuladas_path = os.path.join(self.project_dir, "correcoes_acumuladas.json")
        pending_corrections = []
        if os.path.exists(correcoes_acumuladas_path):
            try:
                with open(correcoes_acumuladas_path, "r", encoding="utf-8") as cf:
                    all_corrs = json.load(cf)
                pending_corrections = [c for c in all_corrs if c.get("status") == "pending"]
            except Exception as e:
                print(f"[WARNING] Failed to read correcoes_acumuladas.json: {e}")

        bot_path = os.path.join(self.project_dir, "code", "bot_producao.py")
        has_existing_bot = os.path.exists(bot_path)
        code_dir = os.path.join(self.project_dir, "code")

        if has_existing_bot and pending_corrections:
            print("[INFO] Iniciando fluxo de CORREÇÃO CIRÚRGICA (Karpathy Style)...")
            return self._surgical_correct(bot_path, pending_corrections, gateway, project_json_path, code_dir, correcoes_acumuladas_path)
        else:
            print("[INFO] Iniciando fluxo de GERAÇÃO DE CÓDIGO NOVO...")
            return self._generate_new_code(bot_path, dict_data, report_content, skills_info_prompt, pending_corrections, gateway, project_json_path, code_dir, correcoes_acumuladas_path)

    def _generate_new_code(self, bot_path: str, dict_data: dict, report_content: str, skills_info_prompt: str, pending_corrections: list, gateway, project_json_path: str, code_dir: str, correcoes_acumuladas_path: str) -> bool:
        correcoes_prompt = ""
        if pending_corrections:
            print(f"[INFO] Detectadas {len(pending_corrections)} correções pendentes aprovadas para aplicação.")
            
            # ── Seção de Insight QA com prioridade máxima ──
            qa_insights = list(set(
                c.get("qa_insight") for c in pending_corrections
                if c.get("qa_insight")
            ))
            
            if qa_insights:
                print(f"[INFO] 🧠 Insight(s) do Analista QA detectado(s): {len(qa_insights)} — Prioridade máxima ativada.")
                correcoes_prompt += "\n---\n\n"
                correcoes_prompt += "### ⚠️🧠 5. INSIGHT CRÍTICO DO ANALISTA QA (PRIORIDADE MÁXIMA)\n"
                correcoes_prompt += "╔══════════════════════════════════════════════════════════════════╗\n"
                correcoes_prompt += "║  ATENÇÃO: A INFORMAÇÃO ABAIXO FOI FORNECIDA POR UM ANALISTA     ║\n"
                correcoes_prompt += "║  QA HUMANO QUE TESTOU MANUALMENTE O SISTEMA E IDENTIFICOU A     ║\n"
                correcoes_prompt += "║  CAUSA REAL DO PROBLEMA. ESTA ANÁLISE TEM PRECEDÊNCIA ABSOLUTA   ║\n"
                correcoes_prompt += "║  SOBRE QUALQUER DIAGNÓSTICO AUTOMÁTICO DA IA.                    ║\n"
                correcoes_prompt += "╚══════════════════════════════════════════════════════════════════╝\n\n"
                for i, insight in enumerate(qa_insights):
                    correcoes_prompt += f"**DIAGNÓSTICO HUMANO #{i+1}:**\n"
                    correcoes_prompt += f"> {insight}\n\n"
                correcoes_prompt += "Você DEVE seguir esta orientação como diretriz principal para aplicar as correções abaixo. "
                correcoes_prompt += "O código gerado deve refletir cirurgicamente o que o analista QA descreveu.\n"
            
            # Coleta de tentativas fracassadas históricas correspondentes a estas correções pendentes
            failed_attempts = []
            if os.path.exists(correcoes_acumuladas_path):
                try:
                    with open(correcoes_acumuladas_path, "r", encoding="utf-8") as cf:
                        all_corrs = json.load(cf)
                    for pc in pending_corrections:
                        p_sel = pc.get("failed_selector")
                        p_act = pc.get("action")
                        
                        # Busca tentativas falhas anteriores
                        for c in all_corrs:
                            if c.get("status") == "failed_attempt" and c.get("failed_selector") == p_sel and c.get("action") == p_act:
                                if c not in failed_attempts:
                                    failed_attempts.append(c)
                except Exception as ex:
                    print(f"[WARNING] Erro ao carregar tentativas anteriores em code_generator: {ex}")
            
            if failed_attempts:
                correcoes_prompt += "\n---\n\n"
                correcoes_prompt += "### ❌ HISTÓRICO DE ABORDAGENS ANTERIORES QUE FALHARAM (PROIBIÇÃO DE REPETIÇÃO)\n"
                correcoes_prompt += "╔══════════════════════════════════════════════════════════════════╗\n"
                correcoes_prompt += "║  ATENÇÃO: AS ABORDAGENS E PROPOSTAS TÉCNICAS LISTADAS ABAIXO     ║\n"
                correcoes_prompt += "║  JÁ FORAM TENTADAS E APLICADAS NO CÓDIGO DO ROBÔ ANTERIORMENTE,  ║\n"
                correcoes_prompt += "║  BUT NÃO SOLUCIONARAM O ERRO (O ROBÔ CONTINUOU FALHANDO).        ║\n"
                correcoes_prompt += "║  VOCÊ ESTÁ TERMINANTEMENTE PROIBIDO DE REPETIR ESSAS ABORDAGENS. ║\n"
                correcoes_prompt += "╚══════════════════════════════════════════════════════════════════╝\n\n"
                for idx, fa in enumerate(failed_attempts):
                    correcoes_prompt += f"**TENTATIVA FRACASSADA #{idx+1} para a ação '{fa.get('action')}' no seletor '{fa.get('failed_selector')}':**\n"
                    correcoes_prompt += f"- Proposta que Falhou: {fa.get('proposed_fix')}\n"
                    if fa.get("root_cause"):
                        correcoes_prompt += f"- Causa do Problema Original: {fa.get('root_cause')}\n"
                    if fa.get("qa_insight"):
                        correcoes_prompt += f"- Diagnóstico Humano do QA: {fa.get('qa_insight')}\n"
                    correcoes_prompt += "\n"
                correcoes_prompt += "Analise os erros pregressos e crie uma nova estratégia técnica totalmente diferente e resiliente para contornar a falha.\n\n"

            # ── Seção de correções técnicas (retroalimentação) ──
            section_num = "7" if (qa_insights and failed_attempts) else ("6" if (qa_insights or failed_attempts) else "5")
            correcoes_prompt += f"\n---\n\n### 🛠️ {section_num}. FEEDBACK DE ERROS E CORREÇÕES OBRIGATÓRIAS (RETROALIMENTAÇÃO)\n"
            correcoes_prompt += "Na última execução deste robô, ocorreram falhas físicas e de sincronização. "
            correcoes_prompt += "Você deve obrigatoriamente aplicar as seguintes correções críticas no código gerado:\n\n"
            for idx, corr in enumerate(pending_corrections):
                correcoes_prompt += f"{idx+1}. Para a ação de '{corr.get('action')}' no seletor '{corr.get('failed_selector')}':\n"
                correcoes_prompt += f"   - Problema Identificado: {corr.get('root_cause')}\n"
                correcoes_prompt += f"   - Correção Solicitada: {corr.get('proposed_fix')}\n\n"

        playbook_path = os.path.join(PROJECT_ROOT, "aegis_mentor", "skills", "rpa-copilot-coder.md")
        if not os.path.exists(playbook_path):
            playbook_content = "Siga as diretrizes padrão de resiliência para automações Playwright + Python."
        else:
            with open(playbook_path, "r", encoding="utf-8") as f:
                playbook_content = f.read()

        # Constrói o Prompt de Compilação para a LLM
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
{correcoes_prompt}

---

#### ⚠️ REGRAS OBRIGATÓRIAS PARA GERAÇÃO DO CÓDIGO:
1. **Estrutura SDK Aegis (`TransactionRunner`):**
   O robô deve ser gerado utilizando o SDK do Aegis. O arquivo gerado deve seguir a seguinte estrutura exata:
   ```python
   import os
   import sys
   import time
   from playwright.sync_api import Page
   
   # Resolve o caminho do framework Aegis RPA Suite dinamicamente subindo os diretórios
   current_dir = os.path.dirname(os.path.abspath(__file__))
   AEGIS_SUITE_ROOT = current_dir
   while AEGIS_SUITE_ROOT and not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):
       parent = os.path.dirname(AEGIS_SUITE_ROOT)
       if parent == AEGIS_SUITE_ROOT:
           break
       AEGIS_SUITE_ROOT = parent
   
   # Se não encontrar localmente, adiciona a pasta global padrão da suíte Aegis
   if not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):
       global_path = r"C:\\\\Projetos\\\\aegis_rpa_suite"
       if os.path.exists(global_path):
           AEGIS_SUITE_ROOT = global_path
           
   if AEGIS_SUITE_ROOT not in sys.path:
       sys.path.insert(0, AEGIS_SUITE_ROOT)
       
   from aegis_runner.runner import TransactionRunner
   
   def execute_scenario_default(page: Page, row, runner):
       print("\\\\n[BOT] Iniciando automação do fluxo...")
       # [Implemente aqui o preenchimento passo a passo do cenário 'default']
       
    if __name__ == "__main__":
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Se estiver na pasta 'code', o diretório do projeto é a pasta pai
        project_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) == "code" else current_dir
        runner = TransactionRunner(
            project_dir=project_dir,
            error_message_selector=".toast-error, .alert-danger"
        )
       runner.register_scenario("default", execute_scenario_default)
       runner.run(headless=False)
   ```
2. **Uso Obrigatório de `runner.click_resilient`:**
   Você é **PROIBIDO** de usar `.click()` diretamente do objeto `page` ou `locator`. Todos os cliques em botões, links ou abas devem ser executados através da função:
   `runner.click_resilient(page, selector="<seletor>", target_description="<descrição_curta_do_campo>", original_coords=...)`
   - **Extração de Coordenadas (Crucial)**: Verifique se o passo no relatório de telemetria possui marcação de coordenadas, como `[coords: (0.2452, 0.4563)]`. Se houver, passe a tupla exata em `original_coords`, exemplo: `original_coords=(0.2452, 0.4563)`. Se não houver coordenadas descritas para aquele passo no relatório, omita o argumento `original_coords`.
   - **Menus Suspensos (Padrão N)**: Se um seletor na telemetria pertencer a um menu suspenso ou dropdown (geralmente contendo `.sub-menu`, `.dropdown-menu` ou similar), você é obrigado a convertê-lo em um seletor composto encadeado com ` >> ` separando o item do menu pai (geralmente `#menu-item-XXXXX` ou similar) do item do submenu (exemplo: `#menu-item-28904 >> #menu-item-141846 a:has-text(...)`), ativando a expansão automática por hover do runner. **NÃO** divida o seletor na tag `ul` ou contêiner mais externo (como `#menu-1-43939cc >> ...`), pois isso não disparará o hover no item correto.
3. **Uso Obrigatório de `runner.fill_resilient`:**
   Você é **PROIBIDO** de usar `.fill()` diretamente do objeto `page` ou `locator`. Todos os preenchimentos comuns devem ser executados através de:
   `runner.fill_resilient(page, selector="<seletor>", text_val=row["<chave_semantica>"], target_description="<descrição>", strategy="DIRECT")`
   - **Proibição Absoluta de Valores Fixos**: Você é **PROIBIDO** de passar strings fixas/literais de teste (ex: `text_val="valor_gravado"`) no parâmetro `text_val`. Use obrigatoriamente referências ao registro do dataset `row`, ex: `text_val=row.get("chave", "")`.
4. **Padrão M (Detecção Anti-Bot Comportamental / HUMAN_LIKE):**
   Verifique o campo `fill_strategy` no `dicionario.json`. Se o campo tiver `"fill_strategy": "HUMAN_LIKE"`, ou se o campo for um input de texto que precede um autocomplete ou dropdown dinâmico (onde o usuário digita e depois clica em uma opção da lista correspondente), você é **PROIBIDO** de usar preenchimento direto. Você deve usar **obrigatoriamente** `strategy="HUMAN_LIKE"` para simular a digitação cadenciada humana e disparar os eventos de busca corretos no portal. Você é **PROIBIDO** de usar strings fixas/literais aqui; use sempre a referência à variável `row`, ex:
   `runner.fill_resilient(page, selector="<seletor>", text_val=row.get("<chave_semantica>", ""), target_description="<descrição>", strategy="HUMAN_LIKE")`
5. **Utilização do Dataset (`row`) - PROIBIÇÃO ABSOLUTA DE HARDCODES:**
   Todos os campos do formulário preenchidos dinamicamente devem obter seus valores do dicionário `row` usando as chaves semânticas exatas do dicionário de dados (ex: `row.get("cpf_cliente", "")` ou `row["modelo"]`).
   Você é **TERMINANTEMENTE PROIBIDO** de usar strings literais ou valores hardcoded como entrada no código gerado, seja para preenchimento de input (`fill_resilient`, `fill_human_like`) ou seleção de dropdown (`select_option_resilient`). Mesmo que a telemetria ou o relatório de passos exiba valores observados literais nos passos (ex: "Preencheu com: 'admin@portalsegura.com'"), você é **OBRIGADO** a mapear essa ação para obter o valor dinamicamente da coluna correspondente no dataset (`row.get("email_login", "")`).
   Também é **ESTRITAMENTE PROIBIDO** utilizar valores de dados do negócio observados como o valor padrão/fallback em chamadas `.get()` (ex: usar `row.get("sexo_cliente", "Masculino")` ou `row.get("estado_civil_cliente", "Solteiro(a)")` é uma quebra dessa regra pois contém a string hardcoded `'Masculino'` ou `'Solteiro(a)'`). Se for utilizar `.get()`, utilize string vazia como fallback (ex: `row.get("sexo_cliente", "")`) ou use acesso direto por chave (ex: `row["sexo_cliente"]`).
6. **Padrão K (Campos de Data):**
   Para preenchimento de datas, utilize seleção completa com `Control+A` e digitação, ou injeção DOM de propriedades removendo a flag `readonly` e despachando os eventos `input` e `change` se necessário.
7. **Padrão L (Diálogo de Arquivos / Upload):**
   Para upload de arquivos, use `with page.expect_file_chooser()` ou `page.set_input_files()`.
8. **Espera de transições e Proibição de Seletores Inventados (Crítico):**
   Você é **ESTRITAMENTE PROIBIDO** de inventar, supor ou adivinhar seletores hipotéticos (como `h1:has-text(...)`, cabeçalhos de título, banners ou labels) para usar in `wait_for` ou qualquer espera de transição de tela. Se um elemento ou seletor não foi gravado de fato na lista de passos da telemetria (não consta na lista original de eventos), você **NÃO PODE** criar nenhuma instrução `wait_for` esperando por ele. Para aguardar transições, use apenas a sincronização do próprio passo de clique/preenchimento seguinte da telemetria. É **PROIBIDO** usar `wait_for_url` se o portal for uma SPA. Além disso, sempre adicione uma espera explícita (ex: `time.sleep(2.0)`) logo após preencher campos de identificação (como CPF, CNPJ, CEP) que notoriamente disparam buscas assíncronas no backend e autopreenchimento de outros campos na tela, evitando que o robô interaja com o formulário enquanto o backend ainda está reescrevendo valores. Evite outros `time.sleep` estáticos cegos, a não ser que seja para aguardar a conclusão de animações.
9. **Proibição Absoluta de Hardcode e Tratamento de Variáveis (Segurança e Portabilidade):**
   Não coloque credenciais, dados cadastrais, URLs ou qualquer dado de entrada em texto fixo/literal no código gerado.
   Você é **PROIBIDO** de lançar exceções (`raise ValueError`, `raise Exception`, etc) que abortam a execução do robô caso variáveis de ambiente personalizadas inventadas por você (como EMAIL_LOGIN ou SENHA_LOGIN) não estejam definidas. Toda a leitura de dados de entrada do fluxo transacional deve ser orientada ao dataset `row`. Se precisar usar variáveis de ambiente para configurações globais da execução, sempre utilize um fallback para os dados de `row` ou valores padrão usando `os.getenv`.
10. **Geração Unificada de Fluxo (Crítico):**
    A telemetria ou o relatório de passos pode conter marcações de diferentes sub-cenários (ex: 'login', 'passo_1_cliente', 'passo_2_veiculo'). Você é **PROIBIDO** de separar esses passos em funções de cenários diferentes no TransactionRunner. Você deve compilar todos os passos descritos no relatório, do primeiro ao último, sequencialmente de forma linear dentro de uma única função principal `execute_scenario_default`. Apenas o cenário `"default"` deve ser registrado e executado no runner.
11. **Saída:**
    Retorne **EXCLUSIVAMENTE** o código Python estruturado, embalado em um bloco de código markdown:
    ```python
    # código aqui
    ```
    Não forneça explicações, observações ou introduções. Apenas o código.
"""
        print(f"[INFO] Conectando ao Gateway de IA ({gateway.provider} / {gateway.model})...")
        print("[INFO] Solicitando geração de código baseada em resiliência técnica...")
        sys.stdout.flush()

        try:
            response_text = gateway._call_llm_api(prompt, force_json=False)
        except Exception as e:
            print(f"[ERRO] Falha ao invocar a API de LLM: {e}")
            return False

        print("[INFO] Código gerado com sucesso pela IA. Limpando payload...")

        generated_code = self._extract_python_code(response_text)

        # Validação Sintática
        if not self._validate_syntax(generated_code):
            return False

        # Salva o arquivo bot_producao.py
        self._save_bot_file(bot_path, generated_code)

        # Atualiza o status das correções no JSON histórico
        self._mark_corrections_applied(pending_corrections, correcoes_acumuladas_path)

        # Atualiza os arquivos de índice e project.json
        self._write_index_and_metadata(code_dir, project_json_path)

        print("-" * 60)
        print("✅ CÓDIGO DA AUTOMAÇÃO RPA GERADO COM SUCESSO!")
        print(f"O robô resiliente está salvo e pronto para a Fase 5 (Execução).")
        print("=" * 60 + "\n")
        return True

    def _surgical_correct(self, bot_path: str, pending_corrections: list, gateway, project_json_path: str, code_dir: str, correcoes_acumuladas_path: str) -> bool:
        print("[INFO] Lendo código-fonte existente...")
        with open(bot_path, "r", encoding="utf-8") as f:
            existing_code = f.read()

        # Monta os insights/correções
        correcoes_desc = ""
        qa_insights = list(set(c.get("qa_insight") for c in pending_corrections if c.get("qa_insight")))

        if qa_insights:
            correcoes_desc += "### ⚠️🧠 INSIGHT CRÍTICO DO ANALISTA QA (PRIORIDADE MÁXIMA)\n"
            correcoes_desc += "╔══════════════════════════════════════════════════════════════════╗\n"
            correcoes_desc += "║  ATENÇÃO: A INFORMAÇÃO ABAIXO FOI FORNECIDA POR UM ANALISTA     ║\n"
            correcoes_desc += "║  QA HUMANO QUE TESTOU MANUALMENTE O SISTEMA E IDENTIFICOU A     ║\n"
            correcoes_desc += "║  CAUSA REAL DO PROBLEMA. ESTA ANÁLISE TEM PRECEDÊNCIA ABSOLUTA   ║\n"
            correcoes_desc += "║  SOBRE QUALQUER DIAGNÓSTICO AUTOMÁTICO DA IA.                    ║\n"
            correcoes_desc += "╚══════════════════════════════════════════════════════════════════╝\n\n"
            for idx, insight in enumerate(qa_insights):
                correcoes_desc += f"**DIAGNÓSTICO HUMANO #{idx+1}:**\n"
                correcoes_desc += f"> {insight}\n\n"
            correcoes_desc += "O código corrigido deve refletir cirurgicamente o que o analista QA descreveu acima.\n\n"

        # ── Coleta de tentativas fracassadas históricas para os mesmos seletores/ações ──
        failed_attempts = []
        if os.path.exists(correcoes_acumuladas_path):
            try:
                with open(correcoes_acumuladas_path, "r", encoding="utf-8") as cf:
                    all_corrs = json.load(cf)
                for pc in pending_corrections:
                    p_sel = pc.get("failed_selector")
                    p_act = pc.get("action")
                    for c in all_corrs:
                        if (
                            c.get("status") == "failed_attempt"
                            and c.get("failed_selector") == p_sel
                            and c.get("action") == p_act
                            and c not in failed_attempts
                        ):
                            failed_attempts.append(c)
            except Exception as ex:
                print(f"[WARNING] Erro ao carregar tentativas anteriores em _surgical_correct: {ex}")

        if failed_attempts:
            correcoes_desc += "### ❌ HISTÓRICO DE ABORDAGENS ANTERIORES QUE FALHARAM (PROIBIÇÃO DE REPETIÇÃO)\n"
            correcoes_desc += "╔══════════════════════════════════════════════════════════════════╗\n"
            correcoes_desc += "║  ATENÇÃO: AS ABORDAGENS E PROPOSTAS TÉCNICAS LISTADAS ABAIXO     ║\n"
            correcoes_desc += "║  JÁ FORAM TENTADAS E APLICADAS NO CÓDIGO DO ROBÔ ANTERIORMENTE,  ║\n"
            correcoes_desc += "║  MAS NÃO SOLUCIONARAM O ERRO (O ROBÔ CONTINUOU FALHANDO).        ║\n"
            correcoes_desc += "║  VOCÊ ESTÁ TERMINANTEMENTE PROIBIDO DE REPETIR ESSAS ABORDAGENS. ║\n"
            correcoes_desc += "╚══════════════════════════════════════════════════════════════════╝\n\n"
            for idx, fa in enumerate(failed_attempts):
                correcoes_desc += f"**TENTATIVA FRACASSADA #{idx+1} para a ação '{fa.get('action')}' no seletor '{fa.get('failed_selector')}':**\n"
                correcoes_desc += f"- Proposta que Falhou: {fa.get('proposed_fix')}\n"
                if fa.get("root_cause"):
                    correcoes_desc += f"- Causa Original: {fa.get('root_cause')}\n"
                if fa.get("qa_insight"):
                    correcoes_desc += f"- Diagnóstico Humano do QA: {fa.get('qa_insight')}\n"
                correcoes_desc += "\n"
            correcoes_desc += "Você deve criar uma estratégia técnica completamente nova e diferente para cada um dos seletores acima.\n\n"

        correcoes_desc += "### 🛠️ ERROS E CORREÇÕES OBRIGATÓRIAS (RETROALIMENTAÇÃO):\n"
        for idx, corr in enumerate(pending_corrections):
            correcoes_desc += f"{idx+1}. Ação de '{corr.get('action')}' no seletor '{corr.get('failed_selector')}':\n"
            correcoes_desc += f"   - Causa Raiz: {corr.get('root_cause')}\n"
            correcoes_desc += f"   - Correção Requisitada: {corr.get('proposed_fix')}\n\n"

        prompt = f"""
Você é um Engenheiro de IA especialista em Automação de Processos Robóticos (RPA) de alta resiliência usando Playwright e Python.
Sua tarefa é aplicar correções e melhorias de forma estritamente CIRÚRGICA no código-fonte Python existente do robô RPA.

Você DEVE seguir rigorosamente os princípios de simplicidade e alteração cirúrgica (Karpathy style):
1. **Simplicidade Acima de Tudo (Simplicity First)**:
   - Escreva o menor código possível que resolva o problema. Nada de especulações, abstrações ou flexibilidades não solicitadas.
2. **Alterações Cirúrgicas (Surgical Changes)**:
   - Toque APENAS no código que precisa ser alterado para resolver as correções listadas abaixo.
   - Você é **PROIBIDO** de reescrever ou melhorar trechos de códigos adjacentes, formatar outras seções do arquivo, ou alterar comentários/coordenadas de passos que não estão sob erro.
   - Mantenha exatamente o mesmo estilo do código existente.
3. **Limpeza de Órfãos (Orphan Cleanup)**:
   - Remova apenas imports, variáveis ou funções que suas próprias alterações tornaram obsoletos. Não remova códigos mortos preexistentes se não tiverem relação com os erros indicados.
4. **Proibição Absoluta de Hardcodes**:
   - NUNCA insira valores fixos/hardcoded como CPFs, nomes, datas ou opções nas chamadas de interação (ex: use `row.get("cpf_cliente", "")` ou `row["campo"]`, nunca strings de teste).
   - É terminantemente proibido utilizar valores de dados do negócio observados como fallback de `.get()` (ex: usar `row.get("sexo_cliente", "Masculino")` é proibido; use `row.get("sexo_cliente", "")`).

---

### 💻 1. CÓDIGO-FONTE ATUAL DO ROBÔ:
```python
{existing_code}
```

---

### 📋 2. CORREÇÕES E INSIGHTS A SEREM APLICADOS:
{correcoes_desc}

---

### ⚠️ REGRAS DE SAÍDA:
Retorne **EXCLUSIVAMENTE** o código Python completo atualizado com as correções aplicadas, envelopado em um bloco de código markdown:
```python
# código aqui
```
Não dê explicações ou introduções. Apenas o código.
"""
        print(f"[INFO] Conectando ao Gateway de IA ({gateway.provider} / {gateway.model})...")
        print("[INFO] Solicitando correção cirúrgica do robô...")
        sys.stdout.flush()

        try:
            response_text = gateway._call_llm_api(prompt, force_json=False)
        except Exception as e:
            print(f"[ERRO] Falha ao invocar a API de LLM: {e}")
            return False

        print("[INFO] Código corrigido com sucesso pela IA. Limpando payload...")

        generated_code = self._extract_python_code(response_text)

        # Validação Sintática
        if not self._validate_syntax(generated_code):
            return False

        # Salva o arquivo bot_producao.py
        self._save_bot_file(bot_path, generated_code)

        # Atualiza o status das correções no JSON histórico
        self._mark_corrections_applied(pending_corrections, correcoes_acumuladas_path)

        # Atualiza os arquivos de índice e project.json
        self._write_index_and_metadata(code_dir, project_json_path)

        print("-" * 60)
        print("✅ CÓDIGO DO ROBÔ CORRIGIDO CIRURGICAMENTE COM SUCESSO!")
        print("=" * 60 + "\n")
        return True

    def _extract_python_code(self, response_text: str) -> str:
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

        return generated_code.strip()

    def _validate_syntax(self, code: str) -> bool:
        print("[INFO] Executando validação sintática do código...")
        try:
            # Valida compilação básica
            compile(code, "<string>", "exec")
            
            # Valida estrutura via AST (Garante que não é apenas um JSON ou dicionário literal)
            import ast
            tree = ast.parse(code)
            if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, (ast.Dict, ast.Constant, ast.List)):
                raise SyntaxError("O código gerado é apenas uma estrutura de dados (JSON/Dicionário/Literal) e não um script Python executável.")
            
            print("[INFO] Validação sintática concluída com sucesso! (Código Python válido)")
            return True
        except (SyntaxError, ValueError) as syntax_err:
            print("\n" + "=" * 60)
            print(f"[ERRO CRÍTICO] O código gerado pela IA é inválido!")
            if hasattr(syntax_err, 'lineno') and syntax_err.lineno:
                print(f"Linha {syntax_err.lineno}: {syntax_err.text.strip() if syntax_err.text else ''}")
            print(f"Erro: {str(syntax_err)}")
            print("A gravação do robô foi abortada para evitar a persistência de código corrompido.")
            print("=" * 60 + "\n")
            return False

    def _save_bot_file(self, bot_path: str, code: str):
        print(f"[INFO] Gravando arquivo do robô em: {bot_path}")
        with open(bot_path, "w", encoding="utf-8") as f:
            f.write(code)

    def _mark_corrections_applied(self, pending_corrections: list, correcoes_acumuladas_path: str):
        if pending_corrections and os.path.exists(correcoes_acumuladas_path):
            try:
                with open(correcoes_acumuladas_path, "r", encoding="utf-8") as cf:
                    all_corrs = json.load(cf)
                for corr in all_corrs:
                    if corr.get("status") == "pending":
                        corr["status"] = "applied"
                        corr["applied_at"] = datetime.now().isoformat()
                with open(correcoes_acumuladas_path, "w", encoding="utf-8") as cf:
                    json.dump(all_corrs, cf, indent=4, ensure_ascii=False)
                print(f"[INFO] {len(pending_corrections)} correções foram marcadas como 'aplicadas' (applied) no histórico.")
            except Exception as e:
                print(f"[WARNING] Falha ao atualizar status de correções em correcoes_acumuladas.json: {e}")

    def _write_index_and_metadata(self, code_dir: str, project_json_path: str):
        # Grava o arquivo de índice JSON
        index_data = {
            "component": "code_generator",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "files": [
                {
                    "path": "code/bot_producao.py",
                    "type": "source_code",
                    "description": "Script Python principal contendo o fluxo linear da automação do robô RPA, utilizando cliques e preenchimentos resilientes."
                }
            ]
        }
        if os.path.exists(os.path.join(code_dir, "skills_lib.py")):
            index_data["files"].append({
                "path": "code/skills_lib.py",
                "type": "source_code",
                "description": "Biblioteca de Skills reutilizáveis (funções modulares) do projeto que foram compiladas via IA."
            })
        
        index_path = os.path.join(code_dir, "index_arquivos.json")
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=4, ensure_ascii=False)
        print(f"[INFO] Índice de arquivos do gerador de código salvo em: {index_path}")

        # Atualiza o status do projeto no project.json
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




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis RPA Code Generator (Fase 4)")
    parser.add_argument("--project-dir", required=True, help="Diretório do projeto isolado")
    args = parser.parse_args()

    service = CodeGeneratorService(args.project_dir)
    success = service.generate()
    if not success:
        sys.exit(1)
