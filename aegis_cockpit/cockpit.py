import os
import sys
import json
import re
import shutil
import subprocess
import threading
import argparse
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingTCPServer

sys.stdout.reconfigure(encoding='utf-8')

# ─── Estado Global ────────────────────────────────────────────────────────────
active_process = None
global_logs = []
current_status = "IDLE"
logs_lock = threading.Lock()

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)

CONFIG_FILE = os.path.join(PROJECT_ROOT, "aegis_config.json")

def load_aegis_config() -> dict:
    """Carrega configurações persistentes de diretório de projetos."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "projects_dir": r"C:\Projetos\Lab\projects",
        "telemetry_dir": r"C:\Projetos\Lab\telemetry_data"
    }

def save_aegis_config(cfg: dict):
    """Salva configurações persistentes."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[AEGIS COCKPIT] Erro ao salvar aegis_config.json: {e}")

# Inicializa caminhos ativos de forma dinâmica
config = load_aegis_config()
PROJECTS_DIR = config.get("projects_dir", r"C:\Projetos\Lab\projects")
LEGACY_TELEMETRY_DIR = config.get("telemetry_dir", r"C:\Projetos\Lab\telemetry_data")

os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(LEGACY_TELEMETRY_DIR, exist_ok=True)

WORKSPACE_FILE = os.path.join(LEGACY_TELEMETRY_DIR, "workspace_projects.json")

def update_paths(projects_dir: str, telemetry_dir: str):
    """Atualiza dinamicamente as variáveis de caminho do Cockpit e as persiste."""
    global PROJECTS_DIR, LEGACY_TELEMETRY_DIR, WORKSPACE_FILE
    PROJECTS_DIR = os.path.abspath(projects_dir)
    LEGACY_TELEMETRY_DIR = os.path.abspath(telemetry_dir)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    os.makedirs(LEGACY_TELEMETRY_DIR, exist_ok=True)
    WORKSPACE_FILE = os.path.join(LEGACY_TELEMETRY_DIR, "workspace_projects.json")
    save_aegis_config({"projects_dir": PROJECTS_DIR, "telemetry_dir": LEGACY_TELEMETRY_DIR})

def load_workspace_registry() -> dict:
    """Lê o registro central de projetos mapeados."""
    if os.path.exists(WORKSPACE_FILE):
        try:
            with open(WORKSPACE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"projects": {}}

def save_workspace_registry(registry: dict):
    """Salva o registro central de projetos mapeados."""
    os.makedirs(os.path.dirname(WORKSPACE_FILE), exist_ok=True)
    with open(WORKSPACE_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=4, ensure_ascii=False)

# ─── Gerenciamento de Projetos ────────────────────────────────────────────────

def slugify(name: str) -> str:
    """Converte um nome legível para um slug de diretório seguro."""
    import unicodedata
    # Normaliza unicode (ex: ã→a, ç→c)
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
    # Remove caracteres especiais, substitui espaços e traços por _
    slug = re.sub(r'[^\w\s-]', '', ascii_str).strip().lower()
    slug = re.sub(r'[\s\-]+', '_', slug)
    return slug or "projeto"

def get_unique_slug(base_slug: str) -> str:
    """Garante que o slug seja único dentro de PROJECTS_DIR."""
    candidate = base_slug
    counter = 2
    while os.path.exists(os.path.join(PROJECTS_DIR, candidate)):
        candidate = f"{base_slug}_{counter}"
        counter += 1
    return candidate

def list_projects() -> list:
    """Lista todos os projetos existentes mapeados no workspace."""
    projects = []
    registry = load_workspace_registry()
    
    # Adiciona projetos registrados
    for slug, proj_dir in list(registry.get("projects", {}).items()):
        proj_json = os.path.join(proj_dir, "project.json")
        if os.path.isdir(proj_dir) and os.path.exists(proj_json):
            try:
                with open(proj_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                projects.append(meta)
            except Exception:
                pass
        else:
            # Remove do registro se a pasta física não existe mais
            registry.setdefault("projects", {}).pop(slug, None)
            save_workspace_registry(registry)
            
    # Adiciona pastas locais padrão no PROJECTS_DIR para retrocompatibilidade
    if os.path.isdir(PROJECTS_DIR):
        for entry in sorted(os.listdir(PROJECTS_DIR)):
            proj_dir = os.path.join(PROJECTS_DIR, entry)
            proj_json = os.path.join(proj_dir, "project.json")
            if os.path.isdir(proj_dir) and os.path.exists(proj_json) and entry not in registry.setdefault("projects", {}):
                try:
                    with open(proj_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    projects.append(meta)
                    registry["projects"][entry] = proj_dir
                except Exception:
                    pass
        save_workspace_registry(registry)
        
    return projects

def create_project(name: str, url: str, custom_path: str = "") -> dict:
    """Cria um novo diretório de projeto físico (localizado no PROJECTS_DIR ou em custom_path)."""
    base_slug = slugify(name)
    slug = get_unique_slug(base_slug)
    
    if custom_path:
        proj_dir = os.path.abspath(custom_path)
    else:
        proj_dir = os.path.join(PROJECTS_DIR, slug)
        
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
    registry = load_workspace_registry()
    registry.setdefault("projects", {})[slug] = proj_dir
    save_workspace_registry(registry)
        
    # Grava o prompt de instrução do Mentor na pasta do robô
    prompt_file = os.path.join(PROJECT_ROOT, "aegis_runner", "prompt_template.md")
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
    guide_template_file = os.path.join(PROJECT_ROOT, "aegis_runner", "rpa_development_guide_template.md")
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
    import shutil
    suite_dist = os.path.join(PROJECT_ROOT, "dist", "aegis_rpa_suite-1.0.0-py3-none-any.whl")
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

    # Cria arquivo de template .env com suporte cognitivo completo (OpenRouter, LiteLLM)
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

    # Cria o arquivo README.md explicativo de inicialização
    readme_content = """# 🤖 Projeto RPA Aegis

Este projeto de automação foi gerado com suporte à resiliência e auditoria da suíte **Aegis**.

## ⚙️ Configuração do Ambiente e Execução

Siga as etapas abaixo para configurar o ambiente virtual isolado (`.venv`), instalar as dependências locais e rodar o robô:

### 1. Criar o Ambiente Virtual (`.venv`)
No terminal, navegue até a pasta deste projeto e crie o ambiente isolado do Python:
```bash
python -m venv .venv
```

### 2. Ativar o Ambiente Virtual
* **No Windows (PowerShell):**
  ```powershell
  .venv\\Scripts\\Activate.ps1
  ```
* **No Windows (CMD):**
  ```cmd
  .venv\\Scripts\\activate.bat
  ```
* **No Linux/macOS:**
  ```bash
  source .venv/bin/activate
  ```

### 3. Instalar as Dependências (Incluindo a Biblioteca Aegis local)
Com o ambiente virtual ativo, instale as dependências listadas no `requirements.txt`, que inclui a instalação automatizada da biblioteca Aegis (`.whl` local):
```bash
pip install -r requirements.txt
```

### 4. Inicializar os Navegadores do Playwright
Baixe e instale os binários de navegador requeridos pelo Playwright no seu ambiente virtual:
```bash
playwright install msedge
# ou apenas: playwright install
```

### 5. Configurar as Variáveis de Ambiente
Abra o arquivo `.env` gerado na raiz deste projeto e preencha as variáveis de ambiente e credenciais necessárias para a execução do robô.

### 6. Executar o Robô
Rode o script principal do robô de automação:
```bash
python robot.py
```
"""
    with open(os.path.join(proj_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme_content)
        
    return meta

def _remove_readonly(func, path, excinfo):
    """Remove o atributo de somente-leitura (comum no Windows) para permitir a exclusão."""
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except:
        pass

def delete_project(slug: str) -> bool:
    """Remove o registro do workspace e o diretório físico completo do projeto de forma robusta."""
    global active_process
    if active_process is not None:
        raise RuntimeError("Não é possível deletar projetos enquanto houver um processo em background em execução no Cockpit.")
        
    registry = load_workspace_registry()
    proj_dir = registry.setdefault("projects", {}).get(slug)
    if not proj_dir:
        proj_dir = os.path.join(PROJECTS_DIR, slug)
        
    if os.path.isdir(proj_dir):
        try:
            shutil.rmtree(proj_dir, onerror=_remove_readonly)
        except Exception as e:
            raise RuntimeError(f"Falha ao deletar fisicamente o diretório do projeto: {e}")
            
        if os.path.exists(proj_dir):
            raise RuntimeError("O diretório do projeto não pôde ser completamente removido (arquivos bloqueados pelo sistema).")
            
    registry.setdefault("projects", {}).pop(slug, None)
    save_workspace_registry(registry)
    return True

def get_project_dir(slug: str) -> str:
    """Retorna o caminho absoluto da pasta física associada ao slug do projeto."""
    registry = load_workspace_registry()
    proj_dir = registry.setdefault("projects", {}).get(slug)
    if proj_dir:
        return proj_dir
    return os.path.join(PROJECTS_DIR, slug)

def migrate_legacy_if_needed():
    """
    Se telemetry_data/ contém dados reais (gravacao.json ou telemetry_run.json legado) e
    ainda não foi migrado, cria um projeto de exemplo com esses dados.
    """
    # Aceita tanto o nome novo quanto o legado da telemetria bruta
    legacy_run_new = os.path.join(LEGACY_TELEMETRY_DIR, "gravacao.json")
    legacy_run_old = os.path.join(LEGACY_TELEMETRY_DIR, "telemetry_run.json")
    legacy_flag = os.path.join(LEGACY_TELEMETRY_DIR, ".migrated")
    legacy_run = legacy_run_new if os.path.exists(legacy_run_new) else legacy_run_old

    if os.path.exists(legacy_run) and not os.path.exists(legacy_flag):
        slug = get_unique_slug("exemplo_portal_segura")
        proj_dir = os.path.join(PROJECTS_DIR, slug)
        os.makedirs(proj_dir, exist_ok=True)

        # Detecta URL do arquivo de gravação bruta
        try:
            with open(legacy_run, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            url = legacy_data.get("initial_url", "")
        except Exception:
            url = ""

        # Mapa: nome antigo (telemetry_data/) -> nome novo (dentro do projeto)
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
            src = os.path.join(LEGACY_TELEMETRY_DIR, src_name)
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

        # Marca como migrado para não repetir
        with open(legacy_flag, "w") as f:
            f.write(f"Migrado em {now} para {slug}\n")
        print(f"[AEGIS COCKPIT] Dados legados migrados para o projeto: {slug}")

# ─── Processos em Background ──────────────────────────────────────────────────

def run_command_in_background(cmd, status_name, cwd=PROJECT_ROOT, project_slug=None):
    global active_process, global_logs, current_status
    with logs_lock:
        global_logs.clear()
        global_logs.append(f"[AEGIS COCKPIT] Iniciando: {' '.join(cmd)}\n")
        global_logs.append("-" * 70 + "\n")

    current_status = status_name

    try:
        active_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
            cwd=cwd
        )

        def log_reader():
            global active_process, current_status
            try:
                while True:
                    if active_process is None:
                        break
                    line = active_process.stdout.readline()
                    if not line:
                        break
                    with logs_lock:
                        global_logs.append(line)
                if active_process is not None:
                    exit_code = active_process.wait()
                    with logs_lock:
                        global_logs.append("-" * 70 + "\n")
                        global_logs.append(f"[AEGIS COCKPIT] Processo concluído com código: {exit_code}\n")
                    
                    # Atualiza o status do projeto se a execução do robô terminar com sucesso
                    if status_name == "EXECUÇÃO_ROBÔ" and exit_code == 0 and project_slug:
                        proj_dir = get_project_dir(project_slug)
                        proj_json_path = os.path.join(proj_dir, "project.json")
                        if os.path.exists(proj_json_path):
                            try:
                                with open(proj_json_path, "r", encoding="utf-8") as f:
                                    proj = json.load(f)
                                proj["status"] = "executed"
                                proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                                with open(proj_json_path, "w", encoding="utf-8") as f:
                                    json.dump(proj, f, indent=4, ensure_ascii=False)
                            except Exception as e:
                                print(f"[WARNING] Não foi possível atualizar status para executed: {e}")
            except Exception as e:
                with logs_lock:
                    global_logs.append(f"[AEGIS COCKPIT] Erro: {e}\n")
            finally:
                current_status = "IDLE"
                active_process = None

        t = threading.Thread(target=log_reader, daemon=True)
        t.start()

    except Exception as e:
        with logs_lock:
            global_logs.append(f"[AEGIS COCKPIT] Erro crítico: {e}\n")
        current_status = "IDLE"
        active_process = None

# ─── Frontend HTML (SPA 3 Colunas) ────────────────────────────────────────────
HTML_CONTENT = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🛡️ Aegis RPA Suite Cockpit</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #070714;
            --sidebar-bg: rgba(10,10,25,0.9);
            --card-bg: rgba(18,18,38,0.7);
            --card-border: rgba(124,58,237,0.2);
            --card-border-hover: rgba(124,58,237,0.5);
            --primary: #7c3aed;
            --primary-glow: rgba(124,58,237,0.35);
            --accent: #d946ef;
            --accent-glow: rgba(217,70,239,0.35);
            --text: #f1f5f9;
            --text-muted: #64748b;
            --success: #10b981;
            --warning: #f59e0b;
            --error: #ef4444;
            --info: #3b82f6;
            --sidebar-w: 260px;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; overflow: hidden; }
        body {
            background: var(--bg);
            background-image:
                radial-gradient(at 0% 0%, rgba(124,58,237,0.07) 0, transparent 55%),
                radial-gradient(at 100% 100%, rgba(217,70,239,0.07) 0, transparent 55%);
            color: var(--text);
            font-family: 'Outfit', sans-serif;
            display: flex;
            flex-direction: column;
        }

        /* ── Header ── */
        header {
            flex: 0 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 20px;
            border-bottom: 1px solid rgba(124,58,237,0.15);
            background: rgba(5,5,15,0.6);
            backdrop-filter: blur(10px);
            z-index: 10;
        }
        .logo { font-size: 18px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .logo span { color: var(--accent); }
        .header-right { display: flex; align-items: center; gap: 10px; }
        .status-badge {
            display: inline-flex; align-items: center; gap: 5px;
            padding: 4px 10px; border-radius: 20px;
            font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;
            transition: all 0.3s;
        }
        .badge-dot { width: 6px; height: 6px; border-radius: 50%; }
        .status-idle { background: rgba(16,185,129,0.1); color: var(--success); border: 1px solid rgba(16,185,129,0.3); }
        .status-idle .badge-dot { background: var(--success); }
        .status-active { background: rgba(245,158,11,0.1); color: var(--warning); border: 1px solid rgba(245,158,11,0.4); animation: pulse-badge 1.8s infinite alternate; }
        .status-active .badge-dot { background: var(--warning); animation: pulse-dot 1s infinite; }
        @keyframes pulse-badge { 0% { box-shadow: 0 0 5px rgba(245,158,11,0.1); } 100% { box-shadow: 0 0 15px rgba(245,158,11,0.5); } }
        @keyframes pulse-dot { 0%,100% { opacity:1; } 50% { opacity:0.3; } }

        /* ── Layout Principal ── */
        .main-layout {
            flex: 1 1 auto;
            display: grid;
            grid-template-columns: var(--sidebar-w) 1fr 1.4fr;
            overflow: hidden;
        }

        /* ── Sidebar de Projetos ── */
        .sidebar {
            background: var(--sidebar-bg);
            border-right: 1px solid rgba(124,58,237,0.15);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .sidebar-header {
            padding: 14px 12px 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .sidebar-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); }
        .btn-new-project {
            background: var(--primary);
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 4px;
            transition: all 0.15s;
        }
        .btn-new-project:hover { filter: brightness(1.15); transform: translateY(-1px); }
        .projects-list { flex: 1; overflow-y: auto; padding: 8px; }
        .projects-list::-webkit-scrollbar { width: 4px; }
        .projects-list::-webkit-scrollbar-track { background: transparent; }
        .projects-list::-webkit-scrollbar-thumb { background: rgba(124,58,237,0.3); border-radius: 2px; }

        .project-card {
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.05);
            margin-bottom: 6px;
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
        }
        .project-card:hover { background: rgba(124,58,237,0.08); border-color: rgba(124,58,237,0.25); }
        .project-card.active {
            background: rgba(124,58,237,0.12);
            border-color: var(--primary);
            box-shadow: 0 0 12px rgba(124,58,237,0.15);
        }
        .proj-name { font-size: 12px; font-weight: 600; color: #fff; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 20px; }
        .proj-url { font-size: 10px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 6px; }
        .proj-footer { display: flex; align-items: center; justify-content: space-between; }
        .status-pill {
            font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
            padding: 2px 7px; border-radius: 10px;
        }
        .pill-empty { background: rgba(100,116,139,0.2); color: var(--text-muted); }
        .pill-recorded { background: rgba(59,130,246,0.15); color: var(--info); }
        .pill-sanitized { background: rgba(217,70,239,0.15); color: var(--accent); }
        .pill-validated { background: rgba(16,185,129,0.15); color: var(--success); }
        .pill-generated { background: rgba(236,72,153,0.2); color: #f472b6; border: 1px solid rgba(236,72,153,0.4); }
        .pill-executed { background: rgba(16,185,129,0.25); color: #10b981; border: 1px solid rgba(16,185,129,0.4); }
        .proj-date { font-size: 9px; color: var(--text-muted); }
        .btn-delete-proj {
            position: absolute; top: 8px; right: 8px;
            background: none; border: none; color: var(--text-muted);
            cursor: pointer; font-size: 12px; padding: 2px; line-height: 1;
            opacity: 0; transition: opacity 0.15s;
        }
        .project-card:hover .btn-delete-proj { opacity: 1; }
        .btn-delete-proj:hover { color: var(--error); }

        .no-projects { padding: 30px 12px; text-align: center; color: var(--text-muted); font-size: 12px; }

        /* ── Coluna Central ── */
        .col-center {
            display: flex;
            flex-direction: column;
            border-right: 1px solid rgba(124,58,237,0.1);
            overflow: hidden;
            padding: 14px;
            gap: 12px;
        }

        .active-project-banner {
            background: rgba(124,58,237,0.1);
            border: 1px solid rgba(124,58,237,0.25);
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 11px;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .active-project-banner strong { color: var(--accent); }
        .banner-no-project { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.2); color: rgba(239,68,68,0.8); }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 14px;
            backdrop-filter: blur(12px);
            transition: border-color 0.2s;
        }
        .card:hover { border-color: var(--card-border-hover); }
        .card-title {
            font-size: 13px; font-weight: 600; color: #fff;
            margin-bottom: 12px;
            display: flex; align-items: center; gap: 6px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 8px;
        }

        .ops-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }

        label {
            display: block; font-size: 10px; color: var(--text-muted);
            text-transform: uppercase; font-weight: 600; margin-bottom: 5px;
        }
        input, select {
            width: 100%;
            background: rgba(5,5,15,0.8);
            border: 1px solid rgba(124,58,237,0.3);
            border-radius: 6px;
            padding: 8px 10px;
            color: var(--text);
            font-family: inherit;
            font-size: 12px;
            outline: none;
            transition: all 0.2s;
        }
        input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 8px rgba(217,70,239,0.2); }

        .btn {
            background: var(--primary);
            color: #fff;
            border: none; border-radius: 6px;
            padding: 9px 14px;
            font-weight: 600; font-size: 11px;
            cursor: pointer;
            display: inline-flex; align-items: center; justify-content: center; gap: 5px;
            transition: all 0.15s;
            box-shadow: 0 2px 8px var(--primary-glow);
            width: 100%;
        }
        .btn:hover { transform: translateY(-1.5px); filter: brightness(1.1); }
        .btn:active { transform: translateY(0.5px); }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none !important; }
        .btn-accent { background: var(--accent); box-shadow: 0 2px 8px var(--accent-glow); }
        .btn-blue { background: var(--info); box-shadow: 0 2px 8px rgba(59,130,246,0.3); }
        .btn-stop { background: var(--error); box-shadow: 0 2px 8px rgba(239,68,68,0.3); }
        .btn-sm { padding: 4px 10px; font-size: 10px; width: auto; }

        /* URL editável */
        .url-row { display: flex; gap: 8px; align-items: flex-end; }
        .url-row input { flex: 1; }
        #btn-start-record { flex: 0 0 auto; width: auto; }

        /* Terminal */
        .terminal-header { display: flex; justify-content: space-between; align-items: center; }
        .terminal-header .card-title { margin-bottom: 0; border: none; padding: 0; }
        .terminal-actions { display: flex; gap: 5px; }
        .terminal-box {
            background: #020208;
            border: 1px solid #1a1a35;
            border-radius: 8px;
            padding: 12px;
            font-family: 'Fira Code', monospace;
            color: #00ffcc;
            height: 240px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-size: 10.5px;
            margin-top: 10px;
            line-height: 1.55;
            box-shadow: inset 0 4px 20px rgba(0,0,0,0.8);
        }
        .terminal-box::-webkit-scrollbar { width: 4px; }
        .terminal-box::-webkit-scrollbar-thumb { background: rgba(0,255,204,0.2); border-radius: 2px; }

        /* ── Coluna Direita (Visualizadores) ── */
        .col-right {
            display: flex;
            flex-direction: column;
            overflow: hidden;
            padding: 14px;
        }
        .tabs-header {
            display: flex; gap: 3px;
            border-bottom: 1px solid rgba(124,58,237,0.2);
            margin-bottom: 12px;
            flex-shrink: 0;
        }
        .tab-btn {
            background: none; border: none; border-bottom: 2px solid transparent;
            color: var(--text-muted);
            padding: 7px 13px; cursor: pointer;
            font-family: inherit; font-size: 11px; font-weight: 600;
            transition: all 0.2s;
        }
        .tab-btn:hover { color: #fff; }
        .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
        .tab-content { display: none; flex: 1; overflow-y: auto; min-height: 0; }
        .tab-content.active { display: block; }
        .tab-content::-webkit-scrollbar { width: 4px; }
        .tab-content::-webkit-scrollbar-thumb { background: rgba(124,58,237,0.3); border-radius: 2px; }

        /* Tabelas */
        .table-wrap { overflow-x: auto; border-radius: 6px; border: 1px solid rgba(124,58,237,0.12); }
        table { width: 100%; border-collapse: collapse; font-size: 11px; text-align: left; background: rgba(5,5,15,0.4); }
        th { background: rgba(124,58,237,0.12); color: #fff; padding: 8px 10px; font-weight: 600; border-bottom: 1px solid rgba(124,58,237,0.2); }
        td { padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.03); color: #d1d5db; }
        tr:hover { background: rgba(124,58,237,0.04); }
        code { font-family: 'Fira Code', monospace; background: rgba(217,70,239,0.1); color: var(--accent); padding: 1px 5px; border-radius: 3px; font-size: 10px; }
        .empty-msg { color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 20px; border: 1px dashed rgba(124,58,237,0.1); border-radius: 6px; }

        /* Relatório MD 2 colunas */
        .report-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 20px; }
        @media (max-width: 1400px) { .report-grid { grid-template-columns: 1fr; } }

        /* Firewall */
        .firewall-summary { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 12px; }
        .metric-card { background: rgba(5,5,15,0.6); border: 1px solid rgba(124,58,237,0.15); border-radius: 8px; padding: 10px; text-align: center; }
        .metric-label { font-size: 9px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px; }
        .metric-value { font-size: 22px; font-weight: 700; }
        .v-ok { color: var(--success); }
        .v-err { color: var(--error); }
        .v-neutral { color: #fff; }
        .status-box { padding: 10px 14px; border-radius: 6px; font-size: 12px; margin-bottom: 12px; }
        .box-ok { background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25); color: var(--success); }
        .box-err { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25); color: var(--error); }
        .failure-item { padding: 8px; border-bottom: 1px dashed rgba(239,68,68,0.15); }
        .failure-item:last-child { border: none; }

        /* ── Modal ── */
        .modal-overlay {
            display: none; position: fixed; inset: 0;
            background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
            z-index: 1000; align-items: center; justify-content: center;
        }
        .modal-overlay.open { display: flex; }
        .modal {
            background: #0e0e24;
            border: 1px solid rgba(124,58,237,0.35);
            border-radius: 12px;
            padding: 24px;
            width: 420px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.6);
        }
        .modal h3 { font-size: 16px; margin-bottom: 16px; color: #fff; }
        .modal .form-group { margin-bottom: 14px; }
        .modal-actions { display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end; }
        .btn-ghost { background: transparent; border: 1px solid rgba(255,255,255,0.15); color: var(--text-muted); box-shadow: none; width: auto; }
        .btn-ghost:hover { border-color: rgba(255,255,255,0.3); color: #fff; }
    </style>
</head>
<body>

    <header>
        <div class="logo">🛡️ <span>Aegis</span> RPA Suite Cockpit</div>
        <div class="header-right">
            <button id="btn-install-browsers" class="btn btn-ghost" style="font-size: 11px; padding: 4px 10px; margin-right: 10px; cursor: pointer;" title="Baixar/Instalar navegadores necessários via Playwright CLI">🌐 Playwright Install</button>
            <div id="badge-status" class="status-badge status-idle">
                <span class="badge-dot"></span>Ocioso
            </div>
        </div>
    </header>

    <div class="main-layout">

        <!-- ── Sidebar de Projetos ── -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <span class="sidebar-title">Projetos RPA</span>
                <button class="btn-new-project" id="btn-open-modal">+ Novo</button>
            </div>
            <div class="projects-list" id="projects-list">
                <div class="no-projects">Nenhum projeto encontrado.<br>Crie um novo para começar.</div>
            </div>
            <!-- Configurações de Workspace -->
            <div style="padding: 12px; border-top: 1px solid rgba(124,58,237,0.15); background: rgba(5,5,10,0.4);">
                <label style="font-size: 9px; margin-bottom: 4px; display: block; color: var(--text-muted);">DIRETÓRIO DO WORKSPACE (BASE)</label>
                <div style="display: flex; gap: 6px;">
                    <input type="text" id="cfg-projects-dir" placeholder="Carregando..." style="padding: 5px 8px; font-size: 11px;" title="Caminho raiz onde seus robôs serão salvos por padrão" />
                    <button id="btn-save-cfg" class="btn btn-sm" style="width: auto; padding: 0 8px;" title="Salvar Workspace">💾</button>
                </div>
            </div>
        </aside>

        <!-- ── Coluna Central: Operações + Terminal ── -->
        <div class="col-center">

            <div id="active-banner" class="active-project-banner banner-no-project">
                ⚠️ Nenhum projeto selecionado. Selecione ou crie um projeto na sidebar.
            </div>

            <div class="card">
                <div class="card-title">🕹️ Painel de Operações</div>

                <div style="margin-bottom:12px;">
                    <label for="record-url">URL de Gravação</label>
                    <div class="url-row">
                        <input type="text" id="record-url" placeholder="Selecione um projeto para carregar a URL" readonly />
                        <button id="btn-start-record" class="btn" style="min-width:120px;" disabled>⏺️ Gravar Voo</button>
                    </div>
                </div>

                <div class="ops-grid">
                    <div>
                        <label>Fase 2: Compactador</label>
                        <p style="font-size:10px;color:var(--text-muted);margin:3px 0 8px;">Sanitiza logs e gera o dicionário.</p>
                        <button id="btn-run-sanitizer" class="btn btn-accent" disabled>⚡ Sanitizar Logs</button>
                    </div>
                    <div>
                        <label>Fase 3: Dataset Firewall</label>
                        <p style="font-size:10px;color:var(--text-muted);margin:3px 0 8px;">Valida registros contra o dicionário.</p>
                        <button id="btn-run-validator" class="btn btn-blue" disabled>🔍 Validar Carga</button>
                    </div>
                    <div>
                        <label>Fase 4: Gerador de Código</label>
                        <p style="font-size:10px;color:var(--text-muted);margin:3px 0 8px;">Gera o robô resiliente via IA.</p>
                        <button id="btn-run-generator" class="btn btn-accent" style="background: linear-gradient(135deg, #ec4899 0%, #be185d 100%);" disabled>🤖 Gerar Robô</button>
                    </div>
                    <div>
                        <label>Fase 5: Aegis Runner</label>
                        <p style="font-size:10px;color:var(--text-muted);margin:3px 0 8px;">Executa o robô de produção em lote.</p>
                        <button id="btn-run-bot" class="btn" style="background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);" disabled>🚀 Executar Robô</button>
                    </div>
                </div>
            </div>

            <div class="card" style="flex:1;display:flex;flex-direction:column;min-height:0;">
                <div class="terminal-header">
                    <div class="card-title">📟 Terminal de Execução</div>
                    <div class="terminal-actions">
                        <button id="btn-stop-proc" class="btn btn-stop btn-sm" disabled>⏹ Parar</button>
                        <button id="btn-clear-logs" class="btn btn-sm" style="background:#374151;box-shadow:none;">Limpar</button>
                    </div>
                </div>
                <div id="terminal" class="terminal-box">Aguardando disparo de tarefas...</div>
            </div>
        </div>

        <!-- ── Coluna Direita: Visualizadores ── -->
        <div class="col-right">
            <div class="tabs-header">
                <button class="tab-btn active" onclick="switchTab(event,'tab-dict')">📋 Dicionário</button>
                <button class="tab-btn" onclick="switchTab(event,'tab-dataset')">📊 Dataset</button>
                <button class="tab-btn" onclick="switchTab(event,'tab-report')">📝 Relatório</button>
                <button class="tab-btn" onclick="switchTab(event,'tab-validation')">🛡️ Firewall</button>
            </div>

            <div id="tab-dict" class="tab-content active"><div id="dict-view" class="empty-msg">Selecione um projeto para visualizar o dicionário.</div></div>
            <div id="tab-dataset" class="tab-content"><div id="dataset-view" class="empty-msg">Selecione um projeto para visualizar o dataset.</div></div>
            <div id="tab-report" class="tab-content"><div id="report-view" class="empty-msg">Selecione um projeto para visualizar o relatório.</div></div>
            <div id="tab-validation" class="tab-content"><div id="validation-view" class="empty-msg">Selecione um projeto para visualizar o relatório de validação.</div></div>
        </div>
    </div>

    <!-- ── Modal: Novo Projeto ── -->
    <div class="modal-overlay" id="modal-overlay">
        <div class="modal">
            <h3>➕ Novo Projeto RPA</h3>
            <div class="form-group">
                <label for="modal-proj-name">Nome do Projeto</label>
                <input type="text" id="modal-proj-name" placeholder="Ex: Portal Segura - Cotação PF" />
            </div>
            <div class="form-group">
                <label for="modal-proj-url">URL de Gravação</label>
                <input type="text" id="modal-proj-url" placeholder="Ex: http://localhost:5173/?e2e=true" />
            </div>
            <div class="form-group">
                <label for="modal-proj-path">Caminho Físico de Destino (Opcional)</label>
                <input type="text" id="modal-proj-path" placeholder="Ex: C:\\Projetos\\Lab\\projects\\meu-bot (Em branco usa padrão)" />
                <div id="modal-path-preview" style="font-size: 11px; color: var(--accent); margin-top: 8px; font-family: 'Fira Code', monospace; word-break: break-all; opacity: 0.9;"></div>
            </div>
            <div class="modal-actions">
                <button class="btn btn-ghost btn-sm" id="btn-close-modal">Cancelar</button>
                <button class="btn btn-sm" id="btn-confirm-create" style="width:auto;">✅ Criar Projeto</button>
            </div>
        </div>
    </div>

    <script>
        // ── Estado ──
        let activeProjectSlug = localStorage.getItem('aegis_active_project') || null;
        let logsOffset = 0;
        let logsInterval = null;
        let allProjects = [];

        // ── Utilities ──
        function updateStatusBadge(status, isRunning) {
            const badge = document.getElementById('badge-status');
            const stopBtn = document.getElementById('btn-stop-proc');
            if (isRunning) {
                badge.className = 'status-badge status-active';
                badge.innerHTML = '<span class="badge-dot"></span>' + status;
                stopBtn.disabled = false;
            } else {
                badge.className = 'status-badge status-idle';
                badge.innerHTML = '<span class="badge-dot"></span>Ocioso';
                stopBtn.disabled = true;
            }
        }

        function switchTab(evt, tabId) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            evt.currentTarget.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }

        function fmtDate(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'});
        }

        function pillFor(status) {
            const map = { 
                empty: 'pill-empty', 
                recorded: 'pill-recorded', 
                sanitized: 'pill-sanitized', 
                validated: 'pill-validated',
                generated: 'pill-generated',
                executed: 'pill-executed'
            };
            const label = { 
                empty: 'Novo', 
                recorded: 'Gravado', 
                sanitized: 'Sanitizado', 
                validated: 'Validado',
                generated: 'Gerado',
                executed: 'Executado'
            };
            return `<span class="status-pill ${map[status]||'pill-empty'}">${label[status]||status}</span>`;
        }

        // ── Sidebar de Projetos ──
        function renderProjects(projects) {
            allProjects = projects;
            const list = document.getElementById('projects-list');
            if (!projects.length) {
                list.innerHTML = '<div class="no-projects">Nenhum projeto encontrado.<br>Crie um novo para começar.</div>';
                return;
            }
            list.innerHTML = projects.map(p => `
                <div class="project-card ${p.slug === activeProjectSlug ? 'active' : ''}"
                     id="pcard-${p.slug}" onclick="selectProject('${p.slug}')">
                    <button class="btn-delete-proj" onclick="event.stopPropagation(); confirmDeleteProject('${p.slug}')">🗑</button>
                    <div class="proj-name" title="${p.name}">${p.name}</div>
                    <div class="proj-url" title="${p.url}">${p.url || '—'}</div>
                    <div class="proj-footer">
                        ${pillFor(p.status)}
                        <span class="proj-date">${fmtDate(p.last_activity)}</span>
                    </div>
                </div>
            `).join('');
        }

        function loadProjects() {
            fetch('/api/projects')
                .then(r => r.json())
                .then(data => {
                    renderProjects(data.projects || []);
                    // Se projeto ativo não existe mais, desseleciona
                    if (activeProjectSlug && !(data.projects||[]).find(p => p.slug === activeProjectSlug)) {
                        activeProjectSlug = null;
                        localStorage.removeItem('aegis_active_project');
                    }
                    updateActiveUI();
                    if (activeProjectSlug) loadTelemetryData(activeProjectSlug);
                });
        }

        function selectProject(slug) {
            activeProjectSlug = slug;
            localStorage.setItem('aegis_active_project', slug);
            document.querySelectorAll('.project-card').forEach(c => c.classList.remove('active'));
            const card = document.getElementById('pcard-' + slug);
            if (card) card.classList.add('active');
            updateActiveUI();
            loadTelemetryData(slug);
        }

        function updateActiveUI() {
            const banner = document.getElementById('active-banner');
            const urlInput = document.getElementById('record-url');
            const btns = [
                document.getElementById('btn-start-record'),
                document.getElementById('btn-run-sanitizer'),
                document.getElementById('btn-run-validator'),
                document.getElementById('btn-run-generator'),
            ];
            const runBotBtn = document.getElementById('btn-run-bot');
            if (activeProjectSlug) {
                const proj = allProjects.find(p => p.slug === activeProjectSlug);
                const name = proj ? proj.name : activeProjectSlug;
                const url = proj ? (proj.url || '') : '';
                banner.className = 'active-project-banner';
                banner.innerHTML = `📁 Projeto ativo: <strong>${name}</strong>`;
                urlInput.value = url;
                urlInput.removeAttribute('readonly');
                btns.forEach(b => b.disabled = false);
                if (runBotBtn) runBotBtn.disabled = true; // Será habilitado por loadTelemetryData se tiver bot
            } else {
                banner.className = 'active-project-banner banner-no-project';
                banner.innerHTML = '⚠️ Nenhum projeto selecionado. Selecione ou crie um projeto na sidebar.';
                urlInput.value = '';
                urlInput.setAttribute('readonly', 'readonly');
                btns.forEach(b => b.disabled = true);
                if (runBotBtn) runBotBtn.disabled = true;
            }
        }

        function confirmDeleteProject(slug) {
            const proj = allProjects.find(p => p.slug === slug);
            const name = proj ? proj.name : slug;
            if (confirm(`Remover o projeto "${name}" e todos os seus dados?\nEsta ação não pode ser desfeita.`)) {
                fetch('/api/projects/' + encodeURIComponent(slug), { method: 'DELETE' })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            if (activeProjectSlug === slug) {
                                activeProjectSlug = null;
                                localStorage.removeItem('aegis_active_project');
                                clearVisualizers();
                            }
                            loadProjects();
                        } else {
                            alert(data.message);
                        }
                    });
            }
        }

        // ── Modal & Configurações de Workspace ──
        let defaultProjectsDir = '';

        function slugify(name) {
            return name.toString().toLowerCase()
                .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // remove acentos
                .replace(/[^\\w\\s-]/g, '')
                .replace(/[\\s_-]+/g, '_')
                .trim();
        }

        function fetchConfig() {
            fetch('/api/config')
                .then(r => r.json())
                .then(data => {
                    defaultProjectsDir = data.projects_dir;
                    const input = document.getElementById('cfg-projects-dir');
                    if (input) input.value = defaultProjectsDir;
                    updatePathPreview();
                });
        }

        function updatePathPreview() {
            const name = document.getElementById('modal-proj-name').value.trim();
            const customPath = document.getElementById('modal-proj-path').value.trim();
            const previewDiv = document.getElementById('modal-path-preview');
            
            if (!previewDiv) return;
            
            if (customPath) {
                previewDiv.innerText = '📁 Salvar em: ' + customPath;
            } else if (name) {
                const slug = slugify(name);
                const separator = defaultProjectsDir.includes('/') ? '/' : '\\\\';
                previewDiv.innerText = '📁 Salvar em: ' + defaultProjectsDir + separator + slug;
            } else {
                previewDiv.innerText = '📁 Salvar em: ' + defaultProjectsDir + (defaultProjectsDir.includes('/') ? '/' : '\\\\') + '[slug_do_projeto]';
            }
        }

        document.getElementById('modal-proj-name').addEventListener('input', updatePathPreview);
        document.getElementById('modal-proj-path').addEventListener('input', updatePathPreview);

        document.getElementById('btn-save-cfg').addEventListener('click', () => {
            const projects_dir = document.getElementById('cfg-projects-dir').value.trim();
            if (!projects_dir) return alert('O diretório de projetos não pode ser vazio.');
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ projects_dir })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Diretório do Workspace atualizado com sucesso!');
                    fetchConfig();
                    loadProjects();
                } else {
                    alert(data.message);
                }
            });
        });

        document.getElementById('btn-open-modal').addEventListener('click', () => {
            document.getElementById('modal-overlay').classList.add('open');
            document.getElementById('modal-proj-name').focus();
            fetchConfig(); // Garante o caminho mais atualizado ao abrir
        });
        document.getElementById('btn-close-modal').addEventListener('click', () => {
            document.getElementById('modal-overlay').classList.remove('open');
        });
        document.getElementById('modal-overlay').addEventListener('click', e => {
            if (e.target === document.getElementById('modal-overlay'))
                document.getElementById('modal-overlay').classList.remove('open');
        });
        document.getElementById('btn-confirm-create').addEventListener('click', () => {
            const name = document.getElementById('modal-proj-name').value.trim();
            const url = document.getElementById('modal-proj-url').value.trim();
            const custom_path = document.getElementById('modal-proj-path').value.trim();
            if (!name) { alert('Por favor, informe o nome do projeto.'); return; }
            fetch('/api/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, url, custom_path })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('modal-overlay').classList.remove('open');
                    document.getElementById('modal-proj-name').value = '';
                    document.getElementById('modal-proj-url').value = '';
                    document.getElementById('modal-proj-path').value = '';
                    loadProjects();
                    setTimeout(() => selectProject(data.project.slug), 300);
                } else {
                    alert(data.message);
                }
            });
        });

        // ── Terminal / Polling ──
        function appendLogs(lines) {
            const t = document.getElementById('terminal');
            if (lines.length > 0) {
                if (t.innerText === 'Aguardando disparo de tarefas...') t.innerText = '';
                lines.forEach(l => { t.innerText += l; });
                t.scrollTop = t.scrollHeight;
            }
        }

        function pollLogs() {
            fetch(`/api/logs?offset=${logsOffset}`)
                .then(r => r.json())
                .then(data => {
                    appendLogs(data.lines);
                    logsOffset = data.offset;
                    updateStatusBadge(data.status, data.running);
                    if (!data.running && logsInterval) {
                        clearInterval(logsInterval);
                        logsInterval = null;
                        if (activeProjectSlug) loadTelemetryData(activeProjectSlug);
                        loadProjects(); // Atualiza status pills
                    }
                })
                .catch(err => console.error('Polling error:', err));
        }

        function startPolling() {
            if (logsInterval) clearInterval(logsInterval);
            logsInterval = setInterval(pollLogs, 800);
        }

        // ── Ações dos Botões ──
        document.getElementById('btn-start-record').addEventListener('click', () => {
            if (!activeProjectSlug) return alert('Selecione um projeto primeiro.');
            const url = document.getElementById('record-url').value.trim();
            if (!url) return alert('Por favor, informe a URL.');

            // Salva URL editada no project.json via API (patch)
            fetch('/api/projects/' + encodeURIComponent(activeProjectSlug) + '/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            }).catch(() => {});

            document.getElementById('terminal').innerText = 'Iniciando BlackBox Gravador Headed...';
            logsOffset = 0;
            fetch('/api/run-recorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, project_slug: activeProjectSlug })
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-run-sanitizer').addEventListener('click', () => {
            if (!activeProjectSlug) return alert('Selecione um projeto primeiro.');
            document.getElementById('terminal').innerText = 'Iniciando Sanitizador de Logs...';
            logsOffset = 0;
            fetch('/api/run-sanitizer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_slug: activeProjectSlug })
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-run-validator').addEventListener('click', () => {
            if (!activeProjectSlug) return alert('Selecione um projeto primeiro.');
            document.getElementById('terminal').innerText = 'Iniciando Dataset Firewall Validator...';
            logsOffset = 0;
            fetch('/api/run-validator', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_slug: activeProjectSlug })
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-run-generator').addEventListener('click', () => {
            if (!activeProjectSlug) return alert('Selecione um projeto primeiro.');
            document.getElementById('terminal').innerText = 'Iniciando Gerador de Código com IA...';
            logsOffset = 0;
            fetch('/api/run-code-generator', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_slug: activeProjectSlug })
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-run-bot').addEventListener('click', () => {
            if (!activeProjectSlug) return alert('Selecione um projeto primeiro.');
            document.getElementById('terminal').innerText = 'Iniciando Robô de Produção (Aegis Runner)...';
            logsOffset = 0;
            fetch('/api/run-bot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_slug: activeProjectSlug })
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-stop-proc').addEventListener('click', () => {
            fetch('/api/stop', { method: 'POST' });
        });

        document.getElementById('btn-install-browsers').addEventListener('click', () => {
            if (!confirm('Deseja iniciar a instalação de navegadores via Playwright CLI? (chromium, msedge)')) return;
            document.getElementById('terminal').innerText = 'Iniciando instalação de navegadores via Playwright CLI...';
            logsOffset = 0;
            fetch('/api/install-browsers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
            .then(r => r.json())
            .then(data => { if (data.success) startPolling(); else alert(data.message); });
        });

        document.getElementById('btn-clear-logs').addEventListener('click', () => {
            document.getElementById('terminal').innerText = 'Aguardando disparo de tarefas...';
        });

        // ── Visualizadores ──
        function clearVisualizers() {
            const msg = '<div class="empty-msg">Selecione um projeto para visualizar.</div>';
            document.getElementById('dict-view').innerHTML = msg;
            document.getElementById('dataset-view').innerHTML = msg;
            document.getElementById('report-view').innerHTML = msg;
            document.getElementById('validation-view').innerHTML = msg;
        }

        function loadTelemetryData(slug) {
            fetch('/api/projects/' + encodeURIComponent(slug) + '/telemetry-files')
                .then(r => r.json())
                .then(data => {
                    renderDict(data.dictionary);
                    renderDataset(data.dataset);
                    renderReport(data.report);
                    renderValidation(data.validation);
                    
                    const runBotBtn = document.getElementById('btn-run-bot');
                    if (runBotBtn) {
                        runBotBtn.disabled = !data.has_bot;
                    }
                })
                .catch(() => clearVisualizers());
        }

        function renderDict(dictionary) {
            const div = document.getElementById('dict-view');
            if (!dictionary || !dictionary.fields || !Object.keys(dictionary.fields).length) {
                div.innerHTML = '<div class="empty-msg">Nenhum dicionário gerado. Execute a Sanitização primeiro.</div>';
                return;
            }
            let html = '<div class="table-wrap"><table><tr><th>Chave Semântica</th><th>Tipo</th><th>Seletor</th><th>Valor Observado</th><th>Regex</th></tr>';
            for (const [key, val] of Object.entries(dictionary.fields)) {
                html += `<tr>
                    <td><strong>${key}</strong></td>
                    <td><code>${val.type}</code></td>
                    <td style="font-size:10px;font-family:monospace;">${val.selector}</td>
                    <td>"${val.observed_value}"</td>
                    <td><code>${(val.validation_rules && val.validation_rules.regex) || 'N/A'}</code></td>
                </tr>`;
            }
            html += '</table></div>';
            div.innerHTML = html;
        }

        function renderDataset(dataset) {
            const div = document.getElementById('dataset-view');
            if (!dataset || !dataset.length) {
                div.innerHTML = '<div class="empty-msg">Nenhum dataset gerado ainda.</div>';
                return;
            }
            const keys = Object.keys(dataset[0]);
            let html = '<div class="table-wrap"><table><tr>' + keys.map(k => `<th>${k}</th>`).join('') + '</tr>';
            dataset.forEach(row => {
                html += '<tr>' + keys.map(k => {
                    const v = row[k] === null ? '<em style="color:var(--text-muted)">null</em>' : row[k];
                    return `<td>${v}</td>`;
                }).join('') + '</tr>';
            });
            html += '</table></div>';
            div.innerHTML = html;
        }

        function parseSectionMarkdown(md) {
            let lines = md.split('\\n');
            let html = [], inTable = false, tableHtml = '', inList = false, inCodeBlock = false, codeContent = '';
            for (const rawLine of lines) {
                const line = rawLine.trim();
                if (line.startsWith('```')) {
                    if (inCodeBlock) {
                        inCodeBlock = false;
                        html.push(`<pre style="background:#02020a;border:1px solid rgba(124,58,237,0.15);padding:10px;border-radius:6px;font-family:'Fira Code',monospace;font-size:10px;overflow-x:auto;color:#a78bfa;margin:8px 0;"><code>${codeContent}</code></pre>`);
                        codeContent = '';
                    } else { inCodeBlock = true; }
                    continue;
                }
                if (inCodeBlock) { codeContent += line + '\\n'; continue; }
                if (line.startsWith('|')) {
                    if (inList) { html.push('</ul>'); inList = false; }
                    if (!inTable) { inTable = true; tableHtml = '<div class="table-wrap"><table>'; }
                    const cells = line.split('|').map(c => c.trim()).filter((_, i, a) => i > 0 && i < a.length - 1);
                    if (line.includes('---')) continue;
                    const isHeader = line.includes('Passo') || line.includes('Cenário') || line.includes('Chave');
                    tableHtml += '<tr>' + cells.map(c => isHeader ? `<th>${c}</th>` : `<td>${c}</td>`).join('') + '</tr>';
                    continue;
                } else if (inTable) { inTable = false; tableHtml += '</table></div>'; html.push(tableHtml); }
                if (line.startsWith('# ')) { if(inList){html.push('</ul>');inList=false;} html.push(`<h3 style="color:#fff;margin:0 0 8px;">${line.slice(2)}</h3>`); }
                else if (line.startsWith('## ')) { if(inList){html.push('</ul>');inList=false;} html.push(`<h4 style="color:var(--accent);margin:0 0 10px;border-bottom:1px solid rgba(124,58,237,0.2);padding-bottom:5px;font-size:13px;">${line.slice(3)}</h4>`); }
                else if (line.startsWith('### ')) { if(inList){html.push('</ul>');inList=false;} html.push(`<h5 style="color:#fff;margin:12px 0 6px;font-size:11px;">${line.slice(4)}</h5>`); }
                else if (line.startsWith('* ')) { if(!inList){inList=true;html.push('<ul style="margin:8px 0;padding-left:18px;">')} html.push(`<li style="margin-bottom:5px;font-size:12px;color:#d1d5db;">${line.slice(2)}</li>`); }
                else if (line === '---') { if(inList){html.push('</ul>');inList=false;} html.push('<hr style="border:none;border-bottom:1px solid rgba(124,58,237,0.12);margin:15px 0;">'); }
                else if (line === '') { if(inList){html.push('</ul>');inList=false;} }
                else { if(inList){html.push('</ul>');inList=false;} html.push(`<p style="margin:8px 0;font-size:12px;color:#d1d5db;line-height:1.6;">${line}</p>`); }
            }
            if (inTable) { tableHtml += '</table></div>'; html.push(tableHtml); }
            if (inList) html.push('</ul>');
            let result = html.join('\\n');
            result = result.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
            result = result.replace(/`(.*?)`/g, '<code>$1</code>');
            return result;
        }

        let activeReportContent = '';

        function downloadReport() {
            if (!activeReportContent) {
                alert('Nenhum relatório disponível para download.');
                return;
            }
            const blob = new Blob([activeReportContent], { type: 'text/markdown;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `${activeProjectSlug || 'projeto'}_relatorio.md`);
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }

        function renderReport(md) {
            const div = document.getElementById('report-view');
            activeReportContent = md || '';
            if (!md) { 
                div.innerHTML = '<div class="empty-msg">Nenhum relatório disponível. Execute a Sanitização.</div>'; 
                return; 
            }
            
            div.innerHTML = `
                <div class="report-download-card" style="
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    padding: 40px 30px;
                    margin: 30px auto;
                    max-width: 480px;
                    background: rgba(30, 27, 75, 0.4);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    border: 1px solid rgba(139, 92, 246, 0.25);
                    border-radius: 16px;
                    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                    text-align: center;
                    animation: fadeIn 0.5s ease-out;
                ">
                    <div class="icon-pulse" style="
                        width: 80px;
                        height: 80px;
                        border-radius: 50%;
                        background: rgba(139, 92, 246, 0.15);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 36px;
                        margin-bottom: 24px;
                        border: 1px solid rgba(139, 92, 246, 0.3);
                        box-shadow: 0 0 20px rgba(139, 92, 246, 0.2);
                    ">
                        📥
                    </div>
                    <h3 style="
                        color: #fff;
                        font-size: 20px;
                        font-weight: 600;
                        margin: 0 0 10px 0;
                        background: linear-gradient(135deg, #fff 0%, #c084fc 100%);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                    ">
                        Relatório Disponível para Download
                    </h3>
                    <p style="
                        color: #9ca3af;
                        font-size: 13px;
                        line-height: 1.6;
                        margin: 0 0 28px 0;
                    ">
                        O relatório <strong>relatorio.md</strong> foi gerado e sanitizado com sucesso. Devido à riqueza de detalhes e formatação em Markdown, baixe o arquivo para visualizá-lo em seu editor preferido.
                    </p>
                    <button class="btn btn-accent" style="
                        padding: 12px 28px;
                        font-size: 14px;
                        font-weight: 600;
                        border-radius: 8px;
                        display: inline-flex;
                        align-items: center;
                        gap: 10px;
                        cursor: pointer;
                        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                        box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
                        background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);
                        border: none;
                        color: #fff;
                    " onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 6px 20px rgba(139, 92, 246, 0.6)';" 
                      onmouseout="this.style.transform='none'; this.style.boxShadow='0 4px 15px rgba(139, 92, 246, 0.4)';"
                      onclick="downloadReport()">
                        Baixar Relatório (Markdown)
                    </button>
                </div>
            `;
        }

        function renderValidation(v) {
            const div = document.getElementById('validation-view');
            if (!v || !Object.keys(v).length) {
                div.innerHTML = '<div class="empty-msg">Nenhum resultado de validação. Execute o Firewall.</div>';
                return;
            }
            const ok = v.is_valid;
            let html = `<div class="status-box ${ok ? 'box-ok' : 'box-err'}">
                <strong>${ok ? '✅ DATASET PRONTO PARA CARGA (100% VÁLIDO)' : '❌ DATASET CONTÉM INCONSISTÊNCIAS'}</strong><br>
                <span style="font-size:10px;opacity:0.8;">${v.dataset_path || ''}</span>
            </div>
            <div class="firewall-summary">
                <div class="metric-card"><div class="metric-label">Processados</div><div class="metric-value v-neutral">${v.total_records}</div></div>
                <div class="metric-card"><div class="metric-label">Válidos</div><div class="metric-value v-ok">${v.passed_records}</div></div>
                <div class="metric-card"><div class="metric-label">Inválidos</div><div class="metric-value v-err">${v.failed_records}</div></div>
            </div>`;
            if (v.failures && v.failures.length) {
                html += '<div class="card" style="padding:10px;max-height:200px;overflow-y:auto;">';
                v.failures.forEach(f => {
                    html += `<div class="failure-item">
                        <strong style="font-size:11px;color:var(--error);">Registro ID: ${f.record_id} (Índice ${f.record_index})</strong>
                        <ul style="margin:4px 0 0 14px;font-size:11px;color:#d1d5db;">
                            ${f.errors.map(e => `<li>${e}</li>`).join('')}
                        </ul>
                    </div>`;
                });
                html += '</div>';
            }
            div.innerHTML = html;
        }

        // ── Init ──
        fetchConfig();
        loadProjects();
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                updateStatusBadge(data.status, data.running);
                if (data.running) startPolling();
            });
    </script>
</body>
</html>
"""

# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class AegisHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silencia logs de requisição

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else '{}'

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ('/', '/index.html'):
            body = HTML_CONTENT.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/status':
            self._json({'status': current_status, 'running': active_process is not None})

        elif path == '/api/logs':
            offset = int(query.get('offset', [0])[0])
            with logs_lock:
                lines = global_logs[offset:]
                total = len(global_logs)
            self._json({'lines': lines, 'offset': total, 'running': active_process is not None, 'status': current_status})

        elif path == '/api/config':
            self._json({
                'projects_dir': PROJECTS_DIR,
                'telemetry_dir': LEGACY_TELEMETRY_DIR
            })

        elif path == '/api/projects':
            self._json({'projects': list_projects()})

        elif path.startswith('/api/projects/') and path.endswith('/telemetry-files'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            proj_dir = get_project_dir(slug)

            def load_json(fname):
                p = os.path.join(proj_dir, fname)
                if os.path.exists(p):
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            return json.load(f)
                    except Exception:
                        pass
                return None

            def load_text(fname):
                p = os.path.join(proj_dir, fname)
                if os.path.exists(p):
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            return f.read()
                    except Exception:
                        pass
                return ''

            has_bot = (
                os.path.exists(os.path.join(proj_dir, 'bot_producao.py')) or
                os.path.exists(os.path.join(proj_dir, 'robot.py')) or
                os.path.exists(os.path.join(proj_dir, 'run_bot.py'))
            )
            dataset = load_json('dataset_inicial.json') or []
            self._json({
                'dictionary': load_json('dicionario.json') or {},
                'dataset': dataset if isinstance(dataset, list) else [dataset],
                'report': load_text('relatorio.md'),
                'validation': load_json('relatorio_validacao.json') or {},
                'has_bot': has_bot
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global active_process, current_status
        path = urllib.parse.urlparse(self.path).path
        try:
            body = json.loads(self._read_body())
        except Exception:
            body = {}

        if path == '/api/config':
            projects_dir = body.get('projects_dir', '').strip()
            if not projects_dir:
                self._json({'success': False, 'message': 'Diretório de projetos é obrigatório.'}, 400)
                return
            telemetry_dir = os.path.join(os.path.dirname(projects_dir), "telemetry_data")
            try:
                update_paths(projects_dir, telemetry_dir)
                self._json({'success': True, 'projects_dir': PROJECTS_DIR, 'telemetry_dir': LEGACY_TELEMETRY_DIR})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)
            return

        elif path == '/api/projects':
            name = body.get('name', '').strip()
            url = body.get('url', '').strip()
            custom_path = body.get('custom_path', '').strip()
            if not name:
                self._json({'success': False, 'message': 'Nome do projeto é obrigatório.'}, 400)
                return
            meta = create_project(name, url, custom_path)
            self._json({'success': True, 'project': meta})

        elif path.startswith('/api/projects/') and path.endswith('/url'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            proj_dir = get_project_dir(slug)
            proj_json = os.path.join(proj_dir, 'project.json')
            if os.path.exists(proj_json):
                try:
                    with open(proj_json, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    meta['url'] = body.get('url', meta.get('url', ''))
                    meta['last_activity'] = datetime.now().isoformat(timespec='seconds')
                    with open(proj_json, 'w', encoding='utf-8') as f:
                        json.dump(meta, f, indent=4, ensure_ascii=False)
                    self._json({'success': True})
                except Exception as e:
                    self._json({'success': False, 'message': str(e)}, 500)
            else:
                self._json({'success': False, 'message': 'Projeto não encontrado.'}, 404)

        elif path == '/api/run-recorder':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            url = body.get('url', '')
            if not slug or not url:
                self._json({'success': False, 'message': 'project_slug e url são obrigatórios.'}, 400)
                return
            proj_dir = get_project_dir(slug)
            recorder_script = os.path.join(PROJECT_ROOT, 'aegis_blackbox', 'recorder.py')
            cmd = [sys.executable, '-u', recorder_script, '--url', url, '--output-dir', proj_dir, '--control-port', '9900']
            run_command_in_background(cmd, 'GRAVAÇÃO')
            self._json({'success': True, 'message': 'Gravador iniciado com sucesso!'})

        elif path == '/api/run-sanitizer':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução.'}, 400)
                return
            slug = body.get('project_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = get_project_dir(slug)
            sanitizer_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'sanitizer.py')
            cmd = [sys.executable, '-u', sanitizer_script, '--project-dir', proj_dir]
            run_command_in_background(cmd, 'SANITIZAÇÃO')
            self._json({'success': True, 'message': 'Sanitizador iniciado!'})

        elif path == '/api/run-validator':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução.'}, 400)
                return
            slug = body.get('project_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = get_project_dir(slug)
            # Dataset padrão: dataset_inicial.json ou dados_entrada.csv
            dataset_file = os.path.join(proj_dir, 'dataset_inicial.json')
            if not os.path.exists(dataset_file):
                dataset_file = os.path.join(proj_dir, 'dados_entrada.csv')
            validator_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'dataset_validator.py')
            cmd = [sys.executable, '-u', validator_script, '--dataset', dataset_file, '--project-dir', proj_dir]
            # Passa o slug do projeto para atualizar project.json caso a validação passe
            run_command_in_background(cmd, 'VALIDAÇÃO', project_slug=slug)
            self._json({'success': True, 'message': 'Validador iniciado!'})

        elif path == '/api/run-code-generator':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = get_project_dir(slug)
            generator_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'code_generator.py')
            cmd = [sys.executable, '-u', generator_script, '--project-dir', proj_dir]
            run_command_in_background(cmd, 'GERAÇÃO_CÓDIGO')
            self._json({'success': True, 'message': 'Gerador de código iniciado!'})

        elif path == '/api/run-bot':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = get_project_dir(slug)
            
            # Localiza o script do robô no projeto
            bot_script = None
            for name in ['bot_producao.py', 'robot.py', 'run_bot.py']:
                candidate = os.path.join(proj_dir, name)
                if os.path.exists(candidate):
                    bot_script = candidate
                    break
            
            if not bot_script:
                self._json({'success': False, 'message': 'Nenhum script de robô encontrado no projeto.'}, 400)
                return
                
            cmd = [sys.executable, '-u', bot_script]
            # Executa com cwd=proj_dir para carregar o .env do projeto corretamente
            run_command_in_background(cmd, 'EXECUÇÃO_ROBÔ', cwd=proj_dir, project_slug=slug)
            self._json({'success': True, 'message': 'Robô de produção iniciado!'})

        elif path == '/api/stop':
            if active_process is not None:
                try:
                    shutdown_graceful = False
                    if current_status == "GRAVAÇÃO":
                        try:
                            with logs_lock:
                                global_logs.append('\n[AEGIS COCKPIT] Enviando sinal de término para o Gravador via API HTTP...\n')
                            # Tenta acionar a API de fechamento limpo
                            req = urllib.request.urlopen("http://localhost:9900/api/finish", timeout=3)
                            req.read()
                            # Aguarda o processo terminar voluntariamente (timeout de 15 segundos)
                            active_process.wait(timeout=15)
                            shutdown_graceful = True
                            with logs_lock:
                                global_logs.append('[AEGIS COCKPIT] Gravador encerrado com sucesso via API de controle HTTP. Telemetrias salvas.\n')
                        except Exception as stop_err:
                            with logs_lock:
                                global_logs.append(f'[AEGIS COCKPIT] Não foi possível efetuar o graceful shutdown ({stop_err}). Forçando terminação do processo...\n')

                    if not shutdown_graceful:
                        active_process.terminate()
                        with logs_lock:
                            global_logs.append('\n[AEGIS COCKPIT] Processo interrompido pelo usuário.\n')
                    
                    self._json({'success': True})
                except Exception as e:
                    self._json({'success': False, 'message': str(e)}, 500)
            else:
                self._json({'success': False, 'message': 'Nenhum processo ativo.'}, 400)

        elif path == '/api/install-browsers':
            if active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            # Executa a instalação de navegadores via Playwright CLI
            cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium', 'msedge']
            run_command_in_background(cmd, 'INSTALAÇÃO_NAVEGADORES')
            self._json({'success': True, 'message': 'Instalação de navegadores iniciada!'})

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/projects/'):
            slug = urllib.parse.unquote(path.split('/')[-1])
            try:
                if delete_project(slug):
                    self._json({'success': True})
                else:
                    self._json({'success': False, 'message': f'Projeto "{slug}" não encontrado.'}, 404)
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 400)
        else:
            self.send_response(404)
            self.end_headers()


class ThreadingHTTPServer(ThreadingTCPServer, HTTPServer):
    allow_reuse_address = False

# ─── Entry Point ──────────────────────────────────────────────────────────────

def start_server(port):
    migrate_legacy_if_needed()
    
    max_attempts = 10
    current_port = port
    server = None
    
    for attempt in range(max_attempts):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', current_port), AegisHTTPRequestHandler)
            break
        except OSError:
            print(f"[AEGIS COCKPIT] Porta {current_port} ocupada. Tentando próxima porta...")
            current_port += 1
            
    if server is None:
        print(f"[ERROR] Não foi possível alocar uma porta para o servidor após {max_attempts} tentativas.")
        sys.exit(1)
        
    print('\n' + '=' * 70)
    print('🛡️  AEGIS COCKPIT — MULTI-WORKSPACE v2')
    print(f'🔗  URL de Acesso: http://localhost:{current_port}')
    print(f'📂  Projetos em:   {PROJECTS_DIR}')
    print('=' * 70 + '\n')
    print('Pressione Ctrl+C para encerrar o Cockpit.')
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nDesligando Cockpit do Aegis...')
        server.shutdown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Aegis Cockpit Dashboard Server')
    parser.add_argument('--port', type=int, default=int(os.getenv('AEGIS_COCKPIT_PORT', '8080')), help='Porta do servidor local')
    args = parser.parse_args()
    start_server(args.port)
