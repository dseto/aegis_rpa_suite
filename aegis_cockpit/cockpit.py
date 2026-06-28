import os
import sys
import json
import argparse
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingTCPServer

# Reconfigura stdout para utf-8
sys.stdout.reconfigure(encoding='utf-8')

# Adiciona o diretório principal ao path para importar managers locais
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from aegis_cockpit.project_manager import ProjectManager
from aegis_cockpit.process_manager import ProcessManager

# Instanciação dos managers de negócio (Injeção de dependências via construtores e callbacks)
project_manager = ProjectManager(PROJECT_ROOT)
process_manager = ProcessManager(get_project_dir_fn=project_manager.get_project_dir)

# Cache do HTML estático para evitar leitura de disco desnecessária
STATIC_DIR = os.path.join(MODULE_DIR, "static")
HTML_FILE_PATH = os.path.join(STATIC_DIR, "index.html")
_html_cache = None

def get_html_content() -> bytes:
    global _html_cache
    if _html_cache is None:
        if os.path.exists(HTML_FILE_PATH):
            with open(HTML_FILE_PATH, "r", encoding="utf-8") as f:
                _html_cache = f.read().encode("utf-8")
        else:
            _html_cache = b"<h1>Erro: static/index.html nao encontrado.</h1>"
    return _html_cache


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class AegisHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silencia logs de requisição no terminal para manter a saída limpa

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else '{}'

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            # Não falha o servidor se a conexão for abortada pelo cliente
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ('/', '/index.html'):
            body = get_html_content()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/status':
            self._json({
                'status': process_manager.current_status,
                'running': process_manager.active_process is not None
            })

        elif path == '/api/logs':
            offset = int(query.get('offset', [0])[0])
            lines, total = process_manager.get_logs_slice(offset)
            self._json({
                'lines': lines,
                'offset': total,
                'running': process_manager.active_process is not None,
                'status': process_manager.current_status
            })

        elif path == '/api/config':
            self._json({
                'projects_dir': project_manager.projects_dir,
                'telemetry_dir': project_manager.telemetry_dir
            })

        elif path == '/api/projects':
            self._json({'projects': project_manager.list_projects()})

        elif path.startswith('/api/projects/') and path.endswith('/telemetry-files'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = query.get('test_slug', [None])[0]
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)

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
                'has_bot': has_bot,
                'recording': load_json('gravacao.json') or {},
                'steps_history': load_json('historico_passos.json')
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
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
                project_manager.update_paths(projects_dir, telemetry_dir)
                self._json({
                    'success': True,
                    'projects_dir': project_manager.projects_dir,
                    'telemetry_dir': project_manager.telemetry_dir
                })
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path == '/api/projects':
            name = body.get('name', '').strip()
            url = body.get('url', '').strip()
            custom_path = body.get('custom_path', '').strip()
            if not name:
                self._json({'success': False, 'message': 'Nome do projeto é obrigatório.'}, 400)
                return
            meta = project_manager.create_project(name, url, custom_path)
            self._json({'success': True, 'project': meta})

        elif path.startswith('/api/projects/') and path.endswith('/tests'):
            parts = path.split('/')
            project_slug = urllib.parse.unquote(parts[3])
            name = body.get('name', '').strip()
            url = body.get('url', '').strip()
            if not name:
                self._json({'success': False, 'message': 'Nome do cenário é obrigatório.'}, 400)
                return
            try:
                meta = project_manager.create_test(project_slug, name, url=url)
                self._json({'success': True, 'test': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/steps-history/clear'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = body.get('test_slug', '') or query.get('test_slug', [None])[0]
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
                
            history_path = os.path.join(proj_dir, "historico_passos.json")
            if os.path.exists(history_path):
                try:
                    os.remove(history_path)
                except Exception as e:
                    self._json({'success': False, 'message': str(e)}, 500)
                    return
            self._json({'success': True, 'message': 'Histórico limpo com sucesso.'})

        elif path.startswith('/api/projects/') and path.endswith('/steps-history'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = body.get('test_slug', '') or query.get('test_slug', [None])[0]
            steps_data = body.get('steps', [])
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
                
            history_path = os.path.join(proj_dir, "historico_passos.json")
            try:
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(steps_data, f, indent=4, ensure_ascii=False)
                self._json({'success': True, 'message': 'Histórico de passos gravado.'})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/url'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = body.get('test_slug', '')
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
                
            proj_json = os.path.join(proj_dir, 'project.json')
            if os.path.exists(proj_json):
                try:
                    with open(proj_json, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    meta['url'] = body.get('url', meta.get('url', ''))
                    meta['last_activity'] = datetime.now().isoformat(timespec='seconds')
                    with open(proj_json, 'w', encoding='utf-8') as f:
                        json.dump(meta, f, indent=4, ensure_ascii=False)
                    
                    if test_slug:
                        project_manager.update_project_activity(slug)
                        
                    self._json({'success': True})
                except Exception as e:
                    self._json({'success': False, 'message': str(e)}, 500)
            else:
                self._json({'success': False, 'message': 'Projeto ou cenário não encontrado.'}, 404)

        elif path == '/api/run-recorder':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            test_slug = body.get('test_slug', '')
            url = body.get('url', '')
            if not slug or not url:
                self._json({'success': False, 'message': 'project_slug e url são obrigatórios.'}, 400)
                return
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
            recorder_script = os.path.join(PROJECT_ROOT, 'aegis_blackbox', 'recorder.py')
            cmd = [sys.executable, '-u', recorder_script, '--url', url, '--output-dir', proj_dir, '--control-port', '9900']
            process_manager.run_command_in_background(cmd, 'GRAVAÇÃO', cwd=PROJECT_ROOT, project_slug=slug, test_slug=test_slug)
            self._json({'success': True, 'message': 'Gravador iniciado com sucesso!'})

        elif path == '/api/run-sanitizer':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução.'}, 400)
                return
            slug = body.get('project_slug', '')
            test_slug = body.get('test_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
            sanitizer_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'sanitizer.py')
            cmd = [sys.executable, '-u', sanitizer_script, '--project-dir', proj_dir]
            process_manager.run_command_in_background(cmd, 'SANITIZAÇÃO', cwd=PROJECT_ROOT, project_slug=slug, test_slug=test_slug)
            self._json({'success': True, 'message': 'Sanitizador iniciado!'})

        elif path == '/api/run-validator':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução.'}, 400)
                return
            slug = body.get('project_slug', '')
            test_slug = body.get('test_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
            dataset_file = os.path.join(proj_dir, 'dataset_inicial.json')
            if not os.path.exists(dataset_file):
                dataset_file = os.path.join(proj_dir, 'dados_entrada.csv')
            validator_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'dataset_validator.py')
            cmd = [sys.executable, '-u', validator_script, '--dataset', dataset_file, '--project-dir', proj_dir]
            process_manager.run_command_in_background(cmd, 'VALIDAÇÃO', cwd=PROJECT_ROOT, project_slug=slug, test_slug=test_slug)
            self._json({'success': True, 'message': 'Validador iniciado!'})

        elif path == '/api/run-code-generator':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            test_slug = body.get('test_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
            generator_script = os.path.join(PROJECT_ROOT, 'aegis_sanitizer', 'code_generator.py')
            cmd = [sys.executable, '-u', generator_script, '--project-dir', proj_dir]
            process_manager.run_command_in_background(cmd, 'GERAÇÃO_CÓDIGO', cwd=PROJECT_ROOT, project_slug=slug, test_slug=test_slug)
            self._json({'success': True, 'message': 'Gerador de código iniciado!'})

        elif path == '/api/run-bot':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            slug = body.get('project_slug', '')
            test_slug = body.get('test_slug', '')
            if not slug:
                self._json({'success': False, 'message': 'project_slug é obrigatório.'}, 400)
                return
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
            
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
            process_manager.run_command_in_background(cmd, 'EXECUÇÃO_ROBÔ', cwd=proj_dir, project_slug=slug, test_slug=test_slug)
            self._json({'success': True, 'message': 'Robô de produção iniciado!'})

        elif path == '/api/stop':
            if process_manager.stop_active_process():
                self._json({'success': True})
            else:
                self._json({'success': False, 'message': 'Nenhum processo ativo.'}, 400)

        elif path == '/api/install-browsers':
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
            cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium', 'msedge']
            process_manager.run_command_in_background(cmd, 'INSTALAÇÃO_NAVEGADORES', cwd=PROJECT_ROOT)
            self._json({'success': True, 'message': 'Instalação de navegadores iniciada!'})

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/projects/') and '/tests/' in path:
            parts = path.split('/')
            project_slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Não é possível deletar cenários enquanto houver um processo em execução.'}, 400)
                return
            try:
                if project_manager.delete_test(project_slug, test_slug):
                    self._json({'success': True})
                else:
                    self._json({'success': False, 'message': f'Cenário "{test_slug}" não encontrado.'}, 404)
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 400)
        elif path.startswith('/api/projects/'):
            slug = urllib.parse.unquote(path.split('/')[-1])
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Não é possível deletar projetos enquanto houver um processo em background em execução no Cockpit.'}, 400)
                return
            try:
                if project_manager.delete_project(slug):
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
    print(f'📂  Projetos em:   {project_manager.projects_dir}')
    print('=' * 70 + '\n')
    print('Pressione Ctrl+C para encerrar o Cockpit.')
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nDesligando Cockpit do Aegis...')
        server.shutdown()

def load_default_port() -> int:
    config_file = os.path.join(PROJECT_ROOT, "aegis_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if "port" in cfg:
                    return int(cfg["port"])
        except:
            pass
    return int(os.getenv('AEGIS_COCKPIT_PORT', '8080'))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Aegis Cockpit Dashboard Server')
    parser.add_argument('--port', type=int, default=load_default_port(), help='Porta do servidor local')
    args = parser.parse_args()
    start_server(args.port)
