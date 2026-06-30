import os
import re
import json
import shutil
import stat
import unicodedata
from datetime import datetime
import uuid

class ProjectManager:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.config_file = os.path.join(project_root, "aegis_config.json")
        
        # Inicializa configurações persistentes
        cfg = self.load_aegis_config()
        self.projects_dir = os.path.abspath(cfg.get("projects_dir", os.path.join(project_root, "projects")))
        self.telemetry_dir = os.path.abspath(cfg.get("telemetry_dir", os.path.join(project_root, "telemetry_data")))
        
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.telemetry_dir, exist_ok=True)
        
        self.workspace_file = os.path.join(self.telemetry_dir, "workspace_projects.json")
        
        # Roda migração legada se necessário
        self.migrate_legacy_if_needed()

    def load_aegis_config(self) -> dict:
        """Carrega configurações persistentes de diretório de projetos."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {
            "projects_dir": os.path.abspath(os.path.join(self.project_root, "projects")),
            "telemetry_dir": os.path.abspath(os.path.join(self.project_root, "telemetry_data"))
        }

    def save_aegis_config(self, cfg: dict):
        """Salva configurações persistentes fundindo-as com as existentes."""
        try:
            current_cfg = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        current_cfg = json.load(f)
                except:
                    pass
            current_cfg.update(cfg)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(current_cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[AEGIS COCKPIT] Erro ao salvar aegis_config.json: {e}")

    def update_paths(self, projects_dir: str, telemetry_dir: str):
        """Atualiza dinamicamente as variáveis de caminho do Cockpit e as persiste."""
        self.projects_dir = os.path.abspath(projects_dir)
        self.telemetry_dir = os.path.abspath(telemetry_dir)
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.telemetry_dir, exist_ok=True)
        self.workspace_file = os.path.join(self.telemetry_dir, "workspace_projects.json")
        self.save_aegis_config({"projects_dir": self.projects_dir, "telemetry_dir": self.telemetry_dir})

    def load_workspace_registry(self) -> dict:
        """Lê o registro central de projetos mapeados."""
        if os.path.exists(self.workspace_file):
            try:
                with open(self.workspace_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"projects": {}}

    def save_workspace_registry(self, registry: dict):
        """Salva o registro central de projetos mapeados."""
        os.makedirs(os.path.dirname(self.workspace_file), exist_ok=True)
        with open(self.workspace_file, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)

    def slugify(self, name: str) -> str:
        """Converte um nome legível para um slug de diretório seguro."""
        nfkd = unicodedata.normalize('NFKD', name)
        ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
        slug = re.sub(r'[^\w\s-]', '', ascii_str).strip().lower()
        slug = re.sub(r'[\s\-]+', '_', slug)
        return slug or "projeto"

    def get_unique_slug(self, base_slug: str) -> str:
        """Garante que o slug seja único dentro de projects_dir."""
        candidate = base_slug
        counter = 2
        while os.path.exists(os.path.join(self.projects_dir, candidate)):
            candidate = f"{base_slug}_{counter}"
            counter += 1
        return candidate

    def get_next_project_id(self) -> int:
        """Calcula o próximo ID sequencial único de projeto no workspace."""
        max_id = 0
        registry = self.load_workspace_registry()
        for slug, proj_dir in registry.get("projects", {}).items():
            proj_json = os.path.join(proj_dir, "project.json")
            if os.path.exists(proj_json):
                try:
                    with open(proj_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    p_id = meta.get("project_id") or meta.get("id")
                    if isinstance(p_id, int):
                        max_id = max(max_id, p_id)
                    elif isinstance(p_id, str) and p_id.isdigit():
                        max_id = max(max_id, int(p_id))
                except:
                    pass
        if os.path.isdir(self.projects_dir):
            for entry in os.listdir(self.projects_dir):
                proj_json = os.path.join(self.projects_dir, entry, "project.json")
                if os.path.exists(proj_json):
                    try:
                        with open(proj_json, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        p_id = meta.get("project_id") or meta.get("id")
                        if isinstance(p_id, int):
                            max_id = max(max_id, p_id)
                        elif isinstance(p_id, str) and p_id.isdigit():
                            max_id = max(max_id, int(p_id))
                    except:
                        pass
        return max_id + 1

    def get_next_test_id(self, project_slug: str) -> int:
        """Calcula o próximo ID sequencial único de cenário (teste) para um projeto."""
        proj_dir = self.get_project_dir(project_slug)
        tests_dir = os.path.join(proj_dir, "tests")
        max_id = 0
        if os.path.isdir(tests_dir):
            for entry in os.listdir(tests_dir):
                test_json = os.path.join(tests_dir, entry, "project.json")
                if os.path.exists(test_json):
                    try:
                        with open(test_json, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        t_id = meta.get("test_id") or meta.get("id")
                        if isinstance(t_id, int):
                            max_id = max(max_id, t_id)
                        elif isinstance(t_id, str) and t_id.isdigit():
                            max_id = max(max_id, int(t_id))
                    except:
                        pass
        return max_id + 1

    def list_projects(self) -> list:
        """Lista todos os projetos existentes mapeados no workspace."""
        projects = []
        registry = self.load_workspace_registry()
        
        # Adiciona projetos registrados
        for slug, proj_dir in list(registry.get("projects", {}).items()):
            proj_json = os.path.join(proj_dir, "project.json")
            if os.path.isdir(proj_dir) and os.path.exists(proj_json):
                try:
                    # Executa a migração automática de legado se necessário
                    if self.is_legacy_project(proj_dir):
                        self.migrate_legacy_project(slug)
                        
                    with open(proj_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    
                    # Garante identificador único para o projeto
                    if "project_id" not in meta or "id" not in meta or (isinstance(meta.get("id"), str) and len(meta["id"]) > 10):
                        next_pid = self.get_next_project_id()
                        meta["project_id"] = next_pid
                        meta["id"] = str(next_pid)
                        with open(proj_json, "w", encoding="utf-8") as wf:
                            json.dump(meta, wf, indent=4, ensure_ascii=False)
                    
                    # Carrega os cenários desse projeto
                    meta["tests"] = self.list_tests(slug)
                    projects.append(meta)
                except Exception:
                    pass
            else:
                # Remove do registro se a pasta física não existe mais
                registry.setdefault("projects", {}).pop(slug, None)
                self.save_workspace_registry(registry)
                
        # Adiciona pastas locais padrão no PROJECTS_DIR para retrocompatibilidade
        if os.path.isdir(self.projects_dir):
            for entry in sorted(os.listdir(self.projects_dir)):
                proj_dir = os.path.join(self.projects_dir, entry)
                proj_json = os.path.join(proj_dir, "project.json")
                if os.path.isdir(proj_dir) and os.path.exists(proj_json) and entry not in registry.setdefault("projects", {}):
                    try:
                        # Executa a migração automática de legado se necessário
                        if self.is_legacy_project(proj_dir):
                            self.migrate_legacy_project(entry)
                            
                        with open(proj_json, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        
                        # Garante identificador único para o projeto
                        if "project_id" not in meta or "id" not in meta or (isinstance(meta.get("id"), str) and len(meta["id"]) > 10):
                            next_pid = self.get_next_project_id()
                            meta["project_id"] = next_pid
                            meta["id"] = str(next_pid)
                            with open(proj_json, "w", encoding="utf-8") as wf:
                                json.dump(meta, wf, indent=4, ensure_ascii=False)
                        
                        meta["tests"] = self.list_tests(entry)
                        projects.append(meta)
                        registry["projects"][entry] = proj_dir
                    except Exception:
                        pass
            self.save_workspace_registry(registry)
            
        return projects

    def create_project(self, name: str, url: str, custom_path: str = "", business_description: str = "", expected_business_outcome: str = "") -> dict:
        """Cria um novo diretório de projeto físico (localizado no projects_dir ou em custom_path)."""
        base_slug = self.slugify(name)
        slug = self.get_unique_slug(base_slug)
        
        if custom_path:
            proj_dir = os.path.abspath(custom_path)
        else:
            proj_dir = os.path.join(self.projects_dir, slug)
            
        os.makedirs(proj_dir, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        next_pid = self.get_next_project_id()
        meta = {
            "id": str(next_pid),
            "project_id": next_pid,
            "name": name,
            "slug": slug,
            "url": url,
            "created_at": now,
            "last_activity": now,
            "status": "empty",
            "business_description": business_description,
            "expected_business_outcome": expected_business_outcome
        }
        with open(os.path.join(proj_dir, "project.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)
            
        # Registra no mapa do workspace
        registry = self.load_workspace_registry()
        registry.setdefault("projects", {})[slug] = proj_dir
        self.save_workspace_registry(registry)
            
        # Grava o prompt de instrução do Mentor na pasta do robô
        prompt_file = os.path.join(self.project_root, "aegis_runner", "prompt_template.md")
        prompt_content = ""
        if os.path.exists(prompt_file):
            try:
                with open(prompt_file, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
            except:
                pass
        if not prompt_content:
            prompt_content = """# Instruções para Geração do Robô RPA via Aegis Mentor

Para iniciar o desenvolvimento deste robô de automação, copie e envie o prompt abaixo para a IA em um chat aberto diretamente na pasta deste projeto:

---

## 🤖 Prompt de Inicialização (Copie e cole abaixo)

> **Ative as competências globais 'rpa-copilot-coder' e 'rpa-copilot-analyst' para esta sessão.**
>
> Estou iniciando o desenvolvimento do robô RPA para este projeto. 
> Por favor, examine as especificações locais (project.json, dicionario.json, dataset_inicial.json e relatorio.md) e gere o script de automação correspondente.
"""
        prompt_content = prompt_content.replace("{slug}", slug)
        
        with open(os.path.join(proj_dir, "mentor_prompt.md"), "w", encoding="utf-8") as f:
            f.write(prompt_content)
            
        # Copia o guia de desenvolvimento (playbook) padrão Aegis para a pasta do novo robô
        guide_template_file = os.path.join(self.project_root, "aegis_runner", "rpa_development_guide_template.md")
        guide_content = ""
        if os.path.exists(guide_template_file):
            try:
                with open(guide_template_file, "r", encoding="utf-8") as f:
                    guide_content = f.read()
            except:
                pass
        if not guide_content:
            guide_content = "# 🛡️ Guia Prático de Desenvolvimento RPA Aegis\n\nConsulte a documentação principal da suíte Aegis para as diretrizes de desenvolvimento."
            
        with open(os.path.join(proj_dir, "DEVELOPMENT_GUIDE.md"), "w", encoding="utf-8") as f:
            f.write(guide_content)
            
        # Copia o pacote Wheel (.whl) do aegis_runner para a pasta do novo projeto
        suite_dist = os.path.join(self.project_root, "dist", "aegis_rpa_suite-1.0.0-py3-none-any.whl")
        if os.path.exists(suite_dist):
            proj_dist_dir = os.path.join(proj_dir, "dist")
            os.makedirs(proj_dist_dir, exist_ok=True)
            try:
                shutil.copy(suite_dist, os.path.join(proj_dist_dir, "aegis_rpa_suite-1.0.0-py3-none-any.whl"))
            except Exception as e:
                print(f"[WARNING] Falha ao copiar o arquivo Wheel (.whl): {e}")

        # Cria requirements.txt configurando o path do wheel
        with open(os.path.join(proj_dir, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("playwright>=1.40.0\n./dist/aegis_rpa_suite-1.0.0-py3-none-any.whl\n")

        # Cria arquivo de template .env com suporte cognitivo completo
        env_content = """# ==============================================================================
# CONFIGURAÇÕES DE EXECUÇÃO DO BROWSER (AEGIS RUNNER)
# ==============================================================================
AEGIS_BROWSER_HEADLESS=false
AEGIS_BROWSER_SLOW_MO=50
AEGIS_BROWSER_CHANNEL=msedge

# ==============================================================================
# CONFIGURAÇÕES COGNITIVAS E SELF-HEALING (IA AUTORREPARADORA)
# ==============================================================================
# Ativa o Self-Healing com IA em caso de quebras ou timeouts de seletores
AEGIS_COGNITIVE_ENABLED=true

# Provedor de LLM a ser utilizado ('openrouter', 'litellm' ou 'gemini')
AEGIS_COGNITIVE_PROVIDER=openrouter

# Modelo de IA (Exemplos: 'google/gemini-2.5-flash' para OpenRouter)
AEGIS_COGNITIVE_MODEL=google/gemini-2.5-flash

# Chave de API secreta do provedor (Insira sua chave correspondente)
AEGIS_COGNITIVE_API_KEY=

# URL Base do serviço de LLM (Para OpenRouter ou LiteLLM customizado)
AEGIS_COGNITIVE_BASE_URL=https://openrouter.ai/api/v1

# ==============================================================================
# CREDENCIAIS E DIRETRIZES DO PORTAL (Preencha para evitar hardcode no robô)
# ==============================================================================
PORTAL_USER=
PORTAL_PASSWORD=
"""
        with open(os.path.join(proj_dir, ".env"), "w", encoding="utf-8") as f:
            f.write(env_content)

        # Cria automaticamente o cenário inicial "Cenário Principal"
        self.create_test(slug, "Cenário Principal", "cenario_principal", url=url)

        return meta

    def _remove_readonly(self, func, path, excinfo):
        """Remove o atributo de somente-leitura (comum no Windows) para permitir a exclusão."""
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except:
            pass

    def delete_project(self, slug: str) -> bool:
        """Remove o registro do workspace e o diretório físico completo do projeto."""
        registry = self.load_workspace_registry()
        proj_dir = registry.setdefault("projects", {}).get(slug)
        if not proj_dir:
            proj_dir = os.path.join(self.projects_dir, slug)
            
        if os.path.isdir(proj_dir):
            try:
                shutil.rmtree(proj_dir, onerror=self._remove_readonly)
            except Exception as e:
                raise RuntimeError(f"Falha ao deletar fisicamente o diretório do projeto: {e}")
                
            if os.path.exists(proj_dir):
                raise RuntimeError("O diretório do projeto não pôde ser completamente removido (arquivos bloqueados pelo sistema).")
                
        registry.setdefault("projects", {}).pop(slug, None)
        self.save_workspace_registry(registry)
        return True

    def get_project_dir(self, slug: str) -> str:
        """Retorna o caminho absoluto da pasta física associada ao slug do projeto."""
        registry = self.load_workspace_registry()
        proj_dir = registry.setdefault("projects", {}).get(slug)
        if not proj_dir:
            proj_dir = os.path.join(self.projects_dir, slug)
        return proj_dir

    def migrate_legacy_if_needed(self):
        """
        Se telemetry_data/ contém dados reais (gravacao.json ou telemetry_run.json legado) e
        ainda não foi migrado, cria um projeto de exemplo com esses dados.
        """
        legacy_run_new = os.path.join(self.telemetry_dir, "gravacao.json")
        legacy_run_old = os.path.join(self.telemetry_dir, "telemetry_run.json")
        legacy_flag = os.path.join(self.telemetry_dir, ".migrated")
        legacy_run = legacy_run_new if os.path.exists(legacy_run_new) else legacy_run_old

        if os.path.exists(legacy_run) and not os.path.exists(legacy_flag):
            slug = self.get_unique_slug("exemplo_migrado")
            proj_dir = os.path.join(self.projects_dir, slug)
            os.makedirs(proj_dir, exist_ok=True)

            try:
                with open(legacy_run, "r", encoding="utf-8") as f:
                    legacy_data = json.load(f)
                url = legacy_data.get("initial_url", "")
            except Exception:
                url = ""

            file_renames = {
                "gravacao.json": "gravacao.json",
                "telemetry_run.json": "gravacao.json",
                "dicionario.json": "dicionario.json",
                "aegis_data_dictionary.json": "dicionario.json",
                "dataset_inicial.json": "dataset_inicial.json",
                "aegis_initial_dataset.json": "dataset_inicial.json",
                "template.csv": "template.csv",
                "aegis_data_template.csv": "template.csv",
                "relatorio.md": "relatorio.md",
                "aegis_sanitized_report.md": "relatorio.md",
                "relatorio_validacao.json": "relatorio_validacao.json",
                "aegis_dataset_validation_report.json": "relatorio_validacao.json",
                "exemplo_execution_report.csv": "relatorio_execucao.csv",
                "aegis_execution_report.csv": "relatorio_execucao.csv",
                "exemplo_input_dataset.csv": "dados_entrada.csv",
                "aegis_input_dataset.csv": "dados_entrada.csv",
            }
            status = "empty"
            copied_dests = set()
            for src_name, dest_name in file_renames.items():
                src = os.path.join(self.telemetry_dir, src_name)
                dest = os.path.join(proj_dir, dest_name)
                if os.path.exists(src) and dest_name not in copied_dests:
                    shutil.copy2(src, dest)
                    copied_dests.add(dest_name)
                    if dest_name == "gravacao.json": status = "recorded"
                    if dest_name == "relatorio.md": status = "sanitized"
                    if dest_name == "relatorio_validacao.json": status = "validated"

            now = datetime.now().isoformat(timespec="seconds")
            meta = {
                "name": "[Exemplo] Projeto Migrado - Dados Migrados",
                "slug": slug,
                "url": url,
                "created_at": now,
                "last_activity": now,
                "status": status,
                "note": "Projeto criado automaticamente na migração dos dados legados de telemetry_data/"
            }
            with open(os.path.join(proj_dir, "project.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=4, ensure_ascii=False)

            # Registra no mapa do workspace
            registry = self.load_workspace_registry()
            registry.setdefault("projects", {})[slug] = proj_dir
            self.save_workspace_registry(registry)

            # Marca como migrado para não repetir
            with open(legacy_flag, "w") as f:
                f.write(f"Migrado em {now} para {slug}\n")
            print(f"[AEGIS COCKPIT] Dados legados migrados para o projeto: {slug}")

    def is_legacy_project(self, proj_dir: str) -> bool:
        """Verifica se o projeto é legado (contém arquivos de teste diretamente no root)."""
        legacy_indicators = ["gravacao.json", "bot_producao.py", "relatorio.md", "dicionario.json"]
        return any(os.path.exists(os.path.join(proj_dir, f)) for f in legacy_indicators)

    def migrate_legacy_project(self, project_slug: str):
        """Migra os arquivos de teste do root do projeto para um cenário de teste padrão."""
        proj_dir = self.get_project_dir(project_slug)
        print(f"[AEGIS COCKPIT] Migrando projeto legado: {project_slug}")
        
        proj_json_path = os.path.join(proj_dir, "project.json")
        proj_name = "Cenário Padrão"
        proj_url = ""
        proj_status = "empty"
        proj_created = datetime.now().isoformat(timespec="seconds")
        proj_last = datetime.now().isoformat(timespec="seconds")
        
        if os.path.exists(proj_json_path):
            try:
                with open(proj_json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                proj_url = meta.get("url", "")
                proj_status = meta.get("status", "empty")
                proj_created = meta.get("created_at", proj_created)
                proj_last = meta.get("last_activity", proj_last)
            except:
                pass
                
        test_slug = "cenario_padrao"
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        os.makedirs(test_dir, exist_ok=True)
        
        files_to_move = [
            "gravacao.json",
            "dicionario.json",
            "dataset_inicial.json",
            "relatorio.md",
            "relatorio_validacao.json",
            "bot_producao.py",
            "robot.py",
            "run_bot.py",
            "relatorio_execucao.csv",
            "template.csv",
            "dados_entrada.csv",
            "trace.zip",
        ]
        
        for fname in files_to_move:
            src = os.path.join(proj_dir, fname)
            if os.path.exists(src):
                shutil.move(src, os.path.join(test_dir, fname))
                
        for entry in os.listdir(proj_dir):
            if entry.endswith(".png") and os.path.isfile(os.path.join(proj_dir, entry)):
                shutil.move(os.path.join(proj_dir, entry), os.path.join(test_dir, entry))
                
        test_meta = {
            "name": proj_name,
            "slug": test_slug,
            "url": proj_url,
            "created_at": proj_created,
            "last_activity": proj_last,
            "status": proj_status
        }
        with open(os.path.join(test_dir, "project.json"), "w", encoding="utf-8") as f:
            json.dump(test_meta, f, indent=4, ensure_ascii=False)
            
        proj_env = os.path.join(proj_dir, ".env")
        if os.path.exists(proj_env):
            shutil.copy2(proj_env, os.path.join(test_dir, ".env"))
            
        proj_req = os.path.join(proj_dir, "requirements.txt")
        if os.path.exists(proj_req):
            shutil.copy2(proj_req, os.path.join(test_dir, "requirements.txt"))
            
        proj_dist = os.path.join(proj_dir, "dist")
        if os.path.exists(proj_dist):
            try:
                shutil.copytree(proj_dist, os.path.join(test_dir, "dist"), dirs_exist_ok=True)
            except Exception as e:
                print(f"[WARNING] Erro ao copiar dist para teste: {e}")
            
        if os.path.exists(proj_json_path):
            try:
                with open(proj_json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta.pop("status", None)
                meta["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(proj_json_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=4, ensure_ascii=False)
            except:
                pass

    def list_tests(self, project_slug: str) -> list:
        """Lista todos os testes (cenários) de um projeto."""
        proj_dir = self.get_project_dir(project_slug)
        tests_dir = os.path.join(proj_dir, "tests")
        tests = []
        
        if self.is_legacy_project(proj_dir):
            self.migrate_legacy_project(project_slug)
            
        if os.path.isdir(tests_dir):
            for entry in sorted(os.listdir(tests_dir)):
                test_dir = os.path.join(tests_dir, entry)
                test_json = os.path.join(test_dir, "project.json")
                if os.path.isdir(test_dir) and os.path.exists(test_json):
                    try:
                        with open(test_json, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        
                        # Garante identificador único para o cenário
                        if "test_id" not in meta or "id" not in meta or (isinstance(meta.get("id"), str) and len(meta["id"]) > 10):
                            next_tid = self.get_next_test_id(project_slug)
                            meta["test_id"] = next_tid
                            meta["id"] = str(next_tid)
                            with open(test_json, "w", encoding="utf-8") as wf:
                                json.dump(meta, wf, indent=4, ensure_ascii=False)
                                
                        tests.append(meta)
                    except:
                        pass
        return tests

    def create_test(self, project_slug: str, test_name: str, test_slug: str = None, url: str = "", business_description: str = "", expected_business_outcome: str = "") -> dict:
        """Cria um novo cenário de teste sob um projeto."""
        proj_dir = self.get_project_dir(project_slug)
        tests_dir = os.path.join(proj_dir, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        
        if not test_slug:
            test_slug = self.slugify(test_name)
            
        base_slug = test_slug
        counter = 2
        while os.path.exists(os.path.join(tests_dir, test_slug)):
            test_slug = f"{base_slug}_{counter}"
            counter += 1
            
        test_dir = os.path.join(tests_dir, test_slug)
        os.makedirs(test_dir, exist_ok=True)
        
        now = datetime.now().isoformat(timespec="seconds")
        next_tid = self.get_next_test_id(project_slug)
        meta = {
            "id": str(next_tid),
            "test_id": next_tid,
            "name": test_name,
            "slug": test_slug,
            "url": url,
            "created_at": now,
            "last_activity": now,
            "status": "empty",
            "business_description": business_description,
            "expected_business_outcome": expected_business_outcome
        }
        
        with open(os.path.join(test_dir, "project.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)
            
        proj_env = os.path.join(proj_dir, ".env")
        if os.path.exists(proj_env):
            shutil.copy2(proj_env, os.path.join(test_dir, ".env"))
            
        proj_req = os.path.join(proj_dir, "requirements.txt")
        if os.path.exists(proj_req):
            shutil.copy2(proj_req, os.path.join(test_dir, "requirements.txt"))
            
        proj_dist = os.path.join(proj_dir, "dist")
        if os.path.exists(proj_dist):
            try:
                shutil.copytree(proj_dist, os.path.join(test_dir, "dist"), dirs_exist_ok=True)
            except Exception as e:
                print(f"[WARNING] Erro ao copiar dist para teste: {e}")
            
        self.update_project_activity(project_slug)
        return meta

    def delete_test(self, project_slug: str, test_slug: str) -> bool:
        """Deleta um cenário de teste."""
        proj_dir = self.get_project_dir(project_slug)
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        if os.path.isdir(test_dir):
            try:
                shutil.rmtree(test_dir, onerror=self._remove_readonly)
                self.update_project_activity(project_slug)
                return True
            except Exception as e:
                raise RuntimeError(f"Falha ao deletar fisicamente o cenário de teste: {e}")
        return False

    def update_project_activity(self, project_slug: str):
        proj_dir = self.get_project_dir(project_slug)
        proj_json = os.path.join(proj_dir, "project.json")
        if os.path.exists(proj_json):
            try:
                with open(proj_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(proj_json, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=4, ensure_ascii=False)
            except:
                pass

    def get_skill_dir(self, project_slug: str, skill_slug: str) -> str:
        """Retorna o caminho absoluto da pasta física da Skill."""
        proj_dir = self.get_project_dir(project_slug)
        return os.path.join(proj_dir, "skills", skill_slug)

    def list_skills(self, project_slug: str) -> list:
        """Lista todas as Skills registradas de um projeto."""
        proj_dir = self.get_project_dir(project_slug)
        skills_dir = os.path.join(proj_dir, "skills")
        skills = []
        if os.path.isdir(skills_dir):
            for entry in sorted(os.listdir(skills_dir)):
                s_dir = os.path.join(skills_dir, entry)
                s_json = os.path.join(s_dir, "skill.json")
                if os.path.isdir(s_dir) and os.path.exists(s_json):
                    try:
                        with open(s_json, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        skills.append(meta)
                    except:
                        pass
        return skills

    def promote_to_skill(self, project_slug: str, test_slug: str, skill_name: str, skill_slug: str = None, category: str = "Geral", description: str = "") -> dict:
        """Promove um cenário de teste existente a uma Skill reutilizável no projeto."""
        proj_dir = self.get_project_dir(project_slug)
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        
        if not os.path.exists(test_dir):
            raise FileNotFoundError(f"Cenário de teste '{test_slug}' não encontrado no projeto.")
            
        if not skill_slug:
            skill_slug = self.slugify(skill_name)
            
        # Garante slug único para a Skill
        skills_dir = os.path.join(proj_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        
        base_slug = skill_slug
        counter = 2
        while os.path.exists(os.path.join(skills_dir, skill_slug)):
            skill_slug = f"{base_slug}_{counter}"
            counter += 1
            
        skill_dir = os.path.join(skills_dir, skill_slug)
        os.makedirs(skill_dir, exist_ok=True)
        
        # Copia arquivos estruturais (se existirem)
        files_to_copy = ["gravacao.json", "dicionario.json", "relatorio.md"]
        for fname in files_to_copy:
            src = os.path.join(test_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(skill_dir, fname))
                
        # Extrai parâmetros do dicionário de dados (se houver) para popular a assinatura
        parameters = []
        dict_path = os.path.join(skill_dir, "dicionario.json")
        if os.path.exists(dict_path):
            try:
                with open(dict_path, "r", encoding="utf-8") as f:
                    dict_data = json.load(f)
                inputs = dict_data.get("inputs", [])
                for inp in inputs:
                    parameters.append({
                        "name": inp.get("semantic_key"),
                        "type": inp.get("type", "string"),
                        "description": f"Parâmetro semântico auto-importado: {inp.get('semantic_key')}",
                        "default_observed": inp.get("observed_value", "")
                    })
            except Exception as e:
                print(f"[WARNING] Falha ao extrair parâmetros do dicionário ao promover Skill: {e}")
                
        now = datetime.now().isoformat(timespec="seconds")
        skill_meta = {
            "name": skill_name,
            "slug": skill_slug,
            "description": description,
            "category": category,
            "created_at": now,
            "last_activity": now,
            "parameters": parameters
        }
        
        with open(os.path.join(skill_dir, "skill.json"), "w", encoding="utf-8") as f:
            json.dump(skill_meta, f, indent=4, ensure_ascii=False)
            
        self.update_project_activity(project_slug)
        return skill_meta

    def list_versions(self, project_slug: str, test_slug: str) -> list:
        """Lista todas as versões salvas de um cenário."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        versions_json_path = os.path.join(test_dir, "versions.json")
        if os.path.exists(versions_json_path):
            try:
                with open(versions_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return []

    def create_version(self, project_slug: str, test_slug: str, name: str, description: str, clean: bool = False) -> dict:
        """Cria um snapshot de versão (limpo ou clonado/salvo)."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        versions_dir = os.path.join(test_dir, "versions")
        os.makedirs(versions_dir, exist_ok=True)
        
        versions = self.list_versions(project_slug, test_slug)
        next_num = len(versions) + 1
        version_id = f"v{next_num}"
        
        version_path = os.path.join(versions_dir, version_id)
        os.makedirs(version_path, exist_ok=True)
        
        now = datetime.now().isoformat(timespec="seconds")
        
        if clean:
            # Escreve arquivos zerados na pasta da versão
            with open(os.path.join(version_path, "dicionario.json"), "w", encoding="utf-8") as f:
                json.dump({"fields": {}, "steps": []}, f, indent=4, ensure_ascii=False)
            with open(os.path.join(version_path, "dataset_inicial.json"), "w", encoding="utf-8") as f:
                json.dump([], f, indent=4, ensure_ascii=False)
            
            test_json = os.path.join(test_dir, "project.json")
            test_id = next_num
            if os.path.exists(test_json):
                try:
                    with open(test_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    test_id = meta.get("test_id") or meta.get("id") or next_num
                except:
                    pass
            
            with open(os.path.join(version_path, "project.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "id": test_id,
                    "test_id": test_id,
                    "name": name or f"Versão {next_num}",
                    "slug": test_slug,
                    "status": "empty",
                    "active_version": version_id,
                    "created_at": now
                }, f, indent=4, ensure_ascii=False)
                
            status = "empty"
        else:
            # Arquivos do cenário a serem preservados no snapshot
            files_to_copy = [
                "gravacao.json",
                "dicionario.json",
                "dataset_inicial.json",
                "dados_entrada.csv",
                "template.csv",
                "relatorio.md",
                "relatorio_validacao.json",
                "bot_producao.py",
                "skills_lib.py",
                "project.json"
            ]
            for fname in files_to_copy:
                src = os.path.join(test_dir, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(version_path, fname))
                    
            # Copia todos os prints de tela da pasta de teste (se houver)
            for entry in os.listdir(test_dir):
                if entry.endswith(".png") and os.path.isfile(os.path.join(test_dir, entry)):
                    shutil.copy2(os.path.join(test_dir, entry), os.path.join(version_path, entry))
                    
            status = "empty"
            test_json = os.path.join(test_dir, "project.json")
            if os.path.exists(test_json):
                try:
                    with open(test_json, "r", encoding="utf-8") as f:
                        status = json.load(f).get("status", "empty")
                except:
                    pass
                    
        version_meta = {
            "id": version_id,
            "name": name or f"Versão {next_num}",
            "description": description or ("Criada limpa" if clean else "Criada manualmente"),
            "created_at": now,
            "status": status
        }
        
        versions.append(version_meta)
        versions_json_path = os.path.join(test_dir, "versions.json")
        with open(versions_json_path, "w", encoding="utf-8") as f:
            json.dump(versions, f, indent=4, ensure_ascii=False)
            
        # Restaura a versão imediatamente para o diretório ativo para que venha zerada/limpa no workspace!
        self.restore_version(project_slug, test_slug, version_id)
        
        self.update_project_activity(project_slug)
        return version_meta

    def clone_version(self, project_slug: str, test_slug: str, version_id: str, name: str, description: str) -> dict:
        """Clona uma versão existente para uma nova versão."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        versions_dir = os.path.join(test_dir, "versions")
        src_version_path = os.path.join(versions_dir, version_id)
        if not os.path.exists(src_version_path):
            raise FileNotFoundError(f"Versão de origem {version_id} não encontrada.")
            
        versions = self.list_versions(project_slug, test_slug)
        next_num = len(versions) + 1
        new_version_id = f"v{next_num}"
        
        new_version_path = os.path.join(versions_dir, new_version_id)
        os.makedirs(new_version_path, exist_ok=True)
        
        # Copia todos os arquivos da pasta da versão antiga
        for entry in os.listdir(src_version_path):
            src_file = os.path.join(src_version_path, entry)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, os.path.join(new_version_path, entry))
                
        now = datetime.now().isoformat(timespec="seconds")
        
        # Copia o status da versão de origem
        status = "empty"
        src_meta = next((v for v in versions if v["id"] == version_id), None)
        if src_meta:
            status = src_meta.get("status", "empty")
            
        version_meta = {
            "id": new_version_id,
            "name": name or f"Clone de {version_id}",
            "description": description or f"Clonada de {version_id}",
            "created_at": now,
            "status": status
        }
        
        versions.append(version_meta)
        versions_json_path = os.path.join(test_dir, "versions.json")
        with open(versions_json_path, "w", encoding="utf-8") as f:
            json.dump(versions, f, indent=4, ensure_ascii=False)
            
        # Restaura a nova versão imediatamente
        self.restore_version(project_slug, test_slug, new_version_id)
        
        self.update_project_activity(project_slug)
        return version_meta

    def save_current_version(self, project_slug: str, test_slug: str) -> bool:
        """Salva/sobrescreve os arquivos do workspace ativo de volta na pasta da versão ativa atual."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        test_json = os.path.join(test_dir, "project.json")
        if not os.path.exists(test_json):
            return False
            
        try:
            with open(test_json, "r", encoding="utf-8") as f:
                meta = json.load(f)
            active_version = meta.get("active_version", "draft")
        except:
            active_version = "draft"
            
        if active_version == "draft":
            return True
            
        versions_dir = os.path.join(test_dir, "versions")
        version_path = os.path.join(versions_dir, active_version)
        if not os.path.exists(version_path):
            os.makedirs(version_path, exist_ok=True)
            
        files_to_copy = [
            "gravacao.json",
            "dicionario.json",
            "dataset_inicial.json",
            "dados_entrada.csv",
            "template.csv",
            "relatorio.md",
            "relatorio_validacao.json",
            "bot_producao.py",
            "skills_lib.py",
            "project.json"
        ]
        
        for fname in files_to_copy:
            src = os.path.join(test_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(version_path, fname))
                
        # Copia todos os prints de tela da pasta de teste (se houver)
        for entry in os.listdir(test_dir):
            if entry.endswith(".png") and os.path.isfile(os.path.join(test_dir, entry)):
                shutil.copy2(os.path.join(test_dir, entry), os.path.join(version_path, entry))
                
        # Atualiza status no versions.json se mudou
        versions = self.list_versions(project_slug, test_slug)
        for v in versions:
            if v["id"] == active_version:
                v["status"] = meta.get("status", "empty")
                
        versions_json_path = os.path.join(test_dir, "versions.json")
        with open(versions_json_path, "w", encoding="utf-8") as f:
            json.dump(versions, f, indent=4, ensure_ascii=False)
            
        self.update_project_activity(project_slug)
        return True

    def restore_version(self, project_slug: str, test_slug: str, version_id: str) -> bool:
        """Restaura os arquivos do cenário a partir de um snapshot de versão."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        version_path = os.path.join(test_dir, "versions", version_id)
        
        if not os.path.isdir(version_path):
            raise FileNotFoundError(f"Versão '{version_id}' não encontrada para restauração.")
            
        # Lista de arquivos que devem ser restaurados
        files_to_restore = [
            "gravacao.json",
            "dicionario.json",
            "dataset_inicial.json",
            "dados_entrada.csv",
            "template.csv",
            "relatorio.md",
            "relatorio_validacao.json",
            "bot_producao.py",
            "skills_lib.py",
            "project.json"
        ]
        
        # Remove arquivos antigos do cenário (exceto pastas como versions, executions, dist, etc.)
        for fname in files_to_restore:
            p = os.path.join(test_dir, fname)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except:
                    pass
                    
        # Remove prints antigos
        for entry in os.listdir(test_dir):
            if entry.endswith(".png") and os.path.isfile(os.path.join(test_dir, entry)):
                try:
                    os.remove(os.path.join(test_dir, entry))
                except:
                    pass
                    
        # Copia de volta
        for fname in files_to_restore:
            src = os.path.join(version_path, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(test_dir, fname))
                
        for entry in os.listdir(version_path):
            if entry.endswith(".png") and os.path.isfile(os.path.join(version_path, entry)):
                shutil.copy2(os.path.join(version_path, entry), os.path.join(test_dir, entry))
                
        # Atualiza a marcação da versão ativa atual em project.json
        test_json = os.path.join(test_dir, "project.json")
        if os.path.exists(test_json):
            try:
                with open(test_json, "r", encoding="utf-8") as f:
                    t_meta = json.load(f)
                t_meta["active_version"] = version_id
                t_meta["last_activity"] = datetime.now().isoformat(timespec="seconds")
                with open(test_json, "w", encoding="utf-8") as f:
                    json.dump(t_meta, f, indent=4, ensure_ascii=False)
            except:
                pass
                
        self.update_project_activity(project_slug)
        return True

    def auto_create_version_after_recording(self, project_slug: str, test_slug: str) -> dict:
        """Cria automaticamente uma versão inicial de snapshot após a gravação."""
        versions = self.list_versions(project_slug, test_slug)
        next_num = len(versions) + 1
        name = f"Gravação Auto v{next_num}"
        description = f"Criada automaticamente após finalizar a gravação do fluxo"
        return self.create_version(project_slug, test_slug, name, description)

    def list_executions(self, project_slug: str, test_slug: str) -> list:
        """Lista o histórico de execuções salvas para um cenário."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        executions_json_path = os.path.join(test_dir, "executions.json")
        if os.path.exists(executions_json_path):
            try:
                with open(executions_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return []

    def prepare_execution(self, project_slug: str, test_slug: str, execution_id: str) -> str:
        """Prepara o diretório de execução e cria o registro em executions.json."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        executions_dir = os.path.join(test_dir, "executions")
        exec_dir = os.path.join(executions_dir, execution_id)
        os.makedirs(exec_dir, exist_ok=True)
        
        # Copia arquivos do código fonte atual para a pasta de execução
        # para garantir reprodutibilidade fiel e auditoria do código executado
        for fname in ["bot_producao.py", "skills_lib.py"]:
            src = os.path.join(test_dir, fname)
            if not os.path.exists(src) and not test_slug:
                src = os.path.join(self.get_project_dir(project_slug), fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(exec_dir, fname))
                
        # Tenta identificar qual a versão ativa/mais recente do cenário
        versions = self.list_versions(project_slug, test_slug)
        active_version = None
        
        # Lê de project.json se existe
        test_json = os.path.join(test_dir, "project.json")
        if os.path.exists(test_json):
            try:
                with open(test_json, "r", encoding="utf-8") as f:
                    active_version = json.load(f).get("active_version")
            except:
                pass
                
        if not active_version and versions:
            active_version = versions[-1]["id"]
            
        now = datetime.now().isoformat(timespec="seconds")
        exec_meta = {
            "id": execution_id,
            "timestamp": now,
            "status": "RUNNING",
            "duration_seconds": 0.0,
            "exit_code": None,
            "scenario_version": active_version or "draft"
        }
        
        executions = self.list_executions(project_slug, test_slug)
        executions.append(exec_meta)
        
        executions_json_path = os.path.join(test_dir, "executions.json")
        with open(executions_json_path, "w", encoding="utf-8") as f:
            json.dump(executions, f, indent=4, ensure_ascii=False)
            
        return exec_dir

    def finalize_execution(self, project_slug: str, test_slug: str, execution_id: str, exit_code: int, log_content: str):
        """Finaliza o registro da execução, salvando logs e obtendo estatísticas do relatório CSV."""
        test_dir = os.path.join(self.get_project_dir(project_slug), "tests", test_slug)
        exec_dir = os.path.join(test_dir, "executions", execution_id)
        
        # Salva o arquivo de log da execução
        log_path = os.path.join(exec_dir, "execution.log")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(log_content)
        except Exception as ex:
            print(f"[WARNING] Erro ao gravar execution.log: {ex}")
            
        # Analisa o relatorio_execucao.csv se existir para pegar os detalhes
        report_csv = os.path.join(exec_dir, "relatorio_execucao.csv")
        total_runs = 0
        passed_runs = 0
        status = "FAILED" if exit_code != 0 else "SUCCESS"
        duration = 0.0
        
        if os.path.exists(report_csv):
            try:
                import csv
                with open(report_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                if rows:
                    total_runs = len(rows)
                    passed_rows = [r for r in rows if r.get("status") in ["SUCCESS", "SUCCESS_BLOCKED"]]
                    passed_runs = len(passed_rows)
                    any_fail = any(r.get("status") in ["SYSTEM_FAILED", "FAILED_WRONG_BUSINESS_ERROR", "CRITICAL_UNEXPECTED_SUCCESS"] for r in rows)
                    if any_fail:
                        status = "FAILED"
                    else:
                        status = "SUCCESS"
                    duration = sum(float(r.get("duration_seconds", 0.0)) for r in rows)
            except Exception as ex:
                print(f"[WARNING] Erro ao ler relatorio_execucao.csv: {ex}")
                
        # Atualiza executions.json
        executions_json_path = os.path.join(test_dir, "executions.json")
        if os.path.exists(executions_json_path):
            try:
                with open(executions_json_path, "r", encoding="utf-8") as f:
                    executions = json.load(f)
                    
                for ex in executions:
                    if ex["id"] == execution_id:
                        ex["status"] = status
                        ex["duration_seconds"] = round(duration, 2)
                        ex["exit_code"] = exit_code
                        ex["total_runs"] = total_runs
                        ex["passed_runs"] = passed_runs
                        break
                        
                with open(executions_json_path, "w", encoding="utf-8") as f:
                    json.dump(executions, f, indent=4, ensure_ascii=False)
            except Exception as ex:
                print(f"[WARNING] Erro ao salvar finalização no executions.json: {ex}")

    def clone_test(self, project_slug: str, src_test_slug: str, new_test_name: str) -> dict:
        """Clona um cenário de teste existente com todos os seus dados e histórico."""
        proj_dir = self.get_project_dir(project_slug)
        src_dir = os.path.join(proj_dir, "tests", src_test_slug)
        if not os.path.exists(src_dir):
            raise FileNotFoundError(f"Cenário de origem {src_test_slug} não encontrado.")
            
        new_test_slug = self.slugify(new_test_name)
        
        # Garante slug único do cenário dentro do projeto
        candidate_slug = new_test_slug
        counter = 2
        while os.path.exists(os.path.join(proj_dir, "tests", candidate_slug)):
            candidate_slug = f"{new_test_slug}_{counter}"
            counter += 1
        new_test_slug = candidate_slug
        
        new_dir = os.path.join(proj_dir, "tests", new_test_slug)
        shutil.copytree(src_dir, new_dir)
        
        # Atualiza metadados no novo cenário
        new_id = self.get_next_test_id(project_slug)
        test_json = os.path.join(new_dir, "project.json")
        now = datetime.now().isoformat(timespec="seconds")
        
        if os.path.exists(test_json):
            try:
                with open(test_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["id"] = new_id
                meta["test_id"] = new_id
                meta["name"] = new_test_name
                meta["slug"] = new_test_slug
                meta["created_at"] = now
                meta["last_activity"] = now
                with open(test_json, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=4, ensure_ascii=False)
            except:
                pass
                
        self.update_project_activity(project_slug)
        return {
            "id": new_id,
            "test_id": new_id,
            "name": new_test_name,
            "slug": new_test_slug,
            "created_at": now
        }

    def clone_project(self, src_project_slug: str, new_project_name: str) -> dict:
        """Clona um projeto RPA inteiro com todos os cenários, histórico e scripts."""
        src_dir = self.get_project_dir(src_project_slug)
        if not os.path.exists(src_dir):
            raise FileNotFoundError(f"Projeto de origem {src_project_slug} não encontrado.")
            
        new_slug = self.slugify(new_project_name)
        new_slug = self.get_unique_slug(new_slug)
        
        new_dir = os.path.join(self.projects_dir, new_slug)
        shutil.copytree(src_dir, new_dir)
        
        # Atualiza metadados no novo projeto
        new_id = self.get_next_project_id()
        proj_json = os.path.join(new_dir, "project.json")
        now = datetime.now().isoformat(timespec="seconds")
        
        if os.path.exists(proj_json):
            try:
                with open(proj_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["id"] = str(new_id)
                meta["project_id"] = new_id
                meta["name"] = new_project_name
                meta["slug"] = new_slug
                meta["created_at"] = now
                meta["last_activity"] = now
                with open(proj_json, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=4, ensure_ascii=False)
            except:
                pass
                
        # Registra no registro de workspace central
        registry = self.load_workspace_registry()
        registry["projects"][new_slug] = new_dir
        self.save_workspace_registry(registry)
        
        return {
            "id": str(new_id),
            "project_id": new_id,
            "name": new_project_name,
            "slug": new_slug,
            "created_at": now
        }

    def edit_project(self, project_slug: str, new_name: str, new_business_desc: str, new_expected_outcome: str) -> dict:
        """Edita os detalhes estruturais de um projeto e atualiza o project.json correspondente."""
        proj_dir = self.get_project_dir(project_slug)
        proj_json = os.path.join(proj_dir, "project.json")
        if not os.path.exists(proj_json):
            raise FileNotFoundError(f"Metadados do projeto não encontrados em: {proj_json}")

        with open(proj_json, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["name"] = new_name
        meta["business_description"] = new_business_desc
        meta["expected_business_outcome"] = new_expected_outcome
        meta["last_activity"] = datetime.now().isoformat(timespec="seconds")

        with open(proj_json, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)

        return meta

    def edit_test(self, project_slug: str, test_slug: str, new_name: str, new_business_desc: str, new_expected_outcome: str) -> dict:
        """Edita os detalhes estruturais de um cenário de teste e atualiza o project.json correspondente."""
        proj_dir = self.get_project_dir(project_slug)
        test_dir = os.path.join(proj_dir, "tests", test_slug)
        test_json = os.path.join(test_dir, "project.json")
        if not os.path.exists(test_json):
            raise FileNotFoundError(f"Metadados do cenário não encontrados em: {test_json}")

        with open(test_json, "r", encoding="utf-8") as f:
            meta = json.load(f)

        meta["name"] = new_name
        meta["business_description"] = new_business_desc
        meta["expected_business_outcome"] = new_expected_outcome

        with open(test_json, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4, ensure_ascii=False)

        # Atualiza data de atividade do projeto principal
        self.update_project_activity(project_slug)

        return meta

    def get_devops_config(self, project_slug: str) -> dict:
        """Carrega as configurações do DevOps de um projeto específico."""
        proj_dir = self.get_project_dir(project_slug)
        config_path = os.path.join(proj_dir, "devops_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_devops_config(self, project_slug: str, config_data: dict) -> dict:
        """Salva as configurações do DevOps de um projeto específico."""
        proj_dir = self.get_project_dir(project_slug)
        config_path = os.path.join(proj_dir, "devops_config.json")
        
        # Carrega configuração pré-existente para não sobrescrever tokens mascarados vazios
        existing = self.get_devops_config(project_slug)
        
        # Se vier com chaves mascaradas, restaura o segredo real original
        # Isso previne que o usuário salve "********" por cima do segredo real no disco
        for key in ["pat", "llm_api_key"]:
            val = config_data.get(key)
            if val and all(c == '*' for c in val) and len(val) >= 4:
                config_data[key] = existing.get(key, "")
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
            
        self.update_project_activity(project_slug)
        return config_data


