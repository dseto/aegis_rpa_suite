import os
import sys
import json
import argparse
import urllib.parse
import requests
from datetime import datetime

# Garante que o diretório raiz esteja no PYTHONPATH para importar os módulos
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from aegis_cockpit.project_manager import ProjectManager
from aegis_devops.publisher import AzureDevOpsPublisher

def main():
    parser = argparse.ArgumentParser(description="Aegis DevOps CLI Pipeline Publisher")
    parser.add_argument("--project-slug", required=True, help="Slug do projeto a ser publicado")
    args = parser.parse_args()

    project_slug = args.project_slug
    pm = ProjectManager(PROJECT_ROOT)
    
    print(f"[*] Inicializando publicação DevOps para o projeto: {project_slug}")
    
    # 1. Carrega configuração de DevOps
    cfg = pm.get_devops_config(project_slug)
    if not cfg:
        print("[ERROR] Nenhuma configuração de DevOps encontrada para este projeto. Salve as configurações antes de publicar.")
        sys.exit(1)
        
    org = cfg.get("org", "").strip()
    project_name = cfg.get("project", "").strip()
    repo = cfg.get("repo", "").strip()
    branch = cfg.get("branch", "main").strip()
    pat = cfg.get("pat", "").strip()
    vg_name = cfg.get("vg_name", "aegis-llm-group").strip()
    
    llm_provider = cfg.get("llm_provider", "openrouter").strip()
    llm_model = cfg.get("llm_model", "google/gemini-2.5-flash").strip()
    llm_base_url = cfg.get("llm_base_url", "https://openrouter.ai/api/v1").strip()
    
    included_scenarios = cfg.get("included_scenarios", [])
    
    if not org or not project_name or not repo or not pat:
        print("[ERROR] Parâmetros obrigatórios ausentes nas configurações de DevOps (org, project, repo, pat).")
        sys.exit(1)
        
    if not included_scenarios:
        print("[ERROR] Nenhum cenário de teste foi selecionado para publicação.")
        sys.exit(1)
        
    proj_dir = pm.get_project_dir(project_slug)
    print(f"[*] Diretório do projeto: {proj_dir}")
    print(f"[*] Cenários incluídos ({len(included_scenarios)}): {', '.join(included_scenarios)}")
    
    # 2. Inicializa o publicador do Azure DevOps
    try:
        publisher = AzureDevOpsPublisher(org=org, project=project_name, pat=pat)
    except Exception as e:
        print(f"[ERROR] Falha ao instanciar AzureDevOpsPublisher: {e}")
        sys.exit(1)
        
    # 3. Gerenciamento seguro do Variable Group (preserva valores inseridos manualmente pelo usuário)
    try:
        list_url = f"{publisher.org_url}/{urllib.parse.quote(publisher.project)}/_apis/distributedtask/variablegroups?groupName={urllib.parse.quote(vg_name)}&api-version=7.1-preview.2"
        res = requests.get(list_url, headers=publisher.auth_header)
        vg_exists = False
        if res.status_code == 200:
            value = res.json().get("value", [])
            if value:
                vg_exists = True
                
        if not vg_exists:
            print(f"[*] Criando Variable Group '{vg_name}' no Azure DevOps...")
            # Cria o Variable Group com as chaves cognitivas vazias
            variables = {
                "AEGIS_COGNITIVE_API_KEY": "",
                "AEGIS_COGNITIVE_PROVIDER": llm_provider,
                "AEGIS_COGNITIVE_MODEL": llm_model,
                "AEGIS_COGNITIVE_BASE_URL": llm_base_url
            }
            publisher.create_or_update_variable_group(vg_name, variables)
            print(f"[✓] Variable Group '{vg_name}' criado com sucesso. IMPORTANTE: Preencha a API Key manualmente na UI do Azure DevOps.")
        else:
            print(f"[*] Variable Group '{vg_name}' já existe no Azure DevOps. Preservando credenciais/valores inseridos manualmente.")
    except Exception as e:
        print(f"[WARNING] Falha ao obter ou criar Variable Group '{vg_name}': {e}. A execução do push prosseguirá.")

    # 4. Agrupa todos os arquivos da publicação (core do Aegis Runner + cenários funcionais)
    files = {}
    
    # Core do Aegis Runner
    print("[*] Empacotando core do Aegis Runner...")
    runner_dir = os.path.join(PROJECT_ROOT, "aegis_runner")
    core_files = ["__init__.py", "runner.py", "cognitive_fallback.py", "verify_visual.py"]
    for cf in core_files:
        cpath = os.path.join(runner_dir, cf)
        if os.path.exists(cpath):
            with open(cpath, "r", encoding="utf-8") as f:
                files[f"aegis_runner/{cf}"] = f.read()
                
    # Utilitário de relatório DevOps
    reporter_path = os.path.join(PROJECT_ROOT, "aegis_devops", "junit_reporter.py")
    if os.path.exists(reporter_path):
        with open(reporter_path, "r", encoding="utf-8") as f:
            files["aegis_devops/junit_reporter.py"] = f.read()

    # Arquivos funcionais locais de cada cenário selecionado
    local_files = [
        "bot_producao.py", "robot.py", "run_bot.py",
        "dicionario.json", "gravacao.json", "dataset_inicial.json",
        "requirements.txt", "DEVELOPMENT_GUIDE.md"
    ]
    
    for test_slug in included_scenarios:
        print(f"[*] Empacotando cenário: {test_slug}...")
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        for lf in local_files:
            lpath = os.path.join(test_dir, lf)
            if os.path.exists(lpath):
                with open(lpath, "r", encoding="utf-8") as f:
                    files[f"projects/{project_slug}/tests/{test_slug}/{lf}"] = f.read()
                    
    # 5. Carrega o template da pipeline e popula a matriz de execução do YAML
    print("[*] Gerando pipeline YAML consolidada...")
    template_path = os.path.join(PROJECT_ROOT, "aegis_devops", "azure-pipelines-template.yml")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
            
        matrix_lines = []
        for test_slug in included_scenarios:
            matrix_lines.append(f"        {test_slug}:\n          SCENARIO: {test_slug}")
        matrix_block = "\n".join(matrix_lines)
        
        pipeline_content = template_content.format(
            branch=branch,
            variable_group=vg_name,
            matrix_block=matrix_block,
            project_slug=project_slug
        )
        files["azure-pipelines.yml"] = pipeline_content
    else:
        print("[ERROR] Template de pipeline (azure-pipelines-template.yml) não encontrado.")
        sys.exit(1)

    # 6. Realiza o Git Push atômico
    print(f"[*] Enviando commits via API REST Git v7.1 para a branch '{branch}'...")
    try:
        push_id = publisher.push_files(
            repo_name=repo,
            branch=branch,
            files=files,
            comment=f"Publicado pelo Aegis RPA DevOps — Matriz de {len(included_scenarios)} cenários"
        )
        print(f"[✓] Commit realizado com sucesso! ID do Push: {push_id}")
    except Exception as e:
        print(f"[ERROR] Falha ao enviar arquivos para o repositório git: {e}")
        sys.exit(1)
        
    # 7. Cria ou atualiza a pipeline de build no Azure DevOps
    pipeline_name = f"Aegis RPA - {project_slug}"
    print(f"[*] Registrando Pipeline '{pipeline_name}' no Azure DevOps...")
    try:
        pipeline_id = publisher.create_or_update_pipeline(
            repo_name=repo,
            branch=branch,
            pipeline_name=pipeline_name,
            yaml_path="azure-pipelines.yml"
        )
        print(f"[✓] Pipeline registrada com sucesso! ID da Pipeline: {pipeline_id}")
    except Exception as e:
        print(f"[ERROR] Falha ao registrar pipeline no Azure DevOps: {e}")
        sys.exit(1)

    # 8. Sincroniza os datasets com o Azure DevOps Test Plans
    print("[*] Sincronizando datasets com Azure Test Plans v7.1...")
    
    # Carrega a descrição de negócio do projeto principal
    proj_json_path = os.path.join(proj_dir, "project.json")
    proj_business_desc = ""
    if os.path.exists(proj_json_path):
        try:
            with open(proj_json_path, "r", encoding="utf-8") as f:
                proj_business_desc = json.load(f).get("business_description", "")
        except:
            pass

    for test_slug in included_scenarios:
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        dataset_path = os.path.join(test_dir, "dataset_inicial.json")
        if os.path.exists(dataset_path):
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    dataset = json.load(f)
                    
                test_json_path = os.path.join(test_dir, "project.json")
                test_business_desc = ""
                test_name_display = test_slug
                if os.path.exists(test_json_path):
                    with open(test_json_path, "r", encoding="utf-8") as f:
                        test_meta = json.load(f)
                        test_business_desc = test_meta.get("business_description", "")
                        test_name_display = test_meta.get("name", test_slug)
                        
                if isinstance(dataset, list) and dataset:
                    print(f"[*] Sincronizando cenário '{test_slug}' ({len(dataset)} registros)...")
                    sync_result = publisher.sync_test_suite_from_dataset(
                        project_slug=project_slug,
                        scenario_name=test_name_display,
                        scenario_slug=test_slug,
                        dataset=dataset,
                        project_business_description=proj_business_desc,
                        scenario_business_description=test_business_desc
                    )
                    print(f"[✓] Cenário '{test_slug}' sincronizado. {len(sync_result['test_case_ids'])} Test Cases registrados.")
                else:
                    print(f"[!] Cenário '{test_slug}' possui dataset vazio. Pulando Test Plans.")
            except Exception as e:
                print(f"[WARNING] Falha ao sincronizar Test Plans para cenario '{test_slug}': {e}")
        else:
            print(f"[!] Cenário '{test_slug}' sem dataset_inicial.json. Pulando Test Plans.")

    print("\n" + "=" * 70)
    print("🛡️  PUBLICAÇÃO CONCLUÍDA COM SUCESSO!")
    print(f"🔗  Pipeline Azure DevOps: {publisher.org_url}/{publisher.project}/_build?definitionId={pipeline_id}")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
