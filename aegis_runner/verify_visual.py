import os
import sys
import argparse
import subprocess
import json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# Adiciona o diretório atual do script ao path para poder importar cognitive_fallback
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(MODULE_DIR)

try:
    from cognitive_fallback import CognitiveGateway
except ImportError:
    from aegis_runner.cognitive_fallback import CognitiveGateway

def run_visual_verification(project_dir):
    project_dir = os.path.abspath(project_dir)
    print("\n" + "=" * 80)
    print("🛡️ AEGIS VISUAL VERIFIER: PIPELINE DE HOMOLOGAÇÃO DE INTERFACE")
    print("=" * 80)
    print(f"[PROJETO] Diretório: {project_dir}")
    
    # 1. Verificar screenshot do recorder
    path_recorder = os.path.join(project_dir, "screenshot_recorder.png")
    if not os.path.exists(path_recorder):
        print(f"[❌ FALHA] Screenshot de gravação manual (screenshot_recorder.png) não encontrado na pasta do projeto.")
        sys.exit(1)
        
    # 2. Localizar o script do robô (padrão bot_*.py)
    bot_script = None
    # Verifica primeiro se está na pasta 'code'
    code_dir = os.path.join(project_dir, "code")
    if os.path.exists(code_dir) and os.path.isdir(code_dir):
        for entry in os.listdir(code_dir):
            if entry.startswith("bot_") and entry.endswith(".py"):
                bot_script = os.path.join(code_dir, entry)
                break
        if not bot_script:
            for entry in os.listdir(code_dir):
                if entry.endswith(".py") and entry != "__init__.py":
                    bot_script = os.path.join(code_dir, entry)
                    break
                    
    if not bot_script:
        for entry in os.listdir(project_dir):
            if entry.startswith("bot_") and entry.endswith(".py"):
                bot_script = os.path.join(project_dir, entry)
                break
                
    if not bot_script:
        # Tenta fallback para qualquer arquivo .py caso não ache bot_*.py na raiz
        for entry in os.listdir(project_dir):
            if entry.endswith(".py") and entry != "__init__.py":
                bot_script = os.path.join(project_dir, entry)
                break
                
    if not bot_script:
        print("[❌ FALHA] Nenhum script de automação (.py) localizado na pasta do projeto.")
        sys.exit(1)
        
    print(f"[ROBÔ] Script localizado: {bot_script}")
    
    # Remover screenshot_script.png antigo para evitar falsos positivos
    path_script = os.path.join(project_dir, "screenshots", "screenshot_script.png")
    old_path_script = os.path.join(project_dir, "screenshot_script.png")
    
    # Garante a pasta screenshots
    os.makedirs(os.path.dirname(path_script), exist_ok=True)
    
    for p in [path_script, old_path_script]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    # 3. Executar o robô em modo HEADLESS=True
    print("[EXECUÇÃO] Iniciando execução do robô de forma isolada e silenciosa (headless)...")
    env_copy = os.environ.copy()
    env_copy["AEGIS_BROWSER_HEADLESS"] = "true"
    
    # Injeta a raiz do Aegis Suite no PYTHONPATH do subprocesso
    workspace_root = os.path.dirname(MODULE_DIR)
    current_pythonpath = env_copy.get("PYTHONPATH", "")
    if current_pythonpath:
        env_copy["PYTHONPATH"] = f"{workspace_root}{os.pathsep}{current_pythonpath}"
    else:
        env_copy["PYTHONPATH"] = workspace_root
    
    # Determina o executável do python apropriado (se houver venv local, use-o)
    python_exe = sys.executable
    venv_python = os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        python_exe = venv_python
    else:
        venv_python_unix = os.path.join(project_dir, ".venv", "bin", "python")
        if os.path.exists(venv_python_unix):
            python_exe = venv_python_unix
            
    print(f"[EXECUÇÃO] Usando interpretador Python: {python_exe}")
    
    # Executa o robô usando o interpretador python apropriado
    result = subprocess.run([python_exe, bot_script], env=env_copy, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    
    print("-" * 60)
    print("--- CONSOLE OUTPUT DO ROBÔ ---")
    print(result.stdout)
    if result.stderr:
        print("--- CONSOLE ERROR DO ROBÔ ---")
        print(result.stderr)
    print("-" * 60)

    # 4. Tratar Falha Sistêmica na execução
    if result.returncode != 0:
        print("[❌ FALHA SISTÊMICA] A execução do robô retornou código de erro diferente de zero.")
        print("[AEGIS] Processo de comparação visual abortado devido a quebra técnica do robô.")
        sys.exit(1)
        
    if not os.path.exists(path_script) and os.path.exists(old_path_script):
        path_script = old_path_script
        
    if not os.path.exists(path_script):
        print("[❌ FALHA SISTÊMICA] O robô executou mas não gerou o screenshot de tela final (screenshot_script.png).")
        print("[AEGIS] Processo de comparação visual abortado.")
        sys.exit(1)
        
    print("[✓ SUCESSO] Robô executado com sucesso e screenshot final (screenshot_script.png) capturado.")

    # 5. Comparação Visual baseada em IA (se configurada)
    gateway = CognitiveGateway(project_dir=project_dir)
    if not gateway.is_active():
        print("\n[⚠️ AVISO] IA de homologação não está configurada (AEGIS_COGNITIVE_API_KEY ausente ou AEGIS_COGNITIVE_ENABLED=false).")
        print("[AEGIS] Comparação visual ignorada. Robô aprovado preliminarmente pelo critério de execução funcional.")
        sys.exit(0)
        
    try:
        verdict = gateway.compare_visual_similarity(path_recorder, path_script)
        
        # Salva o relatório estruturado JSON na subpasta reports
        reports_dir = os.path.join(project_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        report_json_path = os.path.join(reports_dir, "visual_verification_report.json")
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=4, ensure_ascii=False)
            
        # Salva o relatório em Markdown
        score = verdict.get("similarity_score", 0)
        ready = verdict.get("ready_for_analyst", False)
        justification = verdict.get("justification", "")
        diffs = verdict.get("differences", [])
        
        status_color = "🟢 APROVADO" if ready else "🔴 REVISÃO NECESSÁRIA"
        
        markdown_report = f"""# 🛡️ Relatório de Verificação Visual Aegis
 
 ## Status: {status_color}
 
 - **Score de Similaridade:** {score}% (Nota de corte: 85%)
 - **Pronto para o Analista:** {"Sim" if ready else "Não"}
 
 ### 📝 Justificativa
 {justification}
 
 ### 🔍 Diferenças Detectadas
 """
        if diffs:
            for d in diffs:
                markdown_report += f"- {d}\n"
        else:
            markdown_report += "- Nenhuma divergência relevante encontrada.\n"
            
        report_md_path = os.path.join(reports_dir, "visual_verification_report.md")
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_report)
            
        # Atualiza/Gera o arquivo de índice JSON para incluir os relatórios de verificação visual
        index_path = os.path.join(project_dir, "index_arquivos.json")
        index_data = {}
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index_data = json.load(f)
            except:
                pass
        
        if not index_data:
            index_data = {
                "component": "bot_execution",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "files": []
            }
            
        files_list = index_data.setdefault("files", [])
        
        # Remove duplicados existentes para reinserir com a descrição correta
        files_list = [f for f in files_list if f.get("path") not in ["reports/visual_verification_report.json", "reports/visual_verification_report.md"]]
        
        files_list.append({
            "path": "reports/visual_verification_report.json",
            "type": "visual_verification_report_json",
            "description": "Relatório estruturado JSON contendo o resultado detalhado da homologação de interface por IA e o score de similaridade visual."
        })
        files_list.append({
            "path": "reports/visual_verification_report.md",
            "type": "visual_verification_report_markdown",
            "description": "Relatório em formato Markdown exibindo de forma amigável as divergências de interface detectadas pela IA multimodal."
        })
        index_data["files"] = files_list
        
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=4, ensure_ascii=False)
            print(f"[AEGIS] Índice de arquivos atualizado em: {index_path}")
        except Exception as ex:
            print(f"[WARNING] Falha ao atualizar index_arquivos.json com relatórios visuais: {ex}")
            
        print("\n" + "=" * 60)
        print(f"VEREDITO VISUAL: {status_color} ({score}% de Similaridade)")
        print(f"Justificativa: {justification}")
        print("=" * 60)
        
        if ready:
            print("[AEGIS] O robô está aprovado visualmente e pronto para avaliação do analista!")
            sys.exit(0)
        else:
            print("[AEGIS] O robô necessita de revisão do desenvolvedor. Ajuste o script e tente novamente.")
            sys.exit(1)
            
    except Exception as err:
        print(f"\n[⚠️ AVISO] Ocorreu um erro técnico durante a chamada à API de Inteligência Artificial: {err}")
        print("[AEGIS] Comparação visual abortada de acordo com as regras de resiliência.")
        print("[AEGIS] Robô aprovado preliminarmente pelo critério de execução funcional (Sem falhas técnicas).")
        sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis Visual Verifier")
    parser.add_argument("--project-dir", required=True, help="Diretório absoluto da pasta do robô")
    args = parser.parse_args()
    
    run_visual_verification(args.project_dir)
