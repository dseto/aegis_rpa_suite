import os
import csv
import sys
import xml.etree.ElementTree as ET

def convert_csv_to_junit(csv_path, xml_path):
    """
    Lê o relatorio_execucao.csv e gera um arquivo test-results.xml no formato JUnit.
    """
    if not os.path.exists(csv_path):
        print(f"[JUNIT REPORTER] Relatório CSV não encontrado em: {csv_path}")
        return False
        
    print(f"[JUNIT REPORTER] Lendo relatório CSV: {csv_path}")
    
    testcases = []
    total_tests = 0
    failures = 0
    total_time = 0.0
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_tests += 1
            scenario = row.get("aegis_scenario", "default")
            row_id = row.get("id", "unknown")
            status = row.get("status", "").upper()
            err_msg = row.get("error_message", "")
            failed_field = row.get("failed_field", "")
            duration = float(row.get("duration_seconds", 0.0) or 0.0)
            total_time += duration
            
            tc = ET.Element("testcase", {
                "name": f"Transaction_Row_{row_id}",
                "classname": f"AegisScenario_{scenario}",
                "time": f"{duration:.3f}"
            })
            
            if status in ("FAILED", "ERROR"):
                failures += 1
                failure_el = ET.SubElement(tc, "failure", {
                    "message": f"Falha na Transação {row_id} no campo '{failed_field}': {err_msg}",
                    "type": "RegressionFailure"
                })
                # Detalhes adicionais na stacktrace do JUnit
                failure_el.text = f"Cenário: {scenario}\nLinha do Dataset ID: {row_id}\nCampo Falho: {failed_field}\nDetalhes do Erro: {err_msg}"
                
            testcases.append(tc)
            
    # Cria a estrutura raiz do JUnit XML
    testsuite = ET.Element("testsuite", {
        "name": "Aegis_RPA_Regression_Suite",
        "tests": str(total_tests),
        "failures": str(failures),
        "errors": "0",
        "time": f"{total_time:.3f}"
    })
    
    for tc in testcases:
        testsuite.append(tc)
        
    tree = ET.ElementTree(testsuite)
    os.makedirs(os.path.dirname(os.path.abspath(xml_path)), exist_ok=True)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    print(f"[JUNIT REPORTER] JUnit XML gerado com sucesso em: {xml_path} (Testes: {total_tests}, Falhas: {failures})")
    return failures == 0

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python junit_reporter.py <caminho_csv> <caminho_xml_saida>")
        sys.exit(1)
        
    csv_file = sys.argv[1]
    xml_file = sys.argv[2]
    success = convert_csv_to_junit(csv_file, xml_file)
    if not success:
        # Retorna código de erro se houver falhas para falhar a build do DevOps
        sys.exit(1)
