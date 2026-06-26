import os
import json
import csv
import re
import argparse
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
TELEMETRY_DIR = r"C:\Projetos\Lab\telemetry_data"
DEFAULT_DICT_FILE = os.path.join(TELEMETRY_DIR, "dicionario.json")
DEFAULT_REPORT_FILE = os.path.join(TELEMETRY_DIR, "relatorio_validacao.json")

def load_dataset(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    elif ext == ".csv":
        records = []
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert null/None and parse types as possible
                parsed_row = {}
                for k, v in row.items():
                    if v == "" or v is None:
                        parsed_row[k] = None
                    elif v.lower() == "true":
                        parsed_row[k] = True
                    elif v.lower() == "false":
                        parsed_row[k] = False
                    else:
                        parsed_row[k] = v
                records.append(parsed_row)
        return records
    else:
        raise ValueError(f"Extensão de arquivo não suportada: {ext}. Use .json ou .csv")

def validate_dataset(dataset_path, dict_path=DEFAULT_DICT_FILE):
    print("\n" + "=" * 60)
    print("🛡️ AEGIS DATASET VALIDATOR: VALIDAÇÃO ANTECIPADA (FIREWALL)")
    print("=" * 60)
    print(f"[DATASET] Caminho: {dataset_path}")
    print(f"[DICIONÁRIO] Caminho: {dict_path}")
    print("-" * 60)

    if not os.path.exists(dataset_path):
        print(f"[ERRO] Arquivo de dataset não encontrado: {dataset_path}")
        return False
    if not os.path.exists(dict_path):
        print(f"[ERRO] Arquivo de dicionário não encontrado: {dict_path}")
        return False

    # Carregar Dicionário
    with open(dict_path, "r", encoding="utf-8") as f:
        dictionary = json.load(f)
    
    fields_schema = dictionary.get("fields", {})
    
    # Extrair cenários conhecidos a partir dos inputs/outputs mapeados (para validar contra aegis_scenario)
    valid_scenarios = set()
    for inp in dictionary.get("inputs", []):
        if "scenario" in inp:
            valid_scenarios.add(str(inp["scenario"]).strip())
    for out in dictionary.get("outputs", []):
        if "scenario" in out:
            valid_scenarios.add(str(out["scenario"]).strip())
            
    # Se não houver cenários definidos no dicionário de dados, inferimos "default"
    if not valid_scenarios:
        valid_scenarios.add("default")

    # Carregar Dataset
    try:
        dataset = load_dataset(dataset_path)
    except Exception as e:
        print(f"[ERRO] Falha ao carregar o dataset: {e}")
        return False

    print(f"[INFO] Total de registros carregados para validação: {len(dataset)}")
    sys_ok = True
    validation_failures = []  # Erros Críticos (bloqueantes para orquestração)
    validation_warnings = []  # Avisos de Validação de Campo
    passed_count = 0
    warnings_count = 0
    failures_count = 0

    for idx, record in enumerate(dataset):
        record_id = record.get("id") or (idx + 1)
        record_critical_errors = []
        record_validation_warnings = []

        # 1. Normalizar expected_result
        expected_result = str(record.get("expected_result", "")).strip()
        expected_result_lower = expected_result.lower()
        if not expected_result:
            expected_result = "success"
            expected_result_lower = "success"

        # 2. Validar metadados críticos de fila
        if "id" not in record or record["id"] is None or str(record["id"]).strip() == "":
            record_critical_errors.append("Metadado crítico 'id' está ausente ou vazio.")
            
        scenario = record.get("aegis_scenario")
        if "aegis_scenario" not in record or scenario is None or str(scenario).strip() == "":
            record_critical_errors.append("Metadado crítico 'aegis_scenario' está ausente ou vazio.")
        else:
            scenario_str = str(scenario).strip()
            if scenario_str not in valid_scenarios:
                record_critical_errors.append(f"Cenário '{scenario_str}' informado não está cadastrado no dicionário de dados. Cenários válidos: {list(valid_scenarios)}")

        # 3. Validar campos mapeados contra o dicionário (se não houver erro crítico de cenário)
        for field_name, rule_info in fields_schema.items():
            required = rule_info.get("required", True)
            field_type = rule_info.get("type", "string")
            rules = rule_info.get("validation_rules", {})
            regex_pattern = rules.get("regex", "")
            enum_list = rules.get("enum", [])

            val = record.get(field_name)

            # Validar obrigatoriedade
            if required and (val is None or val == ""):
                record_validation_warnings.append({
                    "field": field_name,
                    "value": val,
                    "reason": f"Campo obrigatório '{field_name}' está ausente ou vazio."
                })
                continue

            # Se estiver presente, validar tipos e regras específicas
            if val is not None and val != "":
                # Validação de tipo simples
                if field_type == "number":
                    try:
                        float(val)
                    except ValueError:
                        record_validation_warnings.append({
                            "field": field_name,
                            "value": val,
                            "reason": f"Campo '{field_name}' deve ser um número."
                        })
                
                elif field_type == "boolean":
                    if not isinstance(val, bool) and str(val).lower() not in ["true", "false", "1", "0"]:
                        record_validation_warnings.append({
                            "field": field_name,
                            "value": val,
                            "reason": f"Campo '{field_name}' deve ser booleano."
                        })

                elif field_type == "date":
                    # Aceita DD/MM/YYYY ou YYYY-MM-DD
                    date_match = re.match(r"^\d{2}/\d{2}/\d{4}$|^\d{4}-\d{2}-\d{2}$", str(val))
                    if not date_match:
                        record_validation_warnings.append({
                            "field": field_name,
                            "value": val,
                            "reason": f"Campo de data '{field_name}' está malformado. Formato aceito: DD/MM/YYYY ou YYYY-MM-DD."
                        })

                # Validação de Regex
                if regex_pattern:
                    try:
                        if not re.match(regex_pattern, str(val)):
                            record_validation_warnings.append({
                                "field": field_name,
                                "value": val,
                                "reason": f"Campo '{field_name}' quebrou a regra de formato regex '{regex_pattern}'."
                            })
                    except Exception as re_err:
                        print(f"[WARNING] Erro de expressão regular no dicionário para o campo '{field_name}': {re_err}")

                # Validação de Enums
                if enum_list:
                    if str(val) not in [str(e) for e in enum_list]:
                        record_validation_warnings.append({
                            "field": field_name,
                            "value": val,
                            "reason": f"Campo '{field_name}' contém valor '{val}', que não pertence à lista permitida: {enum_list}."
                        })

        # 4. Registrar e exibir resultados do registro
        if record_critical_errors:
            failures_count += 1
            sys_ok = False
            validation_failures.append({
                "record_index": idx,
                "record_id": record_id,
                "errors": record_critical_errors
            })
            print(f"[❌ ERRO CRÍTICO] Registro {record_id} (Índice {idx}) contém {len(record_critical_errors)} erro(s) crítico(s):")
            for err in record_critical_errors:
                print(f"    - {err}")
        else:
            passed_count += 1
            
        if record_validation_warnings:
            # Checar se o erro é intencional
            is_expected_error = any(kw in expected_result_lower for kw in ["error", "fail", "failure", "incorrect", "invalid", "erro", "falha"])
            
            for warning_item in record_validation_warnings:
                warnings_count += 1
                validation_warnings.append({
                    "record_index": idx,
                    "record_id": record_id,
                    "field_name": warning_item["field"],
                    "observed_value": warning_item["value"],
                    "expected_result": expected_result,
                    "is_expected_error": is_expected_error,
                    "message": warning_item["reason"]
                })
                
                scenario_name = str(record.get("aegis_scenario", "default"))
                if is_expected_error:
                    print(f"[⚠️ AEGIS VALIDATOR WARNING] Registro {record_id} (Cenário: {scenario_name}): Inconsistência intencional em '{warning_item['field']}' ('{warning_item['value']}'). Erro esperado: '{expected_result}'. (Caminho Alternativo)")
                else:
                    print(f"[🔥 AEGIS VALIDATOR ALERT] Registro {record_id} (Cenário: {scenario_name}): Campo '{warning_item['field']}' violou regra ('{warning_item['reason']}'), mas o resultado esperado é '{expected_result}'. Risco de falha de execução ou resultado inesperado!")

    # Compilar Relatório
    report = {
        "dataset_path": dataset_path,
        "dictionary_path": dict_path,
        "total_records": len(dataset),
        "passed_records": passed_count,
        "critical_errors_count": failures_count,
        "validation_warnings_count": warnings_count,
        "is_valid": sys_ok,
        "failures": validation_failures,
        "warnings": validation_warnings
    }

    with open(DEFAULT_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)

    print("-" * 60)
    print("📊 RESULTADO DA VALIDAÇÃO:")
    print(f"    - Total Processados: {len(dataset)}")
    print(f"    - Registros com Estrutura Válida: {passed_count} ({(passed_count/len(dataset))*100:.1f}%)")
    print(f"    - Erros Críticos de Fila: {failures_count}")
    print(f"    - Avisos de Validação nos Campos: {warnings_count}")
    print(f"    - Status Geral: " + ("✅ DATASET PRONTO PARA CARGA (ACEITÁVEL)" if sys_ok else "❌ DATASET CONTÉM INCONSISTÊNCIAS CRÍTICAS BLOQUEANTES"))
    print(f"Relatório detalhado salvo em: {DEFAULT_REPORT_FILE}")
    print("=" * 60 + "\n")
    return sys_ok

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis Dataset Validator (Firewall)")
    parser.add_argument("--dataset", required=True, help="Caminho do arquivo de dataset (.json ou .csv)")
    parser.add_argument("--dict", default=None, help="Caminho do arquivo de dicionário de dados")
    parser.add_argument("--project-dir", default=None, help="Diretório do projeto isolado. Sobrescreve --dict e o destino do relatório")
    args = parser.parse_args()

    dict_path = DEFAULT_DICT_FILE
    report_path = DEFAULT_REPORT_FILE
    project_dir = None

    if args.project_dir:
        project_dir = os.path.abspath(args.project_dir)
        dict_path = os.path.join(project_dir, "dicionario.json")
        report_path = os.path.join(project_dir, "relatorio_validacao.json")
        DEFAULT_REPORT_FILE = report_path
    elif args.dict:
        dict_path = args.dict

    result_ok = validate_dataset(args.dataset, dict_path)

    # Atualiza project.json se o projeto foi informado
    if project_dir:
        project_json_path = os.path.join(project_dir, "project.json")
        if os.path.exists(project_json_path):
            try:
                with open(project_json_path, "r", encoding="utf-8") as f:
                    proj = json.load(f)
                proj["status"] = "validated" if result_ok else "validation_failed"
                proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(project_json_path, "w", encoding="utf-8") as f:
                    json.dump(proj, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[WARNING] Não foi possível atualizar project.json: {e}")
