import os
import sys
import json
import re
import ast
import argparse
import difflib
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# Adiciona caminhos necessários ao path
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from aegis_runner.cognitive_fallback import CognitiveGateway
from aegis_sanitizer.step_validator import (
    validate_bot_against_plan, validate_bot_structure, dry_run_bot, reorder_steps_to_match_plan,
    validate_dataset_field_names, validate_resilience_patterns, validate_required_wait_patterns,
    validate_required_reopen_patterns, validate_required_method_patterns, RUNNER_METHODS
)


class CodeGeneratorService:
    def __init__(self, project_dir: str):
        self.project_dir = os.path.abspath(project_dir)
        self.plan_path = os.path.join(self.project_dir, "plano_execucao.json")
        self.bot_path = os.path.join(self.project_dir, "code", "bot_producao.py")

    def _normalize_boilerplate(self, bot_code: str) -> str:
        """
        Substitui deterministicamente o cabeçalho (imports + bootstrap de
        sys.path) e o bloco 'if __name__ == "__main__":' por versões fixas e
        canônicas, em vez de confiar na LLM para reproduzir esse boilerplate —
        que é puramente mecânico e não deveria variar entre gerações. Na
        prática a LLM erra de duas formas distintas: (a) no fluxo de geração
        nova, o __main__ sai incompleto (error_message_selector ausente,
        headless=False vs runner.run()); (b) no fluxo de correção cirúrgica, a
        LLM às vezes reescreve o arquivo inteiro e derruba o bootstrap de
        sys.path que resolve 'from aegis_runner.runner import TransactionRunner'
        quando o bot roda como script standalone (fora do cwd do framework) —
        causa ModuleNotFoundError silencioso só detectável em execução real.
        Por isso só os FunctionDef/ClassDef do corpo do bot (a lógica de
        automação em si) são preservados; imports e qualquer código solto em
        nível de módulo são descartados e reconstruídos aqui.
        """
        canonical_header = [
            'import os',
            'import sys',
            'import time',
            'from playwright.sync_api import Page',
            '',
            'current_dir = os.path.dirname(os.path.abspath(__file__))',
            'AEGIS_SUITE_ROOT = current_dir',
            'while AEGIS_SUITE_ROOT and not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):',
            '    parent = os.path.dirname(AEGIS_SUITE_ROOT)',
            '    if parent == AEGIS_SUITE_ROOT:',
            '        break',
            '    AEGIS_SUITE_ROOT = parent',
            '',
            'if not os.path.exists(os.path.join(AEGIS_SUITE_ROOT, "aegis_runner")):',
            '    global_path = r"C:\\Projetos\\aegis_rpa_suite"',
            '    if os.path.exists(global_path):',
            '        AEGIS_SUITE_ROOT = global_path',
            '',
            'if AEGIS_SUITE_ROOT not in sys.path:',
            '    sys.path.insert(0, AEGIS_SUITE_ROOT)',
            '',
            'from aegis_runner.runner import TransactionRunner',
        ]

        _error_selector = getattr(self, "error_message_selector", ".toast-error, .alert-danger")
        _error_selector_escaped = _error_selector.replace('"', '\\"')

        canonical_main = [
            'if __name__ == "__main__":',
            '    current_dir = os.path.dirname(os.path.abspath(__file__))',
            '    project_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) == "code" else current_dir',
            '',
            f'    runner = TransactionRunner(project_dir=project_dir, error_message_selector="{_error_selector_escaped}")',
            '    runner.register_scenario(scenario_name="default", callback=execute_scenario_default)',
            '    runner.run()',
        ]

        try:
            tree = ast.parse(bot_code)
        except SyntaxError:
            return bot_code

        lines = bot_code.split("\n")
        body_chunks = []
        for node in tree.body:
            is_main_block = (
                isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
            )
            if is_main_block:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start_idx = node.lineno - 1
                end_idx = node.end_lineno
                body_chunks.append("\n".join(lines[start_idx:end_idx]))
            # Imports e qualquer outro statement solto em nível de módulo
            # (ex.: bootstrap de sys.path reescrito pela LLM) são descartados —
            # já cobertos pelo canonical_header acima.

        normalized = (
            "\n".join(canonical_header) + "\n\n"
            + "\n\n".join(body_chunks) + "\n\n"
            + "\n".join(canonical_main) + "\n"
        )
        return normalized

    def _strip_stray_transaction_runner_calls(self, bot_code: str) -> str:
        """
        Remove statements que instanciam TransactionRunner(...) fora do bloco
        canônico 'if __name__' já reconstruído por _normalize_boilerplate.
        Como esse bloco canônico sempre tem project_dir= correto, qualquer
        instanciação sobrevivente (dentro de uma FunctionDef, preservada
        verbatim pela normalização) é necessariamente uma duplicata
        alucinada — o robô só instancia o runner uma vez. Não é algo pra
        "corrigir" adicionando project_dir= (a variável nem existe nesse
        escopo); é lixo pra remover.
        """
        try:
            tree = ast.parse(bot_code)
        except SyntaxError:
            return bot_code

        def is_ctor_call(node):
            return (
                isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Name) and node.func.id == "TransactionRunner") or
                    (isinstance(node.func, ast.Attribute) and node.func.attr == "TransactionRunner")
                )
            )

        def is_main_block(node):
            return (
                isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
            )

        ranges_to_strip = []

        def scan_body(body, inside_main):
            for stmt in body:
                if is_main_block(stmt):
                    scan_body(stmt.body, True)
                    continue
                if (not inside_main and isinstance(stmt, (ast.Assign, ast.Expr))
                        and is_ctor_call(stmt.value)):
                    has_project_dir = any(kw.arg == "project_dir" for kw in stmt.value.keywords)
                    if not has_project_dir:
                        ranges_to_strip.append((stmt.lineno - 1, stmt.end_lineno))
                    continue
                for field in ("body", "orelse", "finalbody"):
                    inner = getattr(stmt, field, None)
                    if isinstance(inner, list):
                        scan_body(inner, inside_main)

        scan_body(tree.body, False)
        if not ranges_to_strip:
            return bot_code

        lines = bot_code.split("\n")
        for start, end in sorted(ranges_to_strip, reverse=True):
            del lines[start:end]
        return "\n".join(lines)

    @staticmethod
    def _strip_internal_step_fields(steps: list) -> list:
        """
        Remove campos internos de bookkeeping do sanitizer (trigger_selector,
        option_selector, fallback_selectors) antes de expor os steps do plano
        pra LLM — esses campos nao sao kwargs validos de select_option_resilient
        (que so aceita original_coords_trigger/original_coords_option) e a LLM os
        confunde com nomes de parametro, gerando TypeError em runtime.
        fallback_selectors e bookkeeping interno do sanitizer para self-healing
        e nao deve ser exposto/manipulado pela LLM.
        """
        internal_fields = ("trigger_selector", "option_selector", "fallback_selectors")
        return [
            {k: v for k, v in step.items() if k not in internal_fields}
            for step in steps
        ]

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
        self.gateway = CognitiveGateway(project_dir=self.project_dir)
        if getattr(self.gateway, "coder_model", None):
            self.gateway.model = self.gateway.coder_model
        print(f"[INFO] Modelo de IA configurado para codificação: {self.gateway.model}")
        if not self.gateway.is_active():
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

        # Campo opcional 'error_message_selector' em project.json permite customizar
        # o seletor de mensagem de erro usado pelo TransactionRunner (default abaixo
        # é o boilerplate canônico histórico, mantido para projetos sem o campo).
        self.error_message_selector = ".toast-error, .alert-danger"
        if os.path.exists(project_json_path):
            try:
                with open(project_json_path, "r", encoding="utf-8") as f:
                    _proj_cfg = json.load(f)
                _custom_selector = _proj_cfg.get("error_message_selector")
                if _custom_selector:
                    self.error_message_selector = _custom_selector
            except Exception as e:
                print(f"[WARNING] Falha ao ler 'error_message_selector' de project.json: {e}")

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
                # Correções com `required_wait` codificam um invariante
                # permanente de runtime atrelado a um step_id (ex.: campo que
                # fica bloqueado por N segundos após outro ser preenchido) —
                # precisam ser reforçadas em TODA regeneração futura, não só
                # na primeira vez. Diferente de uma correção pontual comum
                # (que uma vez "applied" não deve mais poluir o prompt), essas
                # nunca "saem de moda": sem isso, uma regeneração do zero
                # perde silenciosamente o wait já validado antes.
                # EXCETO quando o QA já marcou a entrada como 'resolved' ou
                # 'applied' no Cockpit (cockpit.py, endpoint de update de
                # status) — aí é uma decisão humana terminal de que aquele
                # caso está fechado, e reforçar o invariante mecânico
                # (validate_required_*_patterns) não precisa da entrada no
                # prompt/escopo cirúrgico. Sem essa exclusão, bugs já
                # resolvidos voltavam a ser enviados como "correção
                # obrigatória" e entravam no escopo de edição (_surgical_correct,
                # target_step_ids) a cada regeneração futura.
                pending_corrections = [
                    c for c in all_corrs
                    if c.get("status") not in ("resolved", "applied")
                    and (
                        c.get("status") == "pending" or c.get("required_wait")
                        or c.get("required_reopen") or c.get("required_method")
                    )
                ]
            except Exception as e:
                print(f"[WARNING] Failed to read correcoes_acumuladas.json: {e}")

        code_dir = os.path.join(self.project_dir, "code")
        os.makedirs(code_dir, exist_ok=True)

        # ── Ralph Loop: tentativas com validação AST ──
        MAX_RETRIES = int(os.getenv("AEGIS_CODEGEN_MAX_RETRIES", "5"))
        attempts_history = []
        bot_code = None
        diff = None

        for attempt in range(1, MAX_RETRIES + 1):
            print(f"\n[AEGIS CODEGEN] Tentativa {attempt}/{MAX_RETRIES}...")

            if attempt == 1:
                has_existing_bot = os.path.exists(self.bot_path)
                has_pending_corrections_local = False
                if os.path.exists(correcoes_acumuladas_path):
                    try:
                        with open(correcoes_acumuladas_path, "r", encoding="utf-8") as f:
                            corrections = json.load(f)
                        has_pending_corrections_local = any(
                            c.get("status") == "pending" for c in corrections
                        )
                    except Exception:
                        pass

                if has_existing_bot and has_pending_corrections_local:
                    print("[INFO] Iniciando fluxo de CORREÇÃO CIRÚRGICA (Karpathy Style)...")
                    bot_code = self._surgical_correct(
                        self.bot_path, pending_corrections, self.gateway,
                        project_json_path, code_dir, correcoes_acumuladas_path
                    )
                else:
                    print("[INFO] Iniciando fluxo de GERAÇÃO DE CÓDIGO NOVO...")
                    bot_code = self._generate_new_code(
                        self.bot_path, dict_data, report_content, skills_info_prompt,
                        pending_corrections, self.gateway, project_json_path,
                        code_dir, correcoes_acumuladas_path
                    )
            else:
                # Reflection: surgical correct with diff feedback (Ralph Loop)
                bot_code = self._surgical_correct_with_reflection(
                    current_code=bot_code,
                    current_diff=diff,
                    history=attempts_history,
                    pending_corrections=pending_corrections
                )

            if bot_code is None:
                return False

            # Validate syntax
            if not self._validate_syntax(bot_code):
                return False

            # Normaliza deterministicamente o bloco __main__/imports (a LLM erra
            # esse boilerplate mesmo quando o prompt diz que já está pronto)
            bot_code = self._normalize_boilerplate(bot_code)

            # Validate bot structure (proíbe classes customizadas, asyncio.run, etc.)
            try:
                struct_result = validate_bot_structure(bot_code)
            except Exception as validator_err:
                raise RuntimeError(
                    f"Bug interno no validador (validate_bot_structure): {validator_err}. "
                    f"Corrija o step_validator.py antes de tentar gerar código novamente."
                ) from validator_err

            # Correção determinística de método alucinado: se o nome inválido
            # tem candidato único e próximo entre os métodos reais do SDK
            # (RUNNER_METHODS), renomeia via texto em vez de gastar uma
            # tentativa de LLM. Observado em produção: a IA repete a mesma
            # alucinação (ex.: 'select_native_resilient' em vez de
            # 'select_option_native_resilient') mesmo com o nome correto
            # presente no JSON de reflexão — o token errado continua no
            # bloco que ela vê e ela reancora nele. Remover o token do
            # input é mais forte que só pedir a correção em prosa.
            if struct_result["status"] == "FAIL":
                hallucinated = [e for e in struct_result["errors"] if e["type"] == "HALLUCINATED_RUNNER_METHOD"]
                if hallucinated:
                    renamed_code = bot_code
                    any_renamed = False
                    for err in hallucinated:
                        bad_method = err.get("method", "")
                        candidates = difflib.get_close_matches(bad_method, sorted(RUNNER_METHODS), n=1, cutoff=0.75)
                        if len(candidates) == 1:
                            new_code = renamed_code.replace(f"runner.{bad_method}(", f"runner.{candidates[0]}(")
                            if new_code != renamed_code:
                                renamed_code = new_code
                                any_renamed = True
                    if any_renamed:
                        try:
                            retry_struct = validate_bot_structure(renamed_code)
                        except Exception as validator_err:
                            raise RuntimeError(
                                f"Bug interno no validador (validate_bot_structure): {validator_err}. "
                                f"Corrija o step_validator.py antes de tentar gerar código novamente."
                            ) from validator_err
                        print("[AEGIS CODEGEN] 🔧 Método alucinado corrigido automaticamente por proximidade textual (sem gastar tentativa de LLM).")
                        bot_code = renamed_code
                        struct_result = retry_struct

            # Correção determinística de instanciação espúria de TransactionRunner:
            # _normalize_boilerplate (acima) já reconstrói o bloco 'if __name__'
            # canônico com project_dir= correto sempre — logo, qualquer
            # MISSING_PROJECT_DIR_ARG/RUNNER_INSTANTIATED_AT_MODULE_SCOPE que
            # sobreviva à normalização só pode vir de uma instanciação ESPÚRIA
            # duplicada dentro do corpo de uma função (normalize preserva
            # FunctionDef verbatim). Não é um construtor pra "consertar" — é
            # lixo que não deveria existir (o robô só instancia o runner uma
            # vez, no bloco __main__). Pedir pra IA "corrigir" isso em prosa
            # trava em loop (ela tenta adicionar project_dir=, que nem existe
            # como variável no escopo da função) — remover a linha
            # deterministicamente resolve na raiz.
            if struct_result["status"] == "FAIL":
                stray_types = {"MISSING_PROJECT_DIR_ARG", "RUNNER_INSTANTIATED_AT_MODULE_SCOPE"}
                stray_errors = [e for e in struct_result["errors"] if e["type"] in stray_types]
                if stray_errors:
                    stripped_code = self._strip_stray_transaction_runner_calls(bot_code)
                    if stripped_code != bot_code:
                        try:
                            retry_struct = validate_bot_structure(stripped_code)
                        except Exception as validator_err:
                            raise RuntimeError(
                                f"Bug interno no validador (validate_bot_structure): {validator_err}. "
                                f"Corrija o step_validator.py antes de tentar gerar código novamente."
                            ) from validator_err
                        print("[AEGIS CODEGEN] 🔧 Instanciação espúria de TransactionRunner removida automaticamente (sem gastar tentativa de LLM).")
                        bot_code = stripped_code
                        struct_result = retry_struct

            if struct_result["status"] == "FAIL":
                print(f"[AEGIS CODEGEN] ❌ Validação estrutural falhou: {len(struct_result['errors'])} erro(s)")
                for err in struct_result["errors"]:
                    print(f"  • {err['detail']}")
                if os.getenv("AEGIS_DEBUG_DUMP_BOT"):
                    with open(os.getenv("AEGIS_DEBUG_DUMP_BOT"), "w", encoding="utf-8") as _dbgf:
                        _dbgf.write(bot_code)
                diff = struct_result
                attempts_history.append({
                    "attempt": attempt,
                    "diff": diff,
                    "snippets": self._extract_failing_snippets(bot_code, diff)
                })
                continue

            # Validate against plan (AST step_id validation)
            plan_result = {"status": "PASS", "total_errors": 0, "errors": []}
            if os.path.exists(self.plan_path):
                try:
                    plan_result = validate_bot_against_plan(bot_code, self.plan_path, pending_corrections)
                except Exception as validator_err:
                    raise RuntimeError(
                        f"Bug interno no validador (validate_bot_against_plan): {validator_err}. "
                        f"Corrija o step_validator.py antes de tentar gerar código novamente."
                    ) from validator_err

            # Correção determinística de ordem: se o único problema for STEP_ID_MISMATCH
            # (mesmos step_ids presentes, ordem errada), reordena via AST em vez de
            # gastar uma tentativa de LLM — reordenação é tarefa mecânica, não criativa.
            if plan_result["status"] == "FAIL" and os.path.exists(self.plan_path):
                error_types = {e["type"] for e in plan_result.get("errors", [])}
                if error_types and error_types.issubset({"STEP_ID_MISMATCH"}):
                    with open(self.plan_path, "r", encoding="utf-8") as f:
                        planned_ids = [s["step_id"] for s in json.load(f)["steps"]]
                    reordered_code = reorder_steps_to_match_plan(bot_code, planned_ids)
                    if reordered_code != bot_code:
                        retry_result = validate_bot_against_plan(reordered_code, self.plan_path, pending_corrections)
                        if retry_result["status"] == "PASS":
                            print(f"[AEGIS CODEGEN] 🔧 Ordem dos passos corrigida automaticamente (sem gastar tentativa de LLM).")
                            bot_code = reordered_code
                            plan_result = retry_result

            # Campos de dataset alucinados (row.get("campo_inventado", ...))
            field_result = {"status": "PASS", "total_errors": 0, "errors": []}
            if os.path.exists(dict_path):
                try:
                    field_result = validate_dataset_field_names(bot_code, dict_path)
                except Exception as validator_err:
                    raise RuntimeError(
                        f"Bug interno no validador (validate_dataset_field_names): {validator_err}. "
                        f"Corrija o step_validator.py antes de tentar gerar código novamente."
                    ) from validator_err

            # Padrões de resiliência obrigatórios (click_chained, select_option_resilient, original_coords, HUMAN_LIKE)
            pattern_result = {"status": "PASS", "total_errors": 0, "errors": []}
            if os.path.exists(self.plan_path):
                try:
                    pattern_result = validate_resilience_patterns(bot_code, self.plan_path, dict_path)
                except Exception as validator_err:
                    raise RuntimeError(
                        f"Bug interno no validador (validate_resilience_patterns): {validator_err}. "
                        f"Corrija o step_validator.py antes de tentar gerar código novamente."
                    ) from validator_err

            # Sincronizações assíncronas exigidas explicitamente via correcoes_acumuladas.json
            # (campo 'required_wait') — checagem mecânica porque a LLM ignora esse pedido em prosa
            try:
                wait_result = validate_required_wait_patterns(bot_code, pending_corrections)
            except Exception as validator_err:
                raise RuntimeError(
                    f"Bug interno no validador (validate_required_wait_patterns): {validator_err}. "
                    f"Corrija o step_validator.py antes de tentar gerar código novamente."
                ) from validator_err

            # Re-disparos de campo exigidos explicitamente via correcoes_acumuladas.json
            # (campo 'required_reopen') — mesma lógica do required_wait acima
            try:
                reopen_result = validate_required_reopen_patterns(bot_code, pending_corrections)
            except Exception as validator_err:
                raise RuntimeError(
                    f"Bug interno no validador (validate_required_reopen_patterns): {validator_err}. "
                    f"Corrija o step_validator.py antes de tentar gerar código novamente."
                ) from validator_err

            # Troca de método exigida explicitamente via correcoes_acumuladas.json
            # (campo 'required_method') — mesma lógica do required_wait/required_reopen acima
            try:
                method_result = validate_required_method_patterns(bot_code, pending_corrections)
            except Exception as validator_err:
                raise RuntimeError(
                    f"Bug interno no validador (validate_required_method_patterns): {validator_err}. "
                    f"Corrija o step_validator.py antes de tentar gerar código novamente."
                ) from validator_err

            # Merge structural and plan results
            all_errors = (
                struct_result.get("errors", []) + plan_result.get("errors", [])
                + field_result.get("errors", []) + pattern_result.get("errors", [])
                + wait_result.get("errors", []) + reopen_result.get("errors", [])
                + method_result.get("errors", [])
            )
            total_errors = len(all_errors)

            if total_errors == 0:
                # Gate final: dry run real em sandbox — pega qualquer alucinação
                # (import, atributo, nome indefinido) que a análise estática não cobre.
                framework_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                try:
                    dryrun_result = dry_run_bot(bot_code, framework_root, dataset_dir=self.project_dir)
                except Exception as dryrun_err:
                    raise RuntimeError(
                        f"Bug interno no dry run (dry_run_bot): {dryrun_err}. "
                        f"Corrija o step_validator.py antes de tentar gerar código novamente."
                    ) from dryrun_err

                if dryrun_result["status"] == "FAIL":
                    print(f"[AEGIS CODEGEN] ❌ Dry run falhou: {dryrun_result['errors'][0]['detail']}")
                    diff = dryrun_result
                    attempts_history.append({
                        "attempt": attempt,
                        "diff": diff,
                        "snippets": []
                    })
                    continue

                print(f"[AEGIS CODEGEN] ✅ Validação AST + dry run passaram na tentativa {attempt}!")
                self._write_bot(bot_code)
                self._mark_corrections_applied(
                    pending_corrections, correcoes_acumuladas_path
                )
                self._write_index_and_metadata(code_dir, project_json_path)
                print("-" * 60)
                print("✅ CÓDIGO DA AUTOMAÇÃO RPA GERADO COM SUCESSO!")
                print(f"O robô resiliente está salvo e pronto para a Fase 5 (Execução).")
                print("=" * 60 + "\n")
                return True

            # Merge structural + plan errors for diff tracking
            merged = {
                "status": "FAIL",
                "total_errors": total_errors,
                "errors": all_errors,
                "structural_errors": struct_result.get("total_errors", 0),
                "plan_errors": plan_result.get("total_errors", 0),
                "field_errors": field_result.get("total_errors", 0),
                "pattern_errors": pattern_result.get("total_errors", 0),
                "wait_errors": wait_result.get("total_errors", 0),
                "reopen_errors": reopen_result.get("total_errors", 0),
            }
            diff = merged
            if os.getenv("AEGIS_DEBUG_DUMP_BOT"):
                with open(os.getenv("AEGIS_DEBUG_DUMP_BOT"), "w", encoding="utf-8") as _dbgf:
                    _dbgf.write(bot_code)
            print(f"[AEGIS CODEGEN] ❌ Validação falhou: {total_errors} erro(s) "
                  f"(estrutural={merged['structural_errors']}, plano={merged['plan_errors']}, campos={merged['field_errors']}, padroes={merged['pattern_errors']}, espera_assincrona={merged['wait_errors']}, reabertura={merged['reopen_errors']})")
            for err in all_errors:
                print(f"  - {err.get('type')}: {err.get('detail', '')}")

            attempts_history.append({
                "attempt": attempt,
                "diff": diff,
                "snippets": self._extract_failing_snippets(bot_code, diff)
            })

        raise RuntimeError(
            f"Falha na validação AST após {MAX_RETRIES} tentativas.\n"
            f"Erros restantes: {diff['total_errors'] if diff else 'N/A'}"
        )

    def _generate_new_code(self, bot_path: str, dict_data: dict, report_content: str,
                           skills_info_prompt: str, pending_corrections: list, gateway,
                           project_json_path: str, code_dir: str,
                           correcoes_acumuladas_path: str) -> str | None:
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
                correcoes_prompt += "\n---\n"
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
                correcoes_prompt += "\n---\n"
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

        # Load execution plan for deterministic step binding
        plan_steps_json = ""
        if os.path.exists(self.plan_path):
            with open(self.plan_path, "r", encoding="utf-8") as pf:
                plan = json.load(pf)
            plan_steps = plan.get("steps", [])
            plan_steps_json = json.dumps(self._strip_internal_step_fields(plan_steps), indent=2, ensure_ascii=False)

        # Constrói o Prompt de Compilação para a LLM
        print("[INFO] Montando prompt estruturado para o motor de IA...")
        _error_selector = getattr(self, "error_message_selector", ".toast-error, .alert-danger")
        _error_selector_escaped = _error_selector.replace('"', '\\"')
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

0. **PROIBIÇÃO ABSOLUTA DE CLASSES CUSTOMIZADAS (REGRA ZERO):**
   Você é **TERMINANTEMENTE PROIBIDO** de criar classes próprias de runner (como `class ResilientRunner`, `class BotRunner`, etc).
   Você é **TERMINANTEMENTE PROIBIDO** de usar `async def executar_automacao()` ou funções standalone com `asyncio.run()`.
   Você é **TERMINANTEMENTE PROIBIDO** de abrir arquivos CSV manualmente com `csv.DictReader` ou `open()`.
   Você é **TERMINANTEMENTE PROIBIDO** de gerenciar browser/playwright manualmente (`async_playwright()`, `browser.launch()`, `browser.new_context()`).
   Todo o ciclo de vida (browser, dataset, execução, logging) é gerenciado EXCLUSIVAMENTE pelo `TransactionRunner` do SDK Aegis.
   Se você gerar uma classe customizada, o robô NÃO FUNCIONARÁ e você terá que refazer tudo.

1. **Estrutura SDK Aegis (`TransactionRunner` — USO OBRIGATÓRIO):**
   O robô DEVE ser gerado utilizando o SDK do Aegis. O arquivo gerado DEVE seguir a seguinte estrutura exata, SEM MODIFICAÇÕES estruturais:
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
            error_message_selector="{_error_selector_escaped}"
        )
       runner.register_scenario("default", execute_scenario_default)
       runner.run(headless=False)
   ```

   **IMPORTANTE — Dataset e Caminhos:**
   O `TransactionRunner` carrega automaticamente o arquivo `dataset_inicial.json` do `project_dir`.
   Você NÃO precisa (e NÃO DEVE) abrir arquivos CSV, chamar `asyncio.run()`, ou passar nomes de arquivo manualmente.

   **PROIBIÇÃO ABSOLUTA — Imports do Framework:**
   - O ÚNICO import permitido do namespace `aegis_runner` é: `from aegis_runner.runner import TransactionRunner`.
   - NUNCA importe `aegis_runner.utilities`, `aegis_runner.helpers`, `aegis_runner.config`, `get_config`,
     ou QUALQUER outro submódulo/símbolo de `aegis_runner`. Esses módulos NÃO EXISTEM. Se você "lembrar"
     de algo assim, é alucinação — NÃO EXISTE no framework real.
   - Toda configuração (URL, credenciais) vem exclusivamente de `os.getenv(...)` ou do `row` do dataset.

   **PROIBIÇÃO ABSOLUTA — Ordem dos Parâmetros de `execute_scenario_default`:**
   - A assinatura DEVE ser EXATAMENTE `def execute_scenario_default(page, row, runner):` — nessa ordem.
   - O runner chama essa função POSICIONALMENTE como `callback(page, row, self)`. Se você inverter a ordem
     (ex: `def execute_scenario_default(runner, page, row):`), os objetos ficam TROCADOS dentro da função:
     `runner` vira o objeto Page e `page` vira o dict row — causando erros confusos como
     `'Page' object has no attribute 'fill_resilient'`.
   - NUNCA mude a ordem `page, row, runner`.

   **PROIBIÇÃO ABSOLUTA — Instanciação do TransactionRunner:**
   - `TransactionRunner(...)` DEVE receber `project_dir=` como keyword argument. NUNCA instancie `TransactionRunner()` sem argumentos.
   - `TransactionRunner(...)` DEVE ser instanciado DENTRO do bloco `if __name__ == "__main__":`, nunca no escopo global do módulo (nunca na primeira linha do arquivo).
   - Exemplo ERRADO (NUNCA FAÇA): `runner = TransactionRunner()` fora de qualquer bloco.
   - Exemplo CORRETO: instanciar dentro de `if __name__ == "__main__":` com `project_dir=project_dir` resolvido via `__file__`.
   O `__main__` acima JÁ está completo e funcional — apenas implemente `execute_scenario_default`.

2. **Uso Obrigatório de `runner.click_resilient` e `runner.click_chained`:`
   Você é **PROIBIDO** de usar `.click()` diretamente do objeto `page` ou `locator`. Todos os cliques devem ser executados através do runner:
   - Se o passo no relatório tiver **prefixo `⬆`** (parent context), use `runner.click_chained(page, parent=..., child=..., target_description=..., original_coords=...)`
   - Caso contrário, use `runner.click_resilient(page, selector="<seletor>", target_description="<descrição>", original_coords=...)`
   - **Extração de Coordenadas (Crucial)**: Verifique se o passo no relatório de telemetria possui marcação de coordenadas, como `[coords: (0.2452, 0.4563)]`. Se houver, passe a tupla exata em `original_coords`, exemplo: `original_coords=(0.2452, 0.4563)`. Se não houver coordenadas descritas para aquele passo no relatório, omita o argumento `original_coords`.
   - **Menus Suspensos (Padrão N)**: Se um seletor na telemetria pertencer a um menu suspenso ou dropdown (geralmente contendo `.sub-menu`, `.dropdown-menu` ou similar), você é obrigado a convertê-lo em um seletor composto encadeado com ` >> ` separando o item do menu pai (geralmente `#menu-item-XXXXX` ou similar) do item do submenu (exemplo: `#menu-item-28904 >> #menu-item-141846 a:has-text(...)`), ativando a expansão automática por hover do runner. **NÃO** divida o seletor na tag `ul` ou contêiner mais externo (como `#menu-1-43939cc >> ...`), pois isso não disparará o hover no item correto.
3. **Uso Obrigatório de `runner.fill_resilient` e `runner.fill_chained`:`
   Você é **PROIBIDO** de usar `.fill()` diretamente do objeto `page` ou `locator`. Todos os preenchimentos comuns devem ser executados através do runner:
   - Se o passo no relatório tiver **prefixo `⬆`** (parent context), use `runner.fill_chained(page, parent=..., child=..., text_val=row["<chave>"], target_description=..., strategy="DIRECT")`
   - Caso contrário, use `runner.fill_resilient(page, selector="<seletor>", text_val=row["<chave_semantica>"], target_description="<descrição>", strategy="DIRECT")`
   - **Proibição Absoluta de Valores Fixos**: Você é **PROIBIDO** de passar strings fixas/literais de teste (ex: `text_val="valor_gravado"`) no parâmetro `text_val`. Use obrigatoriamente referências ao registro do dataset `row`, ex: `row.get("chave", "")`.
4. **Padrão M (Detecção Anti-Bot Comportamental / HUMAN_LIKE):**
   Verifique o campo `fill_strategy` no `dicionario.json`. Se o campo tiver `"fill_strategy": "HUMAN_LIKE"`, ou se o campo for um input de texto que precede um autocomplete ou dropdown dinâmico (onde o usuário digita e depois clica em uma opção da lista correspondente), você é **PROIBIDO** de usar preenchimento direto. Você deve usar **obrigatoriamente** `strategy="HUMAN_LIKE"` para simular a digitação cadenciada humana e disparar os eventos de busca corretos no portal. Você é **PROIBIDO** de usar strings fixas/literais aqui; use sempre a referência à variável `row`, ex:
   `runner.fill_resilient(page, selector="<seletor>", text_val=row.get("<chave_semantica>", ""), target_description="<descrição>", strategy="HUMAN_LIKE")`
5. **Utilização do Dataset (`row`) - PROIBIÇÃO ABSOLUTA DE HARDCODES:**
   Todos os campos do formulário preenchidos dinamicamente devem obter seus valores do dicionário `row` usando as chaves semânticas exatas do dicionário de dados (ex: `row.get("cpf_cliente", "")` ou `row["modelo"]`).
   Você é **TERMINANTEMENTE PROIBIDO** de usar strings literais ou valores hardcoded como entrada no código gerado, seja para preenchimento de input (`fill_resilient`, `fill_human_like`) ou seleção de dropdown (`select_option_resilient`). Mesmo que a telemetria ou o relatório de passos exiba valores observados literais nos passos (ex: "Preencheu com: 'valor observado qualquer'"), você é **OBRIGADO** a mapear essa ação para obter o valor dinamicamente da coluna correspondente no dataset (ex: `row.get("<chave_semantica_do_passo>", "")`).
   Também é **ESTRITAMENTE PROIBIDO** utilizar valores de dados do negócio observados como o valor padrão/fallback em chamadas `.get()` (ex: usar `row.get("sexo_cliente", "Masculino")` ou `row.get("estado_civil_cliente", "Solteiro(a)")` é uma quebra dessa regra pois contém a string hardcoded `'Masculino'` ou `'Solteiro(a)'`). Se for utilizar `.get()`, utilize string vazia como fallback (ex: `row.get("sexo_cliente", "")`) ou use acesso direto por chave (ex: `row["sexo_cliente"]`).
   **PROIBIÇÃO ABSOLUTA — NÃO INVENTE PASSOS PARA CAMPOS SEM STEP NO PLANO:** o `dicionario.json`/`dataset_inicial.json` pode conter chaves (ex: campos de login) para as quais NÃO existe nenhum step correspondente na seção 12 (plano de execução) abaixo — isso significa que a gravação real NÃO precisou interagir com esse campo (ex: navegador já estava autenticado no momento da gravação, então não houve preenchimento de usuário/senha para capturar). Você é **TERMINANTEMENTE PROIBIDO** de "ajudar" adicionando um passo de preenchimento para esses campos por conta própria. O robô deve reproduzir EXATAMENTE os passos que o plano de execução lista — nem mais, nem menos — mesmo que isso pareça funcionalmente incompleto. Se a automação realmente precisar desse passo, a correção certa é regravar a telemetria, não inventar o passo na geração de código.
6. **Padrão K (Campos de Data):**
   Para preenchimento de datas, utilize seleção completa com `Control+A` e digitação, ou injeção DOM de propriedades removendo a flag `readonly` e despachando os eventos `input` e `change` se necessário.
   **PROIBIÇÃO ABSOLUTA DE CONVERSÃO DE FORMATO DE DATA INVENTADA:** você é **PROIBIDO** de usar `datetime.strptime(...)`/`datetime.strftime(...)` para reformatar valores de data de `row` a menos que exista evidência explícita e verificável de que o formato do dataset difere do formato exigido pelo campo. O campo `observed_value` de cada entrada em `dicionario.json` mostra o formato que **funcionou de verdade** durante a gravação — se o valor do dataset já está nesse mesmo padrão (ex: ambos `dd/mm/aaaa`), passe o valor de `row` **diretamente**, sem nenhuma conversão. Inventar uma conversão para um formato ISO (`%Y-%m-%d`) ou qualquer outro que não seja o `observed_value` documentado é uma alucinação e quebra o robô em runtime (`ValueError: time data ... does not match format`) — isso já causou falha real em produção.
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
    Retorne **EXCLUSIVAMENTE** o código Python estruturado, envelopado em um bloco de código markdown:
    ```python
    # código aqui
    ```
    Não dê explicações ou introduções. Apenas o código.
12. **Vinculação Determinística de Passos (OBRIGATÓRIO):**
    Cada ação de automação DEVE passar o step_id exato do plano como argumento nomeado.
    O plano de execução determinístico é:

    """ + plan_steps_json + """

    Formato exigido em cada chamada (page é SEMPRE o primeiro argumento posicional):
      runner.{metodo}(page, selector="...", target_description="...", step_id="{step_id}")

    Exemplo CORRETO (fill_resilient usa text_val, NUNCA value):
      runner.fill_resilient(page, selector="#email", text_val=row.get("email", ""),
                            target_description="Preencher email", step_id="st_001")

    Exemplo CORRETO (click_resilient):
      runner.click_resilient(page, selector="#btn-login", target_description="Clicar login", step_id="st_002")

    Exemplo ERRADO (NUNCA FAÇA — falta 'page' e usa 'value' em vez de 'text_val'):
      runner.fill_resilient(selector="#email", target_description="Preencher email",
                            step_id="st_001", value=row.get("email", ""))

    ATENÇÃO: 'page' é OBRIGATÓRIO como primeiro argumento posicional em TODA chamada ao runner.
    ATENÇÃO: O parâmetro correto é 'text_val', NUNCA 'value'.
    ATENÇÃO: O step_id DEVE ser passado como keyword argument.

    ⚠️ **ATENÇÃO — PASSOS COM `"weak_selector": true` (SELETOR DE BAIXA CONFIABILIDADE):**
    Se um passo do plano acima tiver o campo `"weak_selector": true`, o seletor gravado teve baixa
    confiança na gravação e é **PROIBIDO** usá-lo sozinho, "cru", sem reforço de ancoragem. Você é
    **OBRIGADO** a ancorar esse passo com pelo menos UM dos mecanismos abaixo:
      - Usar `runner.click_chained(...)`/`runner.fill_chained(...)` com `parent={{"selector": "...", "has_text": "..."}}`
        (ou o texto embutido diretamente no seletor do parent via `:has-text(...)`); OU
      - Embutir um filtro `:has-text("...")` diretamente no próprio seletor/parent passado a
        `click_resilient`/`fill_resilient`.
    Passar apenas `original_coords`/`original_coords_trigger`/`original_coords_option` **NÃO CONTA**
    como ancoragem — coordenadas são um fallback de self-healing, não uma forma de desambiguar o
    elemento certo. Passos SEM `weak_selector: true` não precisam desse reforço extra.
13. **Padrão Select Nativo (`<select>` HTML puro, NÃO customizado):**
    Se um passo do plano de execução tiver `"type": "select_native"`, o elemento é um `<select>` HTML nativo
    (confirmado pela telemetria) — `.fill()` do Playwright **NÃO FUNCIONA** nele (só aceita `<input>`,
    `<textarea>`, `[contenteditable]`) e trava em runtime com `Locator.fill: Error: Element is not an <input>...`.
    Você é **PROIBIDO** de usar `fill_resilient`/`fill_chained` nesses passos. Use exclusivamente:
      `runner.select_option_native_resilient(page, selector="<seletor do plano>", option_text=row.get("<chave_semantica>", ""), target_description="<descrição>", step_id="<step_id>")`
    Diferente de `select_option_resilient` (dropdown customizado/overlay JS tipo Angular Material, que abre um
    painel `[role='option']` via clique), `select_option_native_resilient` usa o `page.select_option()` nativo
    do Playwright direto no `<select>` — nunca use `select_option_resilient` para um passo `select_native`.
"""
        print(f"[INFO] Conectando ao Gateway de IA ({gateway.provider} / {gateway.model})...")
        print("[INFO] Solicitando geração de código baseada em resiliência técnica...")
        sys.stdout.flush()

        try:
            response_text = gateway._call_llm_api(prompt, force_json=False)
        except Exception as e:
            print(f"[ERRO] Falha ao invocar a API de LLM: {e}")
            return None

        print("[INFO] Código gerado com sucesso pela IA. Limpando payload...")

        generated_code = self._extract_python_code(response_text)
        return generated_code

    _STEP_ANCHOR_RE = re.compile(r'^\s*#\s*\[PASSO\s+([^\]]+)\]')
    _STEP_ID_IN_BLOCK_RE = re.compile(r'step_id\s*=\s*"([^"]+)"')

    def _parse_step_blocks(self, code: str):
        """
        Divide o código em blocos delimitados pelos comentários '# [PASSO X]'
        já exigidos pelo playbook. O step_id de cada bloco é resolvido
        buscando 'step_id="st_XXX"' DENTRO do texto do bloco (a chamada real
        do runner), não o número do comentário — não depende do número do
        PASSO já estar alinhado ao step_id (pode ter sofrido deriva em
        tentativa anterior).
        Retorna None se não houver nenhum anchor no código (sinal para o
        caller usar o fluxo de arquivo inteiro).
        """
        lines = code.split("\n")
        anchors = []
        for i, line in enumerate(lines):
            m = self._STEP_ANCHOR_RE.match(line)
            if m:
                anchors.append((i, m.group(1).strip()))
        if not anchors:
            return None

        blocks = []
        for idx, (start, label) in enumerate(anchors):
            end = anchors[idx + 1][0] if idx + 1 < len(anchors) else len(lines)
            block_text = "\n".join(lines[start:end])
            sid_match = self._STEP_ID_IN_BLOCK_RE.search(block_text)
            blocks.append({
                "label": label,
                "step_id": sid_match.group(1) if sid_match else None,
                "start": start,
                "end": end,
                "text": block_text,
            })
        return blocks

    def _build_scoped_edit_plan(self, existing_code: str, target_step_ids: list):
        """
        Localiza o(s) bloco(s) de `target_step_ids` em `existing_code` via
        `_parse_step_blocks`. Retorna None (sinal de fallback pro arquivo
        inteiro) se: não há anchors; algum target_step_id não é encontrado em
        nenhum bloco; ou algum step_id aparece duplicado em mais de um bloco
        (ambiguidade — sinal de deriva anterior, mais seguro reescrever tudo
        do que arriscar um splice na posição errada).
        """
        blocks = self._parse_step_blocks(existing_code)
        if blocks is None:
            return None

        seen_ids = {}
        for b in blocks:
            sid = b["step_id"]
            if sid is None:
                continue
            if sid in seen_ids:
                return None
            seen_ids[sid] = b

        target_blocks = []
        for sid in target_step_ids:
            b = seen_ids.get(sid)
            if b is None:
                return None
            target_blocks.append(b)

        target_blocks.sort(key=lambda b: b["start"])
        ordered_all = sorted(blocks, key=lambda b: b["start"])
        first_idx = ordered_all.index(target_blocks[0])
        last_idx = ordered_all.index(target_blocks[-1])

        context_before = ordered_all[first_idx - 1] if first_idx > 0 else None
        context_after = ordered_all[last_idx + 1] if last_idx + 1 < len(ordered_all) else None

        return {
            "lines": existing_code.split("\n"),
            "target_blocks": target_blocks,
            "context_before": context_before,
            "context_after": context_after,
        }

    def _surgical_correct_scoped(self, scoped_plan: dict, target_step_ids: list,
                                  correcoes_desc: str, plan_steps: list,
                                  gateway, reflection_block: str):
        """
        Monta um prompt reduzido contendo só o(s) bloco(s) do(s) step_id(s)
        sob correção (+ 1 bloco de contexto antes/depois, somente leitura),
        pede de volta só esse(s) bloco(s) corrigido(s) e splica a resposta no
        arquivo original por substituição de linhas — o resto do arquivo fica
        byte-idêntico por construção.
        Levanta exceção se a chamada à API de LLM falhar (mesma semântica de
        falha do fluxo de arquivo inteiro). Retorna None (não exceção) se a
        resposta não contiver as seções BEGIN_STEP/END_STEP esperadas — o
        caller trata isso como sinal para tentar o fluxo de arquivo inteiro
        nesta mesma tentativa, sem abortar o Ralph Loop.
        """
        lines = scoped_plan["lines"]
        target_blocks = scoped_plan["target_blocks"]
        context_before = scoped_plan["context_before"]
        context_after = scoped_plan["context_after"]

        relevant_ids = set(target_step_ids)
        if context_before and context_before["step_id"]:
            relevant_ids.add(context_before["step_id"])
        if context_after and context_after["step_id"]:
            relevant_ids.add(context_after["step_id"])
        plan_slice = [s for s in plan_steps if s.get("step_id") in relevant_ids]
        plan_slice_json = json.dumps(self._strip_internal_step_fields(plan_slice), indent=2, ensure_ascii=False)

        context_section = ""
        if context_before:
            context_section += (
                f"\n#### Bloco IMEDIATAMENTE ANTERIOR (step_id={context_before['step_id']}) "
                f"— SOMENTE LEITURA, NÃO retorne nem altere este bloco:\n```python\n{context_before['text']}\n```\n"
            )

        targets_section = ""
        for b in target_blocks:
            targets_section += (
                f"\n#### Bloco a corrigir (step_id={b['step_id']}):\n```python\n{b['text']}\n```\n"
            )

        if context_after:
            context_section += (
                f"\n#### Bloco IMEDIATAMENTE POSTERIOR (step_id={context_after['step_id']}) "
                f"— SOMENTE LEITURA, NÃO retorne nem altere este bloco:\n```python\n{context_after['text']}\n```\n"
            )

        return_format = "\n".join(
            f"# BEGIN_STEP {b['step_id']}\n<bloco corrigido completo de {b['step_id']}, incluindo o comentário '# [PASSO ...]'>\n# END_STEP {b['step_id']}"
            for b in target_blocks
        )

        reflection_part = f"\n{reflection_block}\n" if reflection_block else ""

        prompt = f"""
{reflection_part}
Você é um Engenheiro de IA especialista em Automação de Processos Robóticos (RPA) de alta resiliência usando Playwright e Python.
Sua tarefa é aplicar uma correção CIRÚRGICA em UM OU MAIS BLOCOS ISOLADOS de um robô RPA maior. Você está vendo
APENAS um recorte do arquivo — o(s) bloco(s) de contexto (se houver) são fornecidos só pra você entender a
sequência, NUNCA os reproduza na resposta.

Princípios obrigatórios (Karpathy style):
1. Altere APENAS o(s) bloco(s) marcado(s) como "a corrigir" abaixo. Não toque nos blocos de contexto.
2. Mantenha o comentário '# [PASSO X] Descrição' e o step_id exato de cada bloco.
3. Proibição absoluta de hardcode: use row.get("campo", "") para dados de negócio, nunca valores literais de teste.
4. Cada chamada ao runner mantém 'page' como primeiro argumento posicional e step_id como keyword argument.
5. Os ÚNICOS métodos válidos do SDK TransactionRunner são: {sorted(RUNNER_METHODS)} (+ register_scenario/run,
   que não se aplicam dentro de um bloco de passo). NUNCA invente ou aproxime um nome de método — se não está
   nesta lista exata, não existe. Exemplo CORRETO: runner.fill_resilient(page, selector="#email",
   text_val=row.get("email", ""), target_description="...", step_id="st_001").

Fatia do plano de execução relevante a estes blocos:
```json
{plan_slice_json}
```
---
### CONTEXTO E BLOCO(S) A CORRIGIR
{context_section}
{targets_section}
---
### CORREÇÕES E INSIGHTS A APLICAR
{correcoes_desc}
---
### REGRAS DE SAÍDA (OBRIGATÓRIO)
Retorne EXCLUSIVAMENTE o(s) bloco(s) corrigido(s), delimitados EXATAMENTE assim (sem markdown fences, sem texto
antes/depois, um par BEGIN_STEP/END_STEP por step_id alvo):
{return_format}

Não inclua os blocos de contexto na resposta. Não dê explicações.
"""
        print(f"[INFO] Conectando ao Gateway de IA ({gateway.provider} / {gateway.model}) — modo escopado...")
        print(f"[INFO] Solicitando correção cirúrgica ESCOPADA (blocos: {', '.join(target_step_ids)})...")
        sys.stdout.flush()

        response_text = gateway._call_llm_api(prompt, force_json=False)

        section_re = re.compile(
            r'#\s*BEGIN_STEP\s+(\S+)\s*\n(.*?)\n#\s*END_STEP\s+\1',
            re.DOTALL,
        )
        found = {m.group(1): m.group(2) for m in section_re.finditer(response_text)}

        target_ids = [b["step_id"] for b in target_blocks]
        missing = [sid for sid in target_ids if sid not in found]
        if missing:
            print(f"[WARNING] Resposta escopada não contém bloco(s) esperado(s): {missing}")
            return None

        # Guarda contra corrupção estrutural via splice: um bloco de passo é
        # sempre código indentado dentro de execute_scenario_default — uma
        # 'def'/'class' em nível de módulo (coluna 0) na resposta indica que
        # a IA vazou/duplicou uma definição pro meio do bloco. Isso corrompe
        # o arquivo de um jeito que passa despercebido pela validação AST
        # (a def duplicada "sombra" a original só em runtime — Python usa a
        # última) e sem nenhum step_id/lineno pro modo escopado corrigir,
        # virando oscilação infinita entre o erro que a duplicata mascara e o
        # erro que ela introduz. Rejeita e cai pro fluxo de arquivo inteiro,
        # que reescreve o arquivo de forma consistente.
        module_level_def_re = re.compile(r'^(def|class)\s+\w+', re.MULTILINE)
        for sid, block_text in found.items():
            if module_level_def_re.search(block_text):
                print(f"[WARNING] Resposta escopada do bloco {sid} contém definição em nível de módulo (def/class) — rejeitada para evitar corrupção estrutural.")
                return None

        new_lines = list(lines)
        for b in sorted(target_blocks, key=lambda b: b["start"], reverse=True):
            new_block_lines = found[b["step_id"]].strip("\n").split("\n")
            new_lines[b["start"]:b["end"]] = new_block_lines

        return "\n".join(new_lines)

    def _surgical_correct(self, bot_path: str, pending_corrections: list, gateway,
                          project_json_path: str, code_dir: str,
                          correcoes_acumuladas_path: str,
                          reflection_section=None, current_code=None,
                          current_diff=None) -> str | None:
        if current_code is not None:
            existing_code = current_code
            print("[INFO] Usando código fornecido (reflection loop)...")
        else:
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

        # Load execution plan for deterministic step binding
        plan_steps = []
        plan_steps_json = ""
        if os.path.exists(self.plan_path):
            with open(self.plan_path, "r", encoding="utf-8") as pf:
                plan = json.load(pf)
            plan_steps = plan.get("steps", [])
            plan_steps_json = json.dumps(self._strip_internal_step_fields(plan_steps), indent=2, ensure_ascii=False)

        reflection_block = ""
        if reflection_section:
            reflection_block = reflection_section

        # ── Correção ESCOPADA por bloco (# [PASSO X]) ──
        # Quando as correções pendentes referenciam step_id(s) já presentes no
        # código atual, restringe a superfície de edição por construção: manda
        # só o(s) bloco(s) desses step_ids pra LLM, splica a resposta de volta
        # por substituição de linhas. O resto do arquivo fica byte-idêntico —
        # elimina por construção (não por instrução em prosa) a classe de erro
        # "drift em step_id não relacionado à correção pedida" catalogada em
        # múltiplas tentativas de correção de st_055 (ver PROBLEMA_ST055.md).
        # Inclui step_ids dos erros da tentativa ATUAL (current_diff), não só
        # de pending_corrections (correções antigas aprovadas, potencialmente
        # de step_id diferente) — sem isso o modo escopado trava reeditando
        # sempre o mesmo bloco antigo enquanto o erro real migrou pra outro
        # step_id, esgotando tentativas do Ralph Loop sem progresso possível.
        # Erros de plano (step_validator.py: COUNT_MISMATCH, STEP_ID_MISMATCH,
        # MISSING_STEPS, EXTRA_STEPS) não usam a chave "step_id" — usam
        # "expected_id"/"found_id" (STEP_ID_MISMATCH) ou "step_ids", uma lista
        # (MISSING_STEPS/EXTRA_STEPS). Só olhar "step_id" (usado por
        # pattern_result, ex. MISSING_ORIGINAL_COORDS) faz esses erros de
        # plano nunca entrarem no escopo — a LLM fica reeditando só os blocos
        # de pending_corrections + pattern errors, sem nunca tocar no step_id
        # realmente ausente/deslocado, repetindo os mesmos 47 erros em todas
        # as 15 tentativas até esgotar o loop (bug real reproduzido: st_021
        # ausente do plano nunca entrava em target_step_ids).
        # Erros AST-level (HALLUCINATED_RUNNER_METHOD, MISSING_PAGE_ARG,
        # FORBIDDEN_VALUE_KWARG, HARDCODED_TEXT_VAL, MISSING_PROJECT_DIR_ARG,
        # RUNNER_INSTANTIATED_AT_MODULE_SCOPE — step_validator.py) não carregam
        # nenhuma das chaves acima, só "lineno" do node AST que falhou. Sem
        # resolver esse lineno pro bloco que o contém, esses erros ficam
        # estruturalmente invisíveis pro modo escopado: ele só teria a chance
        # de tocá-los se o step_id certo já estivesse (por coincidência) em
        # pending_corrections — e nunca, se o erro estiver fora de qualquer
        # bloco "# [PASSO X]" (ex.: chamada perdida dentro do próprio bloco
        # errado, ou em código não coberto por nenhum step). Resolve via
        # _parse_step_blocks: acha o bloco cujo range de linhas contém o
        # lineno do erro e adiciona o step_id dele ao escopo.
        live_error_step_ids = set()
        if current_diff:
            blocks_for_lineno = self._parse_step_blocks(existing_code)
            for e in current_diff.get("errors", []):
                for key in ("step_id", "expected_id", "found_id"):
                    v = e.get(key)
                    if v:
                        live_error_step_ids.add(v)
                for v in e.get("step_ids") or []:
                    live_error_step_ids.add(v)
                linenos = list(e.get("linenos") or [])
                if e.get("lineno"):
                    linenos.append(e["lineno"])
                if linenos and blocks_for_lineno:
                    for lineno in linenos:
                        line_idx = lineno - 1
                        for b in blocks_for_lineno:
                            if b["start"] <= line_idx < b["end"] and b["step_id"]:
                                live_error_step_ids.add(b["step_id"])
                                break
        target_step_ids = sorted({c.get("step_id") for c in pending_corrections if c.get("step_id")} | live_error_step_ids)
        if target_step_ids:
            scoped_plan = self._build_scoped_edit_plan(existing_code, target_step_ids)
            if scoped_plan is not None:
                print(f"[INFO] Modo cirúrgico ESCOPADO ativo — editando apenas bloco(s): {', '.join(target_step_ids)}")
                try:
                    scoped_code = self._surgical_correct_scoped(
                        scoped_plan, target_step_ids, correcoes_desc, plan_steps,
                        gateway, reflection_block
                    )
                except Exception as e:
                    print(f"[ERRO] Falha ao invocar a API de LLM (modo escopado): {e}")
                    return None
                if scoped_code is not None:
                    return scoped_code
                print("[WARNING] Resposta escopada incompleta/malformada — usando fallback de arquivo inteiro nesta tentativa.")
            else:
                print("[INFO] Modo escopado indisponível (anchors ausentes/ambíguos) — usando fluxo de arquivo inteiro.")

        prompt = f"""
{reflection_block}
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
   - **PROIBIÇÃO ABSOLUTA**: Você NUNCA pode remover `from aegis_runner.runner import TransactionRunner`, a definição de `execute_scenario_default`, `runner.register_scenario(...)` ou `runner.run(...)`. Esses elementos são a espinha dorsal do robô e DEVEM permanecer intactos em toda e qualquer correção.
4. **Proibição Absoluta de Hardcodes**:
   - NUNCA insira valores fixos/hardcoded como CPFs, nomes, datas ou opções nas chamadas de interação (ex: use `row.get("cpf_cliente", "")` ou `row["campo"]`, nunca strings de teste).
   - É terminantemente proibido utilizar valores de dados do negócio observados como fallback de `.get()` (ex: usar `row.get("sexo_cliente", "Masculino")` é proibido; use `row.get("sexo_cliente", "")`).
5. **Comentários de Rastreabilidade e Isolamento de Passos**:
   - Você DEVE manter e adicionar comentários do formato `# [PASSO X] Descrição do Passo` precedendo cada ação alterada ou inserida.
   - Use os comentários de passo pré-existentes no código fonte para se guiar de forma cirúrgica, alterando unicamente o bloco de comandos associado ao passo problemático e preservando intactos todos os demais passos funcionais.
6. **Vinculação Determinística de Passos (OBRIGATÓRIO):**
   Cada ação de automação DEVE passar o step_id exato do plano como argumento nomeado.
   O plano de execução determinístico é:

    """ + plan_steps_json + """

   Formato exigido em cada chamada (page é SEMPRE o primeiro argumento posicional):
     runner.{metodo}(page, selector="...", target_description="...", step_id="{step_id}")

   Exemplo CORRETO (fill_resilient usa text_val, NUNCA value):
     runner.fill_resilient(page, selector="#email", text_val=row.get("email", ""),
                           target_description="Preencher email", step_id="st_001")

   Exemplo ERRADO (NUNCA FAÇA — falta 'page' e usa 'value' em vez de 'text_val'):
     runner.fill_resilient(selector="#email", target_description="Preencher email",
                           step_id="st_001", value=row.get("email", ""))

   ATENÇÃO: 'page' é OBRIGATÓRIO como primeiro argumento posicional em TODA chamada ao runner.
   ATENÇÃO: O parâmetro correto é 'text_val', NUNCA 'value'.
   ATENÇÃO: O step_id DEVE ser passado como keyword argument.

   **PROIBIÇÃO ABSOLUTA — ORDEM DOS PASSOS (causa raiz de falhas recorrentes de STEP_ID_MISMATCH):**
   Os blocos de passo no código gerado DEVEM aparecer na MESMA ORDEM SEQUENCIAL do plano acima
   (st_001, st_002, st_003, ... em ordem crescente, sem pular nem reordenar).
   NUNCA reordene, mova ou intercale blocos de passos existentes ao corrigir um erro pontual —
   isso quebra outros passos que já estavam corretos. Se um step_id está errado em uma posição,
   corrija APENAS o valor do step_id naquele bloco específico, sem mover o bloco de lugar.

   **PROIBIÇÃO ABSOLUTA — NÃO ADICIONE STEP_ID QUE NÃO ESTEJA NO PLANO ACIMA (causa raiz de EXTRA_STEPS):**
   Se o erro reportado for `EXTRA_STEPS` ou `COUNT_MISMATCH` com mais passos no código do que no plano,
   a correção certa é **REMOVER** o(s) bloco(s) de passo com step_id que não existe na lista do plano
   (seção acima) — nunca adicionar um step_id novo pra tentar "completar" um campo do dataset que pareça
   sem preenchimento. Campos do dataset sem step correspondente no plano são intencionais (a gravação
   real não interagiu com esse campo) — não invente uma interação para eles. Delete o bloco inteiro
   (comentário `# [PASSO X]` + chamada `runner.*`) referente a qualquer step_id ausente do plano.


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
            return None

        print("[INFO] Código corrigido com sucesso pela IA. Limpando payload...")

        generated_code = self._extract_python_code(response_text)
        return generated_code

    def _surgical_correct_with_reflection(self, current_code, current_diff, history, pending_corrections=None):
        """
        Surgical correction with reflection (Ralph Loop).
        Includes history of failed attempts to prevent LLM repeating mistakes.
        """
        pending_corrections = pending_corrections or []
        # Build history summary
        history_summary = ""
        for h in history:
            history_summary += f"\n### Tentativa {h['attempt']}:\n"
            for err in h['diff'].get('errors', []):
                history_summary += f"- {err.get('type')}: {err.get('detail', '')}\n"
            if h.get('snippets'):
                history_summary += f"\nTrecho do código que falhou:\n```python\n{h['snippets'][0]}\n```\n"

        reflection_section = f"""
## 🔧 CORREÇÃO CIRÚRGICA COM AUTO-REFLEXÃO (Ralph Loop)

Você está na tentativa {len(history) + 1} de {os.getenv("AEGIS_CODEGEN_MAX_RETRIES", "5")}. Seu código anterior falhou na validação AST.

### 🧠 ANÁLISE DA TENTATIVA ANTERIOR
{history_summary}

Por que o erro aconteceu? (Pense passo a passo):
1. O validador pediu o step_id correto, mas você gerou outro?
2. Você alterou alguma linha que não deveria ter mexido?

### 🎯 DIVERGÊNCIAS ATUAIS
```json
{json.dumps(current_diff.get('errors', []), indent=2, ensure_ascii=False)}
```

### 🛑 REGRAS DE CONTROLE DE DANOS (Anti-Oscilação):
1. NÃO toque em funções ou passos que passaram no validador.
2. Se tentou corrigir um step_id e falhou, mude a abordagem.
3. Corrija APENAS os erros listados. Não refatore nada.
4. Output APENAS o código Python corrigido completo, sem explicações textuais.
"""

        # Use the reflection-enhanced surgical correct
        return self._surgical_correct(
            self.bot_path, pending_corrections, self.gateway,
            "", "", correcoes_acumuladas_path="",
            current_code=current_code,
            reflection_section=reflection_section,
            current_diff=current_diff
        )

    def _extract_failing_snippets(self, bot_code, diff):
        """Extract code snippets around failing step_ids for context."""
        lines = bot_code.split("\n")
        snippets = []

        for error in diff.get("errors", []):
            expected_id = error.get("expected_id")
            if expected_id:
                for i, line in enumerate(lines):
                    if expected_id in line:
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        snippets.append("\n".join(lines[start:end]))
                        break

        return snippets

    def _write_bot(self, bot_code):
        with open(self.bot_path, "w", encoding="utf-8") as f:
            f.write(bot_code)
        print(f"[AEGIS CODEGEN] Bot escrito em: {self.bot_path}")

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