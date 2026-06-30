import os
import sys
import time
import csv
import re
import json
from playwright.sync_api import sync_playwright

try:
    from cognitive_fallback import CognitiveGateway
except ImportError:
    from aegis_runner.cognitive_fallback import CognitiveGateway

class TransactionRunner:
    def __init__(self, project_dir, error_message_selector=".toast-error, .alert-danger, #angular-field-status-message", cognitive_gateway=None, initial_url=None, **kwargs):
        self.project_dir = os.path.abspath(project_dir)
        self.error_message_selector = error_message_selector
        self.initial_url = initial_url
        self.scenarios = {}
        
        # Direcionamento de logs de execução para pasta separada se configurado
        self.output_dir = os.environ.get("AEGIS_EXECUTION_DIR")
        if self.output_dir:
            self.output_dir = os.path.abspath(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)
        else:
            self.output_dir = self.project_dir
        
        # Arquivos de dados do projeto
        self.dataset_json = os.path.join(self.project_dir, "dataset_inicial.json")
        self.dataset_csv = os.path.join(self.project_dir, "dados_entrada.csv")
        self.report_csv = os.path.join(self.output_dir, "relatorio_execucao.csv")
        
        # Configura a saída UTF-8
        sys.stdout.reconfigure(encoding='utf-8')

        # Inicializa Gateway Cognitivo do Aegis apontando para a pasta do projeto
        if cognitive_gateway is not None:
            self.cognitive = cognitive_gateway
        else:
            self.cognitive = CognitiveGateway(project_dir=self.project_dir)

        # Inicializa controle de screenshots por passo e id da transação
        self.step_screenshots = os.environ.get("AEGIS_STEP_SCREENSHOTS", "false").lower() in ("true", "1", "yes")
        self.realtime_logs = os.environ.get("AEGIS_STEP_LOGS_REALTIME", "true").lower() in ("true", "1", "yes")
        self.step_counter = 0
        self.current_row_id = "1"
        self.steps_history = []

    def register_scenario(self, scenario_name, callback):
        """Registra a rotina de preenchimento de formulário para um cenário lógico."""
        self.scenarios[scenario_name] = callback
        print(f"[AEGIS RUNNER] Cenário '{scenario_name}' registrado com sucesso.")

    def _log_step(self, page, status, action, selector, target_description, error_msg=""):
        screenshot_filename = ""
        row_id = getattr(self, "current_row_id", "1")
        if status in ("SUCCESS", "HEALED") and getattr(self, "step_screenshots", False):
            self.step_counter = getattr(self, "step_counter", 0) + 1
            # Substitui caracteres inválidos para nome de arquivo seguro
            clean_sel = re.sub(r'[^a-zA-Z0-9_\-]', '_', selector)[:30]
            screenshot_filename = f"step_{row_id}_{self.step_counter}_{action}_{clean_sel}.png"
            path = os.path.join(self.output_dir, screenshot_filename)
            try:
                page.screenshot(path=path)
                print(f"[AEGIS RUNNER] Screenshot do passo {self.step_counter} salvo em: {path}")
            except Exception as e:
                print(f"[WARNING] Falha ao capturar screenshot do passo {self.step_counter}: {e}")
                screenshot_filename = ""
                
        # Registra o passo no histórico interno da execução
        if not hasattr(self, "steps_history"):
            self.steps_history = []
        self.steps_history.append({
            "index": len(self.steps_history) + 1,
            "type": action,
            "selector": selector,
            "desc": target_description,
            "status": status,
            "error": error_msg,
            "usedHealing": status == "HEALED",
            "screenshot": screenshot_filename or None,
            "row_id": row_id
        })

        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] {status} | {action} | {selector} | {target_description} | {error_msg} | {screenshot_filename} | {row_id}")
            sys.stdout.flush()

    def click_resilient(self, page, selector, target_description, timeout=5000, validate_navigation=False, original_coords=None) -> bool:
        """
        Executa um clique resiliente e inteligente.
        - Expansão de Submenu (Hover-to-Reveal): Se o seletor for composto (>>), tenta fazer hover no pai.
        - Tolerância Temporal: Aguarda o elemento ficar visível antes de listar candidatos.
        - Tratamento de Desprendimento: Retenta o clique caso o nó se desprenda durante o ciclo Angular.
        - Heurística Estática: Se houver múltiplos elementos correspondendo ao seletor,
          prioriza elementos que NÃO são âncoras locais (href='#...').
        - Validação Ativa: Se validate_navigation=True, verifica se o clique causou navegação.
          Caso contrário, tenta clicar em outros elementos correspondentes de forma sequencial.
        """
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | click | {selector} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        # 1. Se o seletor for composto (encadeado com >>), faz hover sequencial nos pais para expandir menus multinível
        if " >> " in selector:
            parts = selector.split(" >> ")
            try:
                # Verifica rápido se o próprio filho já está visível; se não estiver, faz hover nos níveis intermediários
                if not page.locator(selector).first.is_visible(timeout=500):
                    for i in range(1, len(parts)):
                        sub_parent = " >> ".join(parts[:i])
                        try:
                            if page.locator(sub_parent).first.is_visible(timeout=500):
                                print(f"[AEGIS RUNNER] Expandindo nível de menu intermediário: '{sub_parent}'...")
                                page.locator(sub_parent).first.hover(timeout=1000)
                                time.sleep(0.3) # Aguarda transição/animação da revelação
                        except Exception:
                            pass
            except Exception:
                pass

        # 2. Aguarda visibilidade por até 2 segundos antes de listar os candidatos
        try:
            page.wait_for_selector(selector, state="visible", timeout=2000)
        except Exception:
            pass

        try:
            # Tenta listar todos os elementos que combinam com o seletor
            locators = page.locator(selector).all()
        except Exception:
            locators = []

        if not locators:
            # Se não achou nenhum no DOM, faz a tentativa padrão para disparar a exceção correta
            try:
                print(f"[AEGIS RUNNER] Tentando clique físico em '{selector}'...")
                page.locator(selector).click(timeout=timeout)
                self._log_step(page, "SUCCESS", "click", selector, target_description)
                return True
            except Exception as e:
                return self._handle_click_failure(page, selector, target_description, timeout, e, original_coords)

        # Sugestão A: Heurística Estática (Separar âncoras locais de links externos reais)
        prioritized_locators = []
        anchor_locators = []
        for loc in locators:
            try:
                # Limitamos o timeout a 500ms para evitar travar em elementos ocultos do DOM
                href = loc.get_attribute("href", timeout=500) or ""
                if href.startswith("#"):
                    anchor_locators.append(loc)
                else:
                    prioritized_locators.append(loc)
            except Exception:
                prioritized_locators.append(loc)

        # Se temos elementos que não são âncoras, focamos neles. Caso contrário, usamos o que sobrou.
        candidate_locators = prioritized_locators if prioritized_locators else anchor_locators
        
        # Sugestão B: Validação Ativa de Transição de Estado
        initial_url = page.url
        clicked = False
        
        for idx, loc in enumerate(candidate_locators):
            try:
                # Pula rapidamente elementos que não estão visíveis no DOM ativo
                if not loc.is_visible():
                    continue

                print(f"[AEGIS RUNNER] Tentando clique físico no elemento {idx+1}/{len(candidate_locators)} de '{selector}'...")
                loc.scroll_into_view_if_needed(timeout=1000)
                time.sleep(0.2)
                loc.click(timeout=3000, force=True)  # Timeout de 3s para o clique físico do candidato
                clicked = True
                
                if validate_navigation:
                    # Aguarda um pequeno período para validar se a navegação ocorreu
                    time.sleep(3.0)
                    if page.url == initial_url:
                        # A URL não mudou. Se for um link externo válido, força a navegação direta
                        href = loc.get_attribute("href", timeout=500) or ""
                        if href and not href.startswith("#") and href.startswith("http"):
                            print(f"[AEGIS RUNNER] Clique físico no candidato {idx+1} não alterou a URL. Forçando navegação direta para: {href}")
                            try:
                                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                                clicked = True
                                break
                            except Exception as goto_ex:
                                print(f"[AEGIS RUNNER] Falha ao forçar navegação direta: {goto_ex}")

                        # Se não foi possível forçar e houver outro elemento disponível, tenta o próximo candidato.
                        if idx < len(candidate_locators) - 1:
                            print(f"[AEGIS RUNNER] Clique no candidato {idx+1} não resultou em navegação (URL inalterada). Tentando próximo candidato...")
                            clicked = False
                            continue
                break
            except Exception as e:
                # Se for erro de desprendimento (Angular Change Detection / Stale Element), retenta clique direto
                if "attached" in str(e) or "stale" in str(e).lower() or "detached" in str(e).lower():
                    print(f"[AEGIS RUNNER] Elemento desprendido do DOM (Angular Change Detection). Retentando clique direto no primeiro correspondente...")
                    try:
                        page.locator(selector).first.click(timeout=3000)
                        clicked = True
                        break
                    except Exception as retry_ex:
                        e = retry_ex

                if idx == len(candidate_locators) - 1:
                    # Se falhar no último candidato, aciona o manipulador de falha
                    return self._handle_click_failure(page, selector, target_description, timeout, e, original_coords)
                print(f"[AEGIS RUNNER] Falha ao clicar no candidato {idx+1}: {e}. Retentando próximo...")
                continue
                
        if not clicked:
            # Se não conseguimos clicar em nenhum candidato, aciona o autotratamento cognitivo
            return self._handle_click_failure(
                page, selector, target_description, timeout, 
                RuntimeError("Nenhum candidato correspondente ao seletor estava visível ou clicável no DOM."),
                original_coords
            )
        
        if clicked:
            self._log_step(page, "SUCCESS", "click", selector, target_description)
        return clicked

    def _handle_click_failure(self, page, selector, target_description, timeout, e, original_coords=None) -> bool:
        if "strict mode violation" in str(e) or "resolved to" in str(e):
            try:
                print(f"[AEGIS RUNNER] Múltiplos elementos em fallback. Clicando no primeiro deles...")
                page.locator(selector).first.click(timeout=timeout)
                self._log_step(page, "SUCCESS", "click", selector, target_description)
                return True
            except Exception as inner_e:
                e = inner_e

        if self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha no clique padrão de '{selector}'. Acionando Self-Healing cognitivo via IA...")
            healed = self.cognitive.self_healing_click(page, selector, target_description, original_coords)
            if healed:
                self._log_step(page, "HEALED", "click", selector, target_description)
                return True
            else:
                self._log_step(page, "FAILED", "click", selector, target_description, "IA self-healing failed")
                raise e
        else:
            print(f"[AEGIS RUNNER] Falha ao clicar em '{selector}' e módulo cognitivo inativo.")
            self._log_step(page, "FAILED", "click", selector, target_description, str(e))
            raise e

    def wait_for_selector(self, page, selector, state="visible", timeout=10000, target_description=None) -> bool:
        """Aguarda um seletor ficar visível ou oculto com suporte a logs resilientes."""
        desc = target_description or selector
        print(f"[AEGIS RUNNER] Aguardando elemento '{desc}' ficar {state}...")
        try:
            page.locator(selector).wait_for(state=state, timeout=timeout)
            return True
        except Exception as e:
            print(f"[AEGIS WARNING] Timeout ao aguardar seletor '{selector}': {e}")
            raise e

    def fill_resilient(self, page, selector, text_val, target_description,
                       strategy="DIRECT", delay_ms=60, timeout=5000) -> bool:
        """
        Preenche um campo de forma resiliente.
        - strategy="DIRECT": usa .fill() padrão (rápido, sem eventos keydown).
        - strategy="HUMAN_LIKE": usa fill_human_like() com digitacão cadenciada,
          necessário para campos com detecção de cadência de teclado (Zone.js, etc).
        Se falhar por timeout ou outra exceção, localiza visualmente o elemento na tela via IA e digita.
        """
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | fill | {selector} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        if strategy == "HUMAN_LIKE":
            res = self.fill_human_like(page, selector, text_val, target_description, delay_ms=delay_ms, timeout=timeout)
            if res:
                self._log_step(page, "SUCCESS", "fill", selector, target_description)
            return res

        try:
            print(f"[AEGIS RUNNER] Tentando preenchimento físico em '{selector}'...")
            page.locator(selector).fill(text_val, timeout=timeout)
            self._log_step(page, "SUCCESS", "fill", selector, target_description)
            return True
        except Exception as e:
            if "strict mode violation" in str(e) or "resolved to" in str(e):
                try:
                    print(f"[AEGIS RUNNER] Múltiplos elementos encontrados para '{selector}'. Tentando preencher o primeiro...")
                    page.locator(selector).first.fill(text_val, timeout=timeout)
                    self._log_step(page, "SUCCESS", "fill", selector, target_description)
                    return True
                except Exception as inner_e:
                    e = inner_e

            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Falha no preenchimento padrão de '{selector}'. Acionando localização visual por screenshot...")
                clicked = self.cognitive.self_healing_click(page, selector, target_description)
                if clicked:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(text_val)
                    page.evaluate("() => { const active = document.activeElement; if (active) { active.dispatchEvent(new Event('input', { bubbles: true })); active.dispatchEvent(new Event('change', { bubbles: true })); } }")
                    self._log_step(page, "HEALED", "fill", selector, target_description)
                    return True
                self._log_step(page, "FAILED", "fill", selector, target_description, "IA self-healing failed")
                return False
            else:
                print(f"[AEGIS RUNNER] Falha ao preencher em '{selector}' e módulo cognitivo inativo.")
                self._log_step(page, "FAILED", "fill", selector, target_description, str(e))
                raise e

    def fill_human_like(self, page, selector, text_val, target_description=None, delay_ms=60, timeout=5000) -> bool:
        """
        Preenche um campo tecla por tecla com delay real (time.sleep) entre cada keystroke.
        """
        if target_description is None:
            target_description = selector
        import time as _time
        try:
            print(f"[AEGIS RUNNER] Digitacão cadenciada (HUMAN_LIKE) em '{selector}' ({len(str(text_val))} chars, {delay_ms}ms/tecla)...")
            element = page.locator(selector).first
            element.scroll_into_view_if_needed()
            element.click(timeout=timeout)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            _time.sleep(0.1)
            for char in str(text_val):
                page.keyboard.press(char)
                _time.sleep(delay_ms / 1000.0)
            _time.sleep(0.1)
            element.dispatch_event("input")
            element.dispatch_event("change")
            element.dispatch_event("blur")
            _time.sleep(0.1)
            print(f"[AEGIS RUNNER] Digitacão cadenciada concluída em '{selector}'.")
            return True
        except Exception as e:
            print(f"[AEGIS RUNNER] Falha em fill_human_like para '{selector}': {e}")
            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Acionando self-healing cognitivo para HUMAN_LIKE em '{selector}'...")
                clicked = self.cognitive.self_healing_click(page, selector, target_description)
                if clicked:
                    import time as _t2
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    for char in str(text_val):
                        page.keyboard.press(char)
                        _t2.sleep(delay_ms / 1000.0)
                    self._log_step(page, "HEALED", "fill", selector, target_description)
                    return True
            self._log_step(page, "FAILED", "fill", selector, target_description, str(e))
            raise e

    def diagnose_failure(self, page, error) -> str:
        """Diagnóstico de falha cognitivo compatível com chamadas externas."""
        if self.cognitive.is_active():
            try:
                diag = self.cognitive.diagnose_failure(page, str(error))
                if diag and isinstance(diag, dict):
                    category = diag.get("category", "UNKNOWN")
                    cause = diag.get("root_cause_summary", "")
                    fix = diag.get("actionable_fix", "")
                    return f"[{category}]: {cause} (Recomendação: {fix})"
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao executar diagnóstico externo: {e}")
        return f"System Error: {str(error)}"

    def _load_dataset(self):
        """Carrega dados do dataset_inicial.json ou dados_entrada.csv do projeto."""
        # Se houver um dataset_inicial.json filtrado dentro da pasta temporária da execução, use-o!
        exec_dataset = os.path.join(self.output_dir, "dataset_inicial.json")
        if os.path.exists(exec_dataset):
            print(f"[AEGIS RUNNER] Carregando dataset filtrado da pasta de execução: {exec_dataset}")
            with open(exec_dataset, "r", encoding="utf-8") as f:
                import json
                return json.load(f)

        if os.path.exists(self.dataset_json):
            print(f"[AEGIS RUNNER] Carregando dataset JSON: {self.dataset_json}")
            with open(self.dataset_json, "r", encoding="utf-8") as f:
                return json.load(f)
        elif os.path.exists(self.dataset_csv):
            print(f"[AEGIS RUNNER] Carregando dataset CSV: {self.dataset_csv}")
            rows = []
            with open(self.dataset_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            return rows
        else:
            raise FileNotFoundError(f"Nenhum dataset encontrado no diretório do projeto: {self.project_dir}")

    def _write_report(self, reports):
        """Escreve o relatório transacional de conformidade em formato CSV no diretório do projeto."""
        headers = ["id", "aegis_scenario", "status", "error_message", "failed_field", "extracted_value", "duration_seconds"]
        with open(self.report_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(reports)
        print(f"\n[AEGIS RUNNER] [SUCESSO] Relatório Transacional gravado em: {self.report_csv}\n")

    def run(self, url=None, headless=True, slow_mo=50, channel="msedge"):
        """Inicia a orquestração centralizada de loops de transação Playwright."""
        # Override do headless via variável de ambiente (prioridade)
        env_headless = os.environ.get("AEGIS_BROWSER_HEADLESS")
        if env_headless is not None:
            headless = env_headless.lower() in ("true", "1", "yes")

        # Atualiza a flag de screenshots por passo dinamicamente a partir do ambiente
        self.step_screenshots = os.environ.get("AEGIS_STEP_SCREENSHOTS", "false").lower() in ("true", "1", "yes")
        self.realtime_logs = os.environ.get("AEGIS_STEP_LOGS_REALTIME", "true").lower() in ("true", "1", "yes")
        self.steps_history = []

        print("\n" + "=" * 80)
        print("🛡️ AEGIS RUNNER LIBRARY: EXECUTANDO LOOP TRANSACIONAL EM LOTE")
        print("=" * 80)
        
        # 1. Carrega o dataset do projeto
        dataset = self._load_dataset()
        print(f"[AEGIS RUNNER] Total de transações carregadas: {len(dataset)}")
        
        reports = []
        
        # Inicia o Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=slow_mo, channel=channel)
            context = browser.new_context()
            page = None
            
            for idx, row in enumerate(dataset):
                # Cria uma nova página para cada transação para garantir isolamento total e evitar
                # que erros/diálogos abertos/quedas de página afetem transações subsequentes.
                if page:
                    try:
                        page.close()
                    except:
                        pass
                
                try:
                    page = context.new_page()
                    # Dispensa automaticamente todos os diálogos JavaScript (alert, confirm, prompt)
                    page.on("dialog", lambda d: d.dismiss())
                except Exception as page_err:
                    print(f"[AEGIS RUNNER] Erro crítico ao instanciar nova página: {page_err}. Tentando recuperar context...")
                    try:
                        context = browser.new_context()
                        page = context.new_page()
                        page.on("dialog", lambda d: d.dismiss())
                    except:
                        continue
                
                row_id = row.get("id", str(idx + 1))
                self.current_row_id = row_id
                self.step_counter = 0
                scenario = row.get("aegis_scenario", "default")
                expected = row.get("expected_result", "SUCCESS").upper()
                expected_token = row.get("expected_error_token", "")
                
                # Se a URL não foi fornecida por argumento, tenta usar a URL configurada na inicialização, ou do project.json
                target_url = url or self.initial_url
                if not target_url:
                    # Tenta ler do project.json se existir
                    project_json = os.path.join(self.project_dir, "project.json")
                    if os.path.exists(project_json):
                        try:
                            with open(project_json, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                                target_url = meta.get("url")
                        except:
                            pass
                
                if not target_url:
                    target_url = "http://localhost:5173/?e2e=true" # Fallback local
                
                print(f"\n[🚀 TRANSAÇÃO {row_id}/{len(dataset)}] Cenário: '{scenario}' | Expectativa: '{expected}'")
                print(f"[AEGIS_TRANSACTION] START | {row_id} | {scenario}")
                sys.stdout.flush()
                start_time = time.time()
                
                # Executa a automação registrada
                try:
                    if scenario not in self.scenarios:
                        raise ValueError(f"Cenário '{scenario}' não foi registrado no runner.")
                    
                    try:
                        page.goto(target_url, timeout=60000, wait_until="domcontentloaded")
                    except Exception as goto_err:
                        print(f"[AEGIS WARNING] Limite de tempo de carregamento da página excedido no runner: {goto_err}. Prosseguindo com execução...")
                    
                    # Chama o callback do robô de negócio
                    import inspect
                    sig = inspect.signature(self.scenarios[scenario])
                    if len(sig.parameters) >= 3:
                        self.scenarios[scenario](page, row, self)
                    else:
                        self.scenarios[scenario](page, row)
                    
                    # Aguarda 1.5s após a conclusão para certificar estabilidade
                    time.sleep(1.5)
                    duration = round(time.time() - start_time, 2)
                    
                    if expected == "BUSINESS_BLOCKED":
                        # Deu sucesso, mas a regra esperava erro de negócio!
                        print(f"[🚨 ALERTA] Concluído com sucesso, mas esperava bloqueio de negócio!")
                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "CRITICAL_UNEXPECTED_SUCCESS",
                            "error_message": "O portal permitiu concluir o fluxo de forma inesperada.",
                            "failed_field": "None",
                            "extracted_value": "None",
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                        sys.stdout.flush()
                    else:
                        # Sucesso
                        extracted_val = "EMITTED-OK"
                        print(f"[✓ SUCESSO] Transação {row_id} executada com sucesso!")
                        
                        # Captura screenshot da última tela do robô
                        screenshot_path = os.path.join(self.output_dir, "screenshot_script.png")
                        try:
                            page.screenshot(path=screenshot_path)
                            print(f"[AEGIS RUNNER] Screenshot da última tela do robô gravado em: {screenshot_path}")
                        except Exception as e:
                            print(f"[WARNING] Não foi possível capturar o screenshot da última tela do robô: {e}")

                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "SUCCESS",
                            "error_message": "None",
                            "failed_field": "None",
                            "extracted_value": extracted_val,
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] SUCCESS | {row_id}")
                        sys.stdout.flush()
                        
                except Exception as e:
                    duration = round(time.time() - start_time, 2)
                    
                    # Verifica se há mensagem de erro de negócio visível na tela
                    error_text = ""
                    is_business_error = False
                    try:
                        error_locator = page.locator(self.error_message_selector)
                        if error_locator.is_visible(timeout=1500):
                            is_business_error = True
                            error_text = error_locator.inner_text().strip()
                    except:
                        pass
                    
                    if expected == "BUSINESS_BLOCKED" and is_business_error:
                        if expected_token.lower() in error_text.lower():
                            print(f"[✓ BLOQUEIO ESPERADO] Transação {row_id} bloqueada por regra de negócio: '{error_text}'")
                            reports.append({
                                "id": row_id,
                                "aegis_scenario": scenario,
                                "status": "SUCCESS_BLOCKED",
                                "error_message": f"Bloqueio Validado: {error_text}",
                                "failed_field": "None",
                                "extracted_value": "None",
                                "duration_seconds": duration
                            })
                            print(f"[AEGIS_TRANSACTION] SUCCESS | {row_id}")
                            sys.stdout.flush()
                        else:
                            print(f"[❌ FALSO POSITIVO] Bloqueado com erro incorreto. Esperava '{expected_token}', obteve '{error_text}'")
                            reports.append({
                                "id": row_id,
                                "aegis_scenario": scenario,
                                "status": "FAILED_WRONG_BUSINESS_ERROR",
                                "error_message": f"Erro de negócio incorreto. Tela: '{error_text}'",
                                "failed_field": "None",
                                "extracted_value": "None",
                                "duration_seconds": duration
                            })
                            print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                            sys.stdout.flush()
                    else:
                        # Erro sistêmico
                        # Tenta extrair seletor que causou timeout
                        failed_field = "Unknown"
                        if "waiting for locator" in str(e):
                            match = re.search(r"waiting for locator\(['\"]([^'\"]+)['\"]\)", str(e))
                            if match:
                                failed_field = match.group(1)
                        
                        # Diagnóstico Inteligente via IA
                        diagnose_info = ""
                        if self.cognitive.is_active():
                            try:
                                print(f"[AEGIS RUNNER] Acionando diagnóstico de falha via IA...")
                                diag = self.cognitive.diagnose_failure(page, str(e))
                                if diag and isinstance(diag, dict):
                                    category = diag.get("category", "UNKNOWN")
                                    cause = diag.get("root_cause_summary", "")
                                    fix = diag.get("actionable_fix", "")
                                    diagnose_info = f" | IA DIAGNOSE [{category}]: {cause} (Recomendação: {fix})"
                                    print(f"[AEGIS RUNNER] Diagnóstico IA concluído: {diagnose_info}")
                            except Exception as diag_err:
                                print(f"[AEGIS RUNNER] Falha ao executar diagnóstico de IA: {diag_err}")
                        
                        # Tira screenshot do erro
                        screenshot_path = os.path.join(self.output_dir, f"screenshot_erro_transacao_{row_id}.png")
                        try:
                            page.screenshot(path=screenshot_path)
                            print(f"[❌ FALHA] Transação {row_id} quebrou por erro sistêmico. Screenshot salvo em: {screenshot_path}")
                        except:
                            pass
                            
                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "SYSTEM_FAILED",
                            "error_message": (str(e).replace("\n", " ")[:150] + diagnose_info)[:250],
                            "failed_field": failed_field,
                            "extracted_value": "None",
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                        sys.stdout.flush()
            
            # Fecha navegador e grava relatório
            self._write_report(reports)
            
            # Grava o histórico final de passos em JSON na pasta de execução
            steps_json_path = os.path.join(self.output_dir, "historico_passos.json")
            try:
                with open(steps_json_path, "w", encoding="utf-8") as sf:
                    json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)
                print(f"[AEGIS RUNNER] Trilha de auditoria final (historico_passos.json) gravada em: {steps_json_path}")
            except Exception as j_err:
                print(f"[WARNING] Falha ao gravar {steps_json_path}: {j_err}")
                
            if page:
                try:
                    page.close()
                except:
                    pass
            browser.close()

        # Retorna erro se houver falhas nas transações do lote
        has_failures = any(r["status"] not in ["SUCCESS", "SUCCESS_BLOCKED"] for r in reports)
        if has_failures:
            print("\n[AEGIS RUNNER] ❌ Execução em lote finalizada com falhas detectadas nas transações.")
            sys.exit(1)
        else:
            print("\n[AEGIS RUNNER] ✅ Execução em lote finalizada com sucesso total!")
