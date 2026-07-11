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

# Cache do HTML estático para evitar leitura de disco desnecessária.
# Invalida por mtime (não apenas na primeira chamada) para que uma edição em
# static/index.html valha sem precisar reiniciar o processo do cockpit.
STATIC_DIR = os.path.join(MODULE_DIR, "static")
HTML_FILE_PATH = os.path.join(STATIC_DIR, "index.html")
_html_cache = None
_html_cache_mtime = None

def get_html_content() -> bytes:
    global _html_cache, _html_cache_mtime
    if not os.path.exists(HTML_FILE_PATH):
        return b"<h1>Erro: static/index.html nao encontrado.</h1>"

    current_mtime = os.path.getmtime(HTML_FILE_PATH)
    if _html_cache is None or current_mtime != _html_cache_mtime:
        with open(HTML_FILE_PATH, "r", encoding="utf-8") as f:
            _html_cache = f.read().encode("utf-8")
        _html_cache_mtime = current_mtime
    return _html_cache


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _regenerate_report_safe(proj_dir: str, gravacao_data: dict):
    """Regenera relatorio.md a partir de gravacao.json e dicionario.json,
    sem disparar refine_semantics_with_llm (sem chamadas LLM)."""
    dict_path = os.path.join(proj_dir, "dicionario.json")
    if not os.path.exists(dict_path):
        print("[WARNING] dicionario.json nao encontrado, pulando regeneracao de relatorio.md")
        return

    with open(dict_path, "r", encoding="utf-8") as f:
        dict_data = json.load(f)

    events = gravacao_data.get("events", [])
    initial_url = gravacao_data.get("initial_url", dict_data.get("initial_url", ""))
    network = gravacao_data.get("network_payloads", {})

    markdown = []
    markdown.append(f"# Relatorio de Telemetria Aegis RPA Suite V2")
    markdown.append(f"\n* **URL Alvo:** {initial_url}")
    markdown.append(f"* **Total de Acoes Gravadas:** {len(events)}")
    markdown.append(f"* **Respostas de Rede Interceptadas:** {len(network.keys())}")
    markdown.append("\n" + "-" * 60)

    # Dicionario de Dados
    markdown.append("\n## Dicionario de Dados Parametrizado (Sintetizado)")
    markdown.append("\nMapeamento fisico-semantico de campos de entrada e extracao:\n")
    markdown.append("| Cenario | Chave Semantica (Coluna CSV) | Elemento | Seletor Fisico Mapeado | Confiabilidade | Tipo de Seletor | Valor Observado | Fill Strategy |")
    markdown.append("| :---: | :--- | :---: | :--- | :---: | :---: | :--- | :---: |")

    inputs_list = dict_data.get("inputs", [])
    if not inputs_list and "fields" in dict_data:
        for sem_key, field_info in dict_data["fields"].items():
            inputs_list.append({
                "scenario": "default",
                "semantic_key": sem_key,
                "type": field_info.get("type", "string"),
                "selector": field_info.get("selector", ""),
                "observed_value": field_info.get("observed_value", ""),
                "confidence": field_info.get("confidence", 40),
                "selector_type": field_info.get("selector_type", "tag"),
                "fill_strategy": field_info.get("fill_strategy", "DIRECT")
            })

    for inp in inputs_list:
        conf = inp.get("confidence", 40)
        badge = "🟢 ALTA" if conf >= 90 else "🟡 MÉDIA" if conf >= 70 else "🔴 BAIXA"
        strategy = inp.get("fill_strategy", "DIRECT")
        strategy_badge = "🧱 HUMAN_LIKE" if strategy == "HUMAN_LIKE" else "DIRECT"
        markdown.append(f"| `{inp['scenario']}` | **`{inp['semantic_key']}`** | `{inp['type']}` | `{inp['selector']}` | {badge} ({conf}%) | `{inp.get('selector_type', 'tag')}` | \"{inp['observed_value']}\" | `{strategy_badge}` |")

    # Fluxo de Passos
    markdown.append("\n" + "-" * 60)
    markdown.append("\n## Fluxo de Passos e Bifurcacoes por Cenario")
    markdown.append(f"\n### Cenario Logico: `DEFAULT`")
    markdown.append(f"\nTotal de acoes neste caminho: {len(events)}\n")
    markdown.append("| Passo | Tipo | Elemento | Seletor Resiliente Sugerido | Valor / Acao |")
    markdown.append("| :---: | :---: | :---: | :--- | :--- |")

    for i, ev in enumerate(events):
        ev_type = ev.get("type", "").upper()
        if ev_type == "CALL_SKILL":
            skill_slug = ev.get("skill_slug", "")
            params_str = ", ".join([f"{k}={v}" for k, v in ev.get("parameters", {}).items()])
            markdown.append(f"| **👉 CALL** | **SKILL** | `{skill_slug}` | *Parametros:* | `{params_str}` |")
        elif ev_type == "ANNOTATION":
            markdown.append(f"| **📝 REGRA** | **VALIDACAO** | `-` | *N/A (Nota de Negocio)* | **\"{ev.get('text', '')}\"** |")
        else:
            tag = ev.get("tag", "").lower()
            if ev.get("is_date"):
                tag = "input (data)"
            selector = ev.get("selector", "")
            val_text = ""
            if ev_type == "CLICK":
                x = ev.get("x_percent")
                y = ev.get("y_percent")
                coords_str = f" [coords: ({x:.4f}, {y:.4f})]" if (x is not None and y is not None) else ""
                val_text = f"Clique em: '{ev.get('text', '')}'{coords_str}"
            elif ev_type == "FILL":
                if ev.get("is_date"):
                    val_text = f"Preencheu data: '{ev.get('value', '')}'"
                else:
                    val_text = f"Preencheu com: '{ev.get('value', '')}'"
            elif ev_type == "FILECHOOSER":
                val_text = "Abriu o dialogo de selecao de arquivo"
            elif ev_type == "CHANGE":
                val_text = f"Alterou para: '{ev.get('value', '')}'"
            elif ev_type == "SELECT":
                val_text = f"Selecionou: '{ev.get('value', '')}'"

            # Check for parent context (chained locator)
            p_ev = ev.get("parent")
            if p_ev:
                p_sel = p_ev.get("selector", "")
                p_text = p_ev.get("has_text")
                parent_prefix = f"⬆ `{p_sel}[{p_text}]` ➜ " if p_text else f"⬆ `{p_sel}` ➜ "
            else:
                parent_prefix = ""

            sel_display = f"{parent_prefix}`{selector}`"
            if parent_prefix:
                pass  # já formatado com parent
            elif " >> " in selector:
                sel_display = f"🧬 **Shadow DOM:** `{selector}`"
            markdown.append(f"| {i+1} | `{ev_type}` | `{tag}` | {sel_display} | {val_text} |")

    report_path = os.path.join(proj_dir, "relatorio.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown))
    print(f"[STEPS-HISTORY] relatorio.md regenerado em: {report_path}")


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

        elif path.startswith('/api/projects/') and path.endswith('/skills'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            self._json({'skills': project_manager.list_skills(slug)})

        elif path.startswith('/api/projects/') and path.endswith('/devops-config'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            
            cfg = project_manager.get_devops_config(slug)
            
            # Mascara os segredos para enviar para o frontend
            masked_cfg = dict(cfg)
            for key in ["pat", "llm_api_key"]:
                if masked_cfg.get(key):
                    masked_cfg[key] = "********"
                    
            # Inclui a lista de cenários disponíveis do projeto
            tests = project_manager.list_tests(slug)
            tests_meta = [{"slug": t["slug"], "name": t["name"], "status": t["status"]} for t in tests]
            
            self._json({
                'success': True,
                'config': masked_cfg,
                'available_scenarios': tests_meta
            })

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
                os.path.exists(os.path.join(proj_dir, 'code', 'bot_producao.py')) or
                os.path.exists(os.path.join(proj_dir, 'bot_producao.py')) or
                os.path.exists(os.path.join(proj_dir, 'code', 'robot.py')) or
                os.path.exists(os.path.join(proj_dir, 'robot.py')) or
                os.path.exists(os.path.join(proj_dir, 'code', 'run_bot.py')) or
                os.path.exists(os.path.join(proj_dir, 'run_bot.py'))
            )
            dataset = load_json('dataset_inicial.json') or []
            recording = load_json('gravacao.json') or {}
            
            skills_recordings = {}
            if recording and "events" in recording:
                project_dir = project_manager.get_project_dir(slug)
                for ev in recording["events"]:
                    if ev.get("type") == "call_skill":
                        skill_slug = ev.get("skill_slug")
                        if skill_slug and skill_slug not in skills_recordings:
                            sp = os.path.join(project_dir, "skills", skill_slug, "gravacao.json")
                            if os.path.exists(sp):
                                try:
                                    with open(sp, 'r', encoding='utf-8') as sf:
                                        skills_recordings[skill_slug] = json.load(sf)
                                except Exception:
                                    pass

            # ── steps_history: prioriza arquivo raiz (em tempo real) para polling ativo ──
            # Durante execução, runner escreve incrementalmente em historico_passos.json (raiz)
            # Só usa histórico de execuções completas se arquivo raiz não existir ou estiver vazio
            steps_history_data = load_json('historico_passos.json') or None

            # Se arquivo raiz está vazio/inexistente, tenta buscar da última execução completa
            if not steps_history_data and test_slug:
                _exec_base = os.path.join(proj_dir, "executions")
                if os.path.isdir(_exec_base):
                    _execs = sorted(
                        [d for d in os.listdir(_exec_base) if os.path.isdir(os.path.join(_exec_base, d))],
                        reverse=True  # mais recente primeiro
                    )
                    for _eid in _execs:
                        # Tenta primeiro na subpasta reports/, depois diretamente
                        for _sp in [
                            os.path.join(_exec_base, _eid, "reports", "historico_passos.json"),
                            os.path.join(_exec_base, _eid, "historico_passos.json"),
                        ]:
                            if os.path.exists(_sp):
                                try:
                                    with open(_sp, "r", encoding="utf-8") as _f:
                                        steps_history_data = json.load(_f)
                                except Exception:
                                    pass
                                break
                        if steps_history_data is not None:
                            break

            # Filtra por row_id se fornecido no query (para evitar mistura de transações durante polling em tempo real)
            current_row_id = query.get('current_row_id', [None])[0]
            if current_row_id and steps_history_data and isinstance(steps_history_data, list):
                steps_history_data = [s for s in steps_history_data if str(s.get('row_id', '')) == str(current_row_id)]

            self._json({
                'dictionary': load_json('dicionario.json') or {},
                'dataset': dataset if isinstance(dataset, list) else [dataset],
                'report': load_text('relatorio.md'),
                'validation': load_json('relatorio_validacao.json') or {},
                'has_bot': has_bot,
                'recording': recording,
                'skills_recordings': skills_recordings,
                'steps_history': steps_history_data,
                'execution_plan': load_json('plano_execucao.json') or None
            })

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/versions'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            self._json({'versions': project_manager.list_versions(slug, test_slug)})

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/executions'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            self._json({'executions': project_manager.list_executions(slug, test_slug)})

        elif path.startswith('/api/projects/') and '/tests/' in path and '/executions/' in path and '/files/' not in path:
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            execution_id = urllib.parse.unquote(parts[7])
            
            test_dir = os.path.join(project_manager.get_project_dir(slug), "tests", test_slug)
            exec_dir = os.path.join(test_dir, "executions", execution_id)
            
            # Busca logs e relatórios preferencialmente nas subpastas reports/ ou logs/
            log_path = os.path.join(exec_dir, "reports", "execution.log")
            if not os.path.exists(log_path):
                log_path = os.path.join(exec_dir, "execution.log")
                
            steps_path = os.path.join(exec_dir, "reports", "historico_passos.json")
            if not os.path.exists(steps_path):
                steps_path = os.path.join(exec_dir, "historico_passos.json")
                
            report_path = os.path.join(exec_dir, "reports", "relatorio_execucao.csv")
            if not os.path.exists(report_path):
                report_path = os.path.join(exec_dir, "relatorio_execucao.csv")
            
            log_content = ""
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        log_content = f.read()
                except:
                    pass
                    
            steps_data = []
            if os.path.exists(steps_path):
                try:
                    with open(steps_path, "r", encoding="utf-8") as f:
                        steps_data = json.load(f)
                except:
                    pass
                    
            report_rows = []
            if os.path.exists(report_path):
                try:
                    import csv
                    with open(report_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        report_rows = list(reader)
                except:
                    pass
                    
            self._json({
                'log': log_content,
                'steps_history': steps_data,
                'report': report_rows
            })

        elif path.startswith('/api/projects/') and '/tests/' in path and '/executions/' in path and '/files/' in path:
            # /api/projects/<slug>/tests/<test_slug>/executions/<execution_id>/files/<filename>
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            execution_id = urllib.parse.unquote(parts[7])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            exec_dir = os.path.join(test_dir, "executions", execution_id)
            
            files_idx = path.find('/files/')
            filename = urllib.parse.unquote(path[files_idx + 7:])
            
            # Sanitiza filename de forma segura permitindo subpastas
            # Remove qualquer tentativa de usar '..' para subir de nível
            clean_filename = filename.replace('\\', '/').replace('../', '').replace('..', '')
            file_path = os.path.abspath(os.path.join(exec_dir, clean_filename))
            
            # Garante que o caminho final ainda está dentro de exec_dir
            norm_file_path = os.path.normcase(os.path.abspath(file_path))
            norm_exec_dir = os.path.normcase(os.path.abspath(exec_dir))
            if not norm_file_path.startswith(norm_exec_dir):
                self.send_response(403)
                self.end_headers()
                return
            
            if os.path.exists(file_path):
                self.send_response(200)
                if filename.endswith('.png'):
                    self.send_header('Content-Type', 'image/png')
                elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
                    self.send_header('Content-Type', 'image/jpeg')
                else:
                    self.send_header('Content-Type', 'application/octet-stream')
                
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/execution-insights'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            import csv
            import re
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            executions = project_manager.list_executions(slug, test_slug)
            completed = [ex for ex in executions if ex.get("status") != "RUNNING"]
            
            if not completed:
                self._json({'success': True, 'execution_id': None, 'insights': []})
                return
                
            latest_exec = completed[-1]
            execution_id = latest_exec["id"]
            exec_dir = os.path.join(test_dir, "executions", execution_id)
            
            report_csv = os.path.join(exec_dir, "reports", "relatorio_execucao.csv")
            if not os.path.exists(report_csv):
                report_csv = os.path.join(exec_dir, "relatorio_execucao.csv")
                
            steps_json = os.path.join(exec_dir, "reports", "historico_passos.json")
            if not os.path.exists(steps_json):
                steps_json = os.path.join(exec_dir, "historico_passos.json")
                
            if not os.path.exists(report_csv):
                self._json({'success': True, 'execution_id': execution_id, 'insights': []})
                return
                
            failed_transactions = []
            try:
                with open(report_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("status") not in ["SUCCESS", "SUCCESS_BLOCKED"]:
                            failed_transactions.append(row)
            except Exception as e:
                self._json({'success': False, 'message': f'Erro ao ler CSV de relatório: {e}'}, 500)
                return
                
            if not failed_transactions:
                self._json({'success': True, 'execution_id': execution_id, 'insights': []})
                return
                
            steps_history = []
            if os.path.exists(steps_json):
                try:
                    with open(steps_json, "r", encoding="utf-8") as f:
                        steps_history = json.load(f)
                except:
                    pass
                    
            insights = []
            diag_regex = re.compile(
                r"IA DIAGNOSE \[(?P<cat>[^\]]+)\]:\s*(?P<cause>[\s\S]*?)\s*\(Recomendação:\s*(?P<fix>[\s\S]*?)\)",
                re.DOTALL
            )
            
            for tr in failed_transactions:
                row_id = tr.get("id")
                err_msg = tr.get("error_message") or ""
                failed_field = tr.get("failed_field") or "Unknown"
                
                failed_step = None
                tr_steps = [s for s in steps_history if str(s.get("row_id")) == str(row_id)]
                if tr_steps:
                    failed_steps = [s for s in tr_steps if s.get("status") == "FAILED"]
                    if failed_steps:
                        # Prefere o último passo FAILED com step_id real (st_XXX) sobre
                        # o diagnóstico sintético de fim-de-transação que o runner
                        # registra com step_id auto-gerado (padrão "auto_N", ver
                        # runner.py::_log_step, fallback quando step_id não bate com
                        # nenhum bloco do plano). Esse "auto_N" é sempre cronologicamente
                        # o ÚLTIMO FAILED da transação, mas nunca existe como anchor
                        # "# [PASSO X]" em nenhum bot gerado — usá-lo como step_id da
                        # correção faz o code_generator._build_scoped_edit_plan nunca
                        # encontrar o bloco e cair (silenciosamente) no modo full-file,
                        # reescrevendo o robô inteiro a cada correção.
                        real_failed_steps = [
                            s for s in failed_steps
                            if s.get("step_id") and not str(s.get("step_id")).startswith("auto_")
                        ]
                        failed_step = real_failed_steps[-1] if real_failed_steps else failed_steps[-1]
                    else:
                        failed_step = tr_steps[-1]
                
                action = failed_step.get("type", "Unknown") if failed_step else "Unknown"
                selector = failed_step.get("selector", failed_field) if failed_step else failed_field
                description = failed_step.get("desc", "") if failed_step else ""
                
                match = diag_regex.search(err_msg)
                if match:
                    category = match.group("cat").strip()
                    root_cause = match.group("cause").strip()
                    proposed_fix = match.group("fix").strip()
                else:
                    category = "UNKNOWN"
                    # Tenta isolar apenas a parte do diagnóstico da IA (após o separador ' | ')
                    if " | IA DIAGNOSE" in err_msg:
                        # Remove o prefixo técnico do Playwright, mantém só o diagnóstico
                        ia_part = err_msg.split(" | IA DIAGNOSE", 1)[1]
                        # Remove o cabeçalho da categoria ex: [TIMEOUT_SELECTOR]:
                        ia_part = re.sub(r"^\s*\[[^\]]+\]:\s*", "", ia_part)
                        root_cause = ia_part.strip()
                    else:
                        root_cause = err_msg
                    if "waiting for locator" in err_msg.lower():
                        proposed_fix = "Verificar se o seletor mudou no DOM da página alvo ou se há necessidade de espera adicional."
                    else:
                        proposed_fix = "Analisar o log e ajustar as propriedades do seletor ou a temporização do fluxo."

                
                screenshot_rel = f"screenshots/screenshot_erro_transacao_{row_id}.png"
                screenshot_abs = os.path.join(exec_dir, screenshot_rel)
                if not os.path.exists(screenshot_abs):
                    screenshot_rel = f"screenshot_erro_transacao_{row_id}.png"
                    screenshot_abs = os.path.join(exec_dir, screenshot_rel)
                
                has_screenshot = os.path.exists(screenshot_abs)

                insights.append({
                    "transaction_id": row_id,
                    # "index" nunca existiu nos registros de historico_passos.json
                    # (a chave real é "step_id", ex.: "st_059") — com a chave errada
                    # step_number saia sempre None, e a correção criada a partir daqui
                    # nunca tinha como ser escopada cirurgicamente pelo code_generator
                    # (que precisa de um step_id de verdade em target_step_ids).
                    "step_number": failed_step.get("step_id") if failed_step else None,
                    "action": action,
                    "selector": selector,
                    "description": description,
                    "category": category,
                    "root_cause": root_cause,
                    "proposed_fix": proposed_fix,
                    "error_message": err_msg,
                    "screenshot": screenshot_rel if has_screenshot else None
                })

            # ── Marcação automática de failed_attempt ──────────────────────────
            # Se um seletor que tinha uma correção 'applied' ou 'pending' voltou
            # a falhar nesta execução, marcar automaticamente como 'failed_attempt'.
            # Isso garante que o Code Generator nunca repita a mesma abordagem.
            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            if insights and os.path.exists(corr_file):
                try:
                    with open(corr_file, "r", encoding="utf-8") as cf:
                        all_corrs = json.load(cf)

                    # Monta conjunto de (ação, seletor) que falharam nesta execução
                    failed_pairs = set()
                    for ins in insights:
                        a = (ins.get("action") or "").strip().lower()
                        s = (ins.get("selector") or "").strip()
                        if a and s:
                            failed_pairs.add((a, s))

                    invalidated = 0
                    for corr in all_corrs:
                        if corr.get("status") in ("applied", "pending"):
                            ca = (corr.get("action") or "").strip().lower()
                            cs = (corr.get("failed_selector") or "").strip()
                            if (ca, cs) in failed_pairs:
                                corr["status"] = "failed_attempt"
                                corr["failed_at"] = datetime.now().isoformat()
                                invalidated += 1

                    if invalidated > 0:
                        with open(corr_file, "w", encoding="utf-8") as cf:
                            json.dump(all_corrs, cf, indent=4, ensure_ascii=False)
                        print(f"[COCKPIT] ⚠️  {invalidated} correção(ões) marcada(s) como 'failed_attempt' — abordagem anterior não funcionou.")
                except Exception as ex:
                    print(f"[COCKPIT] Erro ao auto-invalidar correções: {ex}")
            # ──────────────────────────────────────────────────────────────────

            self._json({
                'success': True,
                'execution_id': execution_id,
                'insights': insights
            })

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/correcoes-status'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            pending_count = 0
            applied_count = 0
            failed_count = 0
            resolved_count = 0
            needs_review_count = 0
            corrections = []
            
            if os.path.exists(corr_file):
                try:
                    with open(corr_file, "r", encoding="utf-8") as f:
                        corrections = json.load(f)
                    pending_count = len([c for c in corrections if c.get("status") == "pending"])
                    applied_count = len([c for c in corrections if c.get("status") == "applied"])
                    failed_count = len([c for c in corrections if c.get("status") == "failed_attempt"])
                    resolved_count = len([c for c in corrections if c.get("status") == "resolved"])
                    needs_review_count = len([c for c in corrections if c.get("status") == "needs_review"])
                except:
                    pass

            self._json({
                'success': True,
                'pending': pending_count,
                'applied': applied_count,
                'failed_attempt': failed_count,
                'resolved': resolved_count,
                'needs_review': needs_review_count,
                'total': len(corrections)
            })

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/correcoes'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            corrections = []
            if os.path.exists(corr_file):
                try:
                    with open(corr_file, "r", encoding="utf-8") as f:
                        corrections = json.load(f)
                except:
                    pass
            self._json({
                'success': True,
                'correcoes': corrections
            })

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/versions-evolution'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            versions = project_manager.list_versions(slug, test_slug)
            executions = project_manager.list_executions(slug, test_slug)
            
            evolution = []
            
            all_versions_ids = [v["id"] for v in versions]
            if any(ex.get("scenario_version") in [None, "draft", ""] for ex in executions):
                all_versions_ids.insert(0, "draft")
                
            for v_id in all_versions_ids:
                if v_id == "draft":
                    v_meta = {
                        "id": "draft",
                        "name": "Rascunho Inicial",
                        "description": "Estado inicial antes do congelamento da versão v1",
                        "created_at": None,
                        "status": "draft"
                    }
                else:
                    v_meta = next((v for v in versions if v["id"] == v_id), None)
                    if not v_meta:
                        continue
                        
                v_execs = [ex for ex in executions if ex.get("scenario_version") == v_id and ex.get("status") != "RUNNING"]
                
                if not v_execs:
                    evolution.append({
                        "version_id": v_id,
                        "version_name": v_meta["name"],
                        "created_at": v_meta["created_at"],
                        "has_execution": False,
                        "metrics": None
                    })
                    continue
                    
                latest_exec = v_execs[-1]
                execution_id = latest_exec["id"]
                
                total_transactions = latest_exec.get("total_runs", 0)
                passed_transactions = latest_exec.get("passed_runs", 0)
                failed_transactions = total_transactions - passed_transactions
                
                exec_dir = os.path.join(test_dir, "executions", execution_id)
                steps_json = os.path.join(exec_dir, "reports", "historico_passos.json")
                if not os.path.exists(steps_json):
                    steps_json = os.path.join(exec_dir, "historico_passos.json")
                    
                success_steps = 0
                healed_steps = 0
                failed_steps = 0
                has_steps_info = False
                
                if os.path.exists(steps_json):
                    try:
                        with open(steps_json, "r", encoding="utf-8") as sf:
                            steps = json.load(sf)
                        if isinstance(steps, list):
                            has_steps_info = True
                            for step in steps:
                                status = step.get("status", "").upper()
                                if status == "SUCCESS":
                                    success_steps += 1
                                elif status == "HEALED":
                                    healed_steps += 1
                                elif status == "FAILED":
                                    failed_steps += 1
                    except:
                        pass
                        
                evolution.append({
                    "version_id": v_id,
                    "version_name": v_meta["name"],
                    "created_at": v_meta["created_at"],
                    "has_execution": True,
                    "execution_id": execution_id,
                    "timestamp": latest_exec.get("timestamp"),
                    "status": latest_exec.get("status"),
                    "duration_seconds": latest_exec.get("duration_seconds", 0),
                    "metrics": {
                        "transactions": {
                            "total": total_transactions,
                            "passed": passed_transactions,
                            "failed": failed_transactions
                        },
                        "steps": {
                            "has_data": has_steps_info,
                            "success": success_steps,
                            "healed": healed_steps,
                            "failed": failed_steps
                        }
                    }
                })
                
            self._json({
                'success': True,
                'evolution': evolution
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
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
            business_description = body.get('business_description', '').strip()
            expected_business_outcome = body.get('expected_business_outcome', '').strip()
            llm_api_key = body.get('llm_api_key', '').strip()
            if not name:
                self._json({'success': False, 'message': 'Nome do projeto é obrigatório.'}, 400)
                return
            if not llm_api_key:
                self._json({'success': False, 'message': 'O Token da API da LLM é obrigatório.'}, 400)
                return
            meta = project_manager.create_project(
                name=name,
                url=url,
                custom_path=custom_path,
                business_description=business_description,
                expected_business_outcome=expected_business_outcome,
                llm_api_key=llm_api_key
            )
            self._json({'success': True, 'project': meta})

        elif path.startswith('/api/projects/') and path.endswith('/tests'):
            parts = path.split('/')
            project_slug = urllib.parse.unquote(parts[3])
            name = body.get('name', '').strip()
            url = body.get('url', '').strip()
            business_description = body.get('business_description', '').strip()
            expected_business_outcome = body.get('expected_business_outcome', '').strip()
            if not name:
                self._json({'success': False, 'message': 'Nome do cenário é obrigatório.'}, 400)
                return
            try:
                meta = project_manager.create_test(
                    project_slug, name, url=url, 
                    business_description=business_description, 
                    expected_business_outcome=expected_business_outcome
                )
                self._json({'success': True, 'test': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/skills/promote'):
            parts = path.split('/')
            project_slug = urllib.parse.unquote(parts[3])
            test_slug = body.get('test_slug', '').strip()
            skill_name = body.get('skill_name', '').strip()
            skill_slug = body.get('skill_slug', '').strip() or None
            category = body.get('category', 'Geral').strip()
            description = body.get('description', '').strip()
            
            if not test_slug or not skill_name:
                self._json({'success': False, 'message': 'test_slug e skill_name são obrigatórios.'}, 400)
                return
                
            try:
                meta = project_manager.promote_to_skill(
                    project_slug=project_slug,
                    test_slug=test_slug,
                    skill_name=skill_name,
                    skill_slug=skill_slug,
                    category=category,
                    description=description
                )
                self._json({'success': True, 'skill': meta})
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
            execution_id = body.get('execution_id', '') or query.get('execution_id', [None])[0]
            steps_data = body.get('steps', [])
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
                
            history_path = os.path.join(proj_dir, "historico_passos.json")
            try:
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(steps_data, f, indent=4, ensure_ascii=False)

                # Se houver um execution_id ativo, grava também dentro da pasta da execução
                if execution_id:
                    exec_history_path = os.path.join(proj_dir, "executions", execution_id, "historico_passos.json")
                    try:
                        os.makedirs(os.path.dirname(exec_history_path), exist_ok=True)
                        with open(exec_history_path, "w", encoding="utf-8") as f:
                            json.dump(steps_data, f, indent=4, ensure_ascii=False)
                    except Exception as ex:
                        print(f"[WARNING] Falha ao gravar historico_passos na execucao: {ex}")

                # Sincroniza gravacao.json e relatorio.md com os passos editados
                # Coleta os event_index sobreviventes para filtrar gravacao.json
                surviving_indices = set()
                for step in steps_data:
                    ei = step.get("event_index")
                    if ei is not None:
                        surviving_indices.add(int(ei))

                if surviving_indices:
                    gravacao_path = os.path.join(proj_dir, "gravacao.json")
                    if os.path.exists(gravacao_path):
                        try:
                            with open(gravacao_path, "r", encoding="utf-8") as gf:
                                gravacao_data = json.load(gf)
                            events = gravacao_data.get("events", [])
                            original_count = len(events)

                            # Filtra mantendo apenas eventos cujos índices estão nos sobreviventes
                            filtered_events = [
                                ev for i, ev in enumerate(events)
                                if i in surviving_indices
                            ]

                            if len(filtered_events) < original_count:
                                gravacao_data["events"] = filtered_events
                                with open(gravacao_path, "w", encoding="utf-8") as gf:
                                    json.dump(gravacao_data, gf, indent=4, ensure_ascii=False)
                                print(f"[STEPS-HISTORY] gravacao.json sincronizado: {original_count} -> {len(filtered_events)} eventos")

                                # Regenera relatorio.md sem disparar refine_semantics_with_llm
                                try:
                                    _regenerate_report_safe(proj_dir, gravacao_data)
                                    print(f"[STEPS-HISTORY] relatorio.md regenerado")
                                except Exception as san_err:
                                    print(f"[WARNING] Falha ao regenerar relatorio.md: {san_err}")
                        except Exception as gv_err:
                            print(f"[WARNING] Falha ao sincronizar gravacao.json: {gv_err}")

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
                    if 'url' in body:
                        meta['url'] = body.get('url', meta.get('url', ''))
                    if 'business_description' in body:
                        meta['business_description'] = body.get('business_description', '')
                    if 'expected_business_outcome' in body:
                        meta['expected_business_outcome'] = body.get('expected_business_outcome', '')
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

        elif path.startswith('/api/projects/') and path.endswith('/edit') and '/tests/' not in path:
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            new_name = body.get('name', '').strip()
            new_desc = body.get('business_description', '').strip()
            new_outcome = body.get('expected_business_outcome', '').strip()
            if not new_name:
                self._json({'success': False, 'message': 'Nome do projeto é obrigatório.'}, 400)
                return
            try:
                meta = project_manager.edit_project(slug, new_name, new_desc, new_outcome)
                self._json({'success': True, 'project': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/edit'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            new_name = body.get('name', '').strip()
            new_desc = body.get('business_description', '').strip()
            new_outcome = body.get('expected_business_outcome', '').strip()
            if not new_name:
                self._json({'success': False, 'message': 'Nome do cenário é obrigatório.'}, 400)
                return
            try:
                meta = project_manager.edit_test(slug, test_slug, new_name, new_desc, new_outcome)
                self._json({'success': True, 'test': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/enrich') and '/tests/' not in path:
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            name = body.get('name', '').strip()
            url_context = body.get('url', '').strip()
            desc = body.get('business_description', '').strip()
            outcome = body.get('expected_business_outcome', '').strip()
            
            try:
                from aegis_runner.cognitive_fallback import CognitiveGateway
                proj_dir = project_manager.get_project_dir(slug)
                gateway = CognitiveGateway(project_dir=proj_dir)
                if not gateway.is_active():
                    self._json({'success': False, 'message': 'Módulo cognitivo (LLM) inativo ou sem API Key configurada.'}, 400)
                    return
                
                prompt = f"""
                Você é o Aegis Mentor, especialista em engenharia de requisitos de RPA e QA.
                O usuário quer enriquecer a descrição de negócio e o resultado de negócio esperado para o projeto RPA abaixo.
                Nome do Projeto: {name}
                URL/Contexto do Alvo: {url_context}
                Descrição Atual: {desc}
                Resultado Esperado Atual: {outcome}

                Sua tarefa é melhorar, detalhar e refinar tecnicamente a descrição de negócio e o resultado esperado do projeto, tornando-os mais profissionais, claros e focados em QA.

                Retorne OBRIGATORIAMENTE um objeto JSON com os campos:
                - "business_description": Descrição enriquecida e detalhada do projeto.
                - "expected_business_outcome": Descrição enriquecida do resultado esperado.
                
                Retorne EXCLUSIVAMENTE o JSON sem blocos de formatação markdown adicionais.
                """
                response_text = gateway.call_llm(prompt, force_json=True)
                json_data = gateway.parse_json_response(response_text)
                self._json({'success': True, 'enriched': json_data})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/enrich'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            name = body.get('name', '').strip()
            desc = body.get('business_description', '').strip()
            outcome = body.get('expected_business_outcome', '').strip()
            
            try:
                from aegis_runner.cognitive_fallback import CognitiveGateway
                proj_dir = project_manager.get_project_dir(slug)
                gateway = CognitiveGateway(project_dir=os.path.join(proj_dir, "tests", test_slug))
                if not gateway.is_active():
                    self._json({'success': False, 'message': 'Módulo cognitivo (LLM) inativo ou sem API Key configurada.'}, 400)
                    return
                
                prompt = f"""
                Você é o Aegis Mentor, especialista em engenharia de requisitos de RPA e QA.
                O usuário quer enriquecer a descrição de negócio e o resultado de negócio esperado para o cenário de teste abaixo.
                Nome do Cenário: {name}
                Descrição Atual: {desc}
                Resultado Esperado Atual: {outcome}

                Sua tarefa é melhorar, detalhar e refinar tecnicamente a descrição de negócio e o resultado esperado, tornando-os mais focados em cenários de QA e cobertura de testes de regressão.

                Retorne OBRIGATORIAMENTE um objeto JSON com os campos:
                - "business_description": Descrição enriquecida e detalhada do cenário.
                - "expected_business_outcome": Descrição enriquecida do resultado esperado.
                
                Retorne EXCLUSIVAMENTE o JSON sem blocos de formatação markdown adicionais.
                """
                response_text = gateway.call_llm(prompt, force_json=True)
                json_data = gateway.parse_json_response(response_text)
                self._json({'success': True, 'enriched': json_data})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/dataset'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            proj_dir = project_manager.get_project_dir(slug)
            if test_slug:
                proj_dir = os.path.join(proj_dir, "tests", test_slug)
                
            dataset_path = os.path.join(proj_dir, "dataset_inicial.json")
            
            try:
                # O payload deve ser uma lista de registros
                if not isinstance(body, list):
                    self._json({'success': False, 'message': 'O dataset deve ser uma lista de registros.'}, 400)
                    return
                
                with open(dataset_path, "w", encoding="utf-8") as f:
                    json.dump(body, f, indent=4, ensure_ascii=False)
                
                # Atualiza metadados do projeto
                project_manager.update_project_activity(slug)
                
                self._json({'success': True, 'message': 'Dataset atualizado com sucesso.'})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

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

        elif path.startswith('/api/projects/') and path.endswith('/devops-config') and '/tests/' not in path:
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            try:
                saved = project_manager.save_devops_config(slug, body)
                # Oculta segredos ao responder
                masked = dict(saved)
                for key in ["pat", "llm_api_key"]:
                    if masked.get(key):
                        masked[key] = "********"
                self._json({'success': True, 'config': masked})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/publish-devops') and '/tests/' not in path:
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            
            if process_manager.active_process is not None:
                self._json({'success': False, 'message': 'Já existe um processo em execução. Pare-o primeiro.'}, 400)
                return
                
            proj_dir = project_manager.get_project_dir(slug)
            config_file = os.path.join(proj_dir, "devops_config.json")
            if not os.path.exists(config_file):
                self._json({'success': False, 'message': 'Configure o DevOps para este projeto antes de publicar.'}, 400)
                return
                
            publisher_script = os.path.join(PROJECT_ROOT, 'aegis_devops', 'publish_pipeline.py')
            cmd = [sys.executable, '-u', publisher_script, '--project-slug', slug]
            process_manager.run_command_in_background(
                cmd, 'PUBLICAÇÃO_DEVOPS', cwd=PROJECT_ROOT, project_slug=slug
            )
            self._json({'success': True, 'message': 'Publicação do DevOps iniciada em background!'})

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
            for name in ['code/bot_producao.py', 'bot_producao.py', 'code/robot.py', 'robot.py', 'code/run_bot.py', 'run_bot.py']:
                candidate = os.path.join(proj_dir, name)
                if os.path.exists(candidate):
                    bot_script = candidate
                    break
            
            if not bot_script:
                self._json({'success': False, 'message': 'Nenhum script de robô encontrado no projeto.'}, 400)
                return
                
            execution_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                exec_dir = project_manager.prepare_execution(slug, test_slug, execution_id)
            except Exception as e:
                self._json({'success': False, 'message': f'Falha ao preparar diretório de execução: {e}'}, 500)
                return
                
            headless = body.get('headless', True)
            screenshots = body.get('screenshots', False)
            realtime_logs = body.get('realtime_logs', True)
            selected_ids = body.get('selected_ids', [])
            
            if selected_ids and isinstance(selected_ids, list):
                dataset_path = os.path.join(proj_dir, "dataset_inicial.json")
                if os.path.exists(dataset_path):
                    try:
                        with open(dataset_path, "r", encoding="utf-8") as f:
                            full_dataset = json.load(f)
                        if isinstance(full_dataset, dict):
                            full_dataset = [full_dataset]
                        
                        filtered_dataset = [row for row in full_dataset if str(row.get('id', '')) in [str(x) for x in selected_ids]]
                        
                        exec_ds_path = os.path.join(exec_dir, "dataset_inicial.json")
                        with open(exec_ds_path, "w", encoding="utf-8") as f:
                            json.dump(filtered_dataset, f, indent=4, ensure_ascii=False)
                    except Exception as filter_err:
                        print(f"[COCKPIT ERROR] Falha ao filtrar dataset para execução: {filter_err}")
            
            cmd = [sys.executable, '-u', bot_script]
            process_manager.run_command_in_background(
                cmd, 'EXECUÇÃO_ROBÔ', cwd=proj_dir, 
                project_slug=slug, test_slug=test_slug,
                env_vars={
                    "AEGIS_EXECUTION_DIR": exec_dir, 
                    "AEGIS_EXECUTION_ID": execution_id,
                    "AEGIS_BROWSER_HEADLESS": "true" if headless else "false",
                    "AEGIS_STEP_SCREENSHOTS": "true" if screenshots else "false",
                    "AEGIS_STEP_LOGS_REALTIME": "true" if realtime_logs else "false"
                },
                execution_id=execution_id
            )
            self._json({'success': True, 'message': 'Robô de produção iniciado!', 'execution_id': execution_id})

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

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/restore'):
            # POST /api/projects/{slug}/tests/{test_slug}/versions/{version_id}/restore
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            version_id = urllib.parse.unquote(parts[7])
            try:
                project_manager.restore_version(slug, test_slug, version_id)
                self._json({'success': True, 'message': f'Versão {version_id} restaurada com sucesso.'})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and '/versions/' in path and path.endswith('/clone'):
            # POST /api/projects/{slug}/tests/{test_slug}/versions/{version_id}/clone
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            version_id = urllib.parse.unquote(parts[7])
            name = body.get('name', '').strip()
            description = body.get('description', '').strip()
            try:
                meta = project_manager.clone_version(slug, test_slug, version_id, name, description)
                self._json({'success': True, 'version': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/versions'):
            # POST /api/projects/{slug}/tests/{test_slug}/versions
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            name = body.get('name', '').strip()
            description = body.get('description', '').strip()
            clean = body.get('clean', False)
            try:
                meta = project_manager.create_version(slug, test_slug, name, description, clean=clean)
                self._json({'success': True, 'version': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/save'):
            # POST /api/projects/{slug}/tests/{test_slug}/save
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            try:
                project_manager.save_current_version(slug, test_slug)
                self._json({'success': True})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/clone'):
            # POST /api/projects/{slug}/tests/{test_slug}/clone
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            new_test_name = body.get('new_test_name', '').strip()
            try:
                meta = project_manager.clone_test(slug, test_slug, new_test_name)
                self._json({'success': True, 'test': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and path.endswith('/clone'):
            # POST /api/projects/{slug}/clone
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            new_project_name = body.get('new_project_name', '').strip()
            try:
                meta = project_manager.clone_project(slug, new_project_name)
                self._json({'success': True, 'project': meta})
            except Exception as e:
                self._json({'success': False, 'message': str(e)}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and path.endswith('/execution-insights/approve'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            execution_id = body.get('execution_id')
            corrections_list = body.get('corrections', [])
            qa_insight = body.get('qa_insight', '').strip()
            
            if not corrections_list:
                self._json({'success': False, 'message': 'Nenhuma correção informada.'}, 400)
                return
                
            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            existing_corrections = []
            if os.path.exists(corr_file):
                try:
                    with open(corr_file, "r", encoding="utf-8") as f:
                        existing_corrections = json.load(f)
                except:
                    pass
                    
            now_str = datetime.now().isoformat()
            ts_suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            for idx, corr in enumerate(corrections_list):
                sel = corr.get("selector")
                act = corr.get("action")
                # Se houver correção anterior aplicada para o mesmo seletor/ação, ela falhou.
                # Atualiza seu status para 'failed_attempt'.
                for ec in existing_corrections:
                    if ec.get("failed_selector") == sel and ec.get("action") == act and ec.get("status") in ("applied", "pending"):
                        ec["status"] = "failed_attempt"
                        ec["failed_at"] = now_str
                
                new_corr = {
                    "id": f"corr_{ts_suffix}_{idx+1}",
                    "timestamp": now_str,
                    "execution_id": execution_id,
                    "step_number": corr.get("step_number"),
                    # step_id explícito (mesmo valor de step_number, que já é o
                    # step_id real do passo desde a correção de cockpit.py:576) —
                    # code_generator._surgical_correct monta target_step_ids a
                    # partir de "step_id", não de "step_number". Sem essa chave,
                    # a correção nunca entra no escopo cirúrgico e o code
                    # generator cai no modo full-file (risco de reescrever passos
                    # não relacionados à correção pedida).
                    "step_id": corr.get("step_number"),
                    "failed_selector": sel,
                    "action": act,
                    "root_cause": corr.get("root_cause"),
                    "proposed_fix": corr.get("proposed_fix"),
                    "qa_insight": qa_insight if qa_insight else None,
                    "failed_screenshot": corr.get("screenshot"),
                    "status": "pending"
                }
                existing_corrections.append(new_corr)
                
            try:
                with open(corr_file, "w", encoding="utf-8") as f:
                    json.dump(existing_corrections, f, indent=4, ensure_ascii=False)
                
                project_manager.update_project_activity(slug)
                insight_msg = " (com insight QA)" if qa_insight else ""
                self._json({'success': True, 'message': f'{len(corrections_list)} correções aprovadas e registradas com sucesso{insight_msg}.'})
            except Exception as e:
                self._json({'success': False, 'message': f'Erro ao salvar correções: {e}'}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and '/correcoes/' in path and path.endswith('/status'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            corr_id = urllib.parse.unquote(parts[7])
            
            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)
            
            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return
                
            new_status = body.get('status')
            if not new_status:
                self._json({'success': False, 'message': 'Novo status não informado.'}, 400)
                return

            # Campos opcionais que o QA pode atualizar ao recolocar na fila
            new_qa_insight = body.get('qa_insight')       # None = não alterar
            new_proposed_fix = body.get('proposed_fix')   # None = não alterar

            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            if not os.path.exists(corr_file):
                self._json({'success': False, 'message': 'Nenhuma correção registrada.'}, 404)
                return

            try:
                with open(corr_file, "r", encoding="utf-8") as f:
                    corrections = json.load(f)

                found = False
                for corr in corrections:
                    if corr.get("id") == corr_id:
                        corr["status"] = new_status
                        corr["updated_at"] = datetime.now().isoformat()

                        # Atualiza insight QA se fornecido
                        if new_qa_insight is not None:
                            corr["qa_insight"] = new_qa_insight.strip()

                        # Atualiza proposta de correção se fornecida
                        if new_proposed_fix is not None and new_proposed_fix.strip():
                            corr["proposed_fix"] = new_proposed_fix.strip()

                        # Se está voltando para pending, limpa timestamps de falha
                        if new_status == "pending":
                            corr.pop("failed_at", None)
                            corr.pop("applied_at", None)

                        found = True
                        break

                if not found:
                    self._json({'success': False, 'message': f'Correção {corr_id} não encontrada.'}, 404)
                    return

                with open(corr_file, "w", encoding="utf-8") as f:
                    json.dump(corrections, f, indent=4, ensure_ascii=False)

                project_manager.update_project_activity(slug)
                insight_note = " (com novo insight QA)" if new_qa_insight else ""
                self._json({'success': True, 'message': f'Status da correção {corr_id} atualizado para {new_status}{insight_note}.'})
            except Exception as e:
                self._json({'success': False, 'message': f'Erro ao atualizar status: {e}'}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and '/steps/' in path and path.endswith('/flaky'):
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            step_id = urllib.parse.unquote(parts[7])

            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)

            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return

            flaky_value = body.get('flaky')
            if not isinstance(flaky_value, bool):
                self._json({'success': False, 'message': 'Campo "flaky" (booleano) é obrigatório.'}, 400)
                return

            plan_file = os.path.join(test_dir, "plano_execucao.json")
            if not os.path.exists(plan_file):
                self._json({'success': False, 'message': 'plano_execucao.json não encontrado.'}, 404)
                return

            try:
                with open(plan_file, "r", encoding="utf-8") as f:
                    plan = json.load(f)

                steps = plan.get("steps", []) if isinstance(plan, dict) else []
                found = False
                for step in steps:
                    if str(step.get("step_id")) == str(step_id):
                        step["flaky"] = flaky_value
                        found = True
                        break

                if not found:
                    self._json({'success': False, 'message': f'Passo {step_id} não encontrado no plano.'}, 404)
                    return

                with open(plan_file, "w", encoding="utf-8") as f:
                    json.dump(plan, f, indent=4, ensure_ascii=False)

                self._json({'success': True, 'message': f'Passo {step_id} marcado como flaky={flaky_value}.'})
            except Exception as e:
                self._json({'success': False, 'message': f'Erro ao atualizar flaky: {e}'}, 500)

        elif path.startswith('/api/projects/') and '/tests/' in path and '/steps/' in path and path.endswith('/mark-failed'):
            # QA marca manualmente um passo como falho, com descrição própria.
            # Existe porque o runner pode marcar SUCCESS um passo que na prática
            # não teve o efeito esperado (a IA de diagnóstico só roda quando o
            # runner detecta um erro técnico; se o passo "funciona" tecnicamente
            # mas produz o resultado errado, nada aciona correção automática, e
            # a causa raiz real nunca entra no pipeline de correção cirúrgica —
            # travando o Ralph Loop num loop sem solução em passos downstream).
            parts = path.split('/')
            slug = urllib.parse.unquote(parts[3])
            test_slug = urllib.parse.unquote(parts[5])
            step_id = urllib.parse.unquote(parts[7])

            proj_dir = project_manager.get_project_dir(slug)
            test_dir = os.path.join(proj_dir, "tests", test_slug)

            if not os.path.exists(test_dir):
                self._json({'success': False, 'message': 'Cenário não encontrado.'}, 404)
                return

            description = (body.get('description') or '').strip()
            if not description:
                self._json({'success': False, 'message': 'Campo "description" é obrigatório.'}, 400)
                return

            # Busca seletor/ação do passo no plano (opcional, só para contexto —
            # a correção funciona mesmo sem, já que o escopo cirúrgico usa step_id).
            failed_selector = None
            action = "manual_flag"
            plan_file = os.path.join(test_dir, "plano_execucao.json")
            if os.path.exists(plan_file):
                try:
                    with open(plan_file, "r", encoding="utf-8") as f:
                        plan = json.load(f)
                    for step in plan.get("steps", []) if isinstance(plan, dict) else []:
                        if str(step.get("step_id")) == str(step_id):
                            failed_selector = step.get("selector")
                            action = step.get("type", action)
                            break
                except Exception:
                    pass

            corr_file = os.path.join(test_dir, "correcoes_acumuladas.json")
            existing_corrections = []
            if os.path.exists(corr_file):
                try:
                    with open(corr_file, "r", encoding="utf-8") as f:
                        existing_corrections = json.load(f)
                except Exception:
                    pass

            now_str = datetime.now().isoformat()
            ts_suffix = datetime.now().strftime('%Y%m%d_%H%M%S')
            new_corr = {
                "id": f"corr_manual_{ts_suffix}",
                "timestamp": now_str,
                "execution_id": "manual",
                "step_id": step_id,
                "failed_selector": failed_selector,
                "action": action,
                "root_cause": f"Marcado manualmente pelo QA como falho: {description}",
                "proposed_fix": description,
                "qa_insight": description,
                "failed_screenshot": None,
                "status": "pending"
            }
            existing_corrections.append(new_corr)

            try:
                with open(corr_file, "w", encoding="utf-8") as f:
                    json.dump(existing_corrections, f, indent=4, ensure_ascii=False)
                project_manager.update_project_activity(slug)
                self._json({'success': True, 'message': f'Passo {step_id} marcado como falho para correção.', 'correction_id': new_corr['id']})
            except Exception as e:
                self._json({'success': False, 'message': f'Erro ao registrar correção manual: {e}'}, 500)

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
