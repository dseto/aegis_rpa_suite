import os
import json
import base64
import urllib.parse
import requests

class AzureDevOpsPublisher:
    def __init__(self, org: str, project: str, pat: str):
        # Trata a URL da organização se o usuário passar a URL completa
        self.org = org.strip().rstrip('/')
        if 'dev.azure.com' in self.org:
            self.org_url = self.org
        else:
            self.org_url = f"https://dev.azure.com/{self.org}"
            
        self.project = project.strip()
        self.pat = pat.strip()
        self.auth_header = {
            "Authorization": f"Basic {base64.b64encode(f':{self.pat}'.encode()).decode()}",
            "Content-Type": "application/json"
        }

    def get_repository_id(self, repo_name: str) -> str:
        """Busca o ID do repositório Git pelo nome."""
        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/git/repositories/{urllib.parse.quote(repo_name)}?api-version=7.1"
        res = requests.get(url, headers=self.auth_header)
        if res.status_code == 200:
            return res.json().get("id")
        raise RuntimeError(f"Falha ao obter ID do repositório '{repo_name}': {res.text}")

    def get_branch_head_commit(self, repo_id: str, branch: str) -> str:
        """Obtém o hash do último commit (objectId) da branch."""
        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/git/repositories/{repo_id}/refs?filter=heads/{urllib.parse.quote(branch)}&api-version=7.1"
        res = requests.get(url, headers=self.auth_header)
        if res.status_code == 200:
            value = res.json().get("value", [])
            if value:
                return value[0].get("objectId")
        return "0000000000000000000000000000000000000000"

    def push_files(self, repo_name: str, branch: str, files: dict, comment: str = "Aegis RPA Push") -> str:
        """
        Publica múltiplos arquivos no Azure Repos usando a API REST de Pushes v7.1.
        O dicionário 'files' mapeia caminhos no repositório para o conteúdo do arquivo (str).
        """
        repo_id = self.get_repository_id(repo_name)
        old_object_id = self.get_branch_head_commit(repo_id, branch)

        changes = []
        for path, content in files.items():
            path_clean = path.replace('\\', '/').lstrip('/')
            
            # Decide se é ADD ou EDIT (se old_object_id for vazio, é ADD. 
            # Caso contrário, vamos assumir EDIT ou ADD dependendo da existência do arquivo.
            # O Azure DevOps permite usar a API de itens para checar se o arquivo existe).
            change_type = "add"
            if old_object_id != "0000000000000000000000000000000000000000":
                # Verifica se o item já existe para decidir o changeType
                item_url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/git/repositories/{repo_id}/items?path={urllib.parse.quote('/' + path_clean)}&versionDescriptor.version={urllib.parse.quote(branch)}&api-version=7.1"
                item_res = requests.get(item_url, headers=self.auth_header)
                if item_res.status_code == 200:
                    change_type = "edit"

            # Trata conteúdos base64 ou texto normal
            is_base64 = isinstance(content, bytes)
            if is_base64:
                content_str = base64.b64encode(content).decode('utf-8')
                content_type = "base64encoded"
            else:
                content_str = content
                content_type = "rawtext"

            changes.append({
                "changeType": change_type,
                "item": {
                    "path": f"/{path_clean}"
                },
                "newContent": {
                    "content": content_str,
                    "contentType": content_type
                }
            })

        body = {
            "refUpdates": [
                {
                    "name": f"refs/heads/{branch}",
                    "oldObjectId": old_object_id
                }
            ],
            "commits": [
                {
                    "comment": comment,
                    "changes": changes
                }
            ]
        }

        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/git/repositories/{repo_id}/pushes?api-version=7.1"
        res = requests.post(url, headers=self.auth_header, json=body)
        if res.status_code in [200, 201]:
            return res.json().get("pushId")
        raise RuntimeError(f"Falha ao realizar Git Push: {res.text}")

    def create_or_update_variable_group(self, group_name: str, variables: dict) -> int:
        """Cria ou atualiza um Variable Group para armazenar chaves de LLM de forma segura."""
        # 1. Busca se já existe o Variable Group
        list_url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/distributedtask/variablegroups?groupName={urllib.parse.quote(group_name)}&api-version=7.1-preview.2"
        res = requests.get(list_url, headers=self.auth_header)
        
        vg_id = None
        existing_group = None
        if res.status_code == 200:
            value = res.json().get("value", [])
            if value:
                existing_group = value[0]
                vg_id = existing_group.get("id")

        # Converte dicionário de variáveis para o formato de API do Azure DevOps
        SECRET_KEYWORDS = ("api_key", "secret", "password", "totp", "token", "pat")
        azure_vars = {}
        for k, v in variables.items():
            is_secret = any(kw in k.lower() for kw in SECRET_KEYWORDS)
            azure_vars[k] = {
                "value": v,
                "isSecret": is_secret
            }

        body = {
            "name": group_name,
            "description": "Variáveis de integração do Aegis RPA Suite (credenciais, LLM e autenticação SSO/OKTA)",
            "type": "Vsts",
            "variables": azure_vars
        }


        if vg_id:
            # 2. Atualiza
            # Preserva id e dados obrigatórios
            body["id"] = vg_id
            url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/distributedtask/variablegroups/{vg_id}?api-version=7.1-preview.2"
            res = requests.put(url, headers=self.auth_header, json=body)
        else:
            # 2. Cria
            url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/distributedtask/variablegroups?api-version=7.1-preview.2"
            res = requests.post(url, headers=self.auth_header, json=body)

        if res.status_code in [200, 201]:
            return res.json().get("id")
        raise RuntimeError(f"Falha ao criar/atualizar Variable Group '{group_name}': {res.text}")

    def create_or_update_pipeline(self, repo_name: str, branch: str, pipeline_name: str, yaml_path: str) -> int:
        """Cria ou localiza uma Build Definition (Pipeline) associada ao arquivo YAML."""
        repo_id = self.get_repository_id(repo_name)
        
        # 1. Verifica se a pipeline já existe por nome
        list_url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/pipelines?api-version=7.1"
        res = requests.get(list_url, headers=self.auth_header)
        
        pipeline_id = None
        if res.status_code == 200:
            pipelines = res.json().get("value", [])
            for p in pipelines:
                if p.get("name") == pipeline_name:
                    pipeline_id = p.get("id")
                    break

        if pipeline_id:
            # Retorna o ID existente (uma vez criada, atualizações de YAML na branch principal atualizam a execução)
            return pipeline_id

        # 2. Cria se não existir
        body = {
            "name": pipeline_name,
            "configuration": {
                "type": "yaml",
                "path": yaml_path,
                "repository": {
                    "id": repo_id,
                    "type": "azureReposGit"
                }
            }
        }
        
        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/pipelines?api-version=7.1"
        res = requests.post(url, headers=self.auth_header, json=body)
        if res.status_code in [200, 201]:
            return res.json().get("id")
        raise RuntimeError(f"Falha ao registrar Pipeline '{pipeline_name}': {res.text}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST PLANS HIERARCHY: Plan → Suite → Test Cases → Run Results
    # Mapeamento: Projeto Aegis → Test Plan | Cenário → Test Suite | Linha Dataset → Test Case
    # ─────────────────────────────────────────────────────────────────────────

    def create_or_update_test_plan(self, plan_name: str, description: str = "") -> int:
        """
        Cria ou localiza o Test Plan que representa um Projeto Aegis.
        Retorna o planId.
        """
        list_url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/testplan/plans?api-version=7.1"
        res = requests.get(list_url, headers=self.auth_header)
        if res.status_code == 200:
            for plan in res.json().get("value", []):
                if plan.get("name") == plan_name:
                    return plan["id"]

        body = {
            "name": plan_name,
            "description": description,
            "areaPath": self.project,
            "iteration": self.project
        }
        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/testplan/plans?api-version=7.1"
        res = requests.post(url, headers=self.auth_header, json=body)
        if res.status_code in [200, 201]:
            return res.json()["id"]
        raise RuntimeError(f"Falha ao criar Test Plan '{plan_name}': {res.text}")

    def create_or_update_test_suite(self, plan_id: int, suite_name: str, description: str = "") -> int:
        """
        Cria ou localiza uma Test Suite que representa um Cenário Aegis dentro do Test Plan.
        Retorna o suiteId.
        """
        list_url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/testplan/plans/{plan_id}/suites?api-version=7.1"
        res = requests.get(list_url, headers=self.auth_header)
        if res.status_code == 200:
            for suite in res.json().get("value", []):
                if suite.get("name") == suite_name:
                    return suite["id"]

        body = {
            "name": suite_name,
            "suiteType": "staticTestSuite",
            "parentSuite": {"id": plan_id},
            "description": description
        }
        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/testplan/plans/{plan_id}/suites?api-version=7.1"
        res = requests.post(url, headers=self.auth_header, json=body)
        if res.status_code in [200, 201]:
            return res.json()["id"]
        raise RuntimeError(f"Falha ao criar Test Suite '{suite_name}': {res.text}")

    def create_test_case_work_item(self, title: str, steps_description: str = "", row_data: dict = None) -> int:
        """
        Cria um Work Item do tipo 'Test Case' no Azure Boards representando
        uma linha específica do dataset_inicial.json do cenário.
        Retorna o workItemId do Test Case criado.
        """
        # Monta o corpo dos passos de teste no formato HTML do Azure DevOps
        steps_html = "<steps id='0' last='1'>"
        if row_data:
            for i, (key, val) in enumerate(row_data.items(), start=1):
                steps_html += (
                    f"<step id='{i}' type='ActionStep'>"
                    f"<parameterizedString isformatted='true'>&lt;DIV&gt;&lt;P&gt;"
                    f"Preencher campo &lt;B&gt;{key}&lt;/B&gt; com o valor fornecido no dataset"
                    f"&lt;/P&gt;&lt;/DIV&gt;</parameterizedString>"
                    f"<parameterizedString isformatted='true'>&lt;DIV&gt;&lt;P&gt;"
                    f"Valor esperado: &lt;B&gt;{str(val)[:200]}&lt;/B&gt;"
                    f"&lt;/P&gt;&lt;/DIV&gt;</parameterizedString>"
                    f"</step>"
                )
        steps_html += "</steps>"

        ops = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps", "value": steps_html},
        ]
        if steps_description:
            ops.append({"op": "add", "path": "/fields/System.Description", "value": steps_description})

        patch_headers = dict(self.auth_header)
        patch_headers["Content-Type"] = "application/json-patch+json"

        url = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/wit/workitems/$Test%20Case?api-version=7.1"
        res = requests.post(url, headers=patch_headers, json=ops)
        if res.status_code in [200, 201]:
            return res.json()["id"]
        raise RuntimeError(f"Falha ao criar Test Case Work Item '{title}': {res.text}")

    def add_test_cases_to_suite(self, plan_id: int, suite_id: int, test_case_ids: list) -> None:
        """Associa uma lista de Test Case Work Items a uma Test Suite."""
        ids_str = ",".join(str(tc_id) for tc_id in test_case_ids)
        url = (
            f"{self.org_url}/{urllib.parse.quote(self.project)}"
            f"/_apis/testplan/plans/{plan_id}/suites/{suite_id}/testcase/{ids_str}?api-version=7.1"
        )
        res = requests.post(url, headers=self.auth_header)
        if res.status_code not in [200, 201]:
            raise RuntimeError(f"Falha ao vincular Test Cases à Suite {suite_id}: {res.text}")

    def sync_test_suite_from_dataset(
        self,
        project_slug: str,
        scenario_name: str,
        scenario_slug: str,
        dataset: list,
        project_business_description: str = "",
        scenario_business_description: str = ""
    ) -> dict:
        """
        Sincroniza o dataset_inicial.json do cenário com o Azure DevOps Test Plans.

        Granularidade Completa:
          - Test Plan  = Projeto Aegis (project_slug)
          - Test Suite = Cenário Aegis (scenario_slug)
          - Test Case  = Linha do dataset_inicial.json

        Retorna um dicionário com plan_id, suite_id e os test_case_ids criados.
        """
        # 1. Garante que o Test Plan do projeto existe
        plan_name = f"Aegis RPA - {project_slug}"
        plan_id = self.create_or_update_test_plan(
            plan_name=plan_name,
            description=project_business_description or f"Plano de testes automatizados do projeto {project_slug}"
        )

        # 2. Garante que a Test Suite do cenário existe dentro do Plan
        suite_name = f"{scenario_slug} - {scenario_name}"
        suite_id = self.create_or_update_test_suite(
            plan_id=plan_id,
            suite_name=suite_name,
            description=scenario_business_description or f"Suite de testes do cenário {scenario_name}"
        )

        # 3. Cria um Test Case Work Item para cada linha do dataset
        created_tc_ids = []
        for i, row in enumerate(dataset, start=1):
            # Extrai um identificador legível da linha para o título do test case
            # Prioriza campos de identificação comuns (id, cpf, nome, email)
            id_candidates = ["id", "cpf", "nome", "nome_cliente", "email", "placa", "cnpj", "proposta"]
            id_label = None
            for cand in id_candidates:
                val = row.get(cand) or row.get(cand.upper())
                if val:
                    id_label = f"{cand}={val}"
                    break

            title = f"[{scenario_slug}] Transação #{i}"
            if id_label:
                title += f" ({id_label})"

            tc_id = self.create_test_case_work_item(
                title=title,
                steps_description=f"Execução automatizada pelo Aegis RPA. Dataset linha {i}.",
                row_data=row
            )
            created_tc_ids.append(tc_id)

        # 4. Vincula todos os Test Cases criados à Suite
        if created_tc_ids:
            self.add_test_cases_to_suite(plan_id, suite_id, created_tc_ids)

        return {
            "plan_id": plan_id,
            "plan_name": plan_name,
            "suite_id": suite_id,
            "suite_name": suite_name,
            "test_case_ids": created_tc_ids
        }

    def publish_run_results_from_csv(self, plan_id: int, suite_id: int, run_name: str, csv_path: str, test_case_ids: list) -> dict:
        """
        Lê o relatorio_execucao.csv gerado pelo Aegis Runner e publica os resultados
        de cada transação associando-os ao Test Case correspondente na suite.

        Mapeamento: posição da linha do CSV → test_case_ids[i]
        """
        import csv as csv_module

        rows_results = []
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Relatório de execução não encontrado: {csv_path}")

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                rows_results.append(row)

        # 1. Cria a Test Run associada ao Test Plan/Suite
        run_body = {
            "name": run_name,
            "isAutomated": True,
            "plan": {"id": plan_id},
            "pointIds": []   # deixa vazio — os resultados serão associados pelos test case ids
        }
        url_run = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/test/runs?api-version=7.1"
        res_run = requests.post(url_run, headers=self.auth_header, json=run_body)
        if res_run.status_code not in [200, 201]:
            raise RuntimeError(f"Falha ao criar Test Run: {res_run.text}")

        run_id = res_run.json()["id"]

        # 2. Publica o resultado de cada transação
        results_body = []
        for i, row in enumerate(rows_results):
            status = row.get("status", "").upper()
            # Mapeia status do Aegis → outcome do Azure DevOps
            outcome_map = {
                "SUCCESS": "Passed",
                "HEALED": "Passed",
                "FAILED": "Failed",
                "ERROR": "Failed",
                "SKIPPED": "NotExecuted"
            }
            outcome = outcome_map.get(status, "NotExecuted")

            tc_id = test_case_ids[i] if i < len(test_case_ids) else None
            result_entry = {
                "outcome": outcome,
                "state": "Completed",
                "errorMessage": row.get("error_message", ""),
                "durationInMs": int(float(row.get("duration_seconds", 0) or 0) * 1000),
                "comment": f"Campo falho: {row.get('failed_field', 'N/A')} | Cenário: {row.get('aegis_scenario', 'N/A')}"
            }
            if tc_id:
                result_entry["testCase"] = {"id": str(tc_id)}

            results_body.append(result_entry)

        if results_body:
            url_res = f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/test/runs/{run_id}/results?api-version=7.1"
            requests.post(url_res, headers=self.auth_header, json=results_body)

        # 3. Finaliza a Test Run
        requests.patch(
            f"{self.org_url}/{urllib.parse.quote(self.project)}/_apis/test/runs/{run_id}?api-version=7.1",
            headers=self.auth_header,
            json={"state": "Completed"}
        )

        return {"run_id": run_id, "total": len(rows_results)}
