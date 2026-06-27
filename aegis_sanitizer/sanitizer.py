import os
import json
import sys
import argparse
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
# Caminhos definidos dinamicamente via argparse
TELEMETRY_DIR = r"C:\Projetos\Lab\telemetry_data"
TELEMETRY_FILE = os.path.join(TELEMETRY_DIR, "gravacao.json")
DICT_FILE = os.path.join(TELEMETRY_DIR, "dicionario.json")
REPORT_FILE = os.path.join(TELEMETRY_DIR, "relatorio.md")

def sanitize_telemetry():
    print("\n" + "=" * 60)
    print("🛡️ AEGIS SANITIZER V2: PROCESSANDO E COMPACTANDO LOGS MULTI-CENÁRIOS")
    print("=" * 60)

    if not os.path.exists(TELEMETRY_FILE) or not os.path.exists(DICT_FILE):
        print(f"[ERRO] Arquivos de telemetria ou dicionário não encontrados em: {TELEMETRY_DIR}")
        print("Por favor, execute o gravador primeiro (aegis_blackbox/recorder.py).")
        return

    with open(TELEMETRY_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    with open(DICT_FILE, "r", encoding="utf-8") as f:
        dict_data = json.load(f)

    initial_url = raw_data.get("initial_url", "")
    events = raw_data.get("events", [])
    network = raw_data.get("network_payloads", {})
    anti_bot_fields = raw_data.get("anti_bot_fields", [])  # C2: campos com keydown listeners

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
        # C2: exibe fill_strategy na tabela do dicionário
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
    
    # Agrupa eventos por cenário
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
    anti_bot_detected = bool(anti_bot_fields)  # C2: detectado pelo recorder

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
    
    # C2: Alerta de campos anti-bot detectados pelo recorder
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

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown))

    # Atualiza project.json se existir no diretório
    project_json_path = os.path.join(TELEMETRY_DIR, "project.json")
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

    print(f"\n[SUCESSO] Relatório Markdown compilado com sucesso em: {REPORT_FILE}")
    print("=" * 60)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Aegis Sanitizer V2")
    parser.add_argument("--project-dir", default=None, help="Diretório do projeto isolado. Se omitido, usa telemetry_data/")
    args = parser.parse_args()

    if args.project_dir:
        TELEMETRY_DIR = os.path.abspath(args.project_dir)
        TELEMETRY_FILE = os.path.join(TELEMETRY_DIR, "gravacao.json")
        DICT_FILE = os.path.join(TELEMETRY_DIR, "dicionario.json")
        REPORT_FILE = os.path.join(TELEMETRY_DIR, "relatorio.md")

    sanitize_telemetry()
