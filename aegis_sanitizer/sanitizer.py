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

        # Helper para corrigir codificação quebrada (double encoding)
        def fix_encoding(text: str) -> str:
            if not isinstance(text, str):
                return text
            replacements = {
                "Ã¡": "á", "Ã ": "à", "Ã¢": "â", "Ã£": "ã",
                "Ã‰": "É", "Ã©": "é", "Ãª": "ê",
                "Ã": "Í", "Ã­": "í",
                "Ã“": "Ó", "Ã³": "ó", "Ã´": "ô", "Ãµ": "õ",
                "Ãš": "Ú", "Ãº": "ú",
                "Ã‡": "Ç", "Ã§": "ç",
                "Ã‘": "Ñ", "Ã±": "ñ",
                "Ãlcool": "Álcool", "Ãl": "Ál",
            }
            for bad, good in replacements.items():
                text = text.replace(bad, good)
            return text

        # Corrige codificação nos dados brutos do dicionário e eventos
        fields = dict_data.get("fields", {})
        for field_name, field_info in fields.items():
            if "observed_value" in field_info:
                field_info["observed_value"] = fix_encoding(field_info["observed_value"])
            if "selector" in field_info:
                field_info["selector"] = fix_encoding(field_info["selector"])

        for inp in dict_data.get("inputs", []):
            if "observed_value" in inp:
                inp["observed_value"] = fix_encoding(inp["observed_value"])
            if "selector" in inp:
                inp["selector"] = fix_encoding(inp["selector"])
        for out in dict_data.get("outputs", []):
            if "selector" in out:
                out["selector"] = fix_encoding(out["selector"])

        for ev in raw_data.get("events", []):
            if "selector" in ev:
                ev["selector"] = fix_encoding(ev["selector"])
            if "text" in ev:
                ev["text"] = fix_encoding(ev["text"])
            if "value" in ev:
                ev["value"] = fix_encoding(ev["value"])
            if "parent" in ev and ev["parent"]:
                if "selector" in ev["parent"]:
                    ev["parent"]["selector"] = fix_encoding(ev["parent"]["selector"])
                if "has_text" in ev["parent"] and ev["parent"]["has_text"]:
                    ev["parent"]["has_text"] = fix_encoding(ev["parent"]["has_text"])

        # Normalização de datas no formato YYYY-MM-DD para DD/MM/YYYY
        # para garantir resiliência e retrocompatibilidade com gravações antigas
        for field_name, field_info in fields.items():
            if field_info.get("type") == "date" or field_info.get("is_date"):
                val = field_info.get("observed_value")
                if isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                    parts = val.split("-")
                    field_info["observed_value"] = f"{parts[2]}/{parts[1]}/{parts[0]}"

        for ev in raw_data.get("events", []):
            if ev.get("type") == "fill" and (ev.get("is_date") or ev.get("fieldType") == "date"):
                val = ev.get("value")
                if isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                    parts = val.split("-")
                    ev["value"] = f"{parts[2]}/{parts[1]}/{parts[0]}"

        initial_url = raw_data.get("initial_url", "")
        events = raw_data.get("events", [])

        # Estampagem de original_index ANTES do Padrão P (decisão D2 do
        # .specs/plano-sanitizer-alta-fidelidade.md, Seção 8/T2): precisa
        # refletir a ordem FÍSICA original da gravação, não a ordem
        # pós-inversão de autocomplete que roda logo abaixo. Padrão P troca
        # objetos de posição na lista (não recria os dicts), então o valor
        # estampado aqui viaja junto com cada evento mesmo depois da troca.
        # _classify_raw_events (mais abaixo) só LÊ esse campo — nunca o cria.
        for i, ev in enumerate(events):
            ev["original_index"] = i

        # Inversão de eventos de autocomplete gravados incorretamente (Padrão P)
        idx_ev = 0
        while idx_ev < len(events) - 1:
            ev_curr = events[idx_ev]
            ev_next = events[idx_ev+1]
            if (ev_curr.get("type") == "click" and 
                ev_next.get("type") == "fill" and 
                ("autocomplete" in ev_curr.get("selector", "").lower() or 
                 "option" in ev_curr.get("selector", "").lower() or 
                 "option" in ev_curr.get("tag", "").lower() or 
                 "mat-option" in ev_curr.get("selector", "").lower())):
                # Inverte a ordem física dos passos para o compilador gerar corretamente
                events[idx_ev], events[idx_ev+1] = events[idx_ev+1], events[idx_ev]
                idx_ev += 2
            else:
                idx_ev += 1
        
        # Classificação (não mais deleção) de eventos duplicados/ruído de
        # gravação — regras R1-R4. A lógica de detecção foi extraída byte a
        # byte para _classify_raw_events, que agora TAGUEIA cada evento que
        # antes seria descartado por `continue`, em vez de removê-lo da
        # lista. Nenhum evento desaparece de `events`/`raw_data["events"]`.
        events = self._classify_raw_events(events)
        raw_data["events"] = events

        # TEMPORARIO (T1): filtro no call-site. gravacao.json (salvo mais
        # abaixo a partir de raw_data["events"]) passa a ser o superset
        # completo e tagueado. O restante do fluxo interno de sanitize()
        # (refinamento semântico, plano de execução, relatorio.md) continua
        # operando só sobre os eventos MANTIDOS — exatamente como antes desta
        # tarefa — via esta view filtrada. T2 move essa filtragem para
        # dentro de _write_execution_plan.
        kept_events = [e for e in events if e.get("sanitizer_class", {}).get("keep", True)]

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

        # Realiza o refinamento semântico cognitivo. TEMPORARIO (T1): filtro
        # no call-site — refine_semantics_with_llm recebe só os eventos
        # MANTIDOS (kept_events), igual ao comportamento de antes desta
        # tarefa. raw_data["events"] continua apontando para o superset
        # completo (tagueado, já setado acima) para a gravação de
        # gravacao.json logo abaixo — os dicts de evento são compartilhados
        # por referência entre `events` e `kept_events`, então um
        # business_description atribuído aqui já fica visível no superset.
        refine_input = dict(raw_data)
        refine_input["events"] = kept_events
        dict_data, refine_input = self.refine_semantics_with_llm(dict_data, refine_input, business_desc, expected_outcome)
        kept_events = refine_input.get("events", [])

        # Salva o arquivo de gravação e dicionário devidamente sanitizados e traduzidos
        with open(self.telemetry_file, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=4, ensure_ascii=False)

        with open(self.dict_file, "w", encoding="utf-8") as f:
            json.dump(dict_data, f, indent=4, ensure_ascii=False)

        # Normalização do dataset_inicial.json existente (carregado ANTES do
        # plano de execução porque _write_execution_plan precisa de
        # dataset_rows para sanitizar has_text com tokens dinâmicos — ver
        # Padrão Q logo abaixo)
        dataset_rows = []
        dataset_path = os.path.join(self.telemetry_dir, "dataset_inicial.json")
        if os.path.exists(dataset_path):
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    ds_data = json.load(f)

                if isinstance(ds_data, list):
                    dataset_rows = ds_data
                    ds_changed = False
                    for row in ds_data:
                        for k, v in row.items():
                            if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                                parts = v.split("-")
                                row[k] = f"{parts[2]}/{parts[1]}/{parts[0]}"
                                ds_changed = True
                    if ds_changed:
                        with open(dataset_path, "w", encoding="utf-8") as f:
                            json.dump(ds_data, f, indent=4, ensure_ascii=False)
                        print("[AEGIS SANITIZER] dataset_inicial.json normalizado com datas em formato DD/MM/YYYY.")
            except Exception as e:
                print(f"[WARNING] Falha ao normalizar dataset_inicial.json: {e}")

        # Gera o plano de execução a partir do superset completo de eventos
        # classificados por _classify_raw_events (T1). A partir de T2,
        # _write_execution_plan filtra internamente por
        # sanitizer_class.keep e produz os dois espaços de id do schema v2
        # (st_NNN emitível / sup_NNN suprimido) — ver Seção 8/T2 de
        # .specs/plano-sanitizer-alta-fidelidade.md. Os outros dois
        # consumidores temporários (refine_semantics_with_llm, acima, e o
        # loop do relatorio.md, abaixo) continuam recebendo kept_events —
        # fora de escopo de T2, ver comentários "TEMPORARIO (T1)" ali.
        self._write_execution_plan(events, dataset_rows)

        # Normalização de arquivos CSV correspondentes se existirem
        for csv_name in ["template.csv", "dados_entrada.csv"]:
            csv_path = os.path.join(self.telemetry_dir, csv_name)
            if os.path.exists(csv_path):
                try:
                    import csv
                    with open(csv_path, "r", encoding="utf-8", newline="") as f:
                        reader = csv.reader(f)
                        csv_rows = list(reader)
                    
                    if csv_rows:
                        csv_changed = False
                        for r_idx in range(1, len(csv_rows)):
                            for c_idx in range(len(csv_rows[r_idx])):
                                cell_val = csv_rows[r_idx][c_idx]
                                if isinstance(cell_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", cell_val):
                                    parts = cell_val.split("-")
                                    csv_rows[r_idx][c_idx] = f"{parts[2]}/{parts[1]}/{parts[0]}"
                                    csv_changed = True
                        if csv_changed:
                            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                                writer = csv.writer(f)
                                writer.writerows(csv_rows)
                            print(f"[AEGIS SANITIZER] {csv_name} normalizado com datas em formato DD/MM/YYYY.")
                except Exception as e:
                    print(f"[WARNING] Falha ao normalizar {csv_name}: {e}")

        network = raw_data.get("network_payloads", {})
        anti_bot_fields = raw_data.get("anti_bot_fields", [])

        # T5 (.specs/plano-sanitizer-alta-fidelidade.md, Seção 8): o
        # relatorio.md deixa de operar sobre a view filtrada (kept_events) —
        # `events` aqui permanece o superset completo classificado por
        # _classify_raw_events (a mesma lista já apontada por `raw_data
        # ["events"]`, com qualquer business_description de
        # refine_semantics_with_llm já aplicado nos dicts, que são
        # compartilhados por referência com kept_events). Eventos suprimidos
        # (sanitizer_class.keep == False) passam a ser exibidos com badge em
        # vez de omitidos — ver loop de "Fluxo de Passos e Bifurcações por
        # Cenário" abaixo.

        # T5 (extensão nível-step): além da camada de EVENTO bruto
        # (sanitizer_class, regras R1-R4), o relatório também expõe as
        # supressões de nível de STEP (sup_NNN com execution_hint: "skip",
        # produzidas por _mark_superseded_selects/_mark_phantom_pretrigger_
        # clicks dentro de _write_execution_plan — que NUNCA tagueiam o
        # evento bruto). Lê o plano_execucao.json que _write_execution_plan
        # acabou de gravar mais acima neste mesmo fluxo; tolerante a
        # ausência/malformação — o relatório nunca quebra por causa do plano.
        plan_suppressed_steps = None
        try:
            _plan_path = os.path.join(self.telemetry_dir, "plano_execucao.json")
            with open(_plan_path, "r", encoding="utf-8") as _pf:
                _plan_data = json.load(_pf)
            plan_suppressed_steps = [
                s for s in _plan_data.get("steps", [])
                if isinstance(s, dict) and s.get("execution_hint") == "skip"
            ]
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            plan_suppressed_steps = None

        markdown = []
        markdown.append(f"# 🛡️ Relatório de Telemetria Aegis RPA Suite V2")
        markdown.append(f"\n* **URL Alvo:** {initial_url}")
        emittable_events_count = sum(1 for ev in events if ev.get("sanitizer_class", {}).get("keep", True))
        suppressed_events_count = len(events) - emittable_events_count
        # Duas camadas de contagem, cada uma lida da sua fonte real:
        # captura bruta (eventos com sanitizer_class.keep == False) e plano
        # (steps sup_/skip do plano_execucao.json em disco). Se o plano não
        # pôde ser lido, a parte do plano é omitida — nunca inventa "0".
        header_count = f"{len(events)} ({suppressed_events_count} suprimidas na captura bruta"
        if plan_suppressed_steps is not None:
            header_count += f"; {len(plan_suppressed_steps)} passos suprimidos no plano — ver seção 🔇"
        header_count += ")"
        markdown.append(f"* **Total de Ações Gravadas:** {header_count}")
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
            scenario_emittable_count = sum(1 for ev in scenario_events if ev.get("sanitizer_class", {}).get("keep", True))
            scenario_suppressed_count = len(scenario_events) - scenario_emittable_count
            markdown.append(f"\nTotal de ações neste caminho: {len(scenario_events)} ({scenario_emittable_count} emitíveis, {scenario_suppressed_count} suprimidas)\n")
            markdown.append("| Passo | Tipo | Elemento | Seletor Resiliente Sugerido | Valor / Ação |")
            markdown.append("| :---: | :---: | :---: | :--- | :--- |")

            passo_count = 1
            previous_event = None

            for ev in scenario_events:
                ev_type = ev.get("type", "").upper()

                # T5: evento excluído por _classify_raw_events (R1-R4) — em vez
                # de silenciar, renderiza uma linha informativa com o badge
                # SUPRIMIDO no lugar da coluna Tipo, mantendo seletor e
                # descrição/valor visíveis. Não incrementa passo_count nem
                # atualiza previous_event (não é um passo emitível). Esta
                # checagem PRECISA vir antes do dedup consecutivo abaixo: um
                # clique R1 (raw_duplicate_click) tem, por definição, o MESMO
                # seletor do clique anterior mantido — exatamente a condição
                # que o dedup consecutivo usa para dar `continue` silencioso —
                # então sem checar a supressão primeiro esse evento nunca
                # chegaria a ser exibido, reintroduzindo a invisibilidade que
                # esta tarefa existe para corrigir.
                sanitizer_class = ev.get("sanitizer_class")
                if sanitizer_class and sanitizer_class.get("keep") is False:
                    supp_tag = ev.get("tag", "").lower()
                    if ev.get("is_date"):
                        supp_tag = "input (data)"
                    supp_selector = ev.get("selector", "")
                    supp_parent = ev.get("parent")
                    if supp_parent:
                        supp_p_sel = supp_parent.get("selector", "")
                        supp_p_text = supp_parent.get("has_text")
                        supp_parent_prefix = f"⬆ `{supp_p_sel}[{supp_p_text}]` ➜ " if supp_p_text else f"⬆ `{supp_p_sel}` ➜ "
                    else:
                        supp_parent_prefix = ""
                    supp_val_text = ""

                    if ev_type == "CLICK":
                        supp_x = ev.get("x_percent")
                        supp_y = ev.get("y_percent")
                        supp_coords_str = f" [coords: ({supp_x:.4f}, {supp_y:.4f})]" if (supp_x is not None and supp_y is not None) else ""
                        supp_val_text = f"Clique em: '{ev.get('text', '')}'{supp_coords_str}"
                    elif ev_type == "FILL":
                        if ev.get("is_date"):
                            supp_val_text = f"Preencheu data: '{ev.get('value', '')}'"
                        else:
                            supp_val_text = f"Preencheu com: '{ev.get('value', '')}'"
                    elif ev_type == "FILECHOOSER":
                        supp_val_text = "Abriu o diálogo de seleção de arquivo"

                    if supp_parent_prefix:
                        supp_selector = f"{supp_parent_prefix}`{supp_selector}`"
                    elif " >> " in supp_selector:
                        supp_selector = f"🧬 **Shadow DOM:** `{supp_selector}`"
                    else:
                        supp_selector = f"`{supp_selector}`"

                    supp_desc_negocio = ev.get("business_description") or ev.get("description")
                    if supp_desc_negocio:
                        supp_val_text = f"**{supp_desc_negocio}**<br><span style='font-size:10px; color:var(--text-muted);'>{supp_val_text}</span>"

                    supp_badge = f"🔇 SUPRIMIDO ({sanitizer_class.get('reason', '')})"
                    markdown.append(f"| `-` | {supp_badge} | `{supp_tag}` | {supp_selector} | {supp_val_text} |")
                    continue

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
                                    # Parent context (chained locator)
                                    s_parent = sev.get("parent")
                                    if s_parent:
                                        sp_sel = s_parent.get("selector", "")
                                        sp_text = s_parent.get("has_text")
                                        s_parent_prefix = f"⬆ `{sp_sel}[{sp_text}]` ➜ " if sp_text else f"⬆ `{sp_sel}` ➜ "
                                    else:
                                        s_parent_prefix = ""
                                    s_val = ""
                                    if sev_type == "CLICK":
                                        sx = sev.get("x_percent")
                                        sy = sev.get("y_percent")
                                        scoords = f" [coords: ({sx:.4f}, {sy:.4f})]" if (sx is not None and sy is not None) else ""
                                        s_val = f"Clique em: '{sev.get('text', '')}'{scoords}"
                                    elif sev_type == "FILL":
                                        s_val = f"Preencheu com: '{sev.get('value', '')}'"
                                        
                                    if s_parent_prefix:
                                        s_sel = f"{s_parent_prefix}`{s_sel}`"
                                    elif " >> " in s_sel:
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
                    # Parent context (chained locator)
                    p_ev = ev.get("parent")
                    if p_ev:
                        p_sel = p_ev.get("selector", "")
                        p_text = p_ev.get("has_text")
                        parent_prefix = f"⬆ `{p_sel}[{p_text}]` ➜ " if p_text else f"⬆ `{p_sel}` ➜ "
                    else:
                        parent_prefix = ""
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

                    if parent_prefix:
                        selector = f"{parent_prefix}`{selector}`"
                    elif " >> " in selector:
                        selector = f"🧬 **Shadow DOM:** `{selector}`"
                    else:
                        selector = f"`{selector}`"

                    desc_negocio = ev.get("business_description") or ev.get("description")
                    if desc_negocio:
                        val_text = f"**{desc_negocio}**<br><span style='font-size:10px; color:var(--text-muted);'>{val_text}</span>"

                    markdown.append(f"| {passo_count} | `{ev_type}` | `{tag}` | {selector} | {val_text} |")
                    passo_count += 1
                    previous_event = ev

        # 2b. Passos suprimidos no PLANO (nível-step: sup_NNN / skip) — camada
        # distinta da supressão nível-evento (badge 🔇 na tabela de fluxo
        # acima). Dados lidos do plano_execucao.json em disco (ver leitura
        # tolerante antes do cabeçalho). Seção omitida se o plano não pôde
        # ser lido; presente (com aviso de vazio) se lido mas sem sup_.
        if plan_suppressed_steps is not None:
            markdown.append("\n" + "-" * 60)
            markdown.append("\n## 🔇 Passos Suprimidos no Plano de Execução")
            if plan_suppressed_steps:
                markdown.append("\nSteps classificados como `skip` (`sup_NNN`) pelo Sanitizer ao gerar o `plano_execucao.json` — não são emitidos no bot por default, mas permanecem no plano como contexto de fidelidade (o Code Generator pode reintroduzi-los pelo `step_id` se uma correção exigir):\n")
                markdown.append("| Step ID | Status (step_role) | Tipo | Seletor / Alvo | Motivo da Supressão |")
                markdown.append("| :---: | :---: | :---: | :--- | :--- |")
                for sup in plan_suppressed_steps:
                    sup_id = sup.get("step_id", "?")
                    sup_role = sup.get("step_role", "")
                    sup_type = sup.get("type", "")
                    if sup_type == "select":
                        sup_target = f"`{sup.get('dropdown_label', '')}` → `{sup.get('option_text', '')}`"
                    else:
                        sup_target = f"`{sup.get('selector', '')}`"
                    sup_reason = sup.get("suppression_reason", "")
                    markdown.append(f"| `{sup_id}` | 🔇 SUPRIMIDO (`{sup_role}`) | `{sup_type}` | {sup_target} | {sup_reason} |")
            else:
                markdown.append("\nNenhum step suprimido no plano de execução desta gravação.")

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

        # 6. Auditoria de valor dinâmico hardcoded em has_text (Padrão Q)
        # Um `has_text` gravado pode misturar um identificador gerado pelo
        # próprio sistema-alvo em runtime (protocolo, número de proposta/pedido)
        # com valores estáveis do dataset (nome, CPF). Esse identificador nunca
        # se repete entre execuções, fazendo o parent_locator nunca resolver
        # depois da gravação — bug confirmado em produção (st_063 do
        # portal_segura, reportado inicialmente como falso positivo de
        # self-healing). Detecta tokens em formato de código (LETRAS-DIGITOS)
        # dentro de has_text que não aparecem em nenhum valor do dataset.
        dynamic_token_re = re.compile(r"\b[A-Za-zÀ-ÿ]{2,8}-\d{3,}\b")
        dataset_values_str = " | ".join(
            str(v) for row in dataset_rows for v in row.values() if isinstance(v, (str, int, float))
        ).lower()
        suspicious_has_text = []
        seen_suspicious = set()
        for ev in events:
            parent = ev.get("parent")
            if not parent:
                continue
            ht = parent.get("has_text")
            if not ht or not isinstance(ht, str):
                continue
            for token in dynamic_token_re.findall(ht):
                if token.lower() not in dataset_values_str and token not in seen_suspicious:
                    seen_suspicious.add(token)
                    suspicious_has_text.append((token, ht, parent.get("selector", "")))

        if suspicious_has_text:
            markdown.append("\n" + "-" * 60)
            markdown.append("\n## 🚨 Alerta CRÍTICO: Possível Valor Dinâmico Hardcoded em `has_text`")
            markdown.append("Os seguintes filtros `has_text` (Padrão Q — Locator Encadeado) contêm um token em formato de código/identificador que **não aparece em nenhum campo do `dataset_inicial.json`**. Isso indica um valor gerado pelo próprio sistema-alvo em runtime (protocolo, número de proposta, pedido), que muda a cada execução e nunca vai bater depois da gravação. **NÃO copie o `has_text` gravado verbatim** — reconstrua-o usando somente os fragmentos estáveis vindos do dataset (ex.: `row.get('nome_cliente')`, `row.get('cpf_cliente')`).")
            for token, ht, sel in suspicious_has_text:
                markdown.append(f"* Token suspeito **`{token}`** dentro de `has_text=\"{ht}\"` (seletor pai: `{sel}`).")
            print(f"[AEGIS SANITIZER] [WARNING] {len(suspicious_has_text)} token(s) suspeito(s) de valor dinâmico hardcoded em has_text. Ver relatorio.md.")

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

    def _classify_raw_events(self, events: list) -> list:
        """
        Classifica eventos brutos segundo as regras R1-R4 (duplicação/ruído
        de gravação) SEM remover nenhum evento da lista — extraído byte a
        byte do bloco de deleção que existia em `sanitize()` antes desta
        tarefa (T1 de .specs/plano-sanitizer-alta-fidelidade.md, Seção 2/D1
        e 8). Cada evento que antes seria descartado por `continue` agora é
        MANTIDO na lista e ganha a tag:

            ev["sanitizer_class"] = {"role": <...>, "keep": False, "reason": <...>}

        Catálogo de `role` (nomes exatos usados também como `step_role` dos
        steps `sup_` numa tarefa seguinte, T2): "raw_duplicate_click" (R1),
        "overlay_noise" (R2), "stale_panel_click" (R3), "redundant_refill"
        (R4). Eventos que sobrevivem às 4 regras não são tocados (sem a
        chave `sanitizer_class`) — quem quiser a view "limpa" filtra por
        `e.get("sanitizer_class", {}).get("keep", True)`.

        NÃO estampa nem recalcula `original_index`: esse campo é estampado
        em `sanitize()` ANTES do Padrão P (ordem física original da
        gravação); esta função roda DEPOIS do Padrão P (mesma posição do
        bloco R1-R4 original) e só herda o que já estiver presente em cada
        evento, preservando-o intocado.

        Retorna uma lista NOVA com o mesmo comprimento e a mesma ordem física
        de `events` (nunca reordena, nunca remove, nunca duplica).
        """
        classified_events = []
        # Espelha o `cleaned_events`/`seen_fills`/`last_fill_selector` do
        # bloco original: representam o estado dos eventos MANTIDOS até
        # agora, na mesma ordem em que as regras R1-R4 os enxergavam quando
        # descartavam fisicamente via `continue`. R1 (adjacência) e R4
        # (recência por chave) precisam desse estado para decidir; R2 e R3
        # dependem só do evento atual (e, para R3, de `last_fill_selector`).
        cleaned_events = []
        seen_fills = {}
        last_fill_selector = None

        for ev in events:
            ev_type = ev.get("type", "").lower()
            selector = ev.get("selector", "")
            scenario = ev.get("scenario", "default")

            sanitizer_class = None

            # 1. Cliques consecutivos no mesmo seletor
            if cleaned_events:
                last = cleaned_events[-1]
                if ev_type == "click" and last.get("type") == "click" and selector == last.get("selector"):
                    sanitizer_class = {
                        "role": "raw_duplicate_click",
                        "keep": False,
                        "reason": "clique consecutivo no mesmo seletor do clique anterior mantido",
                    }

            # 2. Cliques em overlays genéricos de CDK ou placeholder "Nenhum
            # resultado". Não pega clique em opção específica dentro do
            # overlay (ex.: "#cdk-overlay-container #mat-select-panel-x
            # [role='option']:has-text('...')") — isso é uma seleção real,
            # não ruído de overlay/backdrop vazio.
            if sanitizer_class is None:
                is_generic_overlay_click = (
                    ("cdk-overlay-container" in selector and "[role='option']" not in selector and "has-text(" not in selector)
                    or "backdrop" in selector
                    or "Nenhum resultado" in selector
                    or "Nenhum resultado" in ev.get("text", "")
                )
                if ev_type == "click" and is_generic_overlay_click:
                    sanitizer_class = {
                        "role": "overlay_noise",
                        "keep": False,
                        "reason": "clique em overlay genérico de CDK/backdrop ou placeholder 'Nenhum resultado'",
                    }

            # 3. Cliques em autocomplete de painel órfão (sem nenhum
            # preenchimento prévio no fluxo) — sinal de painel stale/leftover.
            # Não usa matching de idioma/nome de campo (selectors gravados
            # são no idioma do app-alvo e a ordem de fills nem sempre é
            # 1-para-1 com a ordem dos cliques de seleção).
            if sanitizer_class is None:
                if ev_type == "click" and "mat-autocomplete-panel-" in selector and not last_fill_selector:
                    sanitizer_class = {
                        "role": "stale_panel_click",
                        "keep": False,
                        "reason": "clique em painel autocomplete sem nenhum preenchimento prévio no fluxo (painel stale/leftover)",
                    }

            # 4. Preenchimentos duplicados (mesmo seletor e mesmo valor no
            # mesmo cenário). Não é consecutivo: `seen_fills` cobre a
            # gravação inteira (por cenário+seletor).
            if sanitizer_class is None and ev_type in ["fill", "change"]:
                key = (scenario, selector)
                val = ev.get("value", "")
                if key in seen_fills and seen_fills[key] == val:
                    sanitizer_class = {
                        "role": "redundant_refill",
                        "keep": False,
                        "reason": "preenchimento duplicado: mesmo seletor e mesmo valor já vistos neste cenário",
                    }
                else:
                    seen_fills[key] = val
                    last_fill_selector = selector

            if sanitizer_class is not None:
                ev["sanitizer_class"] = sanitizer_class
            else:
                cleaned_events.append(ev)

            classified_events.append(ev)

        return classified_events

    def _update_datasets_with_new_keys(self, mapping: dict):
        """Atualiza as chaves/colunas dos datasets com os novos nomes semânticos."""
        if not mapping:
            return
            
        # 1. Atualiza dataset_inicial.json
        dataset_path = os.path.join(self.telemetry_dir, "dataset_inicial.json")
        if os.path.exists(dataset_path):
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if isinstance(data, list):
                    new_data = []
                    for row in data:
                        new_row = {}
                        for k, v in row.items():
                            new_k = mapping.get(k, k)
                            new_row[new_k] = v
                        new_data.append(new_row)
                    
                    with open(dataset_path, "w", encoding="utf-8") as f:
                        json.dump(new_data, f, indent=4, ensure_ascii=False)
                    print(f"[AEGIS SANITIZER] dataset_inicial.json atualizado com as novas chaves semânticas: {mapping}")
            except Exception as e:
                print(f"[WARNING] Falha ao atualizar dataset_inicial.json: {e}")
                
        # 2. Atualiza arquivos CSV (template.csv, dados_entrada.csv)
        for csv_name in ["template.csv", "dados_entrada.csv"]:
            csv_path = os.path.join(self.telemetry_dir, csv_name)
            if os.path.exists(csv_path):
                try:
                    import csv
                    with open(csv_path, "r", encoding="utf-8", newline="") as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                        
                    if rows:
                        headers = rows[0]
                        new_headers = []
                        for h in headers:
                            new_headers.append(mapping.get(h, h))
                        rows[0] = new_headers
                        
                        with open(csv_path, "w", encoding="utf-8", newline="") as f:
                            writer = csv.writer(f)
                            writer.writerows(rows)
                        print(f"[AEGIS SANITIZER] {csv_name} atualizado com as novas colunas semânticas.")
                except Exception as e:
                    print(f"[WARNING] Falha ao atualizar {csv_name}: {e}")

    def _lookup_dropdown_label_by_value(self, option_text: str, fallback_description: str, opener_parent_has_text: str = None) -> str:
        """
        `select_option_resilient` (runner.py:401) monta seus seletores de
        trigger a partir de `dropdown_label` via `label:has-text('{label}')` —
        precisa do texto REAL do <label>, não de uma frase de negócio. Quando o
        selector do abridor não tem has-text (comum em dropdowns dentro de
        grids/tabelas de cobertura, onde o recorder só capturou um "div"
        genérico), busca no dicionario.json um campo cujo `observed_value`
        bata exatamente com o valor final selecionado (`option_text`) — esse
        campo, se existir, tem o texto real do label embutido no seu próprio
        `selector` (has-text). Único e confiável o bastante porque cada campo
        do formulário tem um valor observado distinto na mesma gravação.

        Se não houver match único no dicionário, `opener_parent_has_text` (o
        `parent.has_text` do próprio abridor, quando existir) é a próxima
        melhor opção: é o texto REAL exibido no trigger no momento do clique
        de gravação (o valor atualmente selecionado), bem mais confiável que
        a `description` (frase de negócio verbosa que nunca bate com texto
        real da página e força o runner a cair sempre no fallback de
        coordenadas — causa raiz confirmada da falha do st_049/vidros no
        cenário 001).
        """
        try:
            with open(self.dict_file, "r", encoding="utf-8") as f:
                dict_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            dict_data = None
        if dict_data:
            matches = []
            for field_info in dict_data.get("fields", {}).values():
                if field_info.get("observed_value") == option_text:
                    m = re.search(r"has-text\((['\"])(.*?)\1\)", field_info.get("selector", ""))
                    if m:
                        matches.append(m.group(2))
            if len(matches) == 1:
                return matches[0]
        if opener_parent_has_text:
            return opener_parent_has_text
        return fallback_description

    @staticmethod
    def _source_indices(step: dict) -> list:
        """
        Retorna TODOS os índices de eventos brutos (`original_index`) que um
        step "representa", nos 3 formatos possíveis conforme como o step foi
        produzido (ver .specs/plano-sanitizer-alta-fidelidade.md, Seção 8/T2,
        definição obrigatória de `_source_indices`):

        - step simples (saído direto de `_classify_raw_events`/construção de
          step): só `original_index` próprio.
        - sobrevivente de `_merge_consecutive_clicks`: `original_index`
          próprio + um `original_index` por evento absorvido em `merged_from`.
        - `select` composto de `_reorder_dropdown_pairs`: só `source_events`
          (lista), sem `original_index` no nível raiz.

        `position_anchor(step) = min(_source_indices(step))`. NUNCA leia só
        `step.get("original_index")` isolado para esse cálculo — um step que
        absorveu um clique anterior via merge tem, tipicamente, o
        `original_index` do evento MAIS TARDIO do grupo no campo raiz (porque
        `choose()` normalmente elege o clique mais recente como conteúdo);
        ignorar `merged_from` dá um anchor ATRASADO. Ver
        `.specs/golden/synthetic_r1_merge_case/README.md` para o caso
        concreto que este método existe para acertar.
        """
        idxs = []
        if "original_index" in step:
            idxs.append(step["original_index"])
        idxs += [m["original_index"] for m in step.get("merged_from", [])]
        idxs += step.get("source_events", [])
        return idxs

    # Nota: não propagar o guard de texts_differ de same_widget() aqui — ver docstring de _merge_consecutive_clicks.
    def _reorder_dropdown_pairs(self, steps: list) -> list:
        """
        Corrige um padrão de gravação que quebra em produção: abrir um dropdown
        (mat-select/CDK overlay), executar uma ação em outro campo, e só depois
        selecionar a opção do dropdown. No browser real (sem as pausas humanas
        da gravação original), clicar em outro campo fecha o overlay antes da
        opção ser selecionada, quebrando o passo com "elemento não visível".

        Detecta pares abertura->opção e os COLAPSA num único step do tipo
        "select" (abridor + opção viram 1 step_id só, não 2) — isso é necessário
        porque `select_option_resilient` no runner só aceita 1 step_id, e se o
        par continuasse como 2 steps distintos o validador de contagem
        (validate_bot_against_plan) entraria em conflito com o validador de
        padrão de resiliência. Passos intercalados entre abridor e opção são
        preservados e movidos para depois do step colapsado.

        Schema v2 (.specs/plano-sanitizer-alta-fidelidade.md Seção 3/4): o
        step colapsado ganha `step_role: "composite_select"` (default
        `primary` de steps emitíveis simples fica implícito pela ausência
        deste campo) e `source_events` (união de `_source_indices` do abridor
        e da opção — necessário para `position_anchor` no merge-insert de
        `_write_execution_plan`, já que um step "select" nunca tem
        `original_index` no nível raiz). Nota deliberada: os steps "between"
        preservados/movidos não ganham um campo `reordered_from` nesta tarefa
        — a Seção 4 do plano menciona esse campo, mas ele não está na lista
        "Implemente também" do backlog de T2 nem é coberto por nenhum DoD; ao
        ficar de fora, nada quebra (é aditivo), mas fica registrado aqui para
        não parecer descuido.
        """
        option_idx = [i for i, s in enumerate(steps) if s["type"] == "click" and "[role='option']" in s["selector"]]
        if not option_idx:
            return steps

        result = list(steps)
        # Processa do fim pro começo: colapsar um par em índice alto não afeta
        # os índices (ainda não processados) de pares em posições mais baixas.
        for opt_i in sorted(option_idx, reverse=True):
            opener_i = None
            for j in range(opt_i - 1, -1, -1):
                if result[j]["type"] == "click" and "[role='option']" not in result[j]["selector"]:
                    opener_i = j
                    break
                if "[role='option']" in result[j]["selector"]:
                    break
            if opener_i is None:
                continue

            opener = result[opener_i]
            option = result[opt_i]
            # dropdown_label/option_text viram argumentos literais de
            # select_option_resilient (runner.py:401), que monta seletores tipo
            # f"label:has-text('{dropdown_label}') ~ div" e
            # f"[role='option']:has-text('{option_text}')". A `description` do
            # step é uma frase de negócio verbosa (ex.: "Selecionar a opção
            # 'Isenção de ICMS'.") e NUNCA bate com o texto real do elemento —
            # isso força o runner a cair no fallback de coordenadas sempre,
            # podendo clicar na opção/campo errado silenciosamente. O texto real
            # já está gravado dentro do próprio selector (has-text('...')),
            # então extrai de lá; description só como último recurso.
            match_opener = re.search(r"has-text\((['\"])(.*?)\1\)", opener["selector"])
            match_option = re.search(r"has-text\((['\"])(.*?)\1\)", option["selector"])
            option_text = match_option.group(2) if match_option else option["description"]
            # Quando o abridor não tem has-text (ex.: selector genérico "div",
            # comum em dropdowns dentro de grids/tabelas de cobertura), a
            # `description` é uma frase de negócio que NUNCA bate com um
            # `<label>` real — tenta antes achar o campo real no
            # dicionario.json pelo valor final selecionado (observed_value),
            # que é único o bastante pra identificar o campo certo, e reusa o
            # texto do label real gravado ali (selector com has-text).
            dropdown_label = match_opener.group(2) if match_opener else self._lookup_dropdown_label_by_value(
                option_text, opener["description"], (opener.get("parent") or {}).get("has_text")
            )
            merged = {
                "type": "select",
                "step_role": "composite_select",
                "dropdown_label": dropdown_label,
                "option_text": option_text,
                "trigger_selector": opener["selector"],
                "option_selector": option["selector"],
                "description": f"Selecionar '{option['description']}' em '{opener['description']}'",
                "source_events": self._source_indices(opener) + self._source_indices(option),
            }
            if "scenario" in opener:
                merged["scenario"] = opener["scenario"]
            if "parent" in opener:
                merged["parent"] = opener["parent"]
            if "coords" in opener:
                merged["coords_trigger"] = opener["coords"]
            if "coords" in option:
                merged["coords_option"] = option["coords"]

            between = result[opener_i + 1:opt_i]
            result = result[:opener_i] + [merged] + between + result[opt_i + 1:]

        return result

    # Nota: não propagar o guard de texts_differ de same_widget() aqui — ver docstring de _merge_consecutive_clicks.
    def _mark_superseded_selects(self, steps: list) -> tuple:
        """
        `_reorder_dropdown_pairs` colapsa cada par abridor+opção num step
        "select", mas quando o usuário errou a opção durante a gravação e
        reabriu o MESMO dropdown pra corrigir, sobram 2 steps "select"
        consecutivos pro MESMO widget (ex.: Combustível -> Álcool,
        Combustível -> Diesel). Replayar os dois em sequência contra a app
        viva confunde o widget Material (observado: campo fica vazio e
        trava o botão Avançar, cascata que acionava self-healing).

        Não dá pra usar `dropdown_label` puro pra identificar "mesmo
        widget": em selects de grid/tabela (cobertura), o fallback de
        label é uma frase genérica ("Clicar na opção '150.000,00'.") que
        se repete em VÁRIAS linhas/campos diferentes da mesma tabela, então
        comparar só o texto colapsaria campos distintos por engano. Sinal
        confiável e verificado nos dados reais: o `parent.has_text` de um
        select captura o estado ATUAL do widget no momento do clique — se o
        segundo select tem, no seu `parent.has_text`, o `option_text` que o
        PRIMEIRO acabou de escolher, é prova de que o clique seguinte caiu
        em cima do mesmo widget já alterado (não só um texto parecido).

        Renomeada de `_drop_redundant_select_corrections` (schema v2): a
        DETECÇÃO é idêntica byte a byte, só o EFEITO muda — o select
        superado não desaparece mais, vira item retornado no 2º elemento da
        tupla (`suppressed`), destinado a virar um step `sup_NNN` com
        `step_role: "superseded_correction"` em `_write_execution_plan`.
        Cadeias de 3+ correções no mesmo widget (A corrigido por B corrigido
        por C) propagam a lista de superados via a chave interna
        `_superseded_chain` no sobrevivente corrente, para que TODOS os elos
        (A e B) acabem com `superseded_by` apontando pro vencedor FINAL (C),
        nunca por um elo intermediário que também seria suprimido.

        Retorna (steps_sobreviventes, suppressed_items) — `suppressed_items`
        são os dicts de step ORIGINAIS dos selects superados (mesmo shape de
        `_reorder_dropdown_pairs`), sem numeração/step_id ainda.
        """
        result = []
        for s in steps:
            if result and s["type"] == "select" and result[-1]["type"] == "select":
                prev = result[-1]
                prev_parent = prev.get("parent") or {}
                cur_parent = s.get("parent") or {}
                prev_text = prev_parent.get("has_text")
                cur_text = cur_parent.get("has_text")
                prev_option = prev.get("option_text")
                if prev_text and cur_text and prev_option and prev_option in cur_text:
                    s["_superseded_chain"] = prev.pop("_superseded_chain", []) + [prev]
                    result[-1] = s
                    continue
            result.append(s)

        suppressed = []
        for s in result:
            chain = s.pop("_superseded_chain", None)
            if chain:
                for prev in chain:
                    prev["step_role"] = "superseded_correction"
                    prev["suppression_reason"] = (
                        f"Selecionou '{prev.get('option_text')}' em '{prev.get('dropdown_label')}' "
                        f"e corrigiu para '{s.get('option_text')}' no mesmo campo, ainda durante a gravação."
                    )
                    prev["_superseded_by_step"] = s
                    suppressed.append(prev)
        return result, suppressed

    # Nota: não propagar o guard de texts_differ de same_widget() aqui — ver docstring de _merge_consecutive_clicks.
    def _mark_phantom_pretrigger_clicks(self, steps: list) -> tuple:
        """
        Mesmo após `_merge_consecutive_clicks`, sobra um padrão de clique
        fantasma: o recorder às vezes gera 2 eventos de clique DIFERENTES
        (selector e parent distintos, geralmente porque o overlay ainda não
        tinha estabilizado no 1º clique) para o MESMO ponto físico da tela —
        um deles vira o `coords_trigger` embutido no step "select" colapsado
        por `_reorder_dropdown_pairs`, o outro sobra como um step "click"
        solto logo antes do "select". Diferente de um clique legítimo que
        precede um dropdown (ex.: marcar um checkbox que revela o campo), que
        aponta pra coordenadas bem distantes do trigger do dropdown, esse
        clique fantasma cai a poucos % de distância do `coords_trigger` do
        próprio select — sinal confiável de que é o mesmo clique físico
        contado 2x.

        Renomeada de `_drop_redundant_pretrigger_clicks` (schema v2): a
        DETECÇÃO (distância < 0.05 do `coords_trigger`) é idêntica; o clique
        fantasma não é mais descartado, é retornado no 2º elemento da tupla
        (`suppressed`), destinado a virar um step `sup_NNN` com
        `step_role: "phantom_click"` — sem `superseded_by` (é o mesmo gesto
        físico do `coords_trigger` do select vizinho, não uma correção de
        negócio; a rastreabilidade já está no próprio `coords_trigger`).

        Retorna (steps_sobreviventes, suppressed_items).
        """
        THRESHOLD = 0.05
        result = []
        suppressed = []
        for i, s in enumerate(steps):
            if (s["type"] == "select" and result and result[-1]["type"] == "click"):
                prev_coords = result[-1].get("coords")
                trigger_coords = s.get("coords_trigger")
                if prev_coords and trigger_coords:
                    dist = ((prev_coords[0] - trigger_coords[0]) ** 2 + (prev_coords[1] - trigger_coords[1]) ** 2) ** 0.5
                    if dist < THRESHOLD:
                        phantom = result.pop()
                        phantom["step_role"] = "phantom_click"
                        phantom["suppression_reason"] = (
                            "Clique registrado a poucos % de distância do coords_trigger do select "
                            "seguinte — mesmo clique físico capturado 2x pelo recorder antes do overlay estabilizar."
                        )
                        suppressed.append(phantom)
            result.append(s)
        return result, suppressed

    def _merge_consecutive_clicks(self, steps: list) -> list:
        """
        O recorder às vezes captura o mesmo elemento clicado 2x seguidas (ex.:
        overlay do CDK ainda fechado no primeiro clique, ou o usuário clicou de
        novo durante a gravação por lentidão da UI). Replay rápido em produção
        quebra: o clique duplicado extra pode deixar o overlay num estado
        inconsistente antes do clique seguinte (ex.: trigger de dropdown que
        já foi processado no passo anterior). Também ocorre quando label/span/
        input do mesmo widget (ex.: checkbox) disparam cliques separados —
        nesse caso o selector muda a cada clique, mas o `parent` gravado é
        idêntico. Mantém apenas o último clique (mais próximo do elemento
        real) de cada sequência consecutiva que aponta pro mesmo widget.

        Risco teórico não resolvido: este guard só cobre cliques
        CONSECUTIVOS. Dois widgets físicos distintos com selector genérico
        idêntico e texto diferente que colidam NÃO-consecutivamente em
        `_reorder_dropdown_pairs`, `_mark_superseded_selects` ou
        `_mark_phantom_pretrigger_clicks` não seriam pegos por esse guard.
        Avaliado e descartado propagar o mesmo guard pra essas 3 funções:
        `_reorder_dropdown_pairs` casa por regex no próprio selector, não
        por colisão genérica; `_mark_superseded_selects` opera
        sobre steps "select" já mesclados, sem o campo `text` de clique
        disponível; e `_mark_phantom_pretrigger_clicks` depende
        justamente de bubbling (div -> span -> input) ter textos
        DIFERENTES entre si para reconhecer o mesmo clique físico — um
        guard de "texto diferente = widget diferente" ali quebraria a
        própria deduplicação que a função existe pra fazer. Sem caso real
        observado ainda; se aparecer, tratar cada função individualmente,
        não replicar este guard cegamente.

        Renomeada de `_dedup_consecutive_clicks` (schema v2): a detecção
        (`same_widget`/`choose`) é idêntica byte a byte. O que muda é o
        destino do clique perdedor — em vez de simplesmente desaparecer ao
        ser sobrescrito por `result[-1] = choose(...)`, ele vira uma entrada
        em `merged_from` do step sobrevivente (`original_index`, `selector`,
        `reason`), com a cadeia de absorções de rodadas anteriores (tanto do
        vencedor quanto do perdedor, se algum já tiver histórico de
        `merged_from` de uma fusão anterior nesta mesma chamada) preservada e
        concatenada — nunca perdida, nunca duplicada.
        """
        def same_widget(a: dict, b: dict) -> bool:
            # Selector genérico (ex.: "label" nu, sem id/data-testid) casa
            # com QUALQUER elemento da mesma tag — 2 checkboxes/labels
            # distintos na mesma tela colapsariam num só mesmo sendo
            # elementos físicos diferentes. Quando ambos os eventos têm
            # `text` capturado e ele difere, isso prova que são 2 widgets
            # diferentes, mesmo com selector/parent idênticos — barra os
            # 4 critérios abaixo nesse caso. Eventos sem texto (ex.: clique
            # no <input> real por trás de um <label>, que não carrega texto
            # próprio) continuam sem essa restrição extra.
            text_a, text_b = a.get("text"), b.get("text")
            texts_differ = bool(text_a) and bool(text_b) and text_a != text_b

            if a["selector"] == b["selector"] and not texts_differ:
                return True
            pa, pb = a.get("parent"), b.get("parent")
            if (pa and pb and pa.get("selector")
                    and pa.get("selector") == pb.get("selector") and pa.get("has_text") == pb.get("has_text")
                    and not texts_differ):
                return True
            # Um clique já achatado (selector = id do widget, sem parent —
            # ex.: idioma <label><input>) é o mesmo widget de um clique
            # ainda encadeado cujo parent aponta pro mesmo id.
            if pa and pa.get("selector") == b["selector"] and not texts_differ:
                return True
            if pb and pb.get("selector") == a["selector"] and not texts_differ:
                return True
            # Último recurso: eventos de bubbling do mesmo clique físico
            # acertam elementos totalmente diferentes na hierarquia (ex.:
            # div container genérico -> span do checkbox -> input real),
            # sem selector/parent em comum algum. Coordenadas praticamente
            # idênticas (< 2% do viewport) confirmam que é o mesmo ponto
            # de clique gravado 2x+, não 2 cliques distintos — validado
            # contra o menor gap real entre 2 widgets diferentes no plano
            # (~4.6%), então 2% não corre risco de fundir coisas distintas.
            ca, cb = a.get("coords"), b.get("coords")
            if ca and cb:
                dist = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
                if dist < 0.02 and not texts_differ:
                    return True
            return False

        # Selectors puramente genéricos (tag sem id/classe) tendem a mirar o
        # <input> nativo por trás de um mat-checkbox/mat-radio, que a Material
        # esconde via CSS (opacity/visibility) — igual ao caso do PCD, isso
        # trava o scroll_into_view_if_needed do Playwright. Entre 2 cliques do
        # mesmo widget, prefere o selector mais específico (ex.: o span visual
        # clicável) em vez de sempre ficar com o último da gravação.
        GENERIC_TAG_SELECTORS = {"input", "span", "div"}

        def choose(kept: dict, candidate: dict) -> dict:
            if candidate["selector"] in GENERIC_TAG_SELECTORS and kept["selector"] not in GENERIC_TAG_SELECTORS:
                return kept
            return candidate

        result = []
        for s in steps:
            if (result and s["type"] == "click" and result[-1]["type"] == "click"
                    and same_widget(s, result[-1])):
                kept, candidate = result[-1], s
                winner = choose(kept, candidate)
                loser = candidate if winner is kept else kept
                # Concatena: histórico já acumulado pelo vencedor (rodadas
                # anteriores desta mesma chamada, ex.: 3+ cliques
                # consecutivos no mesmo widget) + o perdedor desta rodada +
                # o histórico que o PERDEDOR já carregava (relevante quando
                # o vencedor muda de lado entre rodadas, ex.: candidate
                # vence a rodada 1, kept — já com merged_from — vence a
                # rodada 2 por cair na exceção de GENERIC_TAG_SELECTORS).
                merged_from = list(winner.get("merged_from", []))
                merged_from.append({
                    "original_index": loser.get("original_index"),
                    "selector": loser.get("selector", ""),
                    "reason": "clique consecutivo no mesmo widget",
                })
                merged_from.extend(loser.get("merged_from", []))
                winner["merged_from"] = merged_from
                result[-1] = winner
                continue
            result.append(s)
        return result

    @staticmethod
    def _serialize_plan_step(step: dict) -> dict:
        """
        Serializa um step interno (sobrevivente da cadeia de merge/reorder,
        ou candidato a `sup_`) para o formato final do plano v2, numa ordem
        de campos estável. `selector` é sempre emitido (default `""`) mesmo
        quando ausente do dict interno — mesmo comportamento do v1 para
        steps "select" (o abridor/opção viram trigger_selector/
        option_selector; `_reorder_dropdown_pairs` nunca seta uma chave
        "selector" própria no step colapsado).
        """
        field_order = (
            "step_id", "execution_hint", "step_role", "suppression_reason",
            "superseded_by", "type", "selector", "selector_original",
            "description", "scenario", "text", "flaky", "weak_selector",
            "fallback_selectors", "parent", "coords", "dropdown_label",
            "option_text", "trigger_selector", "option_selector",
            "coords_trigger", "coords_option", "sanitization_notes",
            "original_index", "merged_from", "source_events",
        )
        out = {}
        for key in field_order:
            if key == "selector":
                out["selector"] = step.get("selector", "")
                continue
            if key in step:
                out[key] = step[key]
        return out

    def _write_execution_plan(self, events: list, dataset_rows: list = None):
        """
        Gera plano_execucao.json v2: TODOS os eventos classificados por
        `_classify_raw_events` (T1) entram no array `steps`, com dois
        espaços de id — `st_NNN` (emitível: `execution_hint` ausente/
        "required", ou "optional") e `sup_NNN` (suprimido:
        `execution_hint: "skip"`). Ver
        `.specs/plano-sanitizer-alta-fidelidade.md` Seção 3 (schema) e
        Seção 8/T2 (algoritmo de composição R1 × merge) para o contrato
        completo — este método é a implementação literal desse algoritmo.

        `events` é o SUPERSET completo (mantidos + excluídos por R1-R4, já
        tagueados por `_classify_raw_events` com `sanitizer_class`) — a
        filtragem por `sanitizer_class.keep` acontece DENTRO deste método
        (antes de T2, o call-site em `sanitize()` filtrava antes de
        chamar). `dataset_rows` mantém o mesmo papel de sempre (Padrão Q).
        """
        plan_path = os.path.join(self.telemetry_dir, "plano_execucao.json")
        allowed_types = {"click", "fill", "filechooser"}

        # Estampagem defensiva de original_index: em uso normal (via
        # sanitize()), todo evento já chega aqui com original_index
        # estampado ANTES do Padrão P (Seção 8, passo 1). Chamadores que
        # invocam _write_execution_plan diretamente com eventos "crus" (ex.:
        # a suíte de testes existente, que nunca passou por sanitize()) não
        # têm essa garantia — sem um fallback aqui, um evento sem
        # original_index produziria um step com _source_indices() vazio, e
        # min() de lista vazia quebraria o merge-insert mais abaixo.
        # setdefault é no-op quando sanitize() já estampou (produção).
        all_events = events
        for _idx, _ev in enumerate(all_events):
            _ev.setdefault("original_index", _idx)

        kept_events = [e for e in all_events if e.get("sanitizer_class", {}).get("keep", True)]
        excluded_events = [e for e in all_events if not e.get("sanitizer_class", {}).get("keep", True)]

        # Preserva a marcação `flaky` de steps EMITÍVEIS já existentes no
        # plano anterior ao regenerar. Casamento por (type, selector) — não
        # por step_id, que é posicional (f"st_{i+1:03d}") e desloca a cada
        # regeração. Restrito a emitíveis (Seção 3: "herança de flaky por
        # (type, selector) passa a casar apenas contra steps emitíveis") —
        # um `sup_` marcado flaky por QA (Seção 7) não deve vazar para um
        # `st_` que só por coincidência compartilhe (type, selector).
        # Protegido contra plano antigo ausente ou malformado: nesse caso,
        # nenhum flaky é herdado, mas a geração do plano novo segue normal.
        old_flaky_keys = set()
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                old_plan = json.load(f)
            old_flaky_keys = {
                (s.get("type"), s.get("selector"))
                for s in old_plan.get("steps", [])
                if s.get("flaky") and s.get("execution_hint", "required") != "skip"
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            old_flaky_keys = set()

        # Sanitização de valor dinâmico hardcoded em has_text (Padrão Q).
        # Um `has_text` gravado pode misturar um identificador gerado pelo
        # próprio sistema-alvo em runtime (protocolo, número de proposta/
        # pedido, ex.: "PRO-80935") com valores estáveis do dataset (nome,
        # CPF). Esse identificador nunca se repete entre execuções, fazendo
        # o parent_locator nunca resolver depois da gravação — bug real
        # confirmado em produção (st_063 do portal_segura). Em vez de só
        # alertar no relatorio.md (checagem antiga, mantida como auditoria
        # complementar mais abaixo em `sanitize()`), remove o token
        # diretamente do has_text usado no plano, antes de chegar no
        # code_generator — corrige na origem, sem depender de correção
        # manual pra cada projeto/campo que tiver esse padrão. Schema v2
        # (D4): o valor operacional continua sanitizado (comportamento
        # idêntico a sempre), mas agora também informa QUAIS tokens
        # saíram, pra popular has_text_original/sanitization_notes.
        dynamic_token_re = re.compile(r"\b[A-Za-zÀ-ÿ]{2,8}-\d{3,}\b")
        dataset_values_str = " | ".join(
            str(v) for row in (dataset_rows or []) for v in row.values() if isinstance(v, (str, int, float))
        ).lower()

        def sanitize_has_text(ht):
            """Retorna (cleaned, removed_tokens). `cleaned` é o mesmo valor
            operacional de sempre; `removed_tokens` é a lista de tokens
            dinâmicos removidos (vazia se nenhum)."""
            if not ht or not isinstance(ht, str):
                return ht, []
            cleaned = ht
            removed = []
            for token in dynamic_token_re.findall(ht):
                if token.lower() not in dataset_values_str:
                    print(f"[AEGIS SANITIZER] [Padrão Q] Removendo token dinâmico '{token}' de has_text (não encontrado no dataset): \"{ht}\"")
                    cleaned = re.sub(r"\s{2,}", " ", cleaned.replace(token, "")).strip()
                    removed.append(token)
            return cleaned, removed

        def build_step_from_event(ev):
            """
            Constrói o dict de step comum a `st_` e `sup_` a partir de UM
            evento classificado — MESMA lógica de sempre (achatamento
            label>input, select_native, Padrão Q, fallback_selectors,
            weak_selector, coords), aplicada uniformemente a eventos
            mantidos OU excluídos por R1-R4: a supressão é só uma camada de
            metadados (step_role/suppression_reason/execution_hint)
            adicionada DEPOIS, nunca uma bifurcação da construção do step
            em si — ver D3 do plano ("Gesto físico distinto julgado
            redundante ... vira step sup_NNN").
            """
            ev_type = ev.get("type", "").lower()
            selector = ev.get("selector", "")
            # Deriva descrição: business_description > text (clicks) / value (fills) > fallback genérico
            desc = ev.get("business_description") or ""
            if not desc:
                if ev_type == "click":
                    desc = ev.get("text", "")
                elif ev_type == "fill":
                    desc = ev.get("value", "")
            if not desc:
                desc = f"Executar ação {ev_type}"
            step = {
                "type": ev_type,
                "selector": selector,
                "description": desc,
                "scenario": ev.get("scenario", "default"),
            }
            if "original_index" in ev:
                step["original_index"] = ev["original_index"]
            # Flag weak_selector: só quando o evento de origem TEM o campo
            # `confidence` explicitamente E ele é < 70. Gravações antigas
            # (sem o campo, pré-evaluate_selector_reliability) não recebem
            # a flag — nunca usar um default aqui, isso quebraria
            # retrocompatibilidade marcando gravações antigas indevidamente.
            confidence = ev.get("confidence")
            if confidence is not None and confidence < 70:
                step["weak_selector"] = True
            # Propaga fallback_selectors do evento (gravados pelo recorder como
            # candidatos alternativos únicos) pro step do plano, aplicando as
            # mesmas sanitizações do seletor primário: remoção de token
            # dinâmico em has-text (Padrão Q) e dedup contra o primário e entre
            # si. Um fallback idêntico ao selector primário não agrega nada
            # (mesmo alvo) e um fallback dinâmico não sanitizado reintroduziria
            # o mesmo bug que o Padrão Q resolve no seletor principal.
            raw_fallbacks = ev.get("fallback_selectors")
            if raw_fallbacks:
                seen = {selector}
                clean_fallbacks = []
                for fb in raw_fallbacks:
                    if not fb or not isinstance(fb, str):
                        continue
                    fb_clean, fb_removed = sanitize_has_text(fb)
                    if fb_removed:
                        notes = step.setdefault("sanitization_notes", [])
                        for token in fb_removed:
                            notes.append(f"padrao_q: removido token '{token}' de fallback_selectors")
                    if fb_clean in seen:
                        continue
                    seen.add(fb_clean)
                    clean_fallbacks.append(fb_clean)
                if clean_fallbacks:
                    step["fallback_selectors"] = clean_fallbacks
            if ev_type == "click":
                # Usado internamente por _merge_consecutive_clicks
                # (same_widget) pra distinguir 2 widgets físicos diferentes
                # que colapsariam no mesmo selector genérico (ex.: "label"
                # nu). Schema v2: agora também serializado no plano final
                # (T2: "já computado hoje, só não estava sendo serializado").
                step["text"] = ev.get("text", "")
            # <select> nativo dispara 'change' (recorder grava como evento
            # 'fill' igual um <input>), mas .fill() do Playwright não aceita
            # <select> — precisa de select_option_native_resilient, um step
            # type próprio pra o validador exigir o método certo.
            if ev_type == "fill" and ev.get("tag", "").lower() == "select":
                step["type"] = "select_native"
                step["option_text"] = ev.get("value", "")
            parent = ev.get("parent")
            # Idioma nativo <label>...<input>...</label>: clicar em QUALQUER
            # ponto do label já ativa o input descendente (HTML label
            # activation behavior), sem precisar de `for`/`id`. Widgets
            # mat-checkbox/mat-radio escondem o input real via CSS
            # (opacity/visibility), então encadear o clique até ele
            # (click_chained parent=label, child=input) trava no
            # scroll_into_view_if_needed do Playwright ("element is not
            # visible") e escala pra self-healing à toa. Clica no label
            # (`parent`, sempre visível) direto — sem encadear.
            # Clica no próprio <label> (sem encadear no input filho) em vez de
            # confiar no `parent` gravado, que nem sempre é o wrapper
            # específico do widget — dentro de modais/overlays (ex.: dialog de
            # Cláusulas) o recorder às vezes aponta pro container estrutural
            # grande (`.mat-dialog-container`), que não teria efeito nenhum se
            # usado como alvo de clique.
            label_input_match = re.fullmatch(r"(label:has-text\((['\"]).*?\2\))\s+input", selector)
            if ev_type == "click" and label_input_match:
                # Schema v2 (D4): achatamento ganha selector_original com o
                # seletor pré-achatamento; o `selector` operacional continua
                # sendo o achatado, igual a sempre.
                step["selector_original"] = selector
                step["selector"] = label_input_match.group(1)
                parent = None
            elif parent:
                ht_clean, ht_removed = sanitize_has_text(parent.get("has_text"))
                step["parent"] = {"selector": parent.get("selector", ""), "has_text": ht_clean}
                if ht_removed:
                    step["parent"]["has_text_original"] = parent.get("has_text")
                    notes = step.setdefault("sanitization_notes", [])
                    for token in ht_removed:
                        notes.append(f"padrao_q: removido token '{token}'")
            if ev_type == "click":
                x = ev.get("x_percent")
                y = ev.get("y_percent")
                if x is not None and y is not None:
                    step["coords"] = [x, y]
            return step

        # 1. Constrói o step de cada evento classificado cujo tipo está em
        #    allowed_types (idêntico ao filtro de hoje), separado em
        #    mantidos/excluídos — a construção do step em si é IDÊNTICA nos
        #    dois casos (build_step_from_event não sabe nem precisa saber
        #    se o evento foi excluído por R1-R4).
        kept_steps_raw = []
        for ev in kept_events:
            if ev.get("type", "").lower() not in allowed_types:
                continue
            kept_steps_raw.append(build_step_from_event(ev))

        r1r4_suppressed = []
        for ev in excluded_events:
            if ev.get("type", "").lower() not in allowed_types:
                continue
            step = build_step_from_event(ev)
            sc = ev.get("sanitizer_class") or {}
            step["step_role"] = sc.get("role")
            step["suppression_reason"] = sc.get("reason")
            r1r4_suppressed.append(step)

        # 2. Cadeia de merge/reorder/supersede/phantom — EXATAMENTE a lógica
        #    de hoje (só renomeada em 3 pontos, Seção 4 do plano), rodando
        #    SÓ sobre kept_steps_raw. R1-R4 (passo 1, acima) e esta cadeia
        #    operam sobre conjuntos DISJUNTOS de eventos, idêntico ao
        #    pipeline atual — a cadeia nunca vê o que R1-R4 já excluiu.
        steps = self._merge_consecutive_clicks(kept_steps_raw)
        steps = self._reorder_dropdown_pairs(steps)
        steps, superseded_items = self._mark_superseded_selects(steps)
        steps, phantom_items = self._mark_phantom_pretrigger_clicks(steps)
        # Numeração st_NNN sequencial sobre `steps`, NESTA ORDEM. A partir
        # daqui a ordem relativa de `steps` entre si NUNCA é alterada de
        # novo (Seção 8, passo 5) — só se decide ONDE intercalar cada sup_.

        # 3. Numeração st_NNN + herança de flaky (restrita a emitíveis).
        st_steps = []
        for i, s in enumerate(steps):
            s["step_id"] = f"st_{i + 1:03d}"
            if (s["type"], s.get("selector", "")) in old_flaky_keys:
                s["flaky"] = True
            st_steps.append(s)

        # 4. Resolve superseded_by (referência de objeto -> step_id), agora
        #    que o vencedor já tem step_id (passo 3).
        for item in superseded_items:
            winner = item.pop("_superseded_by_step", None)
            if winner is not None:
                item["superseded_by"] = winner["step_id"]

        # 5. sup_NNN: R1-R4 (passo 1) + cadeia (superseded/phantom, passo 2),
        #    todos com a MESMA forma de step, ordenados por position_anchor
        #    (_source_indices) — generalização do "sorted by original_index"
        #    da Seção 8 que também cobre os itens da cadeia (um select
        #    superado só tem source_events, nunca original_index no nível
        #    raiz).
        def _anchor(step):
            idxs = self._source_indices(step)
            return min(idxs) if idxs else 0

        all_suppressed = r1r4_suppressed + superseded_items + phantom_items
        all_suppressed.sort(key=_anchor)
        for i, s in enumerate(all_suppressed):
            s["step_id"] = f"sup_{i + 1:03d}"
            s["execution_hint"] = "skip"

        # 6. Merge-insert (Seção 8, passo 5) — NUNCA reordena st_steps entre
        #    si; só decide onde intercalar cada sup_. position_anchor de um
        #    st_step é o MÍNIMO de _source_indices (nunca só
        #    step.get("original_index") isolado — ver docstring de
        #    _source_indices e .specs/golden/synthetic_r1_merge_case/README.md).
        final_steps = []
        sup_iter = iter(all_suppressed)
        next_sup = next(sup_iter, None)
        for st_step in st_steps:
            st_anchor = _anchor(st_step)
            while next_sup is not None and _anchor(next_sup) < st_anchor:
                final_steps.append(next_sup)
                next_sup = next(sup_iter, None)
            final_steps.append(st_step)
        while next_sup is not None:
            final_steps.append(next_sup)
            next_sup = next(sup_iter, None)

        merges = sum(1 for s in st_steps if s.get("merged_from"))
        steps_required = sum(1 for s in st_steps if s.get("execution_hint", "required") == "required")
        steps_optional = sum(1 for s in st_steps if s.get("execution_hint") == "optional")
        total_recorded_steps = sum(1 for ev in all_events if ev.get("type", "").lower() in allowed_types)

        plan = {
            "version": "2.0",
            "test_dir": os.path.basename(self.telemetry_dir),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_steps": len(st_steps),
            "total_recorded_steps": total_recorded_steps,
            "fidelity_summary": {
                "raw_events": len(all_events),
                "steps_required": steps_required,
                "steps_optional": steps_optional,
                "steps_suppressed": len(all_suppressed),
                "merges": merges,
            },
            "steps": [self._serialize_plan_step(s) for s in final_steps],
        }

        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        print(
            f"[AEGIS SANITIZER] Plano de execução gerado: {plan_path} "
            f"({len(st_steps)} steps emitíveis, {len(all_suppressed)} suprimidos)"
        )

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
        
        inputs = dict_data.get("fields", dict_data.get("inputs", []))
        if isinstance(inputs, dict):
            temp_inputs = []
            for sem_key, inp_info in inputs.items():
                temp_inputs.append({
                    "semantic_key": sem_key,
                    "type": inp_info.get("type"),
                    "selector": inp_info.get("selector"),
                    "observed_value": inp_info.get("observed_value")
                })
            inputs = temp_inputs
            
        outputs = dict_data.get("outputs", [])
        if isinstance(outputs, dict):
            temp_outputs = []
            for sem_key, out_info in outputs.items():
                temp_outputs.append({
                    "semantic_key": sem_key,
                    "selector": out_info.get("selector")
                })
            outputs = temp_outputs
            
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
                
                # Dispara a atualização dos datasets com as novas chaves
                combined_mapping = {**input_mapping, **output_mapping}
                self._update_datasets_with_new_keys(combined_mapping)
                
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
