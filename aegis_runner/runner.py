import os
import sys
import time
import csv
import re
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

try:
    from cognitive_fallback import CognitiveGateway
except ImportError:
    from aegis_runner.cognitive_fallback import CognitiveGateway

class TransactionRunner:
    def __init__(self, project_dir, error_message_selector=".toast-error, .alert-danger, #angular-field-status-message", cognitive_gateway=None, initial_url=None, **kwargs):
        self.project_dir = os.path.abspath(project_dir)
        self.error_message_selector = error_message_selector

        # Resolve initial_url a partir do project.json se não informado
        self.initial_url = initial_url
        if not self.initial_url:
            project_json = os.path.join(self.project_dir, "project.json")
            if os.path.exists(project_json):
                try:
                    with open(project_json, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        self.initial_url = meta.get("url")
                except:
                    pass

        self.scenarios = {}

        # Plano de execução carregado (opcional)
        self.execution_plan = None

        # Direcionamento de logs de execução para pasta separada se configurado
        self.output_dir = os.environ.get("AEGIS_EXECUTION_DIR")
        if self.output_dir:
            self.output_dir = os.path.abspath(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)
        else:
            self.output_dir = self.project_dir

        # Garante a existência das subpastas organizadas de execução
        os.makedirs(os.path.join(self.output_dir, "reports"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "screenshots"), exist_ok=True)
        
        # Arquivos de dados do projeto
        self.dataset_json = os.path.join(self.project_dir, "dataset_inicial.json")
        self.dataset_csv = os.path.join(self.project_dir, "dados_entrada.csv")
        self.report_csv = os.path.join(self.output_dir, "reports", "relatorio_execucao.csv")
        
        # Configura a saída UTF-8
        sys.stdout.reconfigure(encoding='utf-8')

        # Inicializa Gateway Cognitivo do Aegis apontando para a pasta do projeto
        if cognitive_gateway is not None:
            self.cognitive = cognitive_gateway
        else:
            self.cognitive = CognitiveGateway(project_dir=self.project_dir)

        # Inicializa controle de screenshots por passo e id da transação
        self.step_screenshots = os.environ.get("AEGIS_STEP_SCREENSHOTS", "false").lower() in ("true", "1", "yes")
        self.realtime_logs = os.environ.get("AEGIS_STEP_LOGS_REALTIME", "true").lower() in ("true", "1", "yes")
        self.step_counter = 0
        self.current_row_id = "1"
        self.steps_history = []

    def register_scenario(self, scenario_name, callback):
        """Registra a rotina de preenchimento de formulário para um cenário lógico."""
        self.scenarios[scenario_name] = callback
        print(f"[AEGIS RUNNER] Cenário '{scenario_name}' registrado com sucesso.")

    def _log_step(self, step_id, action, selector, target_description, status, error_msg=""):
        """Registra um passo no histórico interno da execução com atualização in-place por step_id."""
        # Captura screenshot se SUCCESS/HEALED e step_screenshots ativo
        screenshot_filename = ""
        row_id = getattr(self, "current_row_id", "1")
        if status in ("SUCCESS", "HEALED") and getattr(self, "step_screenshots", False):
            self.step_counter = getattr(self, "step_counter", 0) + 1
            # Substitui caracteres inválidos para nome de arquivo seguro
            clean_sel = re.sub(r'[^a-zA-Z0-9_\-]', '_', selector)[:30]
            screenshot_filename = f"screenshots/step_{row_id}_{self.step_counter}_{action}_{clean_sel}.png"
            path = os.path.join(self.output_dir, screenshot_filename)
            try:
                if hasattr(self, 'page') and self.page:
                    self.page.screenshot(path=path)
                print(f"[AEGIS RUNNER] Screenshot do passo {self.step_counter} salvo em: {path}")
            except Exception as e:
                try:
                    # Tenta usar 'page' do escopo local se disponível (métodos de ação)
                    page_locals = [v for v in locals().values() if hasattr(v, 'screenshot') and callable(v.screenshot)]
                    if page_locals:
                        page_locals[0].screenshot(path=path)
                    print(f"[AEGIS RUNNER] Screenshot do passo {self.step_counter} salvo em: {path} (via fallback)")
                except Exception as e2:
                    print(f"[WARNING] Falha ao capturar screenshot do passo {self.step_counter}: {e2}")
                    screenshot_filename = ""

        timestamp_iso = datetime.now().isoformat()

        # Atualização in-place: busca step_id no array existente
        updated = False
        if hasattr(self, "steps_history") and self.steps_history:
            for step in self.steps_history:
                if step.get("step_id") == step_id:
                    step["type"] = action
                    step["selector"] = selector
                    step["desc"] = target_description
                    step["status"] = status
                    step["error"] = error_msg
                    step["usedHealing"] = status == "HEALED"
                    step["screenshot"] = screenshot_filename or None
                    step["row_id"] = row_id
                    step["timestamp"] = timestamp_iso
                    updated = True
                    break

        # Fallback: se não encontrou step_id, faz append (modo legado)
        if not updated:
            if not hasattr(self, "steps_history"):
                self.steps_history = []
            self.steps_history.append({
                "step_id": step_id or f"auto_{len(self.steps_history) + 1}",
                "type": action,
                "selector": selector,
                "desc": target_description,
                "status": status,
                "error": error_msg,
                "usedHealing": status == "HEALED",
                "screenshot": screenshot_filename or None,
                "row_id": row_id,
                "timestamp": timestamp_iso
            })
            if step_id:
                print(f"[AEGIS RUNNER] step_id '{step_id}' não encontrado no plano; registrado como novo passo.")

        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] {status} | {step_id} | {action} | {selector} | {target_description} | {error_msg} | {screenshot_filename} | {row_id}")
            sys.stdout.flush()

        # Escreve histórico em tempo real para polling (evita mostrar dados velhos durante execução)
        self._write_steps_realtime()

    def _write_steps_realtime(self):
        """Escreve steps_history atual para arquivo imediatamente (para polling live)."""
        try:
            # Escreve em reports/ (pasta de execução corrente)
            steps_json_path = os.path.join(self.output_dir, "reports", "historico_passos.json")
            with open(steps_json_path, "w", encoding="utf-8") as sf:
                json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)

            # Escreve também na raiz do projeto para fallback de polling (compatibilidade)
            try:
                root_steps_path = os.path.join(self.project_dir, "historico_passos.json")
                with open(root_steps_path, "w", encoding="utf-8") as sf:
                    json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)
            except:
                pass
        except Exception:
            pass  # Falha silenciosa - não interrompe execução

    def click_resilient(self, page, selector, target_description, timeout=5000, validate_navigation=False, original_coords=None, step_id=None, strict=False) -> bool:
        """
        Executa um clique resiliente e inteligente.
        - Expansão de Submenu (Hover-to-Reveal): Se o seletor for composto (>>), tenta fazer hover no pai.
        - Tolerância Temporal: Aguarda o elemento ficar visível antes de listar candidatos.
        - Tratamento de Desprendimento: Retenta o clique caso o nó se desprenda durante o ciclo Angular.
        - Heurística Estática: Se houver múltiplos elementos correspondendo ao seletor,
          prioriza elementos que NÃO são âncoras locais (href='#...').
        - Validação Ativa: Se validate_navigation=True, verifica se o clique causou navegação.
          Caso contrário, tenta clicar em outros elementos correspondentes de forma sequencial.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | click | {selector} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        # 1. Se o seletor for composto (encadeado com >>), faz hover sequencial nos pais para expandir menus multinível
        if " >> " in selector:
            parts = selector.split(" >> ")
            try:
                # Verifica rápido se o próprio filho já está visível; se não estiver, faz hover nos níveis intermediários
                if not page.locator(selector).first.is_visible(timeout=500):
                    for i in range(1, len(parts)):
                        sub_parent = " >> ".join(parts[:i])
                        try:
                            if page.locator(sub_parent).first.is_visible(timeout=500):
                                print(f"[AEGIS RUNNER] Expandindo nível de menu intermediário: '{sub_parent}'...")
                                page.locator(sub_parent).first.hover(timeout=1000)
                                time.sleep(0.3) # Aguarda transição/animação da revelação
                        except Exception:
                            pass
            except Exception:
                pass

        # 2. Loop de retentativas com Auto-Healing de UI
        last_exception = None
        for attempt in range(1, 3):
            try:
                # Nível 2: Auto-Healing de UI - Tenta limpar overlays ativos na segunda tentativa
                if attempt == 2:
                    print(f"[AEGIS RUNNER] [RETRY 2] Limpando possíveis overlays pendentes via Escape...")
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

                # Aguarda visibilidade por até 2 segundos antes de listar os candidatos
                try:
                    page.wait_for_selector(selector, state="visible", timeout=2000)
                except Exception:
                    pass

                locators = page.locator(selector).all()
                if not locators:
                    print(f"[AEGIS RUNNER] Tentando clique físico em '{selector}'...")
                    page.locator(selector).click(timeout=timeout)
                    self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
                    return True

                # Heurística Estática (Separar âncoras locais de links externos reais)
                prioritized_locators = []
                anchor_locators = []
                for loc in locators:
                    try:
                        href = loc.get_attribute("href", timeout=500) or ""
                        if href.startswith("#"):
                            anchor_locators.append(loc)
                        else:
                            prioritized_locators.append(loc)
                    except Exception:
                        prioritized_locators.append(loc)

                candidate_locators = prioritized_locators if prioritized_locators else anchor_locators
                initial_url = page.url
                clicked = False

                for idx, loc in enumerate(candidate_locators):
                    try:
                        if not loc.is_visible():
                            continue

                        print(f"[AEGIS RUNNER] Tentando clique físico no elemento {idx+1}/{len(candidate_locators)} de '{selector}'...")
                        loc.scroll_into_view_if_needed(timeout=1000)
                        time.sleep(0.2)
                        loc.click(timeout=3000, force=True)
                        clicked = True
                        
                        if validate_navigation:
                            time.sleep(3.0)
                            if page.url == initial_url:
                                href = loc.get_attribute("href", timeout=500) or ""
                                if href and not href.startswith("#") and href.startswith("http"):
                                    print(f"[AEGIS RUNNER] Clique físico no candidato {idx+1} não alterou a URL. Forçando navegação direta para: {href}")
                                    try:
                                        page.goto(href, timeout=20000, wait_until="domcontentloaded")
                                        clicked = True
                                        break
                                    except Exception as goto_ex:
                                        print(f"[AEGIS RUNNER] Falha ao forçar navegação direta: {goto_ex}")

                                if idx < len(candidate_locators) - 1:
                                    print(f"[AEGIS RUNNER] Clique no candidato {idx+1} não resultou em navegação (URL inalterada). Tentando próximo candidato...")
                                    clicked = False
                                    continue
                        break
                    except Exception as e:
                        # Nível 1: Elemento desprendido (Stale/Detached)
                        if "attached" in str(e) or "stale" in str(e).lower() or "detached" in str(e).lower():
                            print(f"[AEGIS RUNNER] Elemento desprendido do DOM (Stale/Detached). Aguardando estabilização...")
                            time.sleep(0.2)
                            try:
                                page.locator(selector).first.click(timeout=3000)
                                clicked = True
                                break
                            except Exception as retry_ex:
                                e = retry_ex

                        if idx == len(candidate_locators) - 1:
                            raise e
                        print(f"[AEGIS RUNNER] Falha ao clicar no candidato {idx+1}: {e}. Retentando próximo...")
                        continue

                if clicked:
                    self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
                    return True
                else:
                    raise RuntimeError("Nenhum candidato correspondente ao seletor estava visível ou clicável no DOM.")

            except Exception as e:
                last_exception = e
                print(f"[AEGIS RUNNER] Tentativa {attempt} de clique falhou para '{selector}': {e}")
                if attempt == 2:
                    return self._handle_click_failure(page, selector, target_description, timeout, e, original_coords, step_id=step_id, strict=strict)

    def click_by_coordinates(self, page, original_coords, target_description, step_id=None) -> bool:
        """
        Clique físico direto por coordenadas relativas de gravação, sem
        nenhuma resolução de seletor CSS. Único caminho determinístico para
        elementos dentro de um Shadow DOM fechado (`attachShadow({mode:
        'closed'})`): a árvore de sombra fechada é inacessível a qualquer
        seletor CSS/JS externo por design da plataforma (não é limitação do
        Playwright) — clicar no host apenas atinge o elemento contêiner
        (sucesso falso-positivo, sem efeito real), e não há seletor que
        alcance o botão real interno. Um clique físico do SO na posição de
        tela renderizada, no entanto, chega ao elemento correto independente
        do modo do shadow root, pois opera na camada de composição visual.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        if not original_coords or len(original_coords) != 2:
            raise ValueError(f"original_coords é obrigatório para click_by_coordinates (step_id={step_id}).")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | click_by_coordinates | coords | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        x = int(viewport["width"] * original_coords[0])
        y = int(viewport["height"] * original_coords[1])
        print(f"[AEGIS RUNNER] Clicando por coordenadas diretas (Shadow DOM fechado): ({x}, {y})")
        page.mouse.click(x, y)
        self._log_step(step_id=step_id, action="click_by_coordinates", selector="coords", target_description=target_description, status="SUCCESS")
        return True

    def _handle_click_failure(self, page, selector, target_description, timeout, e, original_coords=None, step_id=None, strict=False) -> bool:
        # Nível 1.5: Se for erro de múltiplos elementos (strict mode)
        if "strict mode violation" in str(e) or "resolved to" in str(e):
            try:
                print(f"[AEGIS RUNNER] Múltiplos elementos em fallback. Clicando no primeiro deles...")
                page.locator(selector).first.click(timeout=timeout)
                self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
                return True
            except Exception as inner_e:
                e = inner_e

        # Nível 2.5: Auto-Healing de UI Reativo (Se ainda não foi limpo, limpa de novo e retenta)
        print(f"[AEGIS RUNNER] Falha de clique físico em '{selector}'. Tentando limpar overlays via Escape...")
        try:
            page.keyboard.press("Escape")
            time.sleep(0.3)
            page.locator(selector).first.click(timeout=3000)
            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
            print(f"[AEGIS RUNNER] Clique resolvido reativamente após limpeza de overlays!")
            return True
        except Exception:
            pass

        # Nível 2.75: Reposiciona CDK overlay no viewport + clique direto via JS
        try:
            print(f"[AEGIS RUNNER] Reposicionando CDK overlay no viewport...")
            clicked = page.evaluate(r"""(sel) => {
                const pane = document.querySelector('.cdk-overlay-pane');
                if (pane) {
                    pane.style.position = 'fixed';
                    pane.style.top = '80px';
                    pane.style.left = '50px';
                    pane.style.maxHeight = '80vh';
                    pane.style.overflow = 'auto';
                }
                let el = null;
                try { el = document.querySelector(sel); } catch(e) {}
                if (!el) {
                    let searchText = null;
                    const re = /:has-text\(['"]([^'"]*)['"]\)/g;
                    let m, last;
                    while ((m = re.exec(sel)) !== null) { last = m; }
                    if (last) { searchText = last[1]; }
                    if (searchText) {
                        const opts = document.querySelectorAll('.mat-option, [role="option"]');
                        for (const opt of opts) {
                            if (opt.textContent.trim().includes(searchText)) {
                                el = opt; break;
                            }
                        }
                    }
                }
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    el.dispatchEvent(new MouseEvent('click', {
                        clientX: rect.left + rect.width / 2,
                        clientY: rect.top + rect.height / 2,
                        bubbles: true, cancelable: true, button: 0, view: window
                    }));
                    return true;
                }
                el.click(); return true;
            }""", selector)
            if clicked:
                time.sleep(0.3)
                self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
                print(f"[AEGIS RUNNER] Clique resolvido apos reposicionar overlay!")
                return True
        except Exception:
            pass

        # Nível 3/4: Self-Healing Cognitivo e Fallback por Coordenadas — pulados em modo
        # strict, pois ambos "adivinham" um alvo (via visão de IA ou coordenada histórica
        # da gravação) sem confirmar que o elemento esperado realmente existe no DOM atual.
        # Quando o elemento genuinamente não existe (ex.: fluxo quebrado por bug upstream
        # na app-alvo), essa adivinhação clica em algo errado, silenciosamente corrompendo
        # o estado da página e mascarando a causa raiz em passos subsequentes — pior do
        # que uma falha limpa e rastreável neste passo.
        if strict:
            print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ao clicar em '{selector}' (self-healing e fallback por coordenadas desativados para este passo).")
            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
            raise e

        # Nível 3: Self-Healing Cognitivo por IA
        healed_by_ia = False
        cognitive_attempt_failed = False
        if self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha no clique padrão de '{selector}'. Acionando Self-Healing cognitivo via IA...")
            try:
                healed_by_ia = self.cognitive.self_healing_click(page, selector, target_description, original_coords)
                if healed_by_ia:
                    self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED")
                    return True
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro durante chamada do Self-Healing de IA: {ia_err}")
                cognitive_attempt_failed = True
        else:
            cognitive_attempt_failed = True

        # Nível 4: Fallback Físico de Coordenadas de Gravação (Último Recurso)
        if not healed_by_ia and cognitive_attempt_failed and original_coords and len(original_coords) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords[0])
                y = int(viewport["height"] * original_coords[1])
                print(f"[AEGIS RUNNER] [FALLBACK ÚLTIMO RECURSO] Clicando em coordenadas históricas da gravação: ({x}, {y})")
                page.mouse.click(x, y)
                self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", error_msg="Fallback coords used")
                return True
            except Exception as coords_err:
                print(f"[AEGIS RUNNER] Falha crítica no clique por coordenadas de fallback: {coords_err}")

        print(f"[AEGIS RUNNER] Falha definitiva ao clicar em '{selector}'.")
        self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
        raise e

    def _slugify(self, text: str) -> str:
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s-]', '', text).strip().lower()
        return re.sub(r'[-\s]+', '-', text)

    def _click_by_live_geometry(self, page, option_text) -> bool:
        """Localiza um elemento de opção pelo texto e clica no centro do seu
        bounding rect atual (via JS), em vez de depender de coordenadas
        percentuais gravadas que ficam obsoletas quando o overlay rola/reflui
        de forma diferente da gravação original. Determinístico, sem LLM."""
        try:
            rect = page.evaluate(
                """(text) => {
                    const sel = "[role='option'], .mat-option, li, .select-option";
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                    const target = norm(text);
                    const els = Array.from(document.querySelectorAll(sel));
                    const el = els.find(e => norm(e.textContent) === target)
                        || els.find(e => norm(e.textContent).includes(target));
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) return null;
                    return {x: r.left + r.width / 2, y: r.top + r.height / 2};
                }""",
                option_text,
            )
        except Exception:
            rect = None

        if not rect:
            return False

        page.mouse.click(rect["x"], rect["y"])
        time.sleep(0.3)
        print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada via geometria DOM ao vivo ({rect['x']:.0f}, {rect['y']:.0f})")
        return True

    def select_option_resilient(self, page, dropdown_label, option_text,
                                original_coords_trigger=None,
                                original_coords_option=None,
                                timeout=5000, step_id=None) -> bool:
        """
        Seleciona uma opção de um dropdown/select customizado (não-nativo).
        Abre o dropdown antes de clicar na opção desejada.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        row_id = getattr(self, "current_row_id", "1")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | select_option | {dropdown_label} -> {option_text} | Selecionar dropdown | | | {row_id}")
            sys.stdout.flush()

        slug = self._slugify(dropdown_label)

        # 1. Tenta abrir o dropdown (Trigger)
        trigger_clicked = False
        trigger_selectors = [
            f"label:has-text('{dropdown_label}') ~ div",
            f"label:has-text('{dropdown_label}') ~ select",
            f"label:has-text('{dropdown_label}') ~ .select-trigger",
            f"#field-{slug} div",
            f"#field-{slug} .select-trigger",
            f"mat-form-field:has-text('{dropdown_label}') .mat-select-trigger",
            f"div:has-text('{dropdown_label}') >> div"
        ]

        print(f"[AEGIS RUNNER] Tentando abrir o dropdown para '{dropdown_label}'...")

        # Linhas de grid (ex.: tabela de coberturas) têm 3 triggers
        # (LMG/Franquia/Desconto) compartilhando o mesmo dropdown_label — o
        # texto completo da linha (às vezes truncado pelo sanitizer). Nenhum
        # seletor CSS de texto consegue distinguir qual dos 3 clicar, e o
        # fallback genérico 'div:has-text(label) >> div' casa com o container
        # da página inteira (o texto "sobe" por todos os ancestrais),
        # clicando em elemento errado (ex.: cabeçalho da tabela). Por isso,
        # antes dos seletores genéricos, tenta localizar a linha (.mat-row)
        # usando o próprio dropdown_label como substring (filter/has_text já
        # faz contains, então funciona mesmo truncado) e escolhe o trigger
        # certo pela coluna, inferida do formato de option_text: percentual
        # puro (ex. '10%') = desconto, 'Isenta'/'A - 5.288,68' = franquia,
        # o resto (valores numéricos, "% FIPE", texto livre) = LMG.
        if dropdown_label.strip():
            try:
                row_loc = page.locator(".mat-row").filter(has_text=dropdown_label.strip()).first
                if row_loc.count() > 0:
                    triggers = row_loc.locator(".mat-select-grid-trigger")
                    trigger_count = triggers.count()
                    if trigger_count > 1:
                        option_norm = option_text.strip()
                        if re.fullmatch(r"\d+%", option_norm):
                            col_idx = 2  # desconto
                        elif option_norm == "Isenta" or re.match(r"^[A-Za-z]\s*-\s*", option_norm):
                            col_idx = 1  # franquia
                        else:
                            col_idx = 0  # lmg
                        if col_idx < trigger_count:
                            row_loc.scroll_into_view_if_needed(timeout=1500)
                            time.sleep(0.2)
                            target_trigger = triggers.nth(col_idx)
                            target_trigger.click(timeout=1000, force=True)
                            time.sleep(0.2)
                            if page.locator(".cdk-overlay-pane, .mat-select-panel, [role='listbox']").count() > 0:
                                trigger_clicked = True
                                print(f"[AEGIS RUNNER] Dropdown '{dropdown_label}' aberto via linha do grid (coluna {col_idx})")
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao tentar localizar trigger via linha do grid: {e}")

        for sel in (trigger_selectors if not trigger_clicked else []):
            try:
                loc = page.locator(sel).first
                # loc.is_visible() não espera o elemento aparecer — retorna o
                # estado atual na hora. Campos condicionais (ex.: 'Nível da
                # Blindagem', que só existe no DOM depois de marcar 'Possui
                # Blindagem?' em st_033) podem levar alguns ms a mais que isso
                # pra renderizar; um pre-check is_visible(timeout=500) descarta
                # o seletor antes mesmo de tentar, mesmo que o elemento fosse
                # aparecer logo em seguida (causa raiz confirmada da falha
                # intermitente do st_034). loc.click(timeout=...) já espera
                # (auto-wait) o elemento ficar anexado ao DOM dentro do
                # timeout — usar direto, sem o pre-check, corrige a corrida.
                loc.click(timeout=1500, force=True)
                time.sleep(0.2)
                # Seletores genéricos como 'div:has-text(X) >> div' podem
                # casar com um container amplo e clicar num filho errado
                # (ex.: cabeçalho da tabela em vez do trigger da linha).
                # Só aceita como aberto se um painel de opções realmente
                # surgiu — senão segue tentando os próximos seletores.
                if page.locator(".cdk-overlay-pane, .mat-select-panel, [role='listbox']").count() > 0:
                    trigger_clicked = True
                    print(f"[AEGIS RUNNER] Dropdown '{dropdown_label}' aberto usando seletor: '{sel}'")
                    break
                else:
                    print(f"[AEGIS RUNNER] Seletor '{sel}' clicou mas não abriu painel de opções. Tentando próximo...")
            except Exception:
                continue

        # Fallback de coordenadas para o trigger
        # Coordenadas gravadas são frações do viewport na gravação original;
        # scroll/reflow do grid em runtime pode deslocar o alvo real. Por isso
        # o clique aqui só conta como sucesso se de fato abrir um painel de
        # opções — sem essa checagem, um clique cego "no vazio" era aceito
        # como sucesso e o dropdown seguia com o valor antigo (causa raiz de
        # falhas em cascata como o st_052 do cenário 001).
        if not trigger_clicked and original_coords_trigger and len(original_coords_trigger) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords_trigger[0])
                y = int(viewport["height"] * original_coords_trigger[1])
                print(f"[AEGIS RUNNER] Abrindo dropdown via coordenadas de fallback: ({x}, {y})")
                page.mouse.click(x, y)
                time.sleep(0.3)
                trigger_clicked = page.locator(".cdk-overlay-pane, .mat-select-panel, [role='listbox']").count() > 0
                if not trigger_clicked:
                    print(f"[AEGIS RUNNER] Coordenada de fallback ({x}, {y}) não abriu nenhum painel de opções. Clique descartado.")
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao clicar nas coordenadas do trigger: {e}")

        if not trigger_clicked:
            print(f"[AEGIS RUNNER] [WARNING] Não foi possível abrir o dropdown '{dropdown_label}' pelos seletores conhecidos ou coordenadas.")

        # Aguarda animação de abertura das opções
        time.sleep(0.4)

        # 2. Seleciona a opção
        option_clicked = False
        option_selectors = [
            f"[role='option']:has-text('{option_text}')",
            f".mat-option:has-text('{option_text}')",
            f"[role='listbox'] [role='option']:has-text('{option_text}')",
            f"li:has-text('{option_text}')",
            f".select-option:has-text('{option_text}')"
        ]

        print(f"[AEGIS RUNNER] Tentando selecionar a opção '{option_text}'...")
        if trigger_clicked:
            for sel in option_selectors:
                option_clicked = self._click_option_with_fallback(page, sel, option_text)
                if option_clicked:
                    break
        else:
            # Sem painel de opções aberto (trigger_clicked=False), nenhum dos
            # 5 seletores x 4 estratégias de _click_option_with_fallback vai
            # achar algo — são ~20 tentativas garantidamente inúteis (~20-30s)
            # antes de chegar no self-healing. Pula direto pros fallbacks que
            # não dependem do painel: geometria ao vivo, coords gravadas, IA.
            print(f"[AEGIS RUNNER] Painel de opções não abriu — pulando cascata de seletores de opção, indo direto aos fallbacks finais.")

        # Fallback por geometria DOM ao vivo: busca o elemento de opção pelo
        # texto (dado que já temos, vindo do plano) e clica no centro do seu
        # bounding rect ATUAL, em vez de confiar em coordenadas percentuais
        # gravadas que ficam obsoletas quando o overlay reflui/rola de forma
        # diferente da gravação original. Ainda determinístico (sem LLM).
        if not option_clicked:
            option_clicked = self._click_by_live_geometry(page, option_text)

        # Fallback de coordenadas gravadas (último recurso) — só é aceito
        # como sucesso se o elemento realmente sob o cursor no ponto clicado
        # contiver o texto esperado. Antes, o clique era aceito às cegas: se
        # a coordenada gravada estivesse obsoleta, o robô "selecionava" o
        # vazio e seguia reportando SUCCESS com o valor antigo inalterado
        # (causa raiz confirmada da falha em cascata do st_052/cenário 001).
        if not option_clicked and original_coords_option and len(original_coords_option) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords_option[0])
                y = int(viewport["height"] * original_coords_option[1])
                hit_text = page.evaluate(
                    "([x, y]) => { const el = document.elementFromPoint(x, y); return el ? el.textContent : null; }",
                    [x, y],
                )
                normalized_hit = (hit_text or "").replace("\xa0", " ")
                if option_text.strip() and option_text.strip() in normalized_hit:
                    print(f"[AEGIS RUNNER] Selecionando opção via coordenadas de fallback: ({x}, {y})")
                    page.mouse.click(x, y)
                    option_clicked = True
                else:
                    print(f"[AEGIS RUNNER] Coordenada de fallback ({x}, {y}) não corresponde a '{option_text}' (encontrado: {normalized_hit!r}). Clique descartado.")
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao clicar nas coordenadas da opção: {e}")

        # Se falhou, aciona o Cognitive Gateway se ativo
        if not option_clicked and self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha nas tentativas normais. Acionando Self-Healing Cognitivo para a opção...")
            try:
                # Tenta localizar visualmente o texto da opção na tela
                option_clicked = self.cognitive.self_healing_click(
                    page, 
                    selector=f"[role='option']:has-text('{option_text}')", 
                    target_description=f"Opção {option_text} do dropdown {dropdown_label}",
                    original_coords=original_coords_option
                )
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro no self-healing cognitivo para opção: {ia_err}")

        if option_clicked:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass
            self._log_step(step_id=step_id, action="select_option", selector=f"[role='option']:has-text('{option_text}')", target_description=f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", status="SUCCESS")
            return True
        else:
            msg = f"Não foi possível selecionar a opção '{option_text}' no dropdown '{dropdown_label}'."
            print(f"[AEGIS RUNNER] ❌ {msg}")
            self._log_step(step_id=step_id, action="select_option", selector=f"[role='option']:has-text('{option_text}')", target_description=f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", status="FAILED", error_msg=msg)
            raise RuntimeError(msg)

    def select_option_native_resilient(self, page, selector, option_text, target_description, timeout=5000, step_id=None) -> bool:
        """
        Seleciona uma opção de um <select> HTML nativo via page.select_option().
        Diferente de select_option_resilient (dropdown customizado/overlay JS),
        aqui o elemento já é o próprio <select> — sem abrir/clicar em painel
        de opções, sem overlay pra detectar. Usa o seletor gravado diretamente
        (igual click_resilient/fill_resilient), não um label/texto adivinhado.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        row_id = getattr(self, "current_row_id", "1")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | select_native | {selector} | {option_text} | {target_description} | | {row_id}")
            sys.stdout.flush()

        try:
            page.locator(selector).first.select_option(label=option_text, timeout=timeout)
            self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="SUCCESS")
            return True
        except Exception as e:
            # Tenta por value= (option_text pode ser o label visível mas o
            # <option> só ter esse texto como value, ou vice-versa)
            try:
                page.locator(selector).first.select_option(value=option_text, timeout=timeout)
                self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="SUCCESS")
                return True
            except Exception:
                pass

            print(f"[AEGIS RUNNER] Falha ao selecionar '{option_text}' em '{selector}'. Tentando limpar overlays via Escape...")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.locator(selector).first.select_option(label=option_text, timeout=3000)
                self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="SUCCESS")
                return True
            except Exception:
                pass

            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Falha padrão ao selecionar '{option_text}' em '{selector}'. Acionando localização visual por screenshot...")
                clicked = self.cognitive.self_healing_click(page, selector, target_description)
                if clicked:
                    try:
                        page.locator(selector).first.select_option(label=option_text, timeout=timeout)
                        self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="HEALED")
                        return True
                    except Exception:
                        pass
                self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise e
            else:
                print(f"[AEGIS RUNNER] Falha ao selecionar em '{selector}' e módulo cognitivo inativo.")
                self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise e

    def _click_option_with_fallback(self, page, selector, option_text) -> bool:
        """
        Tenta clicar em uma opção de dropdown usando estratégias progressivas:
        1. Playwright click (force=True) — se visível no viewport
        2. Scroll overlay no viewport + retry
        3. JS evaluate (ignora viewport)
        4. Zoom 70% + retry (portais com CDK overlay mal posicionado)
        Retorna True se conseguiu, False se todas falharam.
        """
        loc = page.locator(selector).first

        # ─── Estratégia 1: Playwright click padrão ──────────────────────────
        try:
            if loc.is_visible(timeout=1000):
                loc.click(timeout=1500, force=True)
                print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada via Playwright click")
                return True
        except Exception:
            pass

        # ─── Estratégia 2: Scroll overlay no viewport + retry ───────────────
        try:
            print(f"[AEGIS RUNNER] Opção '{option_text}' não visível. Aplicando scroll no CDK overlay...")
            page.evaluate("""() => {
                const panes = document.querySelectorAll('.cdk-overlay-pane');
                if (panes.length > 0) {
                    panes[panes.length - 1].scrollIntoView({block: 'center', behavior: 'instant'});
                }
            }""")
            time.sleep(0.3)
            if loc.is_visible(timeout=1000):
                loc.click(timeout=1500, force=True)
                print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada após scroll do overlay")
                return True
        except Exception:
            pass

        # ─── Estratégia 3: JS evaluate (ignora viewport completamente) ────
        try:
            print(f"[AEGIS RUNNER] Opção '{option_text}' ainda oculta. Tentando injeção JS evaluate...")
            loc.evaluate("el => el.click()")
            time.sleep(0.3)
            print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada via JS evaluate")
            return True
        except Exception:
            pass

        # ─── Estratégia 4: Zoom 70% + retry ─────────────────────────────
        # Portais com CDK overlay mal posicionado: zoom reduz escala e traz
        # opções para dentro do viewport. Restaura zoom após clique.
        try:
            print(f"[AEGIS RUNNER] Opção '{option_text}' inacessível. Aplicando zoom 70%...")
            page.evaluate("() => { document.body.style.zoom = '0.7'; }")
            time.sleep(0.5)  # Aguarda reflow do CSS
            if loc.is_visible(timeout=1500):
                loc.click(timeout=1500, force=True)
                print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada após zoom 70%")
                # Restaura zoom gradualmente
                page.evaluate("() => { document.body.style.zoom = ''; }")
                return True
            else:
                # Tenta JS evaluate com zoom ativo
                loc.evaluate("el => el.click()")
                time.sleep(0.3)
                page.evaluate("() => { document.body.style.zoom = ''; }")
                print(f"[AEGIS RUNNER] Opção '{option_text}' selecionada via zoom+JS evaluate")
                return True
        except Exception:
            page.evaluate("() => { document.body.style.zoom = ''; }")  # Garante restore

        print(f"[AEGIS RUNNER] Todas as estratégias falharam para opção '{option_text}' no seletor '{selector}'")
        return False

    def wait_for_selector(self, page, selector, state="visible", timeout=10000, target_description=None) -> bool:
        """Aguarda um seletor ficar visível ou oculto com suporte a logs resilientes."""
        desc = target_description or selector
        print(f"[AEGIS RUNNER] Aguardando elemento '{desc}' ficar {state}...")
        try:
            page.locator(selector).wait_for(state=state, timeout=timeout)
            return True
        except Exception as e:
            print(f"[AEGIS WARNING] Timeout ao aguardar seletor '{selector}': {e}")
            raise e

    def _get_relative_child_selector(self, parent_selector: str, child_selector: str) -> str:
        """Relativiza o seletor do filho removendo prefixos que repetem o pai ou ancestrais."""
        parent_clean = parent_selector.strip()
        child_clean = child_selector.strip()

        # 0. Remove prefixo de #cdk-overlay-container do filho quando ele for um ancestral
        # externo ao pai — o Playwright já vai buscar dentro do pai, não é necessário
        CDK_PREFIX = "#cdk-overlay-container"
        if child_clean.startswith(CDK_PREFIX) and CDK_PREFIX not in parent_clean:
            child_clean = child_clean[len(CDK_PREFIX):].strip()

        # 1. Se o seletor do filho contém o seletor do pai exato (igualdade de string)
        if parent_clean in child_clean:
            parts = child_clean.split(parent_clean, 1)
            rel = parts[1].strip()
            if rel.startswith(">>"):
                rel = rel[2:].strip()
            if rel:
                return rel

        # 2. Se o pai começa com # e o filho contém exatamente o mesmo id
        # (comparação só por token completo, evitando casamento parcial como mat-select-panel vs mat-select-panel-combustivel)
        if parent_clean.startswith("#"):
            parent_id = parent_clean[1:]  # sem o '#'
            pattern = r'(?:^|[\s>])#' + re.escape(parent_id) + r'(?=[\s\[\.:\>]|$)'
            m = re.search(pattern, child_clean)
            if m:
                after = child_clean[m.end():].strip()
                if after:
                    return after

        # 3. Caso o filho contenha o seletor do pai como prefixo por classe CSS (. seguido de nome exato)
        if parent_clean.startswith("."):
            pattern = r'(?:^|[\s>])' + re.escape(parent_clean) + r'(?=[\s\[\.:\>]|$)'
            m = re.search(pattern, child_clean)
            if m:
                after = child_clean[m.end():].strip()
                if after:
                    return after

        # 4. Caso seja composto por >>, pega a última parte como fallback
        c_parts = [p.strip() for p in child_clean.split(">>") if p.strip()]
        if len(c_parts) > 1:
            return c_parts[-1]

        # 5. Selector do filho gravado como caminho absoluto a partir da raiz
        # da página (ex.: "table #grid-tbody tr button:has-text('Cláusulas')")
        # em vez de relativo ao pai — comum quando o sanitizer preserva o
        # `selector` original da gravação e só adiciona `parent` como reforço
        # de escopo, sem relativizar o próprio `selector`. O pai (.mat-row/tr)
        # já é a própria linha; buscar esse mesmo ancestral de novo dentro
        # dela nunca casa (uma <tr> não contém outra <tr>/<table> aninhada),
        # forçando fallback físico e, na sequência, self-healing cognitivo —
        # que pode clicar na linha errada (causa raiz confirmada da falha em
        # cascata do st_051→st_052 no cenário 001). Corta tudo até o último
        # token "tr" isolado (com ou sem classe) e usa só o restante.
        tr_match = re.search(r"\btr\b(?:\.[\w-]+)?\s+(.+)$", child_clean)
        if tr_match:
            after = tr_match.group(1).strip()
            if after:
                return after

        return child_clean

    def click_chained(self, page, parent: dict, child: dict, target_description: str,
                      timeout: int = 5000, original_coords: tuple = None, step_id=None) -> bool:
        """
        Clique resiliente com escopo hierárquico (chained locator).
        Resolve o elemento pai via Playwright .filter(has_text=...) e encadeia o filho.

        parent: {"selector": "tr", "has_text": "4.000,00"}
        child:  {"selector": ".mat-select-grid-trigger"}
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        parent_repr = f"{parent.get('selector')}[{parent.get('has_text','')}]"
        child_sel_clean = self._get_relative_child_selector(parent.get('selector',''), child.get('selector',''))
        selector_full = f"{parent_repr} >> {child_sel_clean}"

        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | click_chained | {selector_full} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        # Paineis de autocomplete/overlay dependem de fetch assíncrono simulado
        # (latência observada de até ~4s); usa um piso de espera mais generoso
        # que o timeout padrão de clique para não derrubar a tentativa antes do
        # painel terminar de carregar.
        wait_timeout = max(timeout, 8000)

        for attempt in range(1, 3):
            try:
                if attempt == 2:
                    print(f"[AEGIS RUNNER] [RETRY 2] Limpando possíveis overlays via Escape...")
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

                # 1. Resolve o pai com filtro nativo
                parent_locator = page.locator(parent["selector"])
                if "has_text" in parent and parent.get("has_text"):
                    parent_locator = parent_locator.filter(has_text=parent["has_text"])

                # 2. Aguarda o pai ser anexado ao DOM (paineis async/CDK podem
                # demorar a renderizar; checagem instantânea derrubava a
                # tentativa 1 antes do fetch simulado terminar)
                parent_locator.first.wait_for(state="attached", timeout=wait_timeout)

                # 3. Encadeia o filho e clica com fallback de scroll
                target = parent_locator.first.locator(child_sel_clean).first
                target.wait_for(state="visible", timeout=wait_timeout)
                target.scroll_into_view_if_needed(timeout=timeout)
                target.click(timeout=timeout, force=True)

                self._log_step(step_id=step_id, action="click_chained", selector=selector_full, target_description=target_description, status="SUCCESS")
                return True

            except Exception as e:
                print(f"[AEGIS RUNNER] Tentativa {attempt} falhou para click_chained: {e}")
                if attempt == 2:
                    return self._handle_click_failure(
                        page,
                        f"{parent.get('selector','')} >> {child.get('selector','')}",
                        target_description, timeout, e, original_coords, step_id=step_id
                    )

        return False

    def fill_chained(self, page, parent: dict, child: dict, text_val: str,
                     target_description: str, strategy: str = "DIRECT",
                     delay_ms: int = 60, timeout: int = 5000, step_id=None) -> bool:
        """
        Preenche campo com escopo hierárquico (chained locator).
        strategy="HUMAN_LIKE": digitação cadenciada com limpeza Control+A + Backspace.
        strategy="DIRECT": .fill() padrão no elemento encadeado.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        parent_repr = f"{parent.get('selector')}[{parent.get('has_text','')}]"
        child_sel_clean = self._get_relative_child_selector(parent.get('selector',''), child.get('selector',''))
        selector_full = f"{parent_repr} >> {child_sel_clean}"

        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | fill_chained | {selector_full} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        parent_locator = page.locator(parent["selector"])
        if "has_text" in parent and parent.get("has_text"):
            parent_locator = parent_locator.filter(has_text=parent["has_text"])

        try:
            if strategy == "HUMAN_LIKE":
                target = parent_locator.first.locator(child_sel_clean).first
                target.click(timeout=timeout)
                # Seleciona tudo e apaga antes de digitar (evita concatenação)
                target.press("Control+A")
                target.press("Backspace")
                time.sleep(0.1)
                import time as _time
                for char in text_val:
                    page.keyboard.type(char)
                    _time.sleep(delay_ms / 1000.0)
                page.evaluate("""() => {
                    const el = document.activeElement;
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")
                self._log_step(step_id=step_id, action="fill_chained", selector=selector_full, target_description=target_description, status="SUCCESS")
                return True

            # DIRECT
            target = parent_locator.first.locator(child_sel_clean).first
            try:
                target.fill(text_val, timeout=timeout)
            except Exception as fill_err:
                # Campos "readonly" (ex.: código copia-e-cola PIX) resolvem o
                # locator normalmente mas rejeitam Locator.fill() porque o
                # Playwright exige a propriedade editável. Preenche via DOM
                # diretamente no MESMO elemento já escopado pelo chained
                # locator (determinístico, sem heurística visual) antes de
                # escalar para self-healing.
                print(f"[AEGIS RUNNER] fill() padrão falhou (possível campo readonly): {fill_err}")
                target.evaluate(
                    """(el, val) => {
                        el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    text_val,
                )
                actual = target.input_value(timeout=1000)
                if actual != text_val:
                    raise fill_err
            self._log_step(step_id=step_id, action="fill_chained", selector=selector_full, target_description=target_description, status="SUCCESS")
            return True

        except Exception as e:
            print(f"[AEGIS RUNNER] Falha no fill_chained: {e}")
            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Acionando self-healing cognitivo para fill_chained...")
                clicked = self.cognitive.self_healing_click(page, child.get("selector", ""), target_description)
                if clicked:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(text_val)
                    self._log_step(step_id=step_id, action="fill_chained", selector=f"{parent_repr} >> {child_sel_clean}", target_description=target_description, status="HEALED")
                    return True
            self._log_step(step_id=step_id, action="fill_chained", selector=f"{parent_repr} >> {child_sel_clean}", target_description=target_description, status="FAILED", error_msg=str(e))
            raise e

    def fill_resilient(self, page, selector, text_val, target_description,
                       strategy="DIRECT", delay_ms=60, timeout=5000, step_id=None) -> bool:
        """
        Preenche um campo de forma resiliente.
        - strategy="DIRECT": usa .fill() padrão (rápido, sem eventos keydown).
        - strategy="HUMAN_LIKE": usa fill_human_like() com digitacão cadenciada,
          necessário para campos com detecção de cadência de teclado (Zone.js, etc).
        Se falhar por timeout ou outra exceção, localiza visualmente o elemento na tela via IA e digita.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        if getattr(self, "realtime_logs", True):
            print(f"[AEGIS_STEP] START | {step_id} | fill | {selector} | {target_description} | | | {getattr(self, 'current_row_id', '1')}")
            sys.stdout.flush()

        # Força HUMAN_LIKE globalmente caso a variável de ambiente esteja ativa
        force_human_like = os.environ.get("AEGIS_FORCE_HUMAN_LIKE", "false").lower() in ("true", "1", "yes")
        if force_human_like:
            strategy = "HUMAN_LIKE"

        # Tratamento de formato de data (converte de yyyy-mm-dd para dd/mm/yyyy se não for input nativo type="date")
        is_native_date = False
        try:
            input_type = page.locator(selector).first.get_attribute("type", timeout=300)
            if input_type == "date":
                is_native_date = True
        except Exception:
            pass

        if not is_native_date and isinstance(text_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", text_val):
            parts = text_val.split("-")
            text_val = f"{parts[2]}/{parts[1]}/{parts[0]}"

        if strategy == "HUMAN_LIKE":
            res = self.fill_human_like(page, selector, text_val, target_description, delay_ms=delay_ms, timeout=timeout, step_id=step_id)
            if res:
                self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="SUCCESS")
            return res

        try:
            print(f"[AEGIS RUNNER] Tentando preenchimento físico em '{selector}'...")
            page.locator(selector).fill(text_val, timeout=timeout)
            self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="SUCCESS")
            return True
        except Exception as e:
            if "strict mode violation" in str(e) or "resolved to" in str(e):
                try:
                    print(f"[AEGIS RUNNER] Múltiplos elementos encontrados para '{selector}'. Tentando preencher o primeiro...")
                    page.locator(selector).first.fill(text_val, timeout=timeout)
                    self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="SUCCESS")
                    return True
                except Exception as inner_e:
                    e = inner_e

            # Auto-Healing de UI - Tenta limpar overlays ativos via Escape e retry
            print(f"[AEGIS RUNNER] Falha no preenchimento de '{selector}'. Tentando limpar possíveis overlays via Escape...")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.locator(selector).first.fill(text_val, timeout=3000)
                self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="SUCCESS")
                print(f"[AEGIS RUNNER] Preenchimento resolvido reativamente após limpeza de overlays!")
                return True
            except Exception:
                pass

            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Falha no preenchimento padrão de '{selector}'. Acionando localização visual por screenshot...")
                clicked = self.cognitive.self_healing_click(page, selector, target_description)
                if clicked:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(text_val)
                    page.evaluate("() => { const active = document.activeElement; if (active) { active.dispatchEvent(new Event('input', { bubbles: true })); active.dispatchEvent(new Event('change', { bubbles: true })); } }")
                    self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="HEALED")
                    return True
                self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="FAILED", error_msg="IA self-healing failed")
                raise e
            else:
                print(f"[AEGIS RUNNER] Falha ao preencher em '{selector}' e módulo cognitivo inativo.")
                self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise e

    def fill_human_like(self, page, selector, text_val, target_description=None, delay_ms=60, timeout=5000, step_id=None) -> bool:
        """
        Preenche um campo tecla por tecla com delay real (time.sleep) entre cada keystroke.
        """
        if not step_id:
            raise ValueError(f"step_id é obrigatório. Consulte plano_execucao.json.")
        if target_description is None:
            target_description = selector
        import time as _time

        # Tratamento de formato de data (converte de yyyy-mm-dd para dd/mm/yyyy se não for input nativo type="date")
        is_native_date = False
        try:
            input_type = page.locator(selector).first.get_attribute("type", timeout=300)
            if input_type == "date":
                is_native_date = True
        except Exception:
            pass

        if not is_native_date and isinstance(text_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", text_val):
            parts = text_val.split("-")
            text_val = f"{parts[2]}/{parts[1]}/{parts[0]}"

        try:
            print(f"[AEGIS RUNNER] Digitacão cadenciada (HUMAN_LIKE) em '{selector}' ({len(str(text_val))} chars, {delay_ms}ms/tecla)...")
            element = page.locator(selector).first
            element.scroll_into_view_if_needed()
            element.click(timeout=timeout, force=True)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            _time.sleep(0.1)
            for char in str(text_val):
                page.keyboard.press(char)
                _time.sleep(delay_ms / 1000.0)
            _time.sleep(0.1)
            element.dispatch_event("input")
            element.dispatch_event("change")
            element.dispatch_event("blur")
            _time.sleep(0.1)
            print(f"[AEGIS RUNNER] Digitacão cadenciada concluída em '{selector}'.")
            return True
        except Exception as e:
            print(f"[AEGIS RUNNER] Falha em fill_human_like para '{selector}': {e}")
            if self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Acionando self-healing cognitivo para HUMAN_LIKE em '{selector}'...")
                clicked = self.cognitive.self_healing_click(page, selector, target_description)
                if clicked:
                    import time as _t2
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    for char in str(text_val):
                        page.keyboard.press(char)
                        _t2.sleep(delay_ms / 1000.0)
                    self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="HEALED")
                    return True
            self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
            raise e

    def diagnose_failure(self, page, error) -> str:
        """Diagnóstico de falha cognitivo compatível com chamadas externas."""
        if self.cognitive.is_active():
            try:
                diag = self.cognitive.diagnose_failure(page, str(error), steps_history=getattr(self, "steps_history", None))
                if diag and isinstance(diag, dict):
                    category = diag.get("category", "UNKNOWN")
                    cause = diag.get("root_cause_summary", "")
                    fix = diag.get("actionable_fix", "")
                    return f"[{category}]: {cause} (Recomendação: {fix})"
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao executar diagnóstico externo: {e}")
        return f"System Error: {str(error)}"

    def _load_dataset(self):
        """Carrega dados do dataset_inicial.json ou dados_entrada.csv do projeto."""
        # Se houver um dataset_inicial.json filtrado dentro da pasta temporária da execução, use-o!
        exec_dataset = os.path.join(self.output_dir, "dataset_inicial.json")
        if os.path.exists(exec_dataset):
            print(f"[AEGIS RUNNER] Carregando dataset filtrado da pasta de execução: {exec_dataset}")
            with open(exec_dataset, "r", encoding="utf-8") as f:
                return json.load(f)

        if os.path.exists(self.dataset_json):
            print(f"[AEGIS RUNNER] Carregando dataset JSON: {self.dataset_json}")
            with open(self.dataset_json, "r", encoding="utf-8") as f:
                return json.load(f)
        elif os.path.exists(self.dataset_csv):
            print(f"[AEGIS RUNNER] Carregando dataset CSV: {self.dataset_csv}")
            rows = []
            with open(self.dataset_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            return rows
        else:
            raise FileNotFoundError(f"Nenhum dataset encontrado no diretório do projeto: {self.project_dir}")

    def _write_report(self, reports):
        """Escreve o relatório transacional de conformidade em formato CSV no diretório do projeto."""
        headers = ["id", "aegis_scenario", "status", "error_message", "failed_field", "extracted_value", "duration_seconds"]
        with open(self.report_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(reports)
        print(f"\n[AEGIS RUNNER] [SUCESSO] Relatório Transacional gravado em: {self.report_csv}\n")

    def _write_index_file(self):
        """Escreve um arquivo de índice em JSON com caminhos e descrições dos artefatos para consumo de IAs."""
        index_path = os.path.join(self.output_dir, "index_arquivos.json")
        
        files_metadata = []
        
        # 1. Relatórios e logs
        rel_exec_rel = "reports/relatorio_execucao.csv"
        if os.path.exists(os.path.join(self.output_dir, rel_exec_rel)):
            files_metadata.append({
                "path": rel_exec_rel,
                "type": "execution_report",
                "description": "Relatório estruturado CSV com o status de sucesso/falha, tempo de duração e erros de cada transação processada."
            })
            
        hist_passos_rel = "reports/historico_passos.json"
        if os.path.exists(os.path.join(self.output_dir, hist_passos_rel)):
            files_metadata.append({
                "path": hist_passos_rel,
                "type": "audit_trail",
                "description": "Trilha de auditoria JSON com o detalhamento passo a passo da execução de cada ação física e cognitiva do robô."
            })
            
        # O log de execução é gravado após a finalização do processo pelo Cockpit, mas prevemos sua existência
        files_metadata.append({
            "path": "reports/execution.log",
            "type": "stdout_stderr_log",
            "description": "Log de console bruto gerado pelo interpretador Python durante a execução do script do robô."
        })
        
        # 2. Screenshots gerais
        scr_script_rel = "screenshots/screenshot_script.png"
        if os.path.exists(os.path.join(self.output_dir, scr_script_rel)):
            files_metadata.append({
                "path": scr_script_rel,
                "type": "final_screenshot",
                "description": "Captura de tela do estado final do navegador ao encerrar a execução do robô."
            })
            
        # Procura por prints de erro e de passos
        scr_dir = os.path.join(self.output_dir, "screenshots")
        if os.path.exists(scr_dir):
            for entry in sorted(os.listdir(scr_dir)):
                if entry.endswith(".png"):
                    rel_path = f"screenshots/{entry}"
                    if entry.startswith("screenshot_erro_transacao_"):
                        row_id = entry.replace("screenshot_erro_transacao_", "").replace(".png", "")
                        files_metadata.append({
                            "path": rel_path,
                            "type": "error_screenshot",
                            "description": f"Captura de tela do erro sistêmico ocorrido durante o processamento da transação de ID {row_id}."
                        })
                    elif entry.startswith("step_"):
                        parts = entry.split("_")
                        row_id = parts[1] if len(parts) > 1 else "?"
                        step_num = parts[2] if len(parts) > 2 else "?"
                        action = parts[3] if len(parts) > 3 else "ação"
                        files_metadata.append({
                            "path": rel_path,
                            "type": "step_screenshot",
                            "description": f"Evidência visual do passo {step_num} ({action}) na transação {row_id} executada com sucesso."
                        })
                        
        index_data = {
            "component": "bot_execution",
            "execution_id": os.environ.get("AEGIS_EXECUTION_ID", "local"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "files": files_metadata
        }
        
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=4, ensure_ascii=False)
            print(f"[AEGIS RUNNER] Índice de arquivos (index_arquivos.json) gravado com sucesso em: {index_path}")
        except Exception as ex:
            print(f"[WARNING] Falha ao gravar index_arquivos.json: {ex}")

    def _mark_remaining_stopped(self):
        """Marca passos ainda PENDING como STOPPED quando a transação falha."""
        for step in self.steps_history:
            if step.get("status") == "PENDING":
                step["status"] = "STOPPED"
                step["row_id"] = self.current_row_id
                step["timestamp"] = datetime.now().isoformat()

    def run(self, url=None, headless=True, slow_mo=50, channel="msedge"):
        """Inicia a orquestração centralizada de loops de transação Playwright."""
        # Override do headless via variável de ambiente (prioridade)
        env_headless = os.environ.get("AEGIS_BROWSER_HEADLESS")
        if env_headless is not None:
            headless = env_headless.lower() in ("true", "1", "yes")

        # Atualiza a flag de screenshots por passo dinamicamente a partir do ambiente
        self.step_screenshots = os.environ.get("AEGIS_STEP_SCREENSHOTS", "false").lower() in ("true", "1", "yes")
        self.realtime_logs = os.environ.get("AEGIS_STEP_LOGS_REALTIME", "true").lower() in ("true", "1", "yes")
        self.steps_history = []

        # Carrega plano de execução (plano_execucao.json) se existir
        plan_path = os.path.join(self.project_dir, "plano_execucao.json")
        if os.path.exists(plan_path):
            with open(plan_path, "r", encoding="utf-8") as f:
                self.execution_plan = json.load(f)
            print(f"[AEGIS RUNNER] Plano de execução carregado: {len(self.execution_plan.get('steps',[]))} passos planejados.")
        else:
            self.execution_plan = None
            print(f"[AEGIS RUNNER] Nenhum plano_execucao.json encontrado. Operando em modo legado (append de steps).")

        print("\n" + "=" * 80)
        print("🛡️ AEGIS RUNNER LIBRARY: EXECUTANDO LOOP TRANSACIONAL EM LOTE")
        print("=" * 80)
        
        # 1. Carrega o dataset do projeto
        dataset = self._load_dataset()
        print(f"[AEGIS RUNNER] Total de transações carregadas: {len(dataset)}")
        
        reports = []
        
        # Inicia o Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=slow_mo, channel=channel)
            context = browser.new_context()
            page = None
            
            for idx, row in enumerate(dataset):
                # Cria uma nova página para cada transação para garantir isolamento total e evitar
                # que erros/diálogos abertos/quedas de página afetem transações subsequentes.
                if page:
                    try:
                        page.close()
                    except:
                        pass
                
                try:
                    page = context.new_page()
                    # Dispensa automaticamente todos os diálogos JavaScript (alert, confirm, prompt)
                    page.on("dialog", lambda d: d.dismiss())
                except Exception as page_err:
                    print(f"[AEGIS RUNNER] Erro crítico ao instanciar nova página: {page_err}. Tentando recuperar context...")
                    try:
                        context = browser.new_context()
                        page = context.new_page()
                        page.on("dialog", lambda d: d.dismiss())
                    except:
                        continue
                
                row_id = row.get("id", str(idx + 1))
                self.current_row_id = row_id
                self.step_counter = 0
                self.page = page  # Store reference for _log_step screenshot fallback
                # Inicializa steps_history com PENDING para cada step do plano, ou vazio se não houver plano
                if self.execution_plan:
                    self.steps_history = []
                    for step in self.execution_plan["steps"]:
                        self.steps_history.append({
                            "step_id": step["step_id"],
                            "type": step["type"],
                            "selector": step.get("selector", ""),
                            "desc": step.get("description", ""),
                            "status": "PENDING",
                            "error": "",
                            "usedHealing": False,
                            "screenshot": None,
                            "row_id": row_id,
                            "timestamp": None
                        })
                else:
                    self.steps_history = []  # Reset por transação para não acumular passos de transações anteriores
                scenario = row.get("aegis_scenario", "default")
                expected = row.get("expected_result", "SUCCESS").upper()
                expected_token = row.get("expected_error_token", "")
                
                # Se a URL não foi fornecida por argumento, tenta usar a URL configurada na inicialização, ou do project.json
                target_url = url or self.initial_url
                if not target_url:
                    # Tenta ler do project.json se existir
                    project_json = os.path.join(self.project_dir, "project.json")
                    if os.path.exists(project_json):
                        try:
                            with open(project_json, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                                target_url = meta.get("url")
                        except:
                            pass
                
                if not target_url:
                    target_url = "http://localhost:5173/?e2e=true" # Fallback local
                
                print(f"\n[🚀 TRANSAÇÃO {row_id}/{len(dataset)}] Cenário: '{scenario}' | Expectativa: '{expected}'")
                print(f"[AEGIS_TRANSACTION] START | {row_id} | {scenario}")
                sys.stdout.flush()
                start_time = time.time()
                
                # Executa a automação registrada
                try:
                    if scenario not in self.scenarios:
                        raise ValueError(f"Cenário '{scenario}' não foi registrado no runner.")
                    
                    try:
                        page.goto(target_url, timeout=60000, wait_until="domcontentloaded")
                    except Exception as goto_err:
                        print(f"[AEGIS WARNING] Limite de tempo de carregamento da página excedido no runner: {goto_err}. Prosseguindo com execução...")
                    
                    # Chama o callback do robô de negócio
                    import inspect
                    sig = inspect.signature(self.scenarios[scenario])
                    if len(sig.parameters) >= 3:
                        self.scenarios[scenario](page, row, self)
                    else:
                        self.scenarios[scenario](page, row)
                    
                    # Aguarda 1.5s após a conclusão para certificar estabilidade
                    time.sleep(1.5)
                    duration = round(time.time() - start_time, 2)
                    
                    if expected == "BUSINESS_BLOCKED":
                        # Deu sucesso, mas a regra esperava erro de negócio!
                        print(f"[🚨 ALERTA] Concluído com sucesso, mas esperava bloqueio de negócio!")
                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "CRITICAL_UNEXPECTED_SUCCESS",
                            "error_message": "O portal permitiu concluir o fluxo de forma inesperada.",
                            "failed_field": "None",
                            "extracted_value": "None",
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                        sys.stdout.flush()
                    else:
                        # Sucesso
                        extracted_val = "EMITTED-OK"
                        print(f"[✓ SUCESSO] Transação {row_id} executada com sucesso!")
                        
                        # Captura screenshot da última tela do robô
                        screenshot_path = os.path.join(self.output_dir, "screenshots", "screenshot_script.png")
                        try:
                            page.screenshot(path=screenshot_path)
                            print(f"[AEGIS RUNNER] Screenshot da última tela do robô gravado em: {screenshot_path}")
                        except Exception as e:
                            print(f"[WARNING] Não foi possível capturar o screenshot da última tela do robô: {e}")

                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "SUCCESS",
                            "error_message": "None",
                            "failed_field": "None",
                            "extracted_value": extracted_val,
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] SUCCESS | {row_id}")
                        sys.stdout.flush()
                        
                except Exception as e:
                    self._mark_remaining_stopped()
                    duration = round(time.time() - start_time, 2)
                    
                    # Verifica se há mensagem de erro de negócio visível na tela
                    error_text = ""
                    is_business_error = False
                    try:
                        error_locator = page.locator(self.error_message_selector)
                        if error_locator.is_visible(timeout=1500):
                            is_business_error = True
                            error_text = error_locator.inner_text().strip()
                    except:
                        pass
                    
                    if expected == "BUSINESS_BLOCKED" and is_business_error:
                        if expected_token.lower() in error_text.lower():
                            print(f"[✓ BLOQUEIO ESPERADO] Transação {row_id} bloqueada por regra de negócio: '{error_text}'")
                            reports.append({
                                "id": row_id,
                                "aegis_scenario": scenario,
                                "status": "SUCCESS_BLOCKED",
                                "error_message": f"Bloqueio Validado: {error_text}",
                                "failed_field": "None",
                                "extracted_value": "None",
                                "duration_seconds": duration
                            })
                            print(f"[AEGIS_TRANSACTION] SUCCESS | {row_id}")
                            sys.stdout.flush()
                        else:
                            print(f"[❌ FALSO POSITIVO] Bloqueado com erro incorreto. Esperava '{expected_token}', obteve '{error_text}'")
                            reports.append({
                                "id": row_id,
                                "aegis_scenario": scenario,
                                "status": "FAILED_WRONG_BUSINESS_ERROR",
                                "error_message": f"Erro de negócio incorreto. Tela: '{error_text}'",
                                "failed_field": "None",
                                "extracted_value": "None",
                                "duration_seconds": duration
                            })
                            print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                            sys.stdout.flush()
                    else:
                        # Erro sistêmico
                        # Tenta extrair seletor que causou timeout
                        failed_field = "Unknown"
                        if "waiting for locator" in str(e):
                            match = re.search(r"waiting for locator\(['\"]([^'\"]+)['\"]\)", str(e))
                            if match:
                                failed_field = match.group(1)
                        
                        # Diagnóstico Inteligente via IA
                        diagnose_info = ""
                        if self.cognitive.is_active():
                            try:
                                print(f"[AEGIS RUNNER] Acionando diagnóstico de falha via IA...")
                                diag = self.cognitive.diagnose_failure(page, str(e), steps_history=self.steps_history)
                                if diag and isinstance(diag, dict):
                                    category = diag.get("category", "UNKNOWN")
                                    cause = diag.get("root_cause_summary", "")
                                    fix = diag.get("actionable_fix", "")
                                    diagnose_info = f" | IA DIAGNOSE [{category}]: {cause} (Recomendação: {fix})"
                                    print(f"[AEGIS RUNNER] Diagnóstico IA concluído: {diagnose_info}")
                            except Exception as diag_err:
                                print(f"[AEGIS RUNNER] Falha ao executar diagnóstico de IA: {diag_err}")
                        
                        # Tira screenshot do erro
                        screenshot_path = os.path.join(self.output_dir, "screenshots", f"screenshot_erro_transacao_{row_id}.png")
                        try:
                            page.screenshot(path=screenshot_path)
                            print(f"[❌ FALHA] Transação {row_id} quebrou por erro sistêmico. Screenshot salvo em: {screenshot_path}")
                        except:
                            pass
                            
                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "SYSTEM_FAILED",
                            "error_message": f"{str(e).replace('\n', ' ')} {diagnose_info}".strip(),
                            "failed_field": failed_field,
                            "extracted_value": "None",
                            "duration_seconds": duration
                        })
                        
                        # Registra o passo falho no histórico se o último passo já não for uma falha
                        has_failed_step = len(self.steps_history) > 0 and self.steps_history[-1]["status"] == "FAILED"
                        if not has_failed_step:
                            err_desc = f"Falha na execução: {cause}" if 'cause' in locals() and cause else f"Falha na execução: {str(e)}"
                            inferred_action = "click" if "click" in str(e).lower() else ("fill" if "fill" in str(e).lower() or "type" in str(e).lower() else "action")
                            self._log_step(step_id=None, action=inferred_action, selector=failed_field, target_description=err_desc, status="FAILED", error_msg=f"{str(e).replace('\n', ' ')} {diagnose_info}".strip())
                            
                        print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                        sys.stdout.flush()
            
            # Fecha navegador e grava relatório
            self._write_report(reports)
            
            # Grava o histórico final de passos em JSON na pasta de execução
            steps_json_path = os.path.join(self.output_dir, "reports", "historico_passos.json")
            try:
                with open(steps_json_path, "w", encoding="utf-8") as sf:
                    json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)
                print(f"[AEGIS RUNNER] Trilha de auditoria final (historico_passos.json) gravada em: {steps_json_path}")
            except Exception as j_err:
                print(f"[WARNING] Falha ao gravar {steps_json_path}: {j_err}")

            # Atualiza também o historico_passos.json na raiz do cenário com os dados reais do runner.
            # Isso substitui o arquivo gerado por pareamento FIFO do frontend (que pode divergir do
            # bot após correções cirúrgicas) com a trilha de auditoria precisa e confiável.
            try:
                root_steps_path = os.path.join(self.project_dir, "historico_passos.json")
                with open(root_steps_path, "w", encoding="utf-8") as sf:
                    json.dump(self.steps_history, sf, indent=4, ensure_ascii=False)
            except Exception as j_err:
                print(f"[WARNING] Falha ao atualizar historico_passos.json na raiz do cenário: {j_err}")
                
            self._write_index_file()
                
            if page:
                try:
                    page.close()
                except:
                    pass
            browser.close()

        # Retorna erro se houver falhas nas transações do lote
        has_failures = any(r["status"] not in ["SUCCESS", "SUCCESS_BLOCKED"] for r in reports)
        if has_failures:
            print("\n[AEGIS RUNNER] ❌ Execução em lote finalizada com falhas detectadas nas transações.")
            sys.exit(1)
        else:
            print("\n[AEGIS RUNNER] ✅ Execução em lote finalizada com sucesso total!")
