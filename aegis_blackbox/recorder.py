import os
import sys
import time
import json
import argparse
import re
import signal
import threading
import queue
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
# OUTPUT_DIR é definido dinamicamente via argparse no __main__
OUTPUT_DIR = r"C:\Projetos\Lab\telemetry_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def evaluate_selector_reliability(selector):
    """Calcula o score de confiabilidade do seletor e retorna (score, tipo)."""
    if not selector:
        return 0, "empty"
        
    test_attributes = ["data-testid", "data-test-id", "data-test", "data-qa"]
    if any(attr in selector for attr in test_attributes):
        if " >> " in selector:
            return 90, "data-testid-anchor"
        return 100, "data-testid"
        
    # ID estático (não contém números longos dinâmicos como ng ou tns)
    if "#" in selector and not re.search(r"\d{4,}", selector) and not "mat-input-" in selector and not "mat-select-" in selector:
        return 90, "id"
        
    if "[name=" in selector or "[placeholder=" in selector:
        return 80, "name-or-placeholder"
        
    if ":has-text(" in selector:
        return 70, "has-text"
        
    if "." in selector:
        return 60, "class"
        
    return 40, "tag"

def run_auto_simulation(page, update_scenario, record_annotation):
    # Helpers locais baseados no teste E2E
    def fill_reactive_text_local(selector, text_val, delay_ms=10):
        if isinstance(selector, str):
            element = page.locator(selector).first
        else:
            element = selector
        element.scroll_into_view_if_needed()
        element.click(force=True)
        element.press("Control+A")
        element.press("Backspace")
        time.sleep(0.1)
        for char in text_val:
            page.keyboard.type(char)
            time.sleep(delay_ms / 1000.0)
        # Dispara eventos
        element.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
        time.sleep(0.2)

    def select_dropdown_local(field_selector, target_option_text=None):
        # Aguarda que qualquer overlay antigo seja completamente removido do DOM
        try:
            page.locator(".cdk-overlay-pane").wait_for(state="detached", timeout=2000)
        except Exception:
            pass

        form_field = page.locator(field_selector).first
        form_field.scroll_into_view_if_needed()
        select_trigger = form_field.locator("mat-select, .mat-select-trigger, div[role='combobox']").first
        
        overlay_option_selector = "#cdk-overlay-container .mat-option, .cdk-overlay-pane .mat-option, mat-option"
        
        # Tentativas resilientes de abertura de dropdown
        opened = False
        for attempt in range(3):
            select_trigger.evaluate("el => el.click()")
            time.sleep(0.6)
            
            # Verifica se há opções disponíveis no DOM
            options_count = page.evaluate(f"""() => document.querySelectorAll('{overlay_option_selector}').length""")
            if options_count > 0:
                opened = True
                break
            print(f"[AEGIS SIMULATOR WARNING] Tentativa {attempt + 1}: Dropdown {field_selector} não abriu. Retentando...")
            time.sleep(0.4)

        if not opened:
            print(f"[AEGIS SIMULATOR ERROR] Falha grave ao abrir dropdown {field_selector} após 3 tentativas.")
            return

        options_data = page.evaluate(f"""() => {{
            const elms = Array.from(document.querySelectorAll('{overlay_option_selector}'));
            return elms.map((el, idx) => ({{
                index: idx,
                text: el.innerText || el.textContent || '',
                visible: el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none'
            }}));
        }}""")
        
        options = [opt for opt in options_data if opt['visible']]
        if not options:
            options = options_data
            
        best_opt = None
        if target_option_text:
            target_norm = target_option_text.lower().strip()
            for opt in options:
                if target_norm in opt['text'].lower():
                    best_opt = opt
                    break
                    
        if not best_opt and options:
            best_opt = options[0]
            
        if best_opt:
            best_idx = best_opt['index']
            page.evaluate("""([idx, selector]) => {
                const elms = document.querySelectorAll(selector);
                const el = elms[idx];
                if (el) {
                    el.scrollIntoView({ block: 'center', behavior: 'instant' });
                    el.click();
                }
            }""", [best_idx, overlay_option_selector])
        else:
            print(f"[AEGIS SIMULATOR WARNING] Nenhuma opção encontrada para o dropdown {field_selector}.")
        time.sleep(0.6)

    def click_next_step_local():
        print("[AEGIS SIMULATOR] Aguardando o botão 'Avançar' ser habilitado no DOM...")
        page.wait_for_function("() => { const btn = document.getElementById('btn-next-step'); return btn && !btn.disabled; }", timeout=15000)
        time.sleep(0.4)
        page.locator("#btn-next-step").first.evaluate("el => el.click()")
        print("[AEGIS SIMULATOR] Botão 'Avançar' clicado.")
        time.sleep(1.5)

    def fill_autocomplete_local(field_selector, search_text, option_text):
        input_el = page.locator(field_selector).first
        input_el.scroll_into_view_if_needed()
        fill_reactive_text_local(input_el, search_text)
        time.sleep(0.6)
        
        overlay_option_selector = "#cdk-overlay-container .mat-option, .cdk-overlay-pane .mat-option, mat-option"
        try:
            page.locator(overlay_option_selector).first.wait_for(state="attached", timeout=4000)
        except Exception:
            pass
        
        options_data = page.evaluate("""(sel) => {
            const elms = Array.from(document.querySelectorAll(sel));
            return elms.map((el, idx) => ({
                index: idx,
                text: el.innerText || el.textContent || '',
                visible: el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none'
            }));
        }""", overlay_option_selector)
        
        options = [opt for opt in options_data if opt['visible']]
        best_opt = None
        target_norm = option_text.lower().strip()
        for opt in options:
            if target_norm in opt['text'].lower():
                best_opt = opt
                break
                
        if not best_opt and options:
            best_opt = options[0]
            
        if best_opt:
            best_idx = best_opt['index']
            page.evaluate("""([idx, selector]) => {
                const elms = document.querySelectorAll(selector);
                const el = elms[idx];
                if (el) {
                    el.scrollIntoView({ block: 'center', behavior: 'instant' });
                    el.click();
                }
            }""", [best_idx, overlay_option_selector])
        time.sleep(0.6)

    print("[AEGIS SIMULATOR] Aguardando tela carregar...")
    time.sleep(2.0)

    # --- LOGIN ---
    update_scenario("login")
    print("[AEGIS SIMULATOR] Preenchendo credenciais de login...")
    fill_reactive_text_local("#username", "admin@portalsegura.com")
    fill_reactive_text_local("#password", "Segura@2026")
    page.locator("#btn-login").click(force=True)
    
    page.locator("#btn-new-quote").first.wait_for(state="visible", timeout=12000)
    print("[AEGIS SIMULATOR] Login realizado!")
    time.sleep(1.0)
    
    # --- NOVA COTAÇÃO ---
    page.locator("#btn-new-quote").click(force=True)
    time.sleep(1.5)
    
    # --- PASSO 1 ---
    update_scenario("passo_1_cliente")
    print("[AEGIS SIMULATOR] Passo 1: Preenchendo dados do cliente...")
    page.locator("#toggle-pf").click(force=True)
    fill_reactive_text_local("input[id^='mat-input-doc']", "123.456.789-00")
    
    # Aguarda o autocomplete
    nome_input = page.locator("input[id^='mat-input-nome']").first
    nome_input.wait_for(state="visible", timeout=6000)
    start_wait = time.time()
    while time.time() - start_wait < 8:
        val = nome_input.input_value()
        if val and len(val) > 3 and "buscando" not in val.lower():
            print(f"[AEGIS SIMULATOR] Cliente autocompletado: '{val}'")
            break
        time.time()
        time.sleep(0.2)

    # Preenche dropdowns adicionais para garantir validação do Passo 1
    select_dropdown_local("#field-sexo", "Feminino")
    time.sleep(0.5)
    select_dropdown_local("#field-estadoCivil", "Solteiro")
    time.sleep(0.5)
        
    click_next_step_local()
    
    # --- PASSO 2 ---
    update_scenario("passo_2_veiculo")
    print("[AEGIS SIMULATOR] Passo 2: Preenchendo dados do veículo por FIPE...")
    toggle_fipe = page.locator("#toggle-busca-fipe").first
    toggle_fipe.wait_for(state="visible", timeout=8000)
    toggle_fipe.click(force=True)
    time.sleep(0.5)
    
    fill_autocomplete_local("#field-marca input", "Toyota", "Toyota")
    fill_autocomplete_local("#field-modelo input", "Corolla", "Corolla")
    fill_autocomplete_local("#field-versao input", "Corolla Altis Premium", "Corolla Altis Premium 2.0 Flex Automático")
    
    fill_reactive_text_local("input[id^='mat-input-anofab']", "2024")
    fill_reactive_text_local("input[id^='mat-input-anomod']", "2024")
    
    select_dropdown_local("#field-zeroKm", "Não")
    time.sleep(0.5)
    select_dropdown_local("#field-usoVeiculo", "Particular")
    time.sleep(0.5)
    select_dropdown_local("#field-combustivel", "Flex")
    time.sleep(0.5)
    
    click_next_step_local()
    
    # --- PASSO 3 ---
    update_scenario("passo_3_condutor")
    print("[AEGIS SIMULATOR] Passo 3: Preenchendo condutor e risco...")
    select_dropdown_local("#field-condutor", "Sim, o próprio segurado")
    time.sleep(0.5)
    fill_reactive_text_local("input[id^='mat-input-cep']", "20040-002")
    time.sleep(1.5)
    click_next_step_local()
    
    # --- PASSO 4 ---
    update_scenario("passo_4_coberturas")
    print("[AEGIS SIMULATOR] Passo 4: Confirmando coberturas...")
    click_next_step_local()
    
    # --- PASSO 5 (Calendário e Upload) ---
    update_scenario("passo_5_vistoria")
    print("[AEGIS SIMULATOR] Passo 5: Módulo de Vistoria e Documentação...")
    page.locator("h3:has-text('Passo 5')").wait_for(state="visible", timeout=8000)
    
    page.click("#btn-open-datepicker")
    time.sleep(0.8)
    calendar_pane = page.locator(".mat-calendar").first
    calendar_pane.wait_for(state="visible", timeout=2000)
    target_day_cell = calendar_pane.locator(".mat-calendar-day-cell:has-text('25')").first
    target_day_cell.evaluate("el => el.click()")
    print("[AEGIS SIMULATOR] Dia 25 selecionado no calendário!")
    time.sleep(1.0)
    
    # Upload
    dummy_pdf = os.path.abspath("documento_teste_blackbox.pdf")
    with open(dummy_pdf, "w") as f:
        f.write("Aegis BlackBox simulation upload file.")
    try:
        print("[AEGIS SIMULATOR] Fazendo upload do documento...")
        page.set_input_files("#file-picker-input", dummy_pdf)
        uploaded_item = page.locator("#uploaded-files-list .file-item").first
        uploaded_item.wait_for(state="visible", timeout=6000)
        print(f"[AEGIS SIMULATOR] Arquivo detectado no painel: '{uploaded_item.inner_text().strip()}'")
    finally:
        # Remove arquivo dummy após injeção
        if os.path.exists(dummy_pdf):
            os.remove(dummy_pdf)
            
    time.sleep(1.0)
    click_next_step_local()
    
    # --- TELA DE CONSOLIDAÇÃO & PAGAMENTO ---
    update_scenario("pagamento")
    print("[AEGIS SIMULATOR] Prosseguindo para pagamento...")
    page.locator("#btn-go-to-payment").click(force=True)
    
    print("[AEGIS SIMULATOR] Aguardando confirmação do PIX...")
    page.locator("#tab-content-pix .status-aprovado, #tab-content-pix :has-text('Aprovado'), #btn-confirm-payment-progress").first.wait_for(state="visible", timeout=12000)
    
    btn_emitir = page.locator("#btn-confirm-payment-progress").first
    btn_emitir.wait_for(state="visible", timeout=8000)
    start_wait = time.time()
    while time.time() - start_wait < 8:
        if not btn_emitir.evaluate("el => el.disabled"):
            print("[AEGIS SIMULATOR] Botão de emissão habilitado!")
            break
        time.sleep(0.2)
        
    btn_emitir.click(force=True)
    time.sleep(2.0)
    
    # --- FORMALIZAÇÃO SMS ---
    update_scenario("formalizacao")
    print("[AEGIS SIMULATOR] Segurança jurídica via Token SMS...")
    btn_sms = page.locator("#btn-send-sms").first
    btn_sms.click(force=True)
    time.sleep(1.0)
    
    try:
        page.locator("mat-dialog-container button:has-text('Fechar'), .mat-dialog-container button").first.click(force=True)
        time.sleep(0.5)
    except Exception:
        pass
    
    token_input = page.locator("#field-sms-token input, #sms-input-panel input, input[placeholder*='Token']").first
    fill_reactive_text_local(token_input, "882091")
    
    btn_val_sms = page.locator("#btn-verify-sms").first
    btn_val_sms.click(force=True)
    
    print("[AEGIS SIMULATOR] Aguardando erro de expiração na primeira tentativa...")
    page.locator("#sms-error-container .error-banner").wait_for(state="visible", timeout=8000)
    time.sleep(1.0)
    
    print("[AEGIS SIMULATOR] Re-enviando token na segunda tentativa...")
    btn_val_sms.click(force=True)
    
    # Sucesso final
    sucesso_el = page.locator(".mat-dialog-title:has-text('Apólice Emitida com Sucesso')").first
    sucesso_el.wait_for(state="visible", timeout=10000)
    print(f"[AEGIS SIMULATOR] Emissão concluída com sucesso: {sucesso_el.inner_text().strip()}")
    
    # Registra a anotação extract para o número da proposta/apólice para demonstrar compliance
    record_annotation("extract: .mat-dialog-title : Apólice Emitida")
    time.sleep(2.0)

class AegisControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        response = {"success": True}

        try:
            if path == "/api/status":
                response = self.server.control_callbacks["get_status"]()
            elif path == "/api/pause":
                self.server.control_callbacks["set_paused"](True)
                response["message"] = "Paused"
            elif path == "/api/resume":
                self.server.control_callbacks["set_paused"](False)
                response["message"] = "Resumed"
            elif path == "/api/scenario":
                name = query.get("name", [""])[0]
                if name:
                    self.server.control_callbacks["set_scenario"](name)
                    response["message"] = f"Scenario updated to {name}"
                else:
                    self.send_response(400)
                    response = {"success": False, "error": "Missing 'name' parameter"}
            elif path == "/api/annotation":
                text = query.get("text", [""])[0]
                if text:
                    self.server.control_callbacks["add_annotation"](text)
                    response["message"] = "Annotation recorded"
                else:
                    self.send_response(400)
                    response = {"success": False, "error": "Missing 'text' parameter"}
            elif path == "/api/scan":
                self.server.control_callbacks["trigger_scan"]()
                response["message"] = "Scan triggered"
            elif path == "/api/finish":
                self.server.control_callbacks["finish_session"]()
                response["message"] = "Session finishing"
            else:
                self.send_response(404)
                response = {"success": False, "error": "Not Found"}
        except Exception as e:
            response = {"success": False, "error": str(e)}

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))

def start_control_server(callbacks, port=9900):
    server = HTTPServer(('localhost', port), AegisControlHandler)
    server.control_callbacks = callbacks
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server

def scan_fields_python(page, record_action_fn):
    try:
        inputs = page.locator("input, textarea, select, .mat-select-trigger").all()
        for el in inputs:
            if not el.is_visible():
                continue
            
            is_aegis = el.evaluate("el => el.closest('#aegis-indicator-host') !== null")
            if is_aegis:
                continue

            tag_name = el.evaluate("el => el.tagName.toLowerCase()")
            is_mat_select = el.evaluate("el => el.classList.contains('mat-select-trigger')")
            
            value = ""
            field_type = tag_name
            if is_mat_select:
                field_type = "select"
                val_el = el.locator(".mat-select-value").first
                if val_el.is_visible():
                    value = val_el.inner_text().strip()
                if value == "Selecione":
                    value = ""
            else:
                value = el.input_value() if tag_name in ("input", "textarea") else el.evaluate("el => el.value")
                el_type = el.evaluate("el => el.type")
                if el_type in ('checkbox', 'radio'):
                    value = "true" if el.is_checked() else "false"

            selector = el.evaluate("el => window.getAegisSelector ? window.getAegisSelector(el) : ''")
            if not selector:
                continue

            name = el.evaluate("el => window.getSemanticFieldName ? window.getSemanticFieldName(el) : ''")
            placeholder = el.get_attribute("placeholder") or ""
            id_val = el.get_attribute("id") or ""

            record_action_fn(json.dumps({
                "type": "scan_field",
                "tag": tag_name.upper(),
                "selector": selector,
                "value": value,
                "name": name,
                "placeholder": placeholder,
                "id": id_val,
                "fieldType": field_type
            }, ensure_ascii=False))
    except Exception:
        pass

def run_recorder(url, auto_simulate=False, control_port=None):
    global OUTPUT_DIR
    print("\n" + "=" * 60)
    print("🛡️ AEGIS BLACKBOX V4: PERSISTÊNCIA ATIVA E FECHAMENTO BASEADO EM EVENTOS")
    print("=" * 60)
    print(f"[TARGET URL] Alvo: {url}")
    print(f"[OUTPUT DIR] Destino: {OUTPUT_DIR}")
    print("-" * 60)

    events_log = []
    captured_network = {}
    
    # Controle de estado do gravador
    active_scenario = "default"
    schema_inputs = {} # key: (scenario, selector) -> {semantic_key, observed_value, type}
    schema_outputs = {} # key: (scenario, selector) -> semantic_key
    recording_paused = False
    session_finished = False
    browser_closed = False
    finish_requested = False

    # Captura de sinal para término limpo
    def handle_termination_signal(signum, frame):
        nonlocal finish_requested
        finish_requested = True
        print(f"\n[AEGIS] Sinal {signum} de término recebido. Finalizando gravação de forma limpa...")
        sys.stdout.flush()

    try:
        signal.signal(signal.SIGTERM, handle_termination_signal)
        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, handle_termination_signal)
    except Exception:
        pass

    anti_bot_fields_cache = []

    def save_telemetry_files_disk(active_evaluate=False):
        """Salva a telemetria, o dicionario estruturado e o dataset inicial no disco."""
        nonlocal anti_bot_fields_cache
        try:
            def get_default_regex(sem_key, field_type):
                sem_key_lower = sem_key.lower()
                if "cpf" in sem_key_lower:
                    return r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"
                if "cnpj" in sem_key_lower:
                    return r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"
                if "cep" in sem_key_lower:
                    return r"^\d{5}-?\d{3}$"
                if "email" in sem_key_lower:
                    return r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
                if field_type == "date":
                    return r"^\d{2}/\d{2}/\d{4}$|^\d{4}-\d{2}-\d{2}$"
                return ""

            # Compila o dicionário estruturado e a primeira linha do dataset
            fields_schema = {}
            dataset_row = {
                "id": 1,
                "aegis_scenario": "default",
                "expected_result": "SUCCESS",
                "expected_error_token": None
            }
            csv_headers = ["id", "aegis_scenario", "expected_result", "expected_error_token"]
            csv_first_row = ["1", "default", "SUCCESS", ""]

            # Coleta campos com keydown listeners detectados pelo interceptor JS
            anti_bot_detected = []
            if active_evaluate and not browser_closed:
                try:
                    anti_bot_detected = page.evaluate(
                        "() => window.__aegis_keydown_fields__ ? [...window.__aegis_keydown_fields__] : []"
                    )
                    anti_bot_fields_cache = anti_bot_detected
                except Exception:
                    pass
            else:
                anti_bot_detected = anti_bot_fields_cache

            for (scenario, selector), info in schema_inputs.items():
                sem_key = info["semantic_key"]
                val = info["observed_value"]
                field_type = info["type"]

                score, sel_type = evaluate_selector_reliability(selector)

                # Estrutura o campo no dicionário
                # C1: se o campo for detectado como anti-bot (keydown listener ativo),
                # marca fill_strategy como HUMAN_LIKE para guiar a geração de código.
                fill_strategy = "HUMAN_LIKE" if selector in anti_bot_detected else "DIRECT"

                fields_schema[sem_key] = {
                    "selector": selector,
                    "type": field_type,
                    "observed_value": val,
                    "required": True,
                    "confidence": score,
                    "selector_type": sel_type,
                    "fill_strategy": fill_strategy,
                    "description": f"Campo de entrada {sem_key} mapeado na tela",
                    "validation_rules": {
                        "regex": get_default_regex(sem_key, field_type),
                        "enum": []
                    }
                }

                # Alimenta o dataset
                dataset_row[sem_key] = val
                
                if sem_key not in csv_headers:
                    csv_headers.append(sem_key)
                    csv_first_row.append(str(val))

            # Compila dicionario de saídas
            outputs_schema = {}
            for (scenario, selector), sem_key in schema_outputs.items():
                score, sel_type = evaluate_selector_reliability(selector)
                outputs_schema[sem_key] = {
                    "selector": selector,
                    "confidence": score,
                    "selector_type": sel_type,
                    "description": f"Dado extraído da tela para o campo {sem_key}"
                }
                dataset_row[sem_key] = ""
                if sem_key not in csv_headers:
                    csv_headers.append(sem_key)
                    csv_first_row.append("")

            # 1. Salva gravação bruta
            # Coleta campos com keydown listeners detectados pelo interceptor JS
            anti_bot_fields = anti_bot_detected

            telemetry_file = os.path.join(OUTPUT_DIR, "gravacao.json")
            with open(telemetry_file, "w", encoding="utf-8") as f:
                json.dump({
                    "initial_url": url,
                    "events": events_log,
                    "network_payloads": captured_network,
                    "anti_bot_fields": anti_bot_fields  # C1: campos com keydown listeners
                }, f, indent=4, ensure_ascii=False)

            # 2. Salva dicionário de dados estruturado
            dict_file = os.path.join(OUTPUT_DIR, "dicionario.json")
            with open(dict_file, "w", encoding="utf-8") as f:
                json.dump({
                    "initial_url": url,
                    "fields": fields_schema,
                    "outputs": outputs_schema
                }, f, indent=4, ensure_ascii=False)

            # 3. Salva dataset inicial em JSON
            dataset_file = os.path.join(OUTPUT_DIR, "dataset_inicial.json")
            with open(dataset_file, "w", encoding="utf-8") as f:
                json.dump([dataset_row], f, indent=4, ensure_ascii=False)

            # 4. Salva template CSV com as colunas
            template_file = os.path.join(OUTPUT_DIR, "template.csv")
            with open(template_file, "w", encoding="utf-8") as f:
                f.write(",".join(csv_headers) + "\n")
                f.write(",".join(csv_first_row) + "\n")
            # 5. Atualiza project.json se existir no OUTPUT_DIR
            project_json_path = os.path.join(OUTPUT_DIR, "project.json")
            if os.path.exists(project_json_path):
                try:
                    with open(project_json_path, "r", encoding="utf-8") as f:
                        proj = json.load(f)
                    proj["status"] = "recorded"
                    proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                    with open(project_json_path, "w", encoding="utf-8") as f:
                        json.dump(proj, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"[WARNING] Não foi possível atualizar project.json: {e}")
        except Exception as e:
            print(f"[WARNING] Erro ao gravar telemetria no disco: {e}")
            sys.stdout.flush()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="msedge")
        context = browser.new_context()

        # Inicia trace de auditoria
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        # ESCUTA EVENTO NATIVO DE FECHAMENTO (Thread-Safe)
        def on_page_close(_):
            nonlocal browser_closed
            browser_closed = True
            print("\n[AEGIS] Navegador fechado pelo usuário. Finalizando gravação...")
            sys.stdout.flush()
            try:
                save_telemetry_files_disk(active_evaluate=True)
            except Exception:
                pass

        page.on("close", on_page_close)

        # 1. Binding: Registrar ações
        def record_action(event_json_str):
            nonlocal recording_paused
            if recording_paused:
                return

            try:
                event_data = json.loads(event_json_str)
                event_type = event_data["type"]
                selector = event_data.get("selector", "")
                
                if selector:
                    score, sel_type = evaluate_selector_reliability(selector)
                    event_data["confidence"] = score
                    event_data["selector_type"] = sel_type
                    
                    if score < 70 and event_type != "scan_field":
                        print(f"\n[⚠️ AEGIS RECORDER ALERT] Seletor pouco confiável detectado: '{selector}' "
                              f"(Elemento: {event_data.get('tag')}, Confiança: {score}% ({sel_type})). "
                              f"Sugestão: Adicione um atributo 'data-testid' no código-fonte.\n")
                        sys.stdout.flush()
                
                # scan_field não é uma ação física do usuário, então não entra nos logs de eventos brutos
                if event_type != "scan_field":
                    event_data["timestamp"] = time.time()
                    event_data["scenario"] = active_scenario
                    events_log.append(event_data)
                    print(f"[{active_scenario.upper()}] ACTION: {event_type.upper()} | Seletor: '{event_data['selector']}' | Detalhe: {event_data.get('text', '') or event_data.get('value', '')}")
                    sys.stdout.flush()
                
                # Se for preenchimento de input ou varredura de campo
                if event_type in ("fill", "scan_field"):
                    selector = event_data["selector"]
                    val = event_data["value"]
                    field_type = event_data.get("fieldType") or event_data.get("tag", "input").lower()
                    
                    # Normalização semântica
                    sem_key = event_data.get("name") or event_data.get("placeholder") or event_data.get("id")
                    if sem_key:
                        sem_key = re.sub(r'[^a-zA-Z0-9_]', '_', sem_key.lower().strip())
                        sem_key = re.sub(r'_+', '_', sem_key).strip('_')
                    
                    # Tenta reaproveitar a chave semântica já existente para o mesmo seletor
                    if not sem_key:
                        existing = schema_inputs.get((active_scenario, selector))
                        if existing:
                            sem_key = existing["semantic_key"]
                        else:
                            sem_key = f"input_{len(schema_inputs) + 1}"
                    
                    # Detecção automática de campos de data/calendário
                    is_date = False
                    if field_type == "input":
                        field_attrs = f"{event_data.get('id', '')} {event_data.get('name', '')} {event_data.get('placeholder', '')}".lower()
                        if any(tok in field_attrs for tok in ["date", "data", "calendar", "picker", "nasc"]):
                            is_date = True
                            event_data["is_date"] = True

                    # Se já existe no schema_inputs, e a varredura ativa viu o campo vazio mas ele tinha um valor anterior,
                    # preserva o valor para que o dicionário/dataset não perca dados observados válidos.
                    if event_type == "scan_field" and not val:
                        existing = schema_inputs.get((active_scenario, selector))
                        if existing and existing["observed_value"]:
                            val = existing["observed_value"]

                    schema_inputs[(active_scenario, selector)] = {
                        "semantic_key": sem_key,
                        "selector": selector,
                        "observed_value": val,
                        "type": "date" if is_date else field_type
                    }
                
                # Persistência ativa write-through a cada evento!
                save_telemetry_files_disk()
            except Exception as e:
                print(f"[WARNING] Falha ao registrar evento: {e}")
                sys.stdout.flush()

        # 2. Binding: Registrar anotações
        def record_annotation(note_text):
            events_log.append({
                "type": "annotation",
                "scenario": active_scenario,
                "text": note_text,
                "timestamp": time.time()
            })
            print(f"\n[📝 AEGIS ANOTAÇÃO - {active_scenario.upper()}] {note_text}\n")
            sys.stdout.flush()
            
            if note_text.startswith("extract:"):
                try:
                    parts = note_text.split(":")
                    selector = parts[1].strip()
                    sem_key = "extracted_protocolo"
                    if len(parts) > 2:
                        sem_key = parts[2].strip()
                    schema_outputs[(active_scenario, selector)] = sem_key
                    print(f"[SCHEMA OUTPUT] Registrado ponto de extração: '{sem_key}' no seletor '{selector}'")
                    sys.stdout.flush()
                except Exception as e:
                    print(f"[WARNING] Erro ao registrar seletor de extração: {e}")
            
            # Persistência ativa
            save_telemetry_files_disk()

        # 3. Binding: Atualizar cenário
        def update_scenario(new_scenario_name):
            nonlocal active_scenario
            if new_scenario_name.strip():
                active_scenario = re.sub(r'[^a-zA-Z0-9_]', '_', new_scenario_name.lower().strip())
                print(f"\n[🔄 AEGIS CENÁRIO ATIVO ALTERADO] Novo cenário: '{active_scenario}'\n")
                sys.stdout.flush()

        # 4. Binding: Pausar e Retomar
        def set_recording_paused(paused):
            nonlocal recording_paused
            recording_paused = bool(paused)
            status_str = "PAUSADO" if recording_paused else "GRAVANDO"
            print(f"\n[⏸️ AEGIS STATUS DE GRAVAÇÃO ALTERADO] Estado: '{status_str}'\n")
            sys.stdout.flush()

        # 5. Binding: Limpar cache e começar de novo
        def reset_recorder_session():
            nonlocal active_scenario, recording_paused
            events_log.clear()
            schema_inputs.clear()
            schema_outputs.clear()
            active_scenario = "default"
            recording_paused = False
            print("\n" + "=" * 60)
            print("🔄 [AEGIS RECORDER RESETADO] Memória e esquemas limpos. Nova sessão iniciada!")
            print("=" * 60 + "\n")
            sys.stdout.flush()
            save_telemetry_files_disk()

        # 6. Binding: Encerrar sessão via botão
        def finish_recorder_session():
            nonlocal session_finished
            session_finished = True
            print("\n" + "=" * 60)
            print("🏁 [AEGIS GRAVAÇÃO CONCLUÍDA] Fechando navegador de forma segura...")
            print("=" * 60 + "\n")
            sys.stdout.flush()

        page.expose_function("pythonRecordAction", record_action)
        page.expose_function("pythonRecordAnnotation", record_annotation)
        page.expose_function("pythonUpdateScenario", update_scenario)
        page.expose_function("pythonSetRecordingPaused", set_recording_paused)
        page.expose_function("pythonResetRecorderSession", reset_recorder_session)
        page.expose_function("pythonFinishRecorderSession", finish_recorder_session)

        # Interceptação de respostas de API
        def handle_response(response):
            if "api" in response.url or response.headers.get("content-type", "").startswith("application/json"):
                try:
                    url_clean = response.url.split("?")[0].split("/")[-1]
                    captured_network[url_clean] = response.json()
                except Exception:
                    pass

        page.on("response", handle_response)

        # Escuta de eventos de diálogo de arquivo (File Chooser)
        def handle_filechooser(file_chooser):
            nonlocal recording_paused
            if recording_paused:
                return
            try:
                element = file_chooser.element
                selector = element.evaluate("el => window.getAegisSelector ? window.getAegisSelector(el) : el.tagName.toLowerCase()")
                event_data = {
                    "type": "filechooser",
                    "tag": "input",
                    "selector": selector,
                    "timestamp": time.time(),
                    "scenario": active_scenario
                }
                events_log.append(event_data)
                print(f"[{active_scenario.upper()}] ACTION: FILECHOOSER | Seletor: '{selector}'")
                sys.stdout.flush()
                save_telemetry_files_disk()
            except Exception as e:
                print(f"[WARNING] Falha ao capturar filechooser no gravador: {e}")
                sys.stdout.flush()

        page.on("filechooser", handle_filechooser)

        # JS Injetado V4: Captura mínima e LED de gravação piscante
        js_minimal_listeners = """
        (function() {
            if (window.__aegis_recorder_active__) return;
            window.__aegis_recorder_active__ = true;
            window.__aegis_recording_paused__ = false;

            // Seletores resilientes Aegis V4
            function getAegisSelector(element) {
                if (!element || element === document.body || element === document.documentElement) return "";
                
                // Redireciona para o elemento interativo mais próximo se o clique foi em um elemento interno (ex: mat-icon ou span)
                let interactive = element.closest('button, a, [role="button"], [role="menuitem"], mat-option, .mat-option, .mat-menu-item, [role="tab"], [role="option"]');
                if (interactive) {
                    element = interactive;
                }

                let shadowPath = "";
                let current = element;
                while (current) {
                    let parent = current.parentNode || current.host;
                    if (parent && parent.nodeType === 11) { 
                        let host = parent.host;
                        let hostSelector = getAegisSelector(host);
                        shadowPath = hostSelector + " >> ";
                        current = parent.host;
                        break;
                    }
                    current = parent;
                }
                let el = element;
                let baseSelector = "";
                let hasTestId = false;

                const testIdAttrs = ['data-testid', 'data-test-id', 'data-test', 'data-qa'];
                for (let attr of testIdAttrs) {
                    let val = el.getAttribute(attr);
                    if (val) {
                        baseSelector = `[${attr}='${val}']`;
                        hasTestId = true;
                        break;
                    }
                }

                if (!hasTestId) {
                    baseSelector = el.tagName.toLowerCase();
                    
                    if ((el.tagName === 'BUTTON' || el.tagName === 'A' || el.classList.contains('mat-option') || el.classList.contains('mat-menu-item')) && el.innerText && el.innerText.trim().length > 0 && el.innerText.trim().length < 45) {
                        let cleanText = el.innerText.replace(/\\\\s+/g, ' ').trim().replace(/'/g, "\\\\'");
                        baseSelector = `${el.tagName.toLowerCase()}:has-text('${cleanText}')`;
                    } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
                        if (el.getAttribute('placeholder')) {
                            baseSelector = `${el.tagName.toLowerCase()}[placeholder='${el.getAttribute('placeholder')}']`;
                        } else if (el.getAttribute('name')) {
                            baseSelector = `${el.tagName.toLowerCase()}[name='${el.getAttribute('name')}']`;
                        } else if (el.getAttribute('id')) {
                            baseSelector = `#${el.getAttribute('id')}`;
                        }
                    } else if (el.id && !/\\\\d{8,}/.test(el.id) && !el.id.startsWith('mat-input-')) {
                        baseSelector = `#${el.id}`;
                    }

                    let genericTags = ['img', 'span', 'div', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'i', 'b', 'strong', 'em', 'small', 'a'];
                    if (genericTags.includes(el.tagName.toLowerCase()) && (!el.id || /\\\\d{8,}/.test(el.id))) {
                        let parent = el.parentElement;
                        let depth = 0;
                        while (parent && depth < 5) {
                            let parentTag = parent.tagName.toLowerCase();
                            let parentTestId = null;
                            for (let attr of testIdAttrs) {
                                if (parent.getAttribute(attr)) {
                                    parentTestId = `[${attr}='${parent.getAttribute(attr)}']`;
                                    break;
                                }
                            }
                            if (parentTestId) {
                                baseSelector = `${parentTestId} ${baseSelector}`;
                                break;
                            }
                            if (parent.id && !/\\\\d{8,}/.test(parent.id) && !parent.id.startsWith('mat-input-')) {
                                baseSelector = `#${parent.id} ${baseSelector}`;
                                break;
                            }
                            if (['article', 'section', 'nav', 'aside', 'header', 'footer'].includes(parentTag)) {
                                baseSelector = `${parentTag} ${baseSelector}`;
                                break;
                            }
                            let classList = Array.from(parent.classList);
                            let semanticClass = classList.find(cls => 
                                cls.includes('post') || cls.includes('card') || cls.includes('item') || 
                                cls.includes('thumbnail') || cls.includes('menu') || cls.includes('wrapper') || 
                                cls.includes('container') || cls.includes('block') || cls.includes('grid')
                            );
                            if (semanticClass) {
                                baseSelector = `.${semanticClass} ${baseSelector}`;
                                break;
                            }
                            parent = parent.parentElement;
                            depth++;
                        }
                    }
                }
                return shadowPath + baseSelector;
            }
            window.getAegisSelector = getAegisSelector;

            function getSemanticFieldName(el) {
                let name = el.getAttribute('name') || el.getAttribute('placeholder') || "";
                const isDynamicId = el.id && (el.id.startsWith('mat-input-') || el.id.startsWith('mat-select-') || /\\\\d{4,}/.test(el.id));
                if (!name || isDynamicId) {
                    const formField = el.closest('mat-form-field');
                    if (formField) {
                        const labelEl = formField.querySelector('.mat-form-field-label');
                        if (labelEl) {
                            name = labelEl.innerText || labelEl.textContent || "";
                        }
                    }
                }
                if (!name) {
                    name = el.id || "";
                }
                return name;
            }
            window.getSemanticFieldName = getSemanticFieldName;

            // Injeção do Indicador Micro-LED via Shadow DOM Fechado
            function injectIndicator() {
                if (document.getElementById('aegis-indicator-host')) return;
                const host = document.createElement('div');
                host.id = 'aegis-indicator-host';
                host.style.position = 'fixed';
                host.style.top = '10px';
                host.style.right = '10px';
                host.style.zIndex = '2147483647';
                host.style.pointerEvents = 'none';

                const shadow = host.attachShadow({mode: 'closed'});
                
                const led = document.createElement('div');
                led.id = 'aegis-led';
                led.style.width = '12px';
                led.style.height = '12px';
                led.style.borderRadius = '50%';
                led.style.backgroundColor = '#ff5555';
                led.style.boxShadow = '0 0 8px #ff5555';
                led.style.transition = 'all 0.3s ease';
                
                const style = document.createElement('style');
                style.textContent = `
                    @keyframes pulse {
                        0% { opacity: 0.4; transform: scale(0.9); }
                        50% { opacity: 1; transform: scale(1.1); }
                        100% { opacity: 0.4; transform: scale(0.9); }
                    }
                    .recording {
                        animation: pulse 1.5s infinite ease-in-out;
                    }
                `;
                led.classList.add('recording');
                
                shadow.appendChild(led);
                shadow.appendChild(style);
                document.body.appendChild(host);

                window.__aegis_update_indicator__ = function(paused) {
                    window.__aegis_recording_paused__ = paused;
                    if (paused) {
                        led.style.backgroundColor = '#33cc99';
                        led.style.boxShadow = '0 0 8px #33cc99';
                        led.classList.remove('recording');
                    } else {
                        led.style.backgroundColor = '#ff5555';
                        led.style.boxShadow = '0 0 8px #ff5555';
                        led.classList.add('recording');
                    }
                };
            }

            if (document.body) {
                injectIndicator();
            } else {
                document.addEventListener('DOMContentLoaded', injectIndicator);
            }

            // Listeners em fase de captura
            document.addEventListener('click', function(e) {
                if (window.__aegis_recording_paused__) return;
                if (e.target.closest('#aegis-indicator-host')) return;
                
                let x_percent = e.clientX / window.innerWidth;
                let y_percent = e.clientY / window.innerHeight;

                let selector = getAegisSelector(e.target);
                window.pythonRecordAction(JSON.stringify({
                    type: 'click',
                    tag: e.target.tagName,
                    selector: selector,
                    text: e.target.innerText ? e.target.innerText.trim().substring(0, 50) : "",
                    x_percent: x_percent,
                    y_percent: y_percent
                }));
            }, true);

            document.addEventListener('change', function(e) {
                if (window.__aegis_recording_paused__) return;
                if (e.target.closest('#aegis-indicator-host')) return;
                
                let selector = getAegisSelector(e.target);
                let name = getSemanticFieldName(e.target);
                window.pythonRecordAction(JSON.stringify({
                    type: 'fill',
                    tag: e.target.tagName,
                    selector: selector,
                    value: e.target.value,
                    name: name,
                    placeholder: e.target.getAttribute('placeholder') || "",
                    id: e.target.id || ""
                }));
            }, true);

            // ── AEGIS ANTI-BOT DETECTOR ──────────────────────────────────────────────
            // Intercepta addEventListener para detectar campos input que registram
            // listeners de keydown/keyup — padrão típico de detecção de cadência
            // humana (Zone.js, Angular Material, formulários bancários e gov).
            // Campos detectados receberão fill_strategy: "HUMAN_LIKE" no dicionário.
            (function() {
                if (window.__aegis_keydown_detector_active__) return;
                window.__aegis_keydown_detector_active__ = true;
                window.__aegis_keydown_fields__ = new Set();

                const _original_addEventListenerFn = EventTarget.prototype.addEventListener;
                EventTarget.prototype.addEventListener = function(type, listener, options) {
                    try {
                        if ((type === 'keydown' || type === 'keyup') &&
                            this instanceof Element &&
                            (this.tagName === 'INPUT' || this.tagName === 'TEXTAREA')) {

                            const selector = window.getAegisSelector
                                ? window.getAegisSelector(this)
                                : (this.getAttribute('data-testid') || this.id || this.name || '');

                            if (selector) {
                                window.__aegis_keydown_fields__.add(selector);
                            }
                        }
                    } catch (e) {
                        // Protege a inicialização de bibliotecas externas (ex: Zone.js) silenciando exceções
                    }
                    return _original_addEventListenerFn.call(this, type, listener, options);
                };
            })();
            // ── FIM AEGIS ANTI-BOT DETECTOR ──────────────────────────────────────────
        })();
        """

        # Adiciona script de inicialização para injetar nas navegações futuras
        context.add_init_script(js_minimal_listeners)

        print(f"Navegando para: {url}...")
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
        except Exception as goto_err:
            print(f"[AEGIS WARNING] Limite de tempo de carregamento da página excedido: {goto_err}. Prosseguindo com carregamento parcial...")
        
        # Garante injeção na página inicial ativa
        try:
            page.evaluate(js_minimal_listeners)
        except Exception:
            pass

        print("\n[OK] Monitoramento discreto ativo. Navegue pelo Microsoft Edge.")
        print("Use comandos no console (p, s, n, scan, reset, f) ou a API HTTP (localhost:9900/api) para controlar.")
        sys.stdout.flush()

        # Controle de requisições de thread
        recording_paused_requested = None  # True para pausar, False para retomar, None para inalterado
        new_scenario_requested = None
        new_annotation_requested = None
        reset_requested = False
        finish_requested = False
        force_scan_requested = False

        def get_status_callback():
            return {
                "success": True,
                "paused": recording_paused,
                "scenario": active_scenario,
                "events_count": len(events_log)
            }

        def set_paused_callback(paused):
            nonlocal recording_paused_requested
            recording_paused_requested = paused

        def set_scenario_callback(name):
            nonlocal new_scenario_requested
            new_scenario_requested = name

        def add_annotation_callback(text):
            nonlocal new_annotation_requested
            new_annotation_requested = text

        def trigger_scan_callback():
            nonlocal force_scan_requested
            force_scan_requested = True

        def finish_session_callback():
            nonlocal finish_requested
            finish_requested = True

        callbacks = {
            "get_status": get_status_callback,
            "set_paused": set_paused_callback,
            "set_scenario": set_scenario_callback,
            "add_annotation": add_annotation_callback,
            "trigger_scan": trigger_scan_callback,
            "finish_session": finish_session_callback
        }

        # Inicializa o servidor HTTP na porta especificada (ou sequencial a partir de 9900 se não fornecida)
        http_server = None
        if control_port:
            server_port = control_port
            try:
                http_server = start_control_server(callbacks, port=server_port)
                print(f"[AEGIS] Servidor HTTP de Controle ativo de forma estrita em http://localhost:{server_port}")
                sys.stdout.flush()
            except Exception as e:
                print(f"[AEGIS ERROR] Falha crítica ao iniciar servidor HTTP de controle na porta {server_port}: {e}")
                sys.stdout.flush()
                raise e
        else:
            server_port = 9900
            while server_port < 10000:
                try:
                    http_server = start_control_server(callbacks, port=server_port)
                    print(f"[AEGIS] Servidor HTTP de Controle ativo em http://localhost:{server_port}")
                    sys.stdout.flush()
                    break
                except Exception:
                    server_port += 1

        # Thread de leitura de stdin não bloqueante
        cmd_queue = queue.Queue()
        def stdin_reader_thread(q):
            while True:
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    q.put(line.strip())
                except Exception:
                    break
        t_stdin = threading.Thread(target=stdin_reader_thread, args=(cmd_queue,), daemon=True)
        t_stdin.start()

        def process_cli_command(cmd):
            nonlocal recording_paused_requested, new_scenario_requested, new_annotation_requested, reset_requested, finish_requested, force_scan_requested
            cmd_lower = cmd.lower().strip()
            if cmd_lower == "p":
                recording_paused_requested = not recording_paused
            elif cmd_lower.startswith("s "):
                name = cmd[2:].strip()
                if name:
                    new_scenario_requested = name
            elif cmd_lower.startswith("n "):
                text = cmd[2:].strip()
                if text:
                    new_annotation_requested = text
            elif cmd_lower == "scan":
                force_scan_requested = True
            elif cmd_lower == "reset":
                reset_requested = True
            elif cmd_lower in ("q", "f"):
                finish_requested = True

        # Loop principal cooperativo thread-safe
        if auto_simulate:
            print("[AEGIS AUTO-SIMULATOR] Iniciando simulação automática de preenchimento do Portal Segura...")
            sys.stdout.flush()
            try:
                run_auto_simulation(page, update_scenario, record_annotation)
            except Exception as sim_err:
                print(f"[AEGIS AUTO-SIMULATOR ERROR] Erro na simulação: {sim_err}")
                sys.stdout.flush()
            session_finished = True
        else:
            last_scan_time = time.time()
            while True:
                if session_finished or browser_closed:
                    break
                try:
                    page.wait_for_timeout(100)

                    # 1. Trata comandos da fila stdin
                    while not cmd_queue.empty():
                        cmd = cmd_queue.get_nowait()
                        process_cli_command(cmd)

                    # 2. Trata comandos solicitados (do servidor HTTP ou CLI)
                    if recording_paused_requested is not None:
                        new_state = recording_paused_requested
                        recording_paused_requested = None
                        set_recording_paused(new_state)
                        try:
                            page.evaluate(f"if (window.__aegis_update_indicator__) window.__aegis_update_indicator__({json.dumps(new_state)})")
                        except Exception:
                            pass

                    if new_scenario_requested is not None:
                        scenario_name = new_scenario_requested
                        new_scenario_requested = None
                        update_scenario(scenario_name)

                    if new_annotation_requested is not None:
                        annotation_text = new_annotation_requested
                        new_annotation_requested = None
                        record_annotation(annotation_text)

                    if reset_requested:
                        reset_requested = False
                        reset_recorder_session()
                        try:
                            page.reload()
                        except Exception:
                            pass

                    if finish_requested:
                        finish_requested = False
                        finish_recorder_session()

                    if force_scan_requested:
                        force_scan_requested = False
                        scan_fields_python(page, record_action)

                    # 3. Varredura cooperativa periódica do DOM (a cada 3s)
                    if time.time() - last_scan_time >= 3.0:
                        if not recording_paused and not session_finished and not browser_closed:
                            scan_fields_python(page, record_action)
                            # Atualiza cooperativamente o cache de keydown listeners sem interferir com callbacks
                            try:
                                anti_bot_fields_cache = page.evaluate(
                                    "() => window.__aegis_keydown_fields__ ? [...window.__aegis_keydown_fields__] : []"
                                )
                            except Exception:
                                pass
                        last_scan_time = time.time()

                except Exception as loop_ex:
                    print(f"[AEGIS RECORDER ERROR] Erro no loop cooperativo: {loop_ex}")
                    sys.stdout.flush()

        print("\nFinalizando gravação de forma limpa e compilando telemetrias...")
        sys.stdout.flush()
        
        if session_finished and not browser_closed:
            try:
                # Ocultar o micro-LED indicador Aegis para tirar um screenshot limpo
                page.evaluate("() => { const w = document.getElementById('aegis-indicator-host'); if (w) w.style.display = 'none'; }")
                screenshot_path = os.path.join(OUTPUT_DIR, "screenshot_recorder.png")
                page.screenshot(path=screenshot_path)
                print(f"[AEGIS] Screenshot da última tela gravado em: {screenshot_path}")
                sys.stdout.flush()
            except Exception as e:
                print(f"[WARNING] Não foi possível capturar o screenshot da última tela: {e}")
                sys.stdout.flush()
        
        # Consolida e grava ativamente antes de fechar o browser
        save_telemetry_files_disk(active_evaluate=True)
        
        trace_path = os.path.join(OUTPUT_DIR, "trace.zip")
        context.tracing.stop(path=trace_path)
        
        try:
            browser.close()
        except Exception:
            pass

        print(f"\n[SUCESSO] Gravação salva em: {os.path.join(OUTPUT_DIR, 'gravacao.json')}")
        print(f"[SUCESSO] Dicionário gerado em: {os.path.join(OUTPUT_DIR, 'dicionario.json')}")
        print(f"[SUCESSO] Template gerado em:   {os.path.join(OUTPUT_DIR, 'template.csv')}")
        print("=" * 60)
        sys.stdout.flush()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Aegis BlackBox V3 Recorder")
    parser.add_argument("--url", required=True, help="URL para gravação")
    parser.add_argument("--output-dir", default=None, help="Diretório de saída dos artefatos (projeto isolado)")
    parser.add_argument("--auto-simulate", action="store_true", help="Executa gravação automática simulada")
    parser.add_argument("--control-port", type=int, default=None, help="Porta estrita para o servidor HTTP de controle")
    args = parser.parse_args()

    if args.output_dir:
        OUTPUT_DIR = os.path.abspath(args.output_dir)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    run_recorder(args.url, auto_simulate=args.auto_simulate, control_port=args.control_port)
