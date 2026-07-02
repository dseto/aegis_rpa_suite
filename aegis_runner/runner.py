import os
import sys
import time
import csv
import re
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

try:
    from cognitive_fallback import CognitiveGateway
except ImportError:
    from aegis_runner.cognitive_fallback import CognitiveGateway

class TransactionRunner:
    def __init__(self, project_dir, error_message_selector=".toast-error, .alert-danger, #angular-field-status-message", cognitive_gateway=None, initial_url=None, **kwargs):
        self.project_dir = os.path.abspath(project_dir)
        self.error_message_selector = error_message_selector
        
        # Resolve initial_url a partir do project.json se não informado
        self.initial_url = initial_url
        if not self.initial_url:
            project_json = os.path.join(self.project_dir, "project.json")
            if os.path.exists(project_json):
                try:
                    with open(project_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        self.initial_url = meta.get("url")
                except:
                    pass
        
        self.scenarios = {}
        
        # Direcionamento de logs de execução para pasta separada se configurado
        self.output_dir = os.environ.get("AEGIS_EXECUTION_DIR")
        if self.output_dir:
            self.output_dir = os.path.abspath(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)
        else:
            self.output_dir = self.project_dir
        
        # Garante a existência das subpastas organizadas de execução
        os.makedirs(os.path.join(self.output_dir, "reports"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "screenshots"), exist_ok=True)
        
        # Arquivos de dados do projeto
        self.dataset_json = os.path.join(self.project_dir, "dataset_inicial.json")
        self.dataset_csv = os.path.join(self.project_dir, "dados_entrada.csv")
        self.report_csv = os.path.join(self.output_dir, "reports", "relatorio_execucao.csv")
        
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
            screenshot_filename = f"screenshots/step_{row_id}_{self.step_counter}_{action}_{clean_sel}.png"
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

        # 2. Loop de retentativas com Auto-Healing de UI
        last_exception = None
        for attempt in range(1, 3):
            try:
                # Nível 2: Auto-Healing de UI - Tenta limpar overlays ativos na segunda tentativa
                if attempt == 2:
                    print(f"[AEGIS RUNNER] [RETRY 2] Limpando possíveis overlays pendentes via Escape...")
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

                # Aguarda visibilidade por até 2 segundos antes de listar os candidatos
                try:
                    page.wait_for_selector(selector, state="visible", timeout=2000)
                except Exception:
                    pass

                locators = page.locator(selector).all()
                if not locators:
                    print(f"[AEGIS RUNNER] Tentando clique físico em '{selector}'...")
                    page.locator(selector).click(timeout=timeout)
                    self._log_step(page, "SUCCESS", "click", selector, target_description)
                    return True

                # Heurística Estática (Separar âncoras locais de links externos reais)
                prioritized_locators = []
                anchor_locators = []
                for loc in locators:
                    try:
                        href = loc.get_attribute("href", timeout=500) or ""
                        if href.startswith("#"):
                            anchor_locators.append(loc)
                        else:
                            prioritized_locators.append(loc)
                    except Exception:
                        prioritized_locators.append(loc)

                candidate_locators = prioritized_locators if prioritized_locators else anchor_locators
                initial_url = page.url
                clicked = False

                for idx, loc in enumerate(candidate_locators):
                    try:
                        if not loc.is_visible():
                            continue

                        print(f"[AEGIS RUNNER] Tentando clique físico no elemento {idx+1}/{len(candidate_locators)} de '{selector}'...")
                        loc.scroll_into_view_if_needed(timeout=1000)
                        time.sleep(0.2)
                        loc.click(timeout=3000, force=True)
                        clicked = True
                        
                        if validate_navigation:
                            time.sleep(3.0)
                            if page.url == initial_url:
                                href = loc.get_attribute("href", timeout=500) or ""
                                if href and not href.startswith("#") and href.startswith("http"):
                                    print(f"[AEGIS RUNNER] Clique físico no candidato {idx+1} não alterou a URL. Forçando navegação direta para: {href}")
                                    try:
                                        page.goto(href, timeout=20000, wait_until="domcontentloaded")
                                        clicked = True
                                        break
                                    except Exception as goto_ex:
                                        print(f"[AEGIS RUNNER] Falha ao forçar navegação direta: {goto_ex}")

                                if idx < len(candidate_locators) - 1:
                                    print(f"[AEGIS RUNNER] Clique no candidato {idx+1} não resultou em navegação (URL inalterada). Tentando próximo candidato...")
                                    clicked = False
                                    continue
                        break
                    except Exception as e:
                        # Nível 1: Elemento desprendido (Stale/Detached)
                        if "attached" in str(e) or "stale" in str(e).lower() or "detached" in str(e).lower():
                            print(f"[AEGIS RUNNER] Elemento desprendido do DOM (Stale/Detached). Aguardando estabilização...")
                            time.sleep(0.2)
                            try:
                                page.locator(selector).first.click(timeout=3000)
                                clicked = True
                                break
                            except Exception as retry_ex:
                                e = retry_ex

                        if idx == len(candidate_locators) - 1:
                            raise e
                        print(f"[AEGIS RUNNER] Falha ao clicar no candidato {idx+1}: {e}. Retentando próximo...")
                        continue

                if clicked:
                    self._log_step(page, "SUCCESS", "click", selector, target_description)
                    return True
                else:
                    raise RuntimeError("Nenhum candidato correspondente ao seletor estava visível ou clicável no DOM.")

            except Exception as e:
                last_exception = e
                print(f"[AEGIS RUNNER] Tentativa {attempt} de clique falhou para '{selector}': {e}")
                if attempt == 2:
                    return self._handle_click_failure(page, selector, target_description, timeout, e, original_coords)

    def _handle_click_failure(self, page, selector, target_description, timeout, e, original_coords=None) -> bool:
        # Nível 1.5: Se for erro de múltiplos elementos (strict mode)
        if "strict mode violation" in str(e) or "resolved to" in str(e):
            try:
                print(f"[AEGIS RUNNER] Múltiplos elementos em fallback. Clicando no primeiro deles...")
                page.locator(selector).first.click(timeout=timeout)
                self._log_step(page, "SUCCESS", "click", selector, target_description)
                return True
            except Exception as inner_e:
                e = inner_e

        # Nível 2.5: Auto-Healing de UI Reativo (Se ainda não foi limpo, limpa de novo e retenta)
        print(f"[AEGIS RUNNER] Falha de clique físico em '{selector}'. Tentando limpar overlays via Escape...")
        try:
            page.keyboard.press("Escape")
            time.sleep(0.3)
            page.locator(selector).first.click(timeout=3000)
            self._log_step(page, "SUCCESS", "click", selector, target_description)
            print(f"[AEGIS RUNNER] Clique resolvido reativamente após limpeza de overlays!")
            return True
        except Exception:
            pass

        # Nível 3: Self-Healing Cognitivo por IA
        healed_by_ia = False
        cognitive_attempt_failed = False
        if self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha no clique padrão de '{selector}'. Acionando Self-Healing cognitivo via IA...")
            try:
                healed_by_ia = self.cognitive.self_healing_click(page, selector, target_description, original_coords)
                if healed_by_ia:
                    self._log_step(page, "HEALED", "click", selector, target_description)
                    return True
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro durante chamada do Self-Healing de IA: {ia_err}")
                cognitive_attempt_failed = True
        else:
            cognitive_attempt_failed = True

        # Nível 4: Fallback Físico de Coordenadas de Gravação (Último Recurso)
        if not healed_by_ia and cognitive_attempt_failed and original_coords and len(original_coords) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords[0])
                y = int(viewport["height"] * original_coords[1])
                print(f"[AEGIS RUNNER] [FALLBACK ÚLTIMO RECURSO] Clicando em coordenadas históricas da gravação: ({x}, {y})")
                page.mouse.click(x, y)
                self._log_step(page, "HEALED", "click", selector, target_description, "Fallback coords used")
                return True
            except Exception as coords_err:
                print(f"[AEGIS RUNNER] Falha crítica no clique por coordenadas de fallback: {coords_err}")

        print(f"[AEGIS RUNNER] Falha definitiva ao clicar em '{selector}'.")
        self._log_step(page, "FAILED", "click", selector, target_description, str(e))
        raise e

    def _slugify(self, text: str) -> str:
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s-]', '', text).strip().lower()
        return re.sub(r'[-\s]+', '-', text)

    def select_option_resilient(self, page, dropdown_label, option_text,
                                original_coords_trigger=None,
                                original_coords_option=None,
                                timeout=5000) -> bool:
        """
        Seleciona uma opção de um dropdown/select customizado (não-nativo).
        Abre o dropdown antes de clicar na opção desejada.
        """
        row_id = getattr(self, "current_row_id", "1")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | select_option | {dropdown_label} -> {option_text} | Selecionar dropdown | | | {row_id}")
            sys.stdout.flush()

        slug = self._slugify(dropdown_label)
        
        # 1. Tenta abrir o dropdown (Trigger)
        trigger_clicked = False
        trigger_selectors = [
            f"label:has-text('{dropdown_label}') ~ div",
            f"label:has-text('{dropdown_label}') ~ select",
            f"label:has-text('{dropdown_label}') ~ .select-trigger",
            f"#field-{slug} div",
            f"#field-{slug} .select-trigger",
            f"mat-form-field:has-text('{dropdown_label}') .mat-select-trigger",
            f"div:has-text('{dropdown_label}') >> div"
        ]

        print(f"[AEGIS RUNNER] Tentando abrir o dropdown para '{dropdown_label}'...")
        for sel in trigger_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=500):
                    loc.click(timeout=1000, force=True)
                    trigger_clicked = True
                    print(f"[AEGIS RUNNER] Dropdown '{dropdown_label}' aberto usando seletor: '{sel}'")
                    break
            except Exception:
                continue

        # Fallback de coordenadas para o trigger
        if not trigger_clicked and original_coords_trigger and len(original_coords_trigger) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords_trigger[0])
                y = int(viewport["height"] * original_coords_trigger[1])
                print(f"[AEGIS RUNNER] Abrindo dropdown via coordenadas de fallback: ({x}, {y})")
                page.mouse.click(x, y)
                trigger_clicked = True
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao clicar nas coordenadas do trigger: {e}")

        if not trigger_clicked:
            print(f"[AEGIS RUNNER] [WARNING] Não foi possível abrir o dropdown '{dropdown_label}' pelos seletores conhecidos ou coordenadas.")

        # Aguarda animação de abertura das opções
        time.sleep(0.4)

        # 2. Seleciona a opção
        option_clicked = False
        option_selectors = [
            f"[role='option']:has-text('{option_text}')",
            f".mat-option:has-text('{option_text}')",
            f"[role='listbox'] [role='option']:has-text('{option_text}')",
            f"li:has-text('{option_text}')",
            f".select-option:has-text('{option_text}')"
        ]

        print(f"[AEGIS RUNNER] Tentando selecionar a opção '{option_text}'...")
        for sel in option_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=500):
                    loc.click(timeout=1000, force=True)
                    option_clicked = True
                    print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada usando seletor: '{sel}'")
                    break
            except Exception:
                continue

        # Fallback de coordenadas para a opção
        if not option_clicked and original_coords_option and len(original_coords_option) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords_option[0])
                y = int(viewport["height"] * original_coords_option[1])
                print(f"[AEGIS RUNNER] Selecionando opção via coordenadas de fallback: ({x}, {y})")
                page.mouse.click(x, y)
                option_clicked = True
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao clicar nas coordenadas da opção: {e}")

        # Se falhou, aciona o Cognitive Gateway se ativo
        if not option_clicked and self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha nas tentativas normais. Acionando Self-Healing Cognitivo para a opção...")
            try:
                # Tenta localizar visualmente o texto da opção na tela
                option_clicked = self.cognitive.self_healing_click(
                    page, 
                    selector=f"[role='option']:has-text('{option_text}')", 
                    target_description=f"Opção {option_text} do dropdown {dropdown_label}",
                    original_coords=original_coords_option
                )
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro no self-healing cognitivo para opção: {ia_err}")

        if option_clicked:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass
            self._log_step(page, "SUCCESS", "select_option", f"[role='option']:has-text('{option_text}')", f"Selecionar '{option_text}' no dropdown '{dropdown_label}'")
            return True
        else:
            msg = f"Não foi possível selecionar a opção '{option_text}' no dropdown '{dropdown_label}'."
            print(f"[AEGIS RUNNER] ❌ {msg}")
            self._log_step(page, "FAILED", "select_option", f"[role='option']:has-text('{option_text}')", f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", msg)
            raise RuntimeError(msg)


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

        # Força HUMAN_LIKE globalmente caso a variável de ambiente esteja ativa
        force_human_like = os.environ.get("AEGIS_FORCE_HUMAN_LIKE", "false").lower() in ("true", "1", "yes")
        if force_human_like:
            strategy = "HUMAN_LIKE"

        # Tratamento de formato de data (converte de yyyy-mm-dd para dd/mm/yyyy se não for input nativo type="date")
        is_native_date = False
        try:
            input_type = page.locator(selector).first.get_attribute("type", timeout=300)
            if input_type == "date":
                is_native_date = True
        except Exception:
            pass

        if not is_native_date and isinstance(text_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", text_val):
            parts = text_val.split("-")
            text_val = f"{parts[2]}/{parts[1]}/{parts[0]}"

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

            # Auto-Healing de UI - Tenta limpar overlays ativos via Escape e retry
            print(f"[AEGIS RUNNER] Falha no preenchimento de '{selector}'. Tentando limpar possíveis overlays via Escape...")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.locator(selector).first.fill(text_val, timeout=3000)
                self._log_step(page, "SUCCESS", "fill", selector, target_description)
                print(f"[AEGIS RUNNER] Preenchimento resolvido reativamente após limpeza de overlays!")
                return True
            except Exception:
                pass

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
                raise e
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

        # Tratamento de formato de data (converte de yyyy-mm-dd para dd/mm/yyyy se não for input nativo type="date")
        is_native_date = False
        try:
            input_type = page.locator(selector).first.get_attribute("type", timeout=300)
            if input_type == "date":
                is_native_date = True
        except Exception:
            pass

        if not is_native_date and isinstance(text_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", text_val):
            parts = text_val.split("-")
            text_val = f"{parts[2]}/{parts[1]}/{parts[0]}"

        try:
            print(f"[AEGIS RUNNER] Digitacão cadenciada (HUMAN_LIKE) em '{selector}' ({len(str(text_val))} chars, {delay_ms}ms/tecla)...")
            element = page.locator(selector).first
            element.scroll_into_view_if_needed()
            element.click(timeout=timeout, force=True)
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
                diag = self.cognitive.diagnose_failure(page, str(error), steps_history=getattr(self, "steps_history", None))
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

    def _write_index_file(self):
        """Escreve um arquivo de índice em JSON com caminhos e descrições dos artefatos para consumo de IAs."""
        index_path = os.path.join(self.output_dir, "index_arquivos.json")
        
        files_metadata = []
        
        # 1. Relatórios e logs
        rel_exec_rel = "reports/relatorio_execucao.csv"
        if os.path.exists(os.path.join(self.output_dir, rel_exec_rel)):
            files_metadata.append({
                "path": rel_exec_rel,
                "type": "execution_report",
                "description": "Relatório estruturado CSV com o status de sucesso/falha, tempo de duração e erros de cada transação processada."
            })
            
        hist_passos_rel = "reports/historico_passos.json"
        if os.path.exists(os.path.join(self.output_dir, hist_passos_rel)):
            files_metadata.append({
                "path": hist_passos_rel,
                "type": "audit_trail",
                "description": "Trilha de auditoria JSON com o detalhamento passo a passo da execução de cada ação física e cognitiva do robô."
            })
            
        # O log de execução é gravado após a finalização do processo pelo Cockpit, mas prevemos sua existência
        files_metadata.append({
            "path": "reports/execution.log",
            "type": "stdout_stderr_log",
            "description": "Log de console bruto gerado pelo interpretador Python durante a execução do script do robô."
        })
        
        # 2. Screenshots gerais
        scr_script_rel = "screenshots/screenshot_script.png"
        if os.path.exists(os.path.join(self.output_dir, scr_script_rel)):
            files_metadata.append({
                "path": scr_script_rel,
                "type": "final_screenshot",
                "description": "Captura de tela do estado final do navegador ao encerrar a execução do robô."
            })
            
        # Procura por prints de erro e de passos
        scr_dir = os.path.join(self.output_dir, "screenshots")
        if os.path.exists(scr_dir):
            for entry in sorted(os.listdir(scr_dir)):
                if entry.endswith(".png"):
                    rel_path = f"screenshots/{entry}"
                    if entry.startswith("screenshot_erro_transacao_"):
                        row_id = entry.replace("screenshot_erro_transacao_", "").replace(".png", "")
                        files_metadata.append({
                            "path": rel_path,
                            "type": "error_screenshot",
                            "description": f"Captura de tela do erro sistêmico ocorrido durante o processamento da transação de ID {row_id}."
                        })
                    elif entry.startswith("step_"):
                        parts = entry.split("_")
                        row_id = parts[1] if len(parts) > 1 else "?"
                        step_num = parts[2] if len(parts) > 2 else "?"
                        action = parts[3] if len(parts) > 3 else "ação"
                        files_metadata.append({
                            "path": rel_path,
                            "type": "step_screenshot",
                            "description": f"Evidência visual do passo {step_num} ({action}) na transação {row_id} executada com sucesso."
                        })
                        
        index_data = {
            "component": "bot_execution",
            "execution_id": os.environ.get("AEGIS_EXECUTION_ID", "local"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "files": files_metadata
        }
        
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=4, ensure_ascii=False)
            print(f"[AEGIS RUNNER] Índice de arquivos (index_arquivos.json) gravado com sucesso em: {index_path}")
        except Exception as ex:
            print(f"[WARNING] Falha ao gravar index_arquivos.json: {ex}")

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
                        screenshot_path = os.path.join(self.output_dir, "screenshots", "screenshot_script.png")
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
                                diag = self.cognitive.diagnose_failure(page, str(e), steps_history=self.steps_history)
                                if diag and isinstance(diag, dict):
                                    category = diag.get("category", "UNKNOWN")
                                    cause = diag.get("root_cause_summary", "")
                                    fix = diag.get("actionable_fix", "")
                                    diagnose_info = f" | IA DIAGNOSE [{category}]: {cause} (Recomendação: {fix})"
                                    print(f"[AEGIS RUNNER] Diagnóstico IA concluído: {diagnose_info}")
                            except Exception as diag_err:
                                print(f"[AEGIS RUNNER] Falha ao executar diagnóstico de IA: {diag_err}")
                        
                        # Tira screenshot do erro
                        screenshot_path = os.path.join(self.output_dir, "screenshots", f"screenshot_erro_transacao_{row_id}.png")
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
            steps_json_path = os.path.join(self.output_dir, "reports", "historico_passos.json")
            try:
                with open(steps_json_path, "w", encoding="utf-8") as sf:
                    json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)
                print(f"[AEGIS RUNNER] Trilha de auditoria final (historico_passos.json) gravada em: {steps_json_path}")
            except Exception as j_err:
                print(f"[WARNING] Falha ao gravar {steps_json_path}: {j_err}")
                
            self._write_index_file()
                
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
