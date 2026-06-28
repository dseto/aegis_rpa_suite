import os
import sys
import json
import subprocess
import threading
import urllib.request
from datetime import datetime

class ProcessManager:
    def __init__(self, get_project_dir_fn=None):
        self.active_process = None
        self.global_logs = []
        self.current_status = "IDLE"
        self.logs_lock = threading.Lock()
        self.get_project_dir_fn = get_project_dir_fn

    def run_command_in_background(self, cmd: list, status_name: str, cwd: str, project_slug: str = None, test_slug: str = None):
        """Executa um comando em background e captura seus logs em tempo real de forma assíncrona."""
        with self.logs_lock:
            self.global_logs.clear()
            self.global_logs.append(f"[AEGIS COCKPIT] Iniciando: {' '.join(cmd)}\n")
            self.global_logs.append("-" * 70 + "\n")

        self.current_status = status_name

        try:
            self.active_process = subprocess.Popen(
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
                try:
                    while True:
                        if self.active_process is None:
                            break
                        line = self.active_process.stdout.readline()
                        if not line:
                            break
                        with self.logs_lock:
                            self.global_logs.append(line)
                    
                    if self.active_process is not None:
                        exit_code = self.active_process.wait()
                        with self.logs_lock:
                            self.global_logs.append("-" * 70 + "\n")
                            self.global_logs.append(f"[AEGIS COCKPIT] Processo concluído com código: {exit_code}\n")
                        
                        # Atualiza o status do projeto se a execução do robô terminar com sucesso
                        if status_name == "EXECUÇÃO_ROBÔ" and exit_code == 0 and project_slug and self.get_project_dir_fn:
                            proj_dir = self.get_project_dir_fn(project_slug)
                            if test_slug:
                                proj_dir = os.path.join(proj_dir, "tests", test_slug)
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
                    with self.logs_lock:
                        self.global_logs.append(f"[AEGIS COCKPIT] Erro: {e}\n")
                finally:
                    self.current_status = "IDLE"
                    self.active_process = None

            t = threading.Thread(target=log_reader, daemon=True)
            t.start()

        except Exception as e:
            with self.logs_lock:
                self.global_logs.append(f"[AEGIS COCKPIT] Erro crítico: {e}\n")
            self.current_status = "IDLE"
            self.active_process = None

    def stop_active_process(self) -> bool:
        """Interrompe o processo ativo de forma limpa ou forçada."""
        if self.active_process is None:
            return False

        shutdown_graceful = False
        if self.current_status == "GRAVAÇÃO":
            try:
                with self.logs_lock:
                    self.global_logs.append('\n[AEGIS COCKPIT] Enviando sinal de término para o Gravador via API HTTP...\n')
                # Tenta acionar a API de fechamento limpo
                req = urllib.request.urlopen("http://localhost:9900/api/finish", timeout=3)
                req.read()
                # Aguarda o processo terminar voluntariamente (timeout de 15 segundos)
                self.active_process.wait(timeout=15)
                shutdown_graceful = True
                with self.logs_lock:
                    self.global_logs.append('[AEGIS COCKPIT] Gravador encerrado com sucesso via API de controle HTTP. Telemetrias salvas.\n')
            except Exception as stop_err:
                with self.logs_lock:
                    self.global_logs.append(f'[AEGIS COCKPIT] Não foi possível efetuar o graceful shutdown ({stop_err}). Forçando terminação do processo...\n')

        if not shutdown_graceful:
            self.active_process.terminate()
            with self.logs_lock:
                self.global_logs.append('\n[AEGIS COCKPIT] Processo interrompido pelo usuário.\n')
        
        return True

    def get_logs_slice(self, offset: int) -> tuple:
        """Retorna uma fatia de logs a partir do offset e o novo offset/total."""
        with self.logs_lock:
            lines = self.global_logs[offset:]
            total = len(self.global_logs)
        return lines, total
