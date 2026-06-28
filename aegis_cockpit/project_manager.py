import os
import re
import json
import shutil
import stat
import unicodedata
from datetime import datetime

class ProjectManager:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.config_file = os.path.join(project_root, "aegis_config.json")
        
        # Inicializa configurações persistentes
        cfg = self.load_aegis_config()
        self.projects_dir = os.path.abspath(cfg.get("projects_dir", r"C:\Projetos\Lab\projects"))
        self.telemetry_dir = os.path.abspath(cfg.get("telemetry_dir", r"C:\Projetos\Lab\telemetry_data"))
        
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
            "projects_dir": r"C:\Projetos\Lab\projects",
            "telemetry_dir": r"C:\Projetos\Lab\telemetry_data"
        }

    def save_aegis_config(self, cfg: dict):
        """Salva configurações persistentes."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
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
                        
                        meta["tests"] = self.list_tests(entry)
                        projects.append(meta)
                        registry["projects"][entry] = proj_dir
                    except Exception:
                        pass
            self.save_workspace_registry(registry)
            
        return projects

    def create_project(self, name: str, url: str, custom_path: str = "") -> dict:
        """Cria um novo diretório de projeto físico (localizado no projects_dir ou em custom_path)."""
        base_slug = self.slugify(name)
        slug = self.get_unique_slug(base_slug)
        
        if custom_path:
            proj_dir = os.path.abspath(custom_path)
        else:
            proj_dir = os.path.join(self.projects_dir, slug)
            
        os.makedirs(proj_dir, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        meta = {
            "name": name,
            "slug": slug,
            "url": url,
            "created_at": now,
            "last_activity": now,
            "status": "empty"
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
            slug = self.get_unique_slug("exemplo_portal_segura")
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
                "portalsegura_execution_report.csv": "relatorio_execucao.csv",
                "aegis_execution_report.csv": "relatorio_execucao.csv",
                "portalsegura_input_dataset.csv": "dados_entrada.csv",
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
                "name": "[Exemplo] Portal Segura - Dados Migrados",
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
                        tests.append(meta)
                    except:
                        pass
        return tests

    def create_test(self, project_slug: str, test_name: str, test_slug: str = None, url: str = "") -> dict:
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
        meta = {
            "name": test_name,
            "slug": test_slug,
            "url": url,
            "created_at": now,
            "last_activity": now,
            "status": "empty"
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
