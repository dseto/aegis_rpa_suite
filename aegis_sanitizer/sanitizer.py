import os
import json
import sys
import argparse
from datetime import datetime

# Adiciona caminhos necessários ao path
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

sys.stdout.reconfigure(encoding='utf-8')

def evaluate_selector_reliability(selector):
    """Calcula o score de confiabilidade do seletor e retorna (score, tipo)."""
    if not selector:
        return 0, "empty"
        
    test_attributes = ["data-testid", "data-test-id", "data-test", "data-qa"]
    if any(attr in selector for attr in test_attributes):
        if " >> " in selector:
            return 90, "data-testid-anchor"
        return 100, "data-testid"
        
    if "#" in selector and not re.search(r"\d{4,}", selector) and not "mat-input-" in selector and not "mat-select-" in selector:
        return 90, "id"
        
    if "[name=" in selector or "[placeholder=" in selector:
        return 80, "name-or-placeholder"
        
    if ":has-text(" in selector:
        return 70, "has-text"
        
    if "." in selector:
        return 60, "class"
        
    return 40, "tag"

# Importa expressões regulares necessárias
import re


class SanitizerService:
    def __init__(self, telemetry_dir: str):
        self.telemetry_dir = os.path.abspath(telemetry_dir)
        self.telemetry_file = os.path.join(self.telemetry_dir, "gravacao.json")
        self.dict_file = os.path.join(self.telemetry_dir, "dicionario.json")
        self.report_file = os.path.join(self.telemetry_dir, "relatorio.md")

    def sanitize(self) -> bool:
        print("\n" + "=" * 60)
        print("🛡️ AEGIS SANITIZER V2: PROCESSANDO E COMPACTANDO LOGS MULTI-CENÁRIOS")
        print("=" * 60)
        print(f"[TELEMETRY DIR] Diretório: {self.telemetry_dir}")

        if not os.path.exists(self.telemetry_file) or not os.path.exists(self.dict_file):
            print(f"[ERRO] Arquivos de telemetria ou dicionário não encontrados em: {self.telemetry_dir}")
            print("Por favor, execute o gravador primeiro (aegis_blackbox/recorder.py).")
            return False

        with open(self.telemetry_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        with open(self.dict_file, "r", encoding="utf-8") as f:
            dict_data = json.load(f)

        initial_url = raw_data.get("initial_url", "")
        events = raw_data.get("events", [])
        
        # Saneamento de eventos duplicados e ruídos de gravação
        cleaned_events = []
        seen_fills = {}
        last_fill_selector = None
        for ev in events:
            ev_type = ev.get("type", "").lower()
            selector = ev.get("selector", "")
            scenario = ev.get("scenario", "default")
            
            # 1. Ignora cliques consecutivos no mesmo seletor
            if cleaned_events:
                last = cleaned_events[-1]
                if ev_type == "click" and last.get("type") == "click" and selector == last.get("selector"):
                    continue
            
            # 2. Ignora cliques em overlays genéricos de CDK ou placeholder "Nenhum resultado"
            if ev_type == "click" and ("cdk-overlay-container" in selector or "backdrop" in selector or "Nenhum resultado" in selector or "Nenhum resultado" in ev.get("text", "")):
                continue
                
            # 3. Ignora cliques em autocomplete que não seguem o preenchimento do input correspondente
            if ev_type == "click" and "mat-autocomplete-panel-" in selector:
                panel_name = selector.split("mat-autocomplete-panel-")[1].split(" ")[0]
                if last_fill_selector:
                    if panel_name == "marca" and "brand" not in last_fill_selector:
                        continue
                    if panel_name == "modelo" and "model" not in last_fill_selector:
                        continue
                    if panel_name == "versao" and "version" not in last_fill_selector:
                        continue
                else:
                    continue
                
            # 4. Trata preenchimentos duplicados (mesmo seletor e mesmo valor no mesmo cenário)
            if ev_type in ["fill", "change"]:
                key = (scenario, selector)
                val = ev.get("value", "")
                if key in seen_fills and seen_fills[key] == val:
                    continue
                seen_fills[key] = val
                last_fill_selector = selector
                
            cleaned_events.append(ev)
            
        # Carrega metadados do projeto para buscar descrição de negócio e resultado esperado
        project_json_path = os.path.join(self.telemetry_dir, "project.json")
        business_desc = ""
        expected_outcome = ""
        if os.path.exists(project_json_path):
            try:
                with open(project_json_path, "r", encoding="utf-8") as f:
                    proj_meta = json.load(f)
                    business_desc = proj_meta.get("business_description", "")
                    expected_outcome = proj_meta.get("expected_business_outcome", "")
            except:
                pass

        # Realiza o refinamento semântico cognitivo
        dict_data, raw_data = self.refine_semantics_with_llm(dict_data, raw_data, business_desc, expected_outcome)
        events = raw_data.get("events", [])
        raw_data["events"] = events

        # Salva o arquivo de gravação e dicionário devidamente sanitizados e traduzidos
        with open(self.telemetry_file, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=4, ensure_ascii=False)

        with open(self.dict_file, "w", encoding="utf-8") as f:
            json.dump(dict_data, f, indent=4, ensure_ascii=False)

        network = raw_data.get("network_payloads", {})
        anti_bot_fields = raw_data.get("anti_bot_fields", [])

        markdown = []
        markdown.append(f"# 🛡️ Relatório de Telemetria Aegis RPA Suite V2")
        markdown.append(f"\n* **URL Alvo:** {initial_url}")
        markdown.append(f"* **Total de Ações Gravadas:** {len(events)}")
        markdown.append(f"* **Respostas de Rede Interceptadas:** {len(network.keys())}")
        markdown.append("\n" + "-" * 60)

        # 1. Imprime Dicionário de Dados Sintetizado
        markdown.append("\n## 📋 Dicionário de Dados Parametrizado (Sintetizado)")
        markdown.append("\nMapeamento físico-semântico de campos de entrada e extração:\n")
        markdown.append("| Cenário | Chave Semântica (Coluna CSV) | Elemento | Seletor Físico Mapeado | Confiabilidade | Tipo de Seletor | Valor Observado | Fill Strategy |")
        markdown.append("| :---: | :--- | :---: | :--- | :---: | :---: | :--- | :---: |")
        
        inputs_list = dict_data.get("inputs", [])
        if not inputs_list and "fields" in dict_data:
            for sem_key, field_info in dict_data["fields"].items():
                inputs_list.append({
                    "scenario": "default",
                    "semantic_key": sem_key,
                    "type": field_info.get("type", "string"),
                    "selector": field_info.get("selector", ""),
                    "observed_value": field_info.get("observed_value", ""),
                    "confidence": field_info.get("confidence", 40),
                    "selector_type": field_info.get("selector_type", "tag")
                })
                
        outputs_list = dict_data.get("outputs", [])
        if isinstance(outputs_list, dict):
            temp_outputs = []
            for sem_key, out_info in outputs_list.items():
                temp_outputs.append({
                    "scenario": "default",
                    "semantic_key": sem_key,
                    "selector": out_info.get("selector", ""),
                    "confidence": out_info.get("confidence", 40),
                    "selector_type": out_info.get("selector_type", "tag")
                })
            outputs_list = temp_outputs
            
        for inp in inputs_list:
            conf = inp.get("confidence", 40)
            badge = "🟢 ALTA" if conf >= 90 else "🟡 MÉDIA" if conf >= 70 else "🔴 BAIXA"
            strategy = inp.get("fill_strategy", "DIRECT")
            strategy_badge = "🧱 HUMAN_LIKE" if strategy == "HUMAN_LIKE" else "DIRECT"
            markdown.append(f"| `{inp['scenario']}` | **`{inp['semantic_key']}`** | `{inp['type']}` | `{inp['selector']}` | {badge} ({conf}%) | `{inp.get('selector_type', 'tag')}` | \"{inp['observed_value']}\" | `{strategy_badge}` |")
            
        for out in outputs_list:
            conf = out.get("confidence", 40)
            badge = "🟢 ALTA" if conf >= 90 else "🟡 MÉDIA" if conf >= 70 else "🔴 BAIXA"
            markdown.append(f"| `{out['scenario']}` | **`{out['semantic_key']}` (SAÍDA)** | `extract` | `🧬 {out['selector']}` | {badge} ({conf}%) | `{out.get('selector_type', 'tag')}` | *Valor gerado em runtime* |")

        # 2. Sequenciamento de Eventos por Cenário Lógico
        markdown.append("\n" + "-" * 60)
        markdown.append("\n## 🗺️ Fluxo de Passos e Bifurcações por Cenário")
        
        scenarios_map = {}
        for ev in events:
            scen = ev.get("scenario", "default")
            if scen not in scenarios_map:
                scenarios_map[scen] = []
            scenarios_map[scen].append(ev)

        for scenario_name, scenario_events in scenarios_map.items():
            markdown.append(f"\n### 🎯 Cenário Lógico: `{scenario_name.upper()}`")
            markdown.append(f"\nTotal de ações neste caminho: {len(scenario_events)}\n")
            markdown.append("| Passo | Tipo | Elemento | Seletor Resiliente Sugerido | Valor / Ação |")
            markdown.append("| :---: | :---: | :---: | :--- | :--- |")

            passo_count = 1
            previous_event = None

            for ev in scenario_events:
                ev_type = ev.get("type", "").upper()
                
                if previous_event:
                    if ev_type == "CLICK" and previous_event.get("type") == "click" and ev.get("selector") == previous_event.get("selector"):
                        continue
                    if ev_type == "FILL" and previous_event.get("type") == "fill" and ev.get("selector") == previous_event.get("selector"):
                        previous_event = ev
                        continue

                if ev_type == "ANNOTATION":
                    markdown.append(f"| **📝 REGRA** | **VALIDAÇÃO** | `-` | *N/A (Nota de Negócio)* | **\"{ev.get('text', '')}\"** |")
                elif ev_type == "CALL_SKILL":
                    skill_slug = ev.get("skill_slug", "")
                    params_str = ", ".join([f"{k}={v}" for k, v in ev.get("parameters", {}).items()])
                    markdown.append(f"| **👉 CALL** | **SKILL** | `{skill_slug}` | *Parâmetros:* | `{params_str}` |")
                    
                    # Tenta ler passos internos da Skill para expor no relatório (para a LLM)
                    project_dir = os.path.dirname(os.path.dirname(self.telemetry_dir))
                    skill_recording_path = os.path.join(project_dir, "skills", skill_slug, "gravacao.json")
                    if os.path.exists(skill_recording_path):
                        try:
                            with open(skill_recording_path, "r", encoding="utf-8") as sf:
                                s_data = json.load(sf)
                            s_events = s_data.get("events", [])
                            
                            # Adiciona quebra e bloco details
                            markdown.append("\n<details>")
                            markdown.append(f"<summary>Visualizar passos internos da Skill: {skill_slug}</summary>\n")
                            markdown.append("| Passo | Tipo | Elemento | Seletor Resiliente | Valor Mapeado |")
                            markdown.append("| :---: | :---: | :---: | :--- | :--- |")
                            
                            s_step = 1
                            s_prev = None
                            for sev in s_events:
                                sev_type = sev.get("type", "").upper()
                                if s_prev:
                                    if sev_type == "CLICK" and s_prev.get("type") == "click" and sev.get("selector") == s_prev.get("selector"):
                                        continue
                                    if sev_type == "FILL" and s_prev.get("type") == "fill" and sev.get("selector") == s_prev.get("selector"):
                                        s_prev = sev
                                        continue
                                        
                                if sev_type == "ANNOTATION":
                                    markdown.append(f"| **📝 REGRA** | **VALIDAÇÃO** | `-` | *N/A (Nota)* | **\"{sev.get('text', '')}\"** |")
                                else:
                                    s_tag = sev.get("tag", "").lower()
                                    if sev.get("is_date"): s_tag = "input (data)"
                                    s_sel = sev.get("selector", "")
                                    s_val = ""
                                    if sev_type == "CLICK":
                                        sx = sev.get("x_percent")
                                        sy = sev.get("y_percent")
                                        scoords = f" [coords: ({sx:.4f}, {sy:.4f})]" if (sx is not None and sy is not None) else ""
                                        s_val = f"Clique em: '{sev.get('text', '')}'{scoords}"
                                    elif sev_type == "FILL":
                                        s_val = f"Preencheu com: '{sev.get('value', '')}'"
                                        
                                    if " >> " in s_sel:
                                        s_sel = f"🧬 **Shadow DOM:** `{s_sel}`"
                                    else:
                                        s_sel = f"`{s_sel}`"
                                    markdown.append(f"| {s_step} | `{sev_type}` | `{s_tag}` | {s_sel} | {s_val} |")
                                    s_step += 1
                                    s_prev = sev
                            markdown.append("</details>\n")
                        except Exception as e:
                            markdown.append(f"\n*Falha ao carregar passos detalhados da Skill {skill_slug}: {str(e)}*\n")
                else:
                    tag = ev.get("tag", "").lower()
                    if ev.get("is_date"):
                        tag = "input (data)"
                    selector = ev.get("selector", "")
                    val_text = ""
                    
                    if ev_type == "CLICK":
                        x = ev.get("x_percent")
                        y = ev.get("y_percent")
                        coords_str = f" [coords: ({x:.4f}, {y:.4f})]" if (x is not None and y is not None) else ""
                        val_text = f"Clique em: '{ev.get('text', '')}'{coords_str}"
                    elif ev_type == "FILL":
                        if ev.get("is_date"):
                            val_text = f"Preencheu data: '{ev.get('value', '')}'"
                        else:
                            val_text = f"Preencheu com: '{ev.get('value', '')}'"
                    elif ev_type == "FILECHOOSER":
                        val_text = "Abriu o diálogo de seleção de arquivo"

                    if " >> " in selector:
                        selector = f"🧬 **Shadow DOM:** `{selector}`"
                    else:
                        selector = f"`{selector}`"

                    desc_negocio = ev.get("business_description") or ev.get("description")
                    if desc_negocio:
                        val_text = f"**{desc_negocio}**<br><span style='font-size:10px; color:var(--text-muted);'>{val_text}</span>"

                    markdown.append(f"| {passo_count} | `{ev_type}` | `{tag}` | {selector} | {val_text} |")
                    passo_count += 1
                    previous_event = ev

        # 3. Payloads de Rede JSON Interceptados
        if network:
            markdown.append("\n" + "-" * 60)
            markdown.append("\n## 🌐 Payloads de Rede JSON Interceptados")
            markdown.append("\nRespostas de APIs capturadas em background para mapeamento dinâmico:\n")

            for endpoint, payload in network.items():
                markdown.append(f"### 🔗 Endpoint: `{endpoint}`")
                payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
                if len(payload_str) > 2500:
                    payload_str = payload_str[:2500] + "\n\n... [PAYLOAD TRUNCADO POR TAMANHO PARA ECONOMIA DE TOKENS] ..."
                
                markdown.append(f"```json\n{payload_str}\n```\n")

        # 4. Diretrizes e Análise Preventiva
        markdown.append("\n" + "-" * 60)
        markdown.append("\n## 🧠 Diretrizes Arquiteturais para o Compilador (Aegis Mentor)")
        markdown.append("\nPontos críticos V2 identificados pelo motor do Sanitizer:\n")

        shadow_detected = any(" >> " in ev.get("selector", "") for ev in events if ev.get("selector"))
        annotation_detected = any(ev.get("type") == "annotation" for ev in events)
        multiple_scenarios = len(scenarios_map.keys()) > 1
        date_detected = any(ev.get("is_date") for ev in events)
        filechooser_detected = any(ev.get("type") == "filechooser" for ev in events)
        anti_bot_detected = bool(anti_bot_fields)

        if shadow_detected:
            markdown.append("* **🧬 Shadow DOM Ativo:** Existem seletores usando `>>`. O script final deve usar o piercing do Playwright.")
        if annotation_detected:
            markdown.append("* **📝 Regras Manuais Injetadas:** Há notas do desenvolvedor. O compilador deve traduzi-las em esperas explícitas ou validações de texto na interface.")
        if multiple_scenarios:
            markdown.append(f"* **🔀 Multi-Cenários Detectados ({len(scenarios_map.keys())}):** O compilador **deve** gerar funções modulares específicas para cada cenário e um `Scenario Router` central baseado na coluna `aegis_scenario`.")
        if date_detected:
            markdown.append("* **📅 Campos de Calendário Detectados:** Existem campos de data. O compilador deve aplicar o **Padrão K (Bypass/Keyboard Evaluation)** para preenchimento de data resiliente.")
        if filechooser_detected:
            markdown.append("* **📤 Diálogo de Arquivo Detectado:** O fluxo contém eventos de seleção de arquivo. O compilador deve estruturar o preenchimento usando o `page.expect_file_chooser()` ou `page.set_input_files()` associado ao seletor (Padrão L).")
        
        if anti_bot_detected:
            campos_str = ', '.join([f'`{s}`' for s in anti_bot_fields])
            markdown.append(f"* **🧐 ANTI-BOT COMPORTAMENTAL DETECTADO ({len(anti_bot_fields)} campo(s)):** Os seguintes seletores possuíram listeners `keydown`/`keyup` ativos durante a gravação: {campos_str}. "
                            f"Esses campos utilizam detecção de cadência de teclado (padrão Zone.js). O robô **deve** usar `runner.fill_human_like()` ou o helper equivalente com `time.sleep()` entre cada tecla (>= 50ms) para esses campos, "
                            f"caso contrário o botão de avançar permanecerá desabilitado mesmo com o formulário correto.")
        
        markdown.append("* **📊 Matriz de Resiliência (Negative Testing):** O script final deve envelopar o loop de execução transacional (`try/except`) validando erros de negócio na div `.toast-error` ou divs de alertas contendo o token `expected_error_token` se `expected_result` for `BUSINESS_BLOCKED`.")

        # 5. Auditoria de Confiabilidade de Seletores
        low_confidence_fields = [inp for inp in inputs_list if inp.get("confidence", 40) < 70]
        low_confidence_outputs = [out for out in outputs_list if out.get("confidence", 40) < 70]
        
        if low_confidence_fields or low_confidence_outputs:
            markdown.append("\n" + "-" * 60)
            markdown.append("\n## ⚠️ Alerta de Auditoria: Seletores de Baixa Confiabilidade")
            markdown.append("Os seguintes elementos mapeados utilizam seletores voláteis ou genéricos. É altamente recomendado adicionar atributos `data-testid` a eles no portal alvo para evitar quebras estruturais em futuras atualizações:")
            for inp in low_confidence_fields:
                markdown.append(f"* Campo **`{inp['semantic_key']}`** (Seletor: `{inp['selector']}` - Confiabilidade: {inp.get('confidence')}%).")
            for out in low_confidence_outputs:
                markdown.append(f"* Campo de Saída **`{out['semantic_key']}`** (Seletor: `{out['selector']}` - Confiabilidade: {out.get('confidence')}%).")

        with open(self.report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown))

        # Atualiza project.json se existir no diretório
        project_json_path = os.path.join(self.telemetry_dir, "project.json")
        if os.path.exists(project_json_path):
            try:
                with open(project_json_path, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                proj["status"] = "sanitized"
                proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(project_json_path, "w", encoding="utf-8") as f:
                    json.dump(proj, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[WARNING] Não foi possível atualizar project.json: {e}")

        print(f"\n[SUCESSO] Relatório Markdown compilado com sucesso em: {self.report_file}")
        print("=" * 60)
        return True

    def refine_semantics_with_llm(self, dict_data: dict, raw_data: dict, business_desc: str, expected_outcome: str) -> tuple:
        """
        Usa LLM para refinar as chaves do dicionário para linguagem de negócio e traduzir
        os passos de gravação para descrições inteligíveis.
        """
        from aegis_runner.cognitive_fallback import CognitiveGateway
        gateway = CognitiveGateway(project_dir=self.telemetry_dir)
        if not gateway.is_active():
            print("[INFO] Gateway Cognitivo não configurado ou ativo. Ignorando refinamento semântico via LLM.")
            return dict_data, raw_data

        print("[COGNITIVE] Iniciando Higienização Cognitiva Semântica (Fase 2.5)...")
        
        inputs = dict_data.get("inputs", [])
        outputs = dict_data.get("outputs", [])
        events = raw_data.get("events", [])
        
        simplified_inputs = []
        for inp in inputs:
            simplified_inputs.append({
                "semantic_key": inp.get("semantic_key"),
                "type": inp.get("type"),
                "selector": inp.get("selector"),
                "observed_value": inp.get("observed_value")
            })
            
        simplified_outputs = []
        for out in outputs:
            simplified_outputs.append({
                "semantic_key": out.get("semantic_key"),
                "selector": out.get("selector")
            })
            
        simplified_events = []
        for idx, ev in enumerate(events):
            simplified_events.append({
                "index": idx,
                "type": ev.get("type"),
                "selector": ev.get("selector"),
                "text": ev.get("text", ""),
                "value": ev.get("value", ""),
                "voice_annotation": ev.get("voice_annotation", ""),
                "annotation": ev.get("annotation", "")
            })
            
        prompt = f"""
        Você é o Sanitizador Cognitivo da suíte Aegis RPA.
        Sua missão é traduzir termos técnicos, seletores e placeholders brutos para uma linguagem de negócio limpa e legível.
        
        ---
        CONTEXTO DE NEGÓCIO FORNECIDO PELO USUÁRIO:
        Descrição do Caso de Teste: {business_desc or 'Não informada'}
        Resultado de Negócio Esperado: {expected_outcome or 'Não informado'}
        ---
        
        TAREFAS:
        1. Renomear as chaves técnicas de inputs ("semantic_key") para nomes amigáveis baseados no negócio (ex: 'seuemail_exemplo_com' -> 'email_login', 'txt_cpf_pf' -> 'cpf_cliente'). Use snake_case.
        2. Renomear as chaves técnicas de outputs ("semantic_key") para nomes amigáveis baseados no negócio.
        3. Para cada evento do fluxo (identificado pelo seu "index"), crie uma descrição funcional em linguagem de negócio amigável (em português), explicando o que o usuário está realizando (ex: "Preencher email do usuário para autenticação"). 
           - Importante: Se houver "voice_annotation" ou "annotation" fornecidas pelo usuário no evento, use-as como fonte de verdade absoluta para a descrição funcional!
        
        INPUTS BRUTOS:
        {json.dumps(simplified_inputs, indent=2)}
        
        OUTPUTS BRUTOS:
        {json.dumps(simplified_outputs, indent=2)}
        
        EVENTOS DO FLUXO:
        {json.dumps(simplified_events, indent=2)}
        
        Retorne OBRIGATORIAMENTE um objeto JSON estruturado contendo exatamente:
        - "inputs": lista de objetos com "original_key" (a chave original a ser mapeada) e "semantic_key" (nova chave refinada).
        - "outputs": lista de objetos com "original_key" (a chave original a ser mapeada) e "semantic_key" (nova chave refinada).
        - "events": lista de objetos, cada um com "index" (o índice original) e "business_description" (a descrição refinada de negócio em português).
        
        Exemplo de saída esperada:
        {{
            "inputs": [
                {{ "original_key": "seuemail_exemplo_com", "semantic_key": "email_login" }}
            ],
            "outputs": [
                {{ "original_key": "lbl_res_val", "semantic_key": "valor_cotacao" }}
            ],
            "events": [
                {{ "index": 0, "business_description": "Acessar a página de cotações do portal" }},
                {{ "index": 1, "business_description": "Digitar o e-mail de acesso corporativo" }}
            ]
        }}
        
        Retorne EXCLUSIVAMENTE o JSON estruturado.
        """
        
        try:
            raw_response = gateway._call_llm_api(prompt, force_json=True)
            result = gateway._clean_json_response(raw_response)
            
            # Aplica mapeamentos aos inputs originais
            input_mapping = {item["original_key"]: item["semantic_key"] for item in result.get("inputs", []) if "original_key" in item and "semantic_key" in item}
            output_mapping = {item["original_key"]: item["semantic_key"] for item in result.get("outputs", []) if "original_key" in item and "semantic_key" in item}
            event_descriptions = {item["index"]: item["business_description"] for item in result.get("events", []) if "index" in item and "business_description" in item}
            
            # Atualiza o dicionário de dados
            for inp in inputs:
                orig = inp.get("semantic_key")
                if orig in input_mapping:
                    inp["semantic_key"] = input_mapping[orig]
            for out in outputs:
                orig = out.get("semantic_key")
                if orig in output_mapping:
                    out["semantic_key"] = output_mapping[orig]
                    
            # Se o dicionário tiver "fields", atualiza também
            if "fields" in dict_data:
                new_fields = {}
                for sem_key, field_info in dict_data["fields"].items():
                    new_key = input_mapping.get(sem_key, sem_key)
                    new_fields[new_key] = field_info
                dict_data["fields"] = new_fields
                
            # Atualiza eventos em raw_data
            for idx, ev in enumerate(events):
                if idx in event_descriptions:
                    ev["business_description"] = event_descriptions[idx]
                    
            print("[COGNITIVE SUCESSO] Dicionário de dados e fluxo de eventos traduzidos para linguagem de negócio.")
        except Exception as e:
            print(f"[COGNITIVE WARNING] Falha ao realizar a tradução cognitiva semântica: {e}")
            
        return dict_data, raw_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Aegis Sanitizer Service")
    parser.add_argument("--project-dir", default=None, help="Diretório do projeto isolado. Se omitido, usa telemetry_data/")
    args = parser.parse_args()

    telemetry_dir = os.path.abspath(args.project_dir) if args.project_dir else r"C:\Projetos\Lab\telemetry_data"
    service = SanitizerService(telemetry_dir)
    service.sanitize()
