import os
import sys
import time
import csv
import re
import json
import collections
from datetime import datetime
from playwright.sync_api import sync_playwright

try:
    from cognitive_fallback import CognitiveGateway
except ImportError:
    from aegis_runner.cognitive_fallback import CognitiveGateway


class FlakyStepFailure(Exception):
    """Levantada quando um passo marcado como 'flaky' no plano de execução falha
    em modo strict dentro das primeiras 3 tentativas da linha atual. Sinaliza ao
    loop de execução (run()) que a linha deve ser reiniciada, em vez de propagar
    a exceção original como falha definitiva. A exceção original é preservada
    como atributo para log/investigação."""

    def __init__(self, step_id, selector, original_exception):
        self.step_id = step_id
        self.selector = selector
        self.original_exception = original_exception
        super().__init__(
            f"Passo flaky '{step_id}' ({selector}) falhou: {original_exception}"
        )


class _ClickTerminalFailure(Exception):
    """Marcador interno (não faz parte do contrato público de click_resilient):
    envolve uma exceção que _handle_unrecoverable_click já tratou como decisão
    FINAL (strict/flaky, self-healing cognitivo e fallback de coordenadas já
    esgotados, ou FlakyStepFailure já levantada) para o sensor ENABLE_TIMEOUT.
    click_resilient captura esse marcador especificamente no loop de attempts
    e relança `original` imediatamente, em vez de deixar o `except Exception`
    genérico do loop tratá-la como uma falha comum de clique físico e
    retentar o passo inteiro do zero (o que duplicaria self-healing/coordenada
    já executados dentro de _handle_unrecoverable_click)."""

    def __init__(self, original):
        self.original = original


# Regex de chave semântica pra campos numéricos/mascarados (CPF/CNPJ/CEP) --
# espelha aegis_code_generator/deterministic_emitter.py:_ASYNC_GUARD_KEY_RE,
# mantido local ao runtime de propósito (aegis_runner não deve depender do
# módulo design-time só por isto -- ver decoupling design-time/run-time no
# CLAUDE.md). Usada por TransactionRunner._verify_fill_effect (Fundação A1,
# .specs/plano-cauda-longa-verificada.md Seção 4.A1).
_ASYNC_GUARD_KEY_RE = re.compile(r"cpf|cnpj|cep", re.IGNORECASE)

# input[type] nativos tratados como numéricos/mascarados pela comparação
# type-aware de _verify_action_effect -- "date" tem tratamento próprio
# (tolerância de formato yyyy-mm-dd <-> dd/mm/yyyy), não entra aqui.
_NUMERIC_MASKED_INPUT_TYPES = {"number", "tel"}


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
        # Mapa step_id -> flaky derivado do plano de execução (populado em run()).
        # Inicializado vazio aqui para permitir chamadas diretas aos métodos
        # resilientes fora do loop de run() (ex.: testes unitários).
        self.flaky_step_ids = {}
        # Mapa step_id -> fallback_selectors (lista) derivado do plano de execução
        # (populado em run()). M5: cadeia de fallback determinístico gravado na
        # captura. Inicializado vazio para permitir chamadas diretas aos métodos
        # resilientes fora do loop de run() (ex.: testes unitários).
        self.fallback_selectors_by_step = {}
        # Tentativa atual da linha em execução para passos flaky. Valor default de
        # segurança; resetado por linha dentro do loop de run() por outra tarefa.
        self.current_row_flaky_attempt = 1

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
        self._recent_fills = collections.deque(maxlen=30)

    def register_scenario(self, scenario_name, callback):
        """Registra a rotina de preenchimento de formulário para um cenário lógico."""
        self.scenarios[scenario_name] = callback
        print(f"[AEGIS RUNNER] Cenário '{scenario_name}' registrado com sucesso.")

    def _log_step(self, step_id, action, selector, target_description, status, error_msg="", healing_method=None):
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

        # Sensor F1: toda vez que um passo é resolvido via healing, registra
        # automaticamente uma entrada 'needs_review' em correcoes_acumuladas.json
        # para revisão humana/QA posterior (não-fatal por design).
        if status == "HEALED":
            self._register_healing_for_review(step_id, selector, action, healing_method)

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

    def _with_file_lock(self, file_handle):
        """Context manager simples de lock exclusivo de arquivo (Windows via msvcrt)."""
        class _FileLock:
            def __init__(self, fh):
                self.fh = fh
                self.locked = False

            def __enter__(self):
                try:
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
                    self.locked = True
                except Exception:
                    pass
                return self.fh

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.locked:
                    try:
                        import msvcrt
                        self.fh.seek(0)
                        msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                return False

        return _FileLock(file_handle)

    def _register_healing_for_review(self, step_id, selector, action, healing_method=None):
        """
        Sensor F1: registra automaticamente uma entrada 'needs_review' em
        correcoes_acumuladas.json sempre que um passo é resolvido via healing
        (status='HEALED'), com dedup por (action, failed_selector) e escrita
        segura via lock exclusivo de arquivo (read-modify-write atômico).

        Não-fatal por design: qualquer falha aqui é apenas logada, nunca
        propagada, para jamais derrubar a transação em execução.
        """
        try:
            action_key = (action or "").strip().lower()
            selector_key = (selector or "").strip()

            # Throttle: evita escritas repetidas em disco para o mesmo par
            # (action, failed_selector) dentro de uma janela curta na mesma execução.
            if not hasattr(self, "_healing_throttle"):
                self._healing_throttle = {}
            throttle_key = (action_key, selector_key)
            now_ts = time.time()
            last_ts = self._healing_throttle.get(throttle_key)
            if last_ts is not None and (now_ts - last_ts) < 30:
                return
            self._healing_throttle[throttle_key] = now_ts

            corr_file = os.path.join(self.project_dir, "correcoes_acumuladas.json")

            execution_id = os.environ.get("AEGIS_EXECUTION_ID", "local")
            now_iso = datetime.now().isoformat()

            # Garante existência do arquivo antes de abrir em modo r+
            if not os.path.exists(corr_file):
                try:
                    with open(corr_file, "w", encoding="utf-8") as init_f:
                        json.dump([], init_f, indent=4, ensure_ascii=False)
                except Exception:
                    pass

            with open(corr_file, "r+", encoding="utf-8") as f:
                with self._with_file_lock(f):
                    try:
                        f.seek(0)
                        content = f.read()
                        all_corrs = json.loads(content) if content.strip() else []
                        if not isinstance(all_corrs, list):
                            all_corrs = []
                    except Exception:
                        all_corrs = []

                    # Status ATIVOS que indicam correção em andamento para este par
                    # (action, failed_selector). 'resolved'/'applied'/'failed_attempt'
                    # são decisões PASSADAS — se o mesmo par volta a precisar de healing
                    # depois de já ter sido dado como resolvido/aplicado, isso é uma
                    # REGRESSÃO nova e deve gerar entrada nova, não ser suprimida.
                    # Suprimir também esses status fazia qualquer seletor já resolvido
                    # uma vez nunca mais reaparecer no painel de needs_review, mesmo
                    # quebrando de novo em execuções futuras (bug real reproduzido:
                    # st_024/st_025 pararam de gerar needs_review após serem marcados
                    # 'resolved' uma vez, mesmo curando via IA de novo em runs depois).
                    active_statuses = ("needs_review", "pending")

                    existing_needs_review = None
                    has_other_known = False
                    for corr in all_corrs:
                        ca = (corr.get("action") or "").strip().lower()
                        cs = (corr.get("failed_selector") or "").strip()
                        if ca == action_key and cs == selector_key and corr.get("status") in active_statuses:
                            if corr.get("status") == "needs_review":
                                existing_needs_review = corr
                            else:
                                has_other_known = True

                    if existing_needs_review is not None:
                        existing_needs_review["occurrences"] = existing_needs_review.get("occurrences", 1) + 1
                        existing_needs_review["timestamp"] = now_iso
                        existing_needs_review["execution_id"] = execution_id
                        existing_needs_review["step_id"] = step_id
                    elif not has_other_known:
                        new_entry = {
                            "id": f"healing_{execution_id}_{step_id}",
                            "timestamp": now_iso,
                            "execution_id": execution_id,
                            "step_id": step_id,
                            "action": action,
                            "failed_selector": selector,
                            "root_cause": None,
                            "proposed_fix": None,
                            "qa_insight": None,
                            "healing_method": healing_method,
                            "occurrences": 1,
                            "status": "needs_review",
                        }
                        all_corrs.append(new_entry)
                    else:
                        # Já existe correção conhecida com outro status - não duplica.
                        return

                    f.seek(0)
                    f.truncate()
                    json.dump(all_corrs, f, indent=4, ensure_ascii=False)
        except Exception as sensor_err:
            print(f"[AEGIS RUNNER] [WARNING] Sensor de healing falhou ao registrar correcoes_acumuladas.json: {sensor_err}")

    _CLICK_EFFECT_EXCLUDED_SELECTORS = {"#btn-confirm-payment-progress"}

    def _click_effect_sensor_enabled(self) -> bool:
        """Flag mestre M2: AEGIS_CLICK_EFFECT_SENSOR (default true). false desativa
        completamente o sensor CLICK_NO_EFFECT, sem nenhum page.evaluate() extra."""
        return os.environ.get("AEGIS_CLICK_EFFECT_SENSOR", "true").lower() in ("true", "1", "yes")

    def _capture_click_effect_snapshot(self, page, selector=None):
        """Snapshot barato do estado da página em uma única chamada page.evaluate(),
        usado pelo sensor CLICK_NO_EFFECT (M2). Sinais de efeito: url, contagem de
        nós DOM, contagem de overlays, e fingerprint de classe do elemento clicado +
        seus irmãos diretos (4º sinal — ver abaixo). document.activeElement NÃO é
        sinal de efeito (o próprio clique move o foco no engine Chromium/MS Edge,
        mascarando justamente o caso-alvo de clique force=True sob overlay). Falha
        do próprio evaluate (ex.: página navegando) retorna None - tratado como
        "efeito detectado" pelo chamador, nunca como erro.

        4º sinal (siblingClassFingerprint): cobre o caso de troca de estado
        "só-CSS" — ex. abas React/Tailwind que só alternam className entre
        elementos JÁ existentes (sem adicionar/remover nós, sem navegação, sem
        overlay). Achado real no piloto do site novo (.specs/relatorio-piloto-site-novo.md):
        clique em aba de região (LATAM/EMEA/APAC) funcionava de verdade (troca de
        conteúdo confirmada por screenshot) mas os 3 sinais antigos não detectavam
        nada, gerando falso positivo. Concatena className + aria-selected/
        aria-current/aria-pressed do elemento clicado E de seus irmãos diretos
        (o grupo de abas/toggle inteiro) — não depende de o site usar atributos
        ARIA (o Fimm não usa), só de a classe do irmão ativo mudar.

        A resolução do elemento usa `page.locator(selector).evaluate(...)`, NÃO
        `document.querySelector(sel)` dentro do `page.evaluate` — seletores como
        `button:has-text('APAC')` ou `parent >> child` são sintaxe exclusiva do
        Playwright, inválida para `querySelector` nativo do browser (lança
        SyntaxError, capturado pelo try/catch, fingerprint sempre vazio nos dois
        lados = sinal nunca dispara). `page.locator()` resolve essa sintaxe antes
        de rodar o JS no elemento encontrado. Bug real reproduzido: com
        `querySelector`, o 4º sinal nunca detectava a troca de aba real do site
        piloto (fingerprint '' == '' sempre)."""
        base = {}
        try:
            base = page.evaluate(
                "() => ({"
                "url: location.href,"
                "domSize: document.getElementsByTagName('*').length,"
                "overlays: document.querySelectorAll('.cdk-overlay-container *, [role=dialog], .modal.show').length"
                "})"
            )
        except Exception:
            return None

        if not isinstance(base, dict):
            # page.evaluate() retornou algo que não é o snapshot esperado (ex.:
            # falsy simples usado por outro ponto do código/teste) — trata como
            # captura indisponível, igual a uma exceção, nunca quebra o passo.
            return None

        fingerprint = ""
        if selector:
            try:
                fingerprint = page.locator(selector).first.evaluate(
                    "(el) => {"
                    "  const parent = el.parentElement;"
                    "  const scope = parent ? Array.from(parent.children) : [el];"
                    "  return scope.map(c => (c.className || '') + '|' + (c.getAttribute('aria-selected')||'') + (c.getAttribute('aria-current')||'') + (c.getAttribute('aria-pressed')||'')).join(';;');"
                    "}",
                    timeout=1000
                )
            except Exception:
                fingerprint = ""
        base["siblingClassFingerprint"] = fingerprint
        return base

    def _click_effect_signals_changed(self, before, after) -> bool:
        """Compara dois snapshots do sensor CLICK_NO_EFFECT. Tolerância de +/-2 na
        contagem de nós DOM. Qualquer entrada ausente/inválida é tratada como
        'efeito detectado' (nunca bloqueia nem gera falso negativo por erro)."""
        if not before or not after:
            return True
        try:
            if before.get("url") != after.get("url"):
                return True
            if abs(int(after.get("domSize", 0)) - int(before.get("domSize", 0))) > 2:
                return True
            if int(after.get("overlays", 0)) != int(before.get("overlays", 0)):
                return True
            if (before.get("siblingClassFingerprint") or "") != (after.get("siblingClassFingerprint") or ""):
                return True
            return False
        except Exception:
            return True

    def _detect_click_no_effect(self, page, before_snapshot, selector, step_id) -> bool:
        """Polling early-exit pós-clique (M2): recaptura o snapshot em ~100/300/800ms
        (o tempo entre checagens, não o total acumulado - sai assim que algum sinal
        mudar). Retorna True se o clique teve efeito real confirmado (inclusive
        quando o próprio sensor falha internamente - nunca bloqueia o passo por
        erro do próprio sensor) ou False se, ao final do polling, nenhum sinal
        mudou (CLICK_NO_EFFECT). Chamado ANTES do log definitivo do passo, de
        dentro de _finalize_click_success - quem decide o que fazer com um
        resultado False (acionar a cadeia de recuperação determinística antes de
        fechar o passo) é o chamador, não este método."""
        if before_snapshot is None:
            return True
        try:
            for wait_ms in (100, 300, 800):
                page.wait_for_timeout(wait_ms)
                after_snapshot = self._capture_click_effect_snapshot(page, selector)
                if self._click_effect_signals_changed(before_snapshot, after_snapshot):
                    return True
            print(f"[AEGIS RUNNER] ⚠️ CLICK_NO_EFFECT | {step_id} | {selector}")
            return False
        except Exception:
            # Falha no próprio sensor nunca deve impactar a execução do passo.
            return True

    # Seletor genérico de painel/overlay aberto -- mesmo usado hoje em
    # select_option_resilient (runner.py:1383/1409/1433). Reaproveitado pelas
    # pós-condições específicas de select/trigger_open do verificador
    # universal (_verify_action_effect) em vez de duplicar a string.
    _OPEN_PANEL_SELECTOR = ".cdk-overlay-pane, .mat-select-panel, [role='listbox']"

    # Padrões de data reconhecidos pela pós-condição type-aware de fill --
    # mesmos formatos que fill_resilient/fill_human_like já convertem entre si
    # (runner.py ~2100/2205: yyyy-mm-dd <-> dd/mm/yyyy).
    _ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _BR_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

    def _verify_action_effect(self, page, before_snapshot, expected=None) -> bool:
        """
        Verificador universal de efeito (Fundação A1 -- .specs/plano-cauda-longa-
        verificada.md Seção 4.A1). Generaliza a verificação de efeito já
        existente SEM substituí-la: reusa _click_effect_signals_changed como
        base dos sinais genéricos (URL/domSize/overlays/siblingClassFingerprint),
        a mesma primitiva que já alimenta o sensor CLICK_NO_EFFECT (M2,
        _detect_click_no_effect, acima).

        NÃO fiado em nenhum call site ainda -- fundação isolada e testável por
        si só; o rewire dos tiers de decisão (click/select/fill) é outra tarefa
        (Seção 4.A2 do plano).

        Parâmetros:
          page: página Playwright ATUAL (pós-gesto). Só é efetivamente
            consultada quando `expected` não resolve tudo sozinho (painel
            aberto/fechado via page.locator(...).count(), URL via page.url,
            ou recaptura do snapshot genérico "depois" quando o chamador não
            informou um pronto em expected["after_snapshot"]).
          before_snapshot: dict no formato de _capture_click_effect_snapshot,
            capturado ANTES do gesto. None/valor inválido é tratado como "sem
            baseline" -- cai no comportamento conservador já existente de
            _click_effect_signals_changed (retorna True; falha do próprio
            sensor nunca bloqueia o passo).
          expected: dict opcional descrevendo a pós-condição específica do
            gesto -- quando presente e com "kind" reconhecido, é o critério
            PRIMÁRIO (Fase 2 do plano alimenta isto a partir de
            expected_effect gravado; hoje quem popula é o próprio chamador,
            por tipo de gesto). Chaves reconhecidas:
            - "kind": "fill" | "select" | "trigger_open" | "navigation" --
              ausente/não reconhecido cai nos sinais genéricos (ver abaixo).
            - fill: "expected_value" (obrigatório), e o valor realmente
              digitado via "actual_value" (string já lida pelo chamador) OU
              "locator" (objeto Playwright do ALVO QUE DE FATO recebeu a
              digitação -- o curado/proposto, NUNCA o seletor original que já
              falhou no ramo que invoca este verificador -- lido via
              locator.input_value()). "input_type" (ex. "tel", "number") e/ou
              "field_key" (ex. "cpf_titular", cruzado com _ASYNC_GUARD_KEY_RE)
              decidem comparação só-dígitos pra campos numéricos/mascarados;
              sem eles, comparação de texto livre (whitespace normalizado,
              nunca pontuação). Datas (ambos os lados em yyyy-mm-dd ou
              dd/mm/yyyy) são sempre comparadas com tolerância de formato.
            - select: "expected_text" (obrigatório) + "actual_trigger_text"
              (texto já lido pelo chamador) OU "trigger_locator" (lido via
              .inner_text()); painel precisa estar fechado
              (page.locator(panel_selector).count() == 0) E expected_text
              precisa aparecer em actual_trigger_text.
            - trigger_open: confirma que um painel abriu
              (page.locator(panel_selector).count() > 0).
            - navigation: URL mudou em relação a before_snapshot["url"] (ou
              bate exatamente com "url", se informado).
            - "panel_selector": override do seletor de painel/overlay usado
              por "select"/"trigger_open" (default _OPEN_PANEL_SELECTOR).
            - Sem "kind" reconhecido: "after_snapshot" (dict pronto, evita
              recapturar) e "panel_closed_confirmed" (bool) alimentam o
              caminho genérico abaixo.

        Regras (Seção 4.A1 do plano):
          1. Sinais genéricos são sempre a base quando não há pós-condição
             específica reconhecida (_click_effect_signals_changed).
          2. Ressalva de overlay (DEPENDÊNCIA DURA, não cosmética --
             runner.py:894-901 documenta que fechar um painel via clique no
             backdrop CDK muda os MESMOS sinais genéricos sem confirmar o
             clique certo): quando before_snapshot indica que havia painel/
             overlay aberto ANTES do gesto (`overlays` > 0, ou `panel_open`
             explícito), sinais genéricos SOZINHOS nunca aprovam no caminho
             genérico -- só aprovam se o chamador confirmar explicitamente
             via expected["panel_closed_confirmed"] (a própria confirmação É
             a pós-condição específica nesse caminho).
          3. Pós-condição específica por gesto (quando expected["kind"] é
             reconhecido) satisfaz sozinha o requisito -- não depende dos
             sinais genéricos, então a ressalva de overlay do item 2 fica
             automaticamente respeitada nesse caminho.
          4. Gesto não reconhecido (ou expected ausente) cai pros sinais
             genéricos, sujeitos à ressalva de overlay do item 2.
        """
        kind = expected.get("kind") if isinstance(expected, dict) else None

        if kind == "fill":
            return self._verify_fill_effect(page, expected)
        if kind == "select":
            return self._verify_select_effect(page, expected)
        if kind == "trigger_open":
            return self._verify_panel_opened(page, expected)
        if kind == "navigation":
            return self._verify_navigation_effect(page, before_snapshot, expected)

        return self._verify_generic_effect(page, before_snapshot, expected)

    def _verify_generic_effect(self, page, before_snapshot, expected) -> bool:
        """Caminho sem pós-condição específica reconhecida: sinais genéricos
        (URL/domSize/overlays/siblingClassFingerprint via
        _click_effect_signals_changed), com a ressalva obrigatória de overlay
        (regra 2 de _verify_action_effect)."""
        has_expected = isinstance(expected, dict)

        if has_expected and "after_snapshot" in expected:
            after_snapshot = expected["after_snapshot"]
        else:
            after_snapshot = self._capture_click_effect_snapshot(page)
        generic_changed = self._click_effect_signals_changed(before_snapshot, after_snapshot)

        before_had_overlay = isinstance(before_snapshot, dict) and (
            int(before_snapshot.get("overlays", 0) or 0) > 0
            or bool(before_snapshot.get("panel_open"))
        )
        if before_had_overlay:
            # Contexto de painel: sinais genéricos sozinhos nunca aprovam
            # (falso-positivo documentado de fechar painel via backdrop,
            # runner.py:894-901) -- só aprova com confirmação explícita do
            # chamador, que É a pós-condição específica nesse caminho.
            return bool(has_expected and expected.get("panel_closed_confirmed"))

        return generic_changed

    @classmethod
    def _looks_like_date(cls, value: str) -> bool:
        return bool(cls._ISO_DATE_RE.match(value) or cls._BR_DATE_RE.match(value))

    @staticmethod
    def _dates_equivalent(actual: str, expected_value: str) -> bool:
        """Tolera a mesma conversão de formato que fill_resilient/fill_human_like
        já aplicam pra campos que não são input nativo type=date (yyyy-mm-dd ->
        dd/mm/yyyy, runner.py ~2100/2205). Normaliza os dois lados pro formato
        ISO antes de comparar."""
        def to_iso(s):
            s = (s or "").strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                return s
            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
            if m:
                dd, mm, yyyy = m.groups()
                return f"{yyyy}-{mm}-{dd}"
            return s
        return to_iso(actual) == to_iso(expected_value)

    def _verify_fill_effect(self, page, expected) -> bool:
        """Pós-condição de fill: compara o valor esperado com o valor QUE DE
        FATO foi lido do alvo que recebeu a digitação (expected["locator"] --
        o elemento curado/proposto, NUNCA o seletor original que já falhou no
        ramo que invoca este verificador -- ou expected["actual_value"] já
        lido pelo chamador).

        Comparação type-aware (achado da Rodada 2 do plan-critic, Seção 4.A1):
        - Datas (ambos os lados reconhecíveis como yyyy-mm-dd ou dd/mm/yyyy):
          tolera a conversão de formato que fill_resilient/fill_human_like já
          fazem -- compara por equivalência, não por formato.
        - Campo numérico/mascarado (input_type em _NUMERIC_MASKED_INPUT_TYPES,
          ou field_key batendo com _ASYNC_GUARD_KEY_RE -- CPF/CNPJ/CEP):
          compara só dígitos (máscara pode diferir entre gravação e runtime).
        - Texto livre (nome, endereço, etc.): normaliza só whitespace (trim +
          colapsa espaços múltiplos) e compara exato -- NUNCA remove
          pontuação, pra não mascarar um fill genuinamente errado em nomes
          como "José D'Ávila" ou endereços como "Rua X, 123"."""
        if not isinstance(expected, dict):
            return False
        expected_value = expected.get("expected_value")
        if expected_value is None:
            return False

        actual_value = expected.get("actual_value")
        if actual_value is None:
            locator = expected.get("locator")
            if locator is None:
                return False
            try:
                actual_value = locator.input_value()
            except Exception:
                return False
        if actual_value is None:
            return False

        expected_str = str(expected_value)
        actual_str = str(actual_value)

        if self._looks_like_date(expected_str) and self._looks_like_date(actual_str):
            return self._dates_equivalent(actual_str, expected_str)

        input_type = (expected.get("input_type") or "").lower()
        field_key = expected.get("field_key") or ""
        is_numeric_masked = (
            input_type in _NUMERIC_MASKED_INPUT_TYPES
            or bool(_ASYNC_GUARD_KEY_RE.search(str(field_key)))
        )
        if is_numeric_masked:
            actual_digits = re.sub(r"\D", "", actual_str)
            expected_digits = re.sub(r"\D", "", expected_str)
            return actual_digits != "" and actual_digits == expected_digits

        actual_norm = re.sub(r"\s+", " ", actual_str).strip()
        expected_norm = re.sub(r"\s+", " ", expected_str).strip()
        return actual_norm == expected_norm

    def _verify_select_effect(self, page, expected) -> bool:
        """Pós-condição de select: painel fechou E o valor esperado apareceu no
        trigger. Sem como confirmar o valor no trigger (nem
        "actual_trigger_text" nem "trigger_locator" informados), não há como
        distinguir 'fechou porque comitou o valor certo' de 'fechou porque
        cancelou no backdrop' (falso-positivo documentado, runner.py:894-901)
        -- retorna False (não verificado); nunca aprova por omissão de dado."""
        if not isinstance(expected, dict):
            return False
        expected_text = expected.get("expected_text")
        if expected_text is None:
            return False

        panel_selector = expected.get("panel_selector") or self._OPEN_PANEL_SELECTOR
        try:
            panel_open = page.locator(panel_selector).count() > 0
        except Exception:
            return False
        if panel_open:
            return False

        actual_trigger_text = expected.get("actual_trigger_text")
        if actual_trigger_text is None:
            trigger_locator = expected.get("trigger_locator")
            if trigger_locator is None:
                return False
            try:
                actual_trigger_text = trigger_locator.inner_text()
            except Exception:
                return False
        if actual_trigger_text is None:
            return False

        return str(expected_text) in str(actual_trigger_text)

    def _verify_panel_opened(self, page, expected) -> bool:
        """Pós-condição de clique de trigger: um painel de opções abriu (mesma
        primitiva já usada em select_option_resilient, runner.py:1383/1409/1433,
        generalizada aqui)."""
        panel_selector = (expected or {}).get("panel_selector") or self._OPEN_PANEL_SELECTOR
        try:
            return page.locator(panel_selector).count() > 0
        except Exception:
            return False

    def _verify_navigation_effect(self, page, before_snapshot, expected) -> bool:
        """Pós-condição de navegação: a URL mudou (mesma checagem já usada via
        validate_navigation em click_resilient, generalizada aqui)."""
        try:
            current_url = page.url
        except Exception:
            # Falha do próprio sensor nunca deve bloquear o passo.
            return True
        before_url = before_snapshot.get("url") if isinstance(before_snapshot, dict) else None
        target_url = (expected or {}).get("url")
        if target_url:
            return current_url == target_url
        return before_url is not None and before_url != current_url

    def _hit_test_plausible(self, page, x, y, target_description, original_selector=None) -> bool:
        """Gate de plausibilidade PRÉ-clique (Fundação A4 -- .specs/plano-
        cauda-longa-verificada.md Seção 4.A4). Generaliza o hit-test já usado
        no fallback de coordenada de select_option_resilient
        (document.elementFromPoint + comparação de texto) para qualquer
        proposta de clique por coordenada: antes de fisicamente clicar,
        inspeciona o que de fato está sob o ponto proposto e rejeita
        propostas que não tenham nenhuma relação plausível com
        `target_description`.

        Método PURO: nunca clica, nunca muda o estado da página -- só lê via
        page.evaluate(elementFromPoint) e decide True/False. Ainda não é
        fiado em nenhum call site (essa é outra tarefa do backlog); esta
        função existe isolada e é testável por si só.

        Parâmetros:
          page: página Playwright atual.
          x, y: coordenadas (pixels) do ponto proposto para o clique.
          target_description: descrição textual do alvo esperado (rótulo do
            passo/dropdown/opção) -- comparada de forma tolerante (case-
            insensitive, substring em qualquer direção) contra o
            tagName/textContent/role do elemento encontrado sob o ponto.
          original_selector: seletor original que originou esta proposta de
            coordenada, quando disponível. Quando contém a substring ' >> '
            (seletor de Shadow DOM sancionado, Padrão A), o gate roda em
            MODO SOFT.

        Ressalva de Shadow DOM (Rodada 2 do plan-critic, achado aplicado
        neste documento): document.elementFromPoint() no nível do documento
        sofre "event retargeting" -- para um ponto dentro de uma shadow tree,
        ele retorna o shadow HOST, nunca o elemento interno, e o textContent
        do host não atravessa a fronteira do Shadow DOM. Um gate rígido
        rejeitaria sistematicamente propostas corretas nesses fluxos,
        neutralizando o tier de coordenada. Por isso, quando
        `original_selector` contém ' >> ', esta função APENAS loga a
        checagem e sempre retorna True (aprovado), deixando a verificação
        PÓS-clique (_verify_action_effect) como única linha de defesa nesse
        caso. Não tenta shadowRoot.elementFromPoint -- fora de escopo aqui.
        """
        is_shadow_dom = bool(original_selector) and " >> " in str(original_selector)

        try:
            hit = page.evaluate(
                "([x, y]) => { const el = document.elementFromPoint(x, y); "
                "if (!el) return null; "
                "return { tagName: el.tagName, textContent: el.textContent, "
                "role: el.getAttribute('role') || '' }; }",
                [x, y],
            )
        except Exception as e:
            print(f"[AEGIS RUNNER] [HIT-TEST] Falha ao inspecionar ponto ({x}, {y}): {e}")
            if is_shadow_dom:
                print("[AEGIS RUNNER] [HIT-TEST] Seletor Shadow DOM (' >> ') -- modo soft, aprovando apesar da falha de inspeção.")
                return True
            return False

        if is_shadow_dom:
            print(f"[AEGIS RUNNER] [HIT-TEST] Seletor Shadow DOM (' >> ') -- modo soft: elemento sob ({x}, {y}) = {hit!r}, aprovando sem checar compatibilidade (textContent não atravessa a fronteira do shadow host).")
            return True

        if not hit:
            print(f"[AEGIS RUNNER] [HIT-TEST] Nenhum elemento sob ({x}, {y}) -- proposta implausível para '{target_description}'.")
            return False

        target_norm = (target_description or "").strip().lower()
        text_norm = (hit.get("textContent") or "").replace("\xa0", " ").strip().lower()
        role_norm = (hit.get("role") or "").strip().lower()
        tag_norm = (hit.get("tagName") or "").strip().lower()

        plausible = bool(
            target_norm
            and (
                (text_norm and (text_norm in target_norm or target_norm in text_norm))
                or (role_norm and role_norm in target_norm)
                or (tag_norm and tag_norm in target_norm)
            )
        )

        if plausible:
            print(f"[AEGIS RUNNER] [HIT-TEST] Elemento sob ({x}, {y}) compatível com '{target_description}' (tag={tag_norm!r}, role={role_norm!r}, texto={text_norm!r}) -- plausível.")
        else:
            print(f"[AEGIS RUNNER] [HIT-TEST] Elemento sob ({x}, {y}) incompatível com '{target_description}' (tag={tag_norm!r}, role={role_norm!r}, texto={text_norm!r}) -- implausível, clique descartado.")

        return plausible

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

        # Espera genérica pré-clique para qualquer alvo que comece disabled e
        # só habilite depois de um timer/fetch assíncrono real do app (caso
        # motivador: '#btn-confirm-payment-progress' fica "Aguardando
        # Pagamento..." por ~6s) — o clique físico mais abaixo usa force=True
        # (necessário para outros seletores instáveis), que ignora a checagem
        # de enabled do Playwright. Sem esperar aqui, o robô clica cedo demais
        # e a ação não tem efeito. Ver
        # .specs/handoff-autocomplete-select-nao-verificavel.md ("st_054 em
        # diante"). Generalizada para qualquer selector desde o sensor
        # ENABLE_TIMEOUT (ver _wait_for_known_disabled_button).
        self._wait_for_known_disabled_button(page, selector)

        # Sensor M2 (CLICK_NO_EFFECT): snapshot pré-clique, só quando aplicável.
        # Exclusões: validate_navigation=True (já tem verificação própria de
        # navegação) e '#btn-confirm-payment-progress', que já tem tratamento
        # dedicado via _wait_for_known_disabled_button (espera PRÉ-clique).
        # '#btn-next-step' deixou de ser excluído: agora tem cobertura própria
        # via sensor ENABLE_TIMEOUT (_wait_if_wizard_transition_button +
        # _recover_via_recent_fills), que trata o caso de falso-sucesso
        # específico de botão que nunca habilita — não faz sentido também
        # ficar de fora do sensor geral.
        click_effect_before_snapshot = None
        if (
            self._click_effect_sensor_enabled()
            and not validate_navigation
            and selector not in self._CLICK_EFFECT_EXCLUDED_SELECTORS
        ):
            click_effect_before_snapshot = self._capture_click_effect_snapshot(page, selector)

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
                    # force=True alinhado ao restante do método (loop de candidatos,
                    # linha ~557): sem isso, este ramo fica vulnerável ao mesmo
                    # "intercepts pointer events" que o resto do clique resiliente
                    # já contorna (ver .specs/plans/correcao-causa-raiz-overlay-click-e-timeout-recorder.design.md).
                    # Item B: tenta o clique nativo (sem force) primeiro, com
                    # timeout curto — só cai pro force=True (necessário para o
                    # "intercepts pointer events" que o resto do clique
                    # resiliente já contorna) se o nativo falhar.
                    try:
                        page.locator(selector).click(timeout=500, force=False)
                    except Exception:
                        page.locator(selector).click(timeout=timeout, force=True)
                    target_enabled = self._wait_if_wizard_transition_button(page, selector, before_snapshot=click_effect_before_snapshot)
                    enable_timeout_recovered = False
                    if not target_enabled:
                        target_enabled = self._recover_via_recent_fills(page, selector, step_id)
                        enable_timeout_recovered = target_enabled
                    if target_enabled:
                        finalize_result = self._finalize_click_success(
                            page, selector, target_description, step_id, strict, original_coords, click_effect_before_snapshot
                        )
                        if enable_timeout_recovered:
                            self._register_healing_for_review(step_id, selector, "click", "enable_timeout_recovered")
                        return finalize_result
                    enable_timeout_exc = RuntimeError(
                        f"ENABLE_TIMEOUT: elemento-alvo do clique em '{selector}' permaneceu desabilitado "
                        f"mesmo após recuperação via re-preenchimento dos campos recentes."
                    )
                    # _handle_unrecoverable_click já é a decisão FINAL (strict/
                    # flaky/cognitivo/coordenadas esgotados) — qualquer exceção
                    # que ela levante precisa propagar direto pra fora de
                    # click_resilient, não ser recapturada pelo except genérico
                    # do loop de attempts logo abaixo (que trataria como uma
                    # falha comum de clique físico e retentaria o passo do
                    # zero, duplicando self-healing/coordenada já executados).
                    try:
                        return self._handle_unrecoverable_click(
                            page, selector, target_description, enable_timeout_exc, original_coords, step_id, strict
                        )
                    except Exception as terminal_exc:
                        raise _ClickTerminalFailure(terminal_exc) from terminal_exc

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
                # A3 (.specs/plano-cauda-longa-verificada.md Seção 4.A3): só é
                # ambiguidade REAL quando o seletor casou mais de um elemento
                # candidato — um único candidato segue o caminho de sempre
                # (identity tier), sem custo extra de verificação de efeito.
                real_ambiguity = len(candidate_locators) > 1
                ambiguous_candidate_verified = False

                for idx, loc in enumerate(candidate_locators):
                    try:
                        if not loc.is_visible():
                            continue

                        print(f"[AEGIS RUNNER] Tentando clique físico no elemento {idx+1}/{len(candidate_locators)} de '{selector}'...")
                        loc.scroll_into_view_if_needed(timeout=1000)
                        time.sleep(0.2)

                        # A3: captura o snapshot ANTES do clique do candidato
                        # escolhido quando há ambiguidade real, para verificar
                        # o efeito depois em vez de aceitar SUCCESS silencioso
                        # na troca de alvo (bug real confirmado ao vivo:
                        # seletor ambíguo casando múltiplos botões dentro de
                        # um painel de autocomplete — clicava em ALGUM botão,
                        # o painel permanecia aberto, e o passo era logado
                        # como HEALED mesmo assim).
                        candidate_before_snapshot = None
                        if real_ambiguity and not validate_navigation:
                            candidate_before_snapshot = self._capture_click_effect_snapshot(page, selector)

                        # Item B: mesma ideia do branch acima — tenta sem
                        # force primeiro (timeout curto), só força se falhar.
                        try:
                            loc.click(timeout=500, force=False)
                        except Exception:
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
                        elif real_ambiguity:
                            # A3: heurística multi-candidato só aceita o
                            # candidato clicado quando um efeito real é
                            # confirmado — nunca mais SUCCESS silencioso ao
                            # escolher entre elementos ambíguos.
                            if self._verify_action_effect(page, candidate_before_snapshot):
                                ambiguous_candidate_verified = True
                                break
                            print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Clique no candidato ambíguo {idx+1}/{len(candidate_locators)} de '{selector}' não confirmado por efeito real. Tentando próximo candidato...")
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
                    target_enabled = self._wait_if_wizard_transition_button(page, selector, before_snapshot=click_effect_before_snapshot)
                    enable_timeout_recovered = False
                    if not target_enabled:
                        target_enabled = self._recover_via_recent_fills(page, selector, step_id)
                        enable_timeout_recovered = target_enabled
                    if target_enabled:
                        if ambiguous_candidate_verified:
                            # A3: o efeito já foi verificado no candidato
                            # específico que foi clicado — fecha direto como
                            # HEALED, sem passar por _finalize_click_success
                            # (cujo sensor CLICK_NO_EFFECT reconsultaria o
                            # snapshot genérico capturado ANTES do loop de
                            # candidatos, não o do candidato que de fato foi
                            # clicado).
                            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", healing_method="ambiguous_candidate_verified")
                            return True
                        finalize_result = self._finalize_click_success(
                            page, selector, target_description, step_id, strict, original_coords, click_effect_before_snapshot
                        )
                        if enable_timeout_recovered:
                            self._register_healing_for_review(step_id, selector, "click", "enable_timeout_recovered")
                        return finalize_result
                    enable_timeout_exc = RuntimeError(
                        f"ENABLE_TIMEOUT: elemento-alvo do clique em '{selector}' permaneceu desabilitado "
                        f"mesmo após recuperação via re-preenchimento dos campos recentes."
                    )
                    # _handle_unrecoverable_click já é a decisão FINAL (strict/
                    # flaky/cognitivo/coordenadas esgotados) — qualquer exceção
                    # que ela levante precisa propagar direto pra fora de
                    # click_resilient, não ser recapturada pelo except genérico
                    # do loop de attempts logo abaixo (que trataria como uma
                    # falha comum de clique físico e retentaria o passo do
                    # zero, duplicando self-healing/coordenada já executados).
                    try:
                        return self._handle_unrecoverable_click(
                            page, selector, target_description, enable_timeout_exc, original_coords, step_id, strict
                        )
                    except Exception as terminal_exc:
                        raise _ClickTerminalFailure(terminal_exc) from terminal_exc
                else:
                    raise RuntimeError("Nenhum candidato correspondente ao seletor estava visível ou clicável no DOM.")

            except _ClickTerminalFailure as terminal:
                # Decisão já finalizada (ver comentário no ponto de disparo) -
                # propaga a exceção original sem retentar o passo.
                raise terminal.original
            except Exception as e:
                last_exception = e
                print(f"[AEGIS RUNNER] Tentativa {attempt} de clique falhou para '{selector}': {e}")
                if attempt == 2:
                    return self._handle_click_failure(page, selector, target_description, timeout, e, original_coords, step_id=step_id, strict=strict)

    def _finalize_click_success(self, page, selector, target_description, step_id, strict, original_coords, click_effect_before_snapshot) -> bool:
        """
        Fecha um clique físico que executou sem lançar exceção. Quando o sensor
        CLICK_NO_EFFECT não está aplicável a este passo (click_effect_before_snapshot
        é None - sensor desativado, validate_navigation=True, ou seletor
        excluído), fecha direto como SUCCESS, igual ao comportamento anterior a
        esta mudança.

        Quando o sensor está aplicável, só fecha como SUCCESS se
        _detect_click_no_effect confirmar efeito real na página. Se o sensor
        detectar CLICK_NO_EFFECT (falso-sucesso silencioso), aciona a mesma
        cadeia de recuperação determinística que _handle_click_failure já usa
        para falhas por exceção (Escape+retry, reposicionar `.cdk-overlay-pane`
        + clique via JS, fallback_selectors gravados) ANTES de considerar o
        passo fechado. Se alguma camada produzir efeito real confirmado, fecha
        como HEALED (healing_method="click_no_effect_recovered"). Se nenhuma
        camada produzir efeito real, trata como falha genuína e delega a
        _handle_unrecoverable_click (mesma decisão de strict/cognitivo/
        coordenadas que _handle_click_failure já usa hoje para falhas por
        exceção).
        """
        if click_effect_before_snapshot is None:
            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
            return True

        effect_confirmed = self._detect_click_no_effect(page, click_effect_before_snapshot, selector, step_id)
        if effect_confirmed:
            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
            return True

        recovered, _method, resolved_selector = self._attempt_deterministic_click_recovery(
            page, selector, step_id, identity_scoped=False, before_snapshot=click_effect_before_snapshot
        )
        if recovered:
            print(f"[AEGIS RUNNER] Clique sem efeito real recuperado via camada determinística ({_method}) em '{resolved_selector}'.")
            self._log_step(step_id=step_id, action="click", selector=resolved_selector, target_description=target_description, status="HEALED", healing_method="click_no_effect_recovered")
            return True

        synthetic_exc = RuntimeError(
            f"CLICK_NO_EFFECT: clique em '{selector}' não produziu nenhum efeito detectável na página, "
            f"mesmo após as camadas de recuperação determinística (Escape+retry, reposição de overlay CDK, fallback_selectors)."
        )
        return self._handle_unrecoverable_click(page, selector, target_description, synthetic_exc, original_coords, step_id, strict)

    def _attempt_deterministic_click_recovery(self, page, selector, step_id, identity_scoped=False, before_snapshot=None):
        """
        Tenta, em sequência, as camadas determinísticas de recuperação de
        clique: Nível 2.5 (Escape + retry no próprio seletor), Nível 2.75
        (reposicionar `.cdk-overlay-pane` no viewport + clique sintético via
        JS) e Nível 2.9 (`fallback_selectors` gravados na captura, um a um).

        Compartilhado entre _handle_click_failure (recuperação de falha por
        EXCEÇÃO do Playwright) e _finalize_click_success (recuperação de
        CLICK_NO_EFFECT - falso-sucesso SEM exceção, mas sem efeito real
        confirmado na página) para não duplicar a lógica JS/Python destas
        camadas nos dois pontos de chamada.

        - before_snapshot=None (uso de _handle_click_failure): a primeira
          camada que conseguir clicar sem lançar exceção já é considerada
          resolução - mesmo contrato de antes desta extração.
        - before_snapshot=<snapshot> (uso de _finalize_click_success): depois
          de CADA clique bem-sucedido (sem exceção), recaptura o snapshot e só
          aceita a camada como resolução se o efeito real for confirmado
          (_click_effect_signals_changed); caso contrário, segue tentando a
          próxima camada (inclusive o próximo fallback_selector da lista) em
          vez de parar no primeiro clique mecânico "sem erro".

        Retorna (True, method_label, resolved_selector) na primeira camada que
        resolver segundo o critério acima, ou (False, None, None) se todas
        esgotarem sem resolver.

        Níveis 2.5/2.75 são pulados quando identity_scoped=True (mesma regra
        já existente em _handle_click_failure: um seletor plano reconsultado
        via page.locator()/document.querySelector() pode casar a linha errada
        quando o pai tinha filtro de identidade has_text). Nível 2.9 sempre
        roda, mesma decisão de design M5 já existente.
        """
        def _effect_confirmed(used_selector):
            if before_snapshot is None:
                return True
            after_snapshot = self._capture_click_effect_snapshot(page, used_selector)
            return self._click_effect_signals_changed(before_snapshot, after_snapshot)

        if not identity_scoped:
            # Nível 2.5: Auto-Healing de UI Reativo (Se ainda não foi limpo, limpa de novo e retenta)
            print(f"[AEGIS RUNNER] Falha de clique físico em '{selector}'. Tentando limpar overlays via Escape...")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
                page.locator(selector).first.click(timeout=3000)
                if _effect_confirmed(selector):
                    print(f"[AEGIS RUNNER] Clique resolvido reativamente após limpeza de overlays!")
                    return True, "escape_retry", selector
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
                    if _effect_confirmed(selector):
                        print(f"[AEGIS RUNNER] Clique resolvido apos reposicionar overlay!")
                        return True, "cdk_reposition", selector
            except Exception:
                pass

        # Nível 2.9 (M5): Fallback de seletores determinísticos gravados na captura.
        fallback_selectors = self.fallback_selectors_by_step.get(step_id, []) if hasattr(self, "fallback_selectors_by_step") else []
        for fb_selector in fallback_selectors:
            try:
                print(f"[AEGIS RUNNER] [FALLBACK SELECTOR] Tentando seletor alternativo gravado: '{fb_selector}'...")
                page.locator(fb_selector).first.click(timeout=2000)
                if _effect_confirmed(fb_selector):
                    return True, "fallback_selector", fb_selector
            except Exception:
                continue

        return False, None, None

    def _handle_unrecoverable_click(self, page, selector, target_description, e, original_coords=None, step_id=None, strict=False, live_text=None) -> bool:
        """
        Decide o desfecho final de um clique que NENHUMA camada determinística
        conseguiu resolver: aplica a mesma regra de strict/flaky, tenta a
        Geometria DOM ao Vivo por texto (Nível 3, só quando o chamador
        extraiu `live_text` do seletor), o Fallback Físico de Coordenadas de
        Gravação, agora COM verificação de efeito pós-clique (Nível 4,
        `.specs/plano-cauda-longa-verificada.md` Seção 3/4.A2 — reordenado
        pra ANTES do cognitivo) e o Self-Healing Cognitivo por IA (Nível 5,
        quando a coordenada não resolveu) quando permitido, e por fim loga
        FAILED e relança a exceção `e`.

        Compartilhado entre _handle_click_failure (falha por exceção do
        Playwright, depois de _attempt_deterministic_click_recovery esgotar)
        e _finalize_click_success (CLICK_NO_EFFECT confirmado mesmo após a
        recuperação determinística) para não duplicar a decisão de
        strict/cognitivo/coordenadas nos dois pontos de chamada.

        live_text: literal extraído de um :has-text('...') do seletor do
        filho por click_chained (via _extract_has_text_literal). None nos
        demais chamadores — o Nível 3 (geometria) então não se aplica e o
        fluxo cai direto no Self-Healing Cognitivo (Nível 3.5), byte-idêntico
        ao comportamento anterior à introdução do tier de geometria.
        """
        is_flaky_step = self.flaky_step_ids.get(step_id, False)
        flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4
        if (strict or is_flaky_step) and not flaky_healing_unlocked:
            if is_flaky_step and self.current_row_flaky_attempt <= 3:
                self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise FlakyStepFailure(step_id, selector, e)
            print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ao clicar em '{selector}' (self-healing e fallback por coordenadas desativados para este passo).")
            self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
            raise e

        # Nível 3: Geometria DOM ao Vivo por texto da opção (determinístico,
        # sem LLM). Só se aplica quando o chamador (click_chained) extraiu o
        # literal de um :has-text('...') do seletor do filho — caso típico:
        # opção de autocomplete/overlay (ex.: div:has-text('Creta')). Overlays
        # CDK reancoram o painel na posição VIVA do input a cada abertura
        # (getBoundingClientRect().bottom), então a coordenada de gravação do
        # Nível 4 fica obsoleta e pode cair no backdrop transparente — que
        # CANCELA o overlay sem commitar o valor no estado do app (o commit só
        # acontece no listener de clique da própria opção). Causa raiz
        # confirmada da falha em cascata st_024→st_025 do Portal Segura
        # (Modelo "selecionado" via coordenada morta a ~161px da opção real →
        # Versão nunca popula). O sensor CLICK_NO_EFFECT não cobre este caso:
        # fechar o painel via backdrop MUDA overlays/domSize, parecendo efeito
        # real. Reaproveita _click_by_live_geometry (mesma primitiva já usada
        # por select_option_resilient): resolve a opção por TEXTO e clica no
        # centro do bounding rect ATUAL. Roda ANTES da coordenada gravada
        # (Nível 4) e do Self-Healing Cognitivo (Nível 5) porque nenhum dos
        # dois tem a mesma garantia de identidade — a coordenada gravada
        # pode ter ficado obsoleta e a IA de visão clica onde aponta sem
        # confirmar que o clique realmente comitou o valor no estado do app
        # (ex.: confundir o texto já digitado no campo de busca com a opção
        # do dropdown, "clicando" no próprio input e retornando sucesso
        # falso). A geometria ao vivo é determinística e verificável, então
        # tem prioridade sempre que há `live_text` disponível; qualquer
        # exceção aqui cai para o Nível 4, nunca propaga.
        healed_by_ia = False
        if live_text:
            try:
                print(f"[AEGIS RUNNER] Tentando resolver clique via geometria DOM ao vivo pelo texto '{live_text}'...")
                if self._click_by_live_geometry(page, live_text):
                    # _log_step com status="HEALED" já registra needs_review
                    # via _register_healing_for_review (Sensor F1), como nos
                    # demais tiers de healing.
                    self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", healing_method="live_geometry_by_text")
                    return True
            except Exception as geo_err:
                print(f"[AEGIS RUNNER] Falha no tier de geometria ao vivo por texto: {geo_err}")

        # Nível 4: Fallback Físico de Coordenadas de Gravação, agora ANTES do
        # Self-Healing Cognitivo e COM verificação de efeito pós-clique
        # (.specs/plano-cauda-longa-verificada.md Seção 3/4.A2). Antes desta
        # reordenação, a coordenada gravada era o "Último Recurso" depois do
        # cognitivo e era aceita às cegas (sem verificação alguma) — se
        # estivesse obsoleta e caísse no backdrop transparente de um overlay
        # CDK, o clique "funcionava" mecanicamente (fecha o overlay, muda
        # DOM/overlays) mas não commitava nenhum valor de negócio, um
        # falso-positivo silencioso. Promover a coordenada pra antes do
        # cognitivo só é seguro PORQUE `_verify_action_effect` (SUB01) já tem
        # a ressalva de overlay que detecta exatamente esse caso — sem ela,
        # esta reordenação teria introduzido o falso-positivo genérico em vez
        # de eliminá-lo. Proposta (clique físico) rejeitada pela verificação
        # é VERIFY_REJECTED — cadeia segue pro próximo tier (cognitivo), nunca
        # aborta por uma coordenada obsoleta.
        if original_coords and len(original_coords) == 2:
            try:
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                x = int(viewport["width"] * original_coords[0])
                y = int(viewport["height"] * original_coords[1])
                print(f"[AEGIS RUNNER] Tentando coordenadas históricas da gravação (verificado): ({x}, {y})")
                before_snapshot = self._capture_click_effect_snapshot(page, selector)
                page.mouse.click(x, y)
                if self._verify_action_effect(page, before_snapshot, expected=None):
                    self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", error_msg="Fallback coords used", healing_method="coordinate")
                    return True
                print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Coordenada gravada ({x}, {y}) não produziu efeito verificável para '{target_description}'.")
            except Exception as coords_err:
                print(f"[AEGIS RUNNER] Falha ao tentar clique por coordenadas de fallback: {coords_err}")

        # Nível 5: Self-Healing Cognitivo por IA. Roda quando a geometria ao
        # vivo (Nível 3) e a coordenada gravada verificada (Nível 4) não
        # resolveram.
        #
        # Contrato proposto→verificado (.specs/plano-cauda-longa-verificada.md
        # Seção 4.B1/A4/A1): `self_healing_click` só PROPÕE {x, y, reason,
        # confidence} (ou None) — nunca clica. O runner faz o gate de
        # plausibilidade PRÉ-clique (`_hit_test_plausible`, A4); só uma
        # proposta plausível é fisicamente clicada; o efeito é então
        # verificado PÓS-clique (`_verify_action_effect`, A1) antes de virar
        # HEALED. Proposta implausível ou efeito não verificado é
        # VERIFY_REJECTED — cadeia segue pro esgotamento final, nunca aborta
        # por proposta ruim.
        if self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha no clique padrão de '{selector}'. Acionando Self-Healing cognitivo via IA...")
            try:
                proposal = self.cognitive.self_healing_click(
                    page, selector, target_description, original_coords,
                    expected_effect=(
                        "Após o clique, a página deve reagir de forma perceptível "
                        "(navegação, abertura/fechamento de painel, ou mudança visual no estado do elemento)."
                    ),
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], target_description, original_selector=selector):
                    before_snapshot = self._capture_click_effect_snapshot(page, selector)
                    page.mouse.click(proposal["x"], proposal["y"])
                    if self._verify_action_effect(page, before_snapshot, expected=None):
                        self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", healing_method="visual_ai")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva em ({proposal['x']}, {proposal['y']}) não produziu efeito verificável para '{target_description}'.")
                else:
                    if proposal:
                        print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva em ({proposal['x']}, {proposal['y']}) rejeitada pelo gate de plausibilidade (pré-clique) para '{target_description}'.")
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro durante chamada do Self-Healing de IA: {ia_err}")

        print(f"[AEGIS RUNNER] Falha definitiva ao clicar em '{selector}'.")
        self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
        raise e

    def _wait_for_known_disabled_button(self, page, selector, timeout_ms=15000) -> bool:
        """
        Espera PRÉ-clique para qualquer botão que comece 'disabled' e só
        habilite depois de um timer/fetch assíncrono real do app (caso
        motivador original: '#btn-confirm-payment-progress'). Simétrico a
        _wait_if_wizard_transition_button (que espera DEPOIS do clique, para
        botões que se desabilitam ao serem clicados) — aqui a espera é
        ANTES, porque o botão já nasce desabilitado. Generalizado para
        QUALQUER selector (não mais restrito a uma lista literal conhecida) —
        mesmo padrão de polling de 300ms e teto de 15s.

        Retorna True se o elemento ficou habilitado dentro do prazo, False se
        o prazo esgotou com o elemento ainda desabilitado/inacessível.
        """
        waited_ms = 0
        while True:
            try:
                if page.locator(selector).first.is_enabled(timeout=300):
                    return True
            except Exception:
                pass
            if waited_ms >= timeout_ms:
                return False
            page.wait_for_timeout(300)
            waited_ms += 300

    def _wait_if_wizard_transition_button(self, page, selector, timeout_ms=15000, before_snapshot=None) -> bool:
        """
        Espera PÓS-clique genérica para qualquer botão que dispare uma
        transição assíncrona (fetch simulando cálculo/submissão) e se
        desabilite de forma síncrona no clique, só se liberando (ou trocando
        de tela) quando a resposta chega — caso motivador original:
        '#btn-next-step' num wizard (ver
        .specs/handoff-autocomplete-select-nao-verificavel.md, seção 'st_054
        em diante'). Sem esperar isso, o passo seguinte do bot tenta
        interagir com uma tela que ainda não foi renderizada. Generalizado
        para QUALQUER selector (não mais restrito a um literal único) —
        mesmo padrão de polling de 300ms e teto de 15s.

        `before_snapshot` (opcional, mesmo snapshot pré-clique do sensor
        CLICK_NO_EFFECT): a cada iteração do polling, além de checar se o
        MESMO seletor reabilitou, checa se a página já mudou de verdade
        (url, tamanho do DOM, overlays, fingerprint de classe dos irmãos) —
        se mudou, sai IMEDIATAMENTE, mesmo que o seletor continue
        desabilitado. Achado real, reproduzido ao vivo: '#btn-next-step' é o
        MESMO id em toda tela de um wizard multi-etapa (Cliente, Veículo,
        Condutor...) — depois de uma navegação bem-sucedida, reconsultar
        '#btn-next-step' resolve pro botão da TELA NOVA, que nasce
        desabilitado até os campos DAQUELA tela serem preenchidos (o que só
        acontece vários passos depois no plano) — nada a ver com o clique que
        acabou de rodar. Sem essa checagem, o sensor confundia "tela mudou,
        botão novo da tela seguinte ainda não habilitou" com "clique não fez
        efeito", disparando recuperação via re-fill + self-healing cognitivo
        à toa (~35s de custo por transição de tela, sempre, mesmo quando o
        clique já tinha funcionado perfeitamente). Uma checagem avulsa
        IMEDIATAMENTE após o clique (sem esperar nada) quase nunca pega essa
        mudança a tempo — a navegação real leva um instante pra renderizar;
        por isso a checagem entra DENTRO do mesmo loop de polling de 300ms,
        não como um passo isolado antes dele.

        Retorna True se o elemento deixou de estar desabilitado dentro do
        prazo (ou sumiu/mudou de identidade, sinal de que a tela já trocou,
        ou a página mudou de verdade segundo o snapshot), False se o prazo
        esgotou com o elemento ainda desabilitado e a página aparentemente
        igual.
        """
        waited_ms = 0
        while True:
            try:
                if not page.locator(selector).first.is_disabled(timeout=300):
                    return True
            except Exception:
                # Elemento sumiu/mudou de identidade no meio da checagem —
                # sinal de que a tela já trocou (re-render destruiu o botão
                # antigo). Seguro assumir que a transição terminou.
                return True
            if before_snapshot is not None:
                try:
                    after_snapshot = self._capture_click_effect_snapshot(page, selector)
                    if self._click_effect_signals_changed(before_snapshot, after_snapshot):
                        return True
                except Exception:
                    pass
            if waited_ms >= timeout_ms:
                return False
            page.wait_for_timeout(300)
            waited_ms += 300

    def _recover_via_recent_fills(self, page, selector, step_id) -> bool:
        """
        Sensor ENABLE_TIMEOUT: acionado quando um clique físico teve sucesso
        mecânico mas o alvo do qual ele depende (checado via
        _wait_if_wizard_transition_button, agora generalizado para qualquer
        selector) nunca habilitou dentro do prazo. Caso motivador real (piloto
        Portal Segura): o campo Nome é preenchido antes de a busca assíncrona
        de CPF terminar, e o botão '#btn-next-step' nunca habilita — o clique
        seguinte reporta falso-sucesso.

        Reexecuta, na ordem em que foram preenchidos, os fills mais recentes
        registrados em self._recent_fills (buffer populado exclusivamente por
        fill_resilient — fill_chained não é coberto aqui) usando a mesma
        strategy gravada, aguarda um settle curto entre cada um (mesma faixa
        de tolerância 300-800ms usada pelo sensor CLICK_NO_EFFECT) e, ao
        final, refaz a espera de habilitação generalizada UMA única vez.

        Retorna o resultado dessa espera final: True se o elemento habilitou
        após a recuperação, False se a falha é genuína (o chamador delega
        para _handle_unrecoverable_click, mesma decisão de
        strict/cognitivo/coordenadas usada em qualquer outra falha de
        clique).
        """
        if not self._recent_fills:
            return self._wait_if_wizard_transition_button(page, selector)

        print(
            f"[AEGIS RUNNER] ⚠️ ENABLE_TIMEOUT | {step_id} | {selector} | "
            f"Alvo não habilitou; reexecutando {len(self._recent_fills)} preenchimento(s) "
            f"recente(s) antes de desistir..."
        )
        # Feature 2 (diagnóstico, não decide nada): a intenção original era
        # anexar aqui as entradas mais recentes de self.captured_network para
        # ajudar o QA a correlacionar o timeout de habilitação com uma chamada
        # de rede pendente. captured_network é uma estrutura do RECORDER
        # (aegis_blackbox), não existe no runner em tempo de execução — não há
        # fonte de dados real para anexar, então este sub-item é pulado (ver
        # nota no relatório da tarefa) em vez de inventar uma fonte que não
        # existe.

        for entry in list(self._recent_fills):
            entry_selector = entry.get("selector")
            # Checagem rápida de presença ANTES de chamar fill_resilient — sem
            # isso, uma entrada stale (campo de uma tela já navegada) paga o
            # timeout interno cheio de fill_resilient (default 5s) e pode
            # escalar até o fallback visual/cognitivo (chamada de LLM), custo
            # de minutos por entrada stale em vez de milissegundos. Achado ao
            # vivo no gate de regressão (bot de referência): cascata de
            # timeouts de 30s+ quando o buffer continha campos de uma tela
            # anterior à transição real.
            try:
                if not page.locator(entry_selector).first.is_visible(timeout=500):
                    print(f"[AEGIS RUNNER] Recuperação: '{entry_selector}' não está mais visível na tela — pulando (não é mais parte do passo atual).")
                    continue
            except Exception:
                print(f"[AEGIS RUNNER] Recuperação: '{entry_selector}' não resolvido na tela atual — pulando.")
                continue

            try:
                self.fill_resilient(
                    page,
                    entry_selector,
                    entry.get("text_val"),
                    entry.get("target_description"),
                    strategy=entry.get("strategy", "DIRECT"),
                    step_id=entry.get("step_id"),
                )
            except Exception as refill_err:
                print(f"[AEGIS RUNNER] Falha ao reexecutar fill de recuperação em '{entry_selector}': {refill_err}")
            page.wait_for_timeout(500)

        return self._wait_if_wizard_transition_button(page, selector)

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

    def _handle_click_failure(self, page, selector, target_description, timeout, e, original_coords=None, step_id=None, strict=False, identity_scoped=False, live_text=None) -> bool:
        # Níveis 1.5/2.5/2.75 reconsultam `selector` como string plana via
        # page.locator()/document.querySelector(). Chamadores encadeados
        # (click_chained) montam essa string concatenando parent >> child sem
        # o filtro .filter(has_text=...) do pai — impossível de expressar em
        # CSS puro. Sem o filtro, esses níveis podem casar com a PRIMEIRA
        # ocorrência do seletor no DOM inteiro (linha/registro errado) e
        # reportar status="SUCCESS" (nem "HEALED"), um falso-positivo pior e
        # mais silencioso que o de self-healing por IA. identity_scoped=True
        # pula esses níveis quando o pai tem filtro de identidade (has_text).
        if not identity_scoped:
            # Nível 1.5: Se for erro de múltiplos elementos (strict mode).
            # A3 (.specs/plano-cauda-longa-verificada.md Seção 4.A3): o
            # fallback pra '.first' também entra na doutrina de verificação —
            # só fecha como HEALED quando um efeito real é confirmado, nunca
            # mais SUCCESS silencioso na troca de alvo ambíguo.
            if "strict mode violation" in str(e) or "resolved to" in str(e):
                try:
                    print(f"[AEGIS RUNNER] Múltiplos elementos em fallback. Clicando no primeiro deles...")
                    t2_before_snapshot = self._capture_click_effect_snapshot(page, selector)
                    page.locator(selector).first.click(timeout=timeout)
                    if self._verify_action_effect(page, t2_before_snapshot):
                        self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="HEALED", healing_method="ambiguous_candidate_verified")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Clique em fallback '.first' de '{selector}' não confirmado por efeito real. Prosseguindo para a cadeia de recuperação existente...")
                except Exception as inner_e:
                    e = inner_e

        # Níveis 2.5/2.75/2.9: camadas determinísticas compartilhadas com
        # _finalize_click_success (recuperação de CLICK_NO_EFFECT). Ver
        # docstring de _attempt_deterministic_click_recovery para o
        # detalhamento de cada nível.
        recovered, method, resolved_selector = self._attempt_deterministic_click_recovery(
            page, selector, step_id, identity_scoped=identity_scoped
        )
        if recovered:
            if method == "fallback_selector":
                # _log_step já registra needs_review via _register_healing_for_review
                # quando status="HEALED" (Sensor F1) — não duplica a chamada aqui.
                self._log_step(step_id=step_id, action="click", selector=resolved_selector, target_description=target_description, status="HEALED", healing_method="fallback_selector")
            else:
                self._log_step(step_id=step_id, action="click", selector=selector, target_description=target_description, status="SUCCESS")
            return True

        # Nível 3/4: Self-Healing Cognitivo e Fallback por Coordenadas — pulados em modo
        # strict, pois ambos "adivinham" um alvo (via visão de IA ou coordenada histórica
        # da gravação) sem confirmar que o elemento esperado realmente existe no DOM atual.
        # Quando o elemento genuinamente não existe (ex.: fluxo quebrado por bug upstream
        # na app-alvo), essa adivinhação clica em algo errado, silenciosamente corrompendo
        # o estado da página e mascarando a causa raiz em passos subsequentes — pior do
        # que uma falha limpa e rastreável neste passo. Decisão compartilhada com
        # _finalize_click_success via _handle_unrecoverable_click.
        return self._handle_unrecoverable_click(page, selector, target_description, e, original_coords, step_id, strict, live_text=live_text)

    def _slugify(self, text: str) -> str:
        import unicodedata
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        text = re.sub(r'[^\w\s-]', '', text).strip().lower()
        return re.sub(r'[-\s]+', '-', text)

    # Literal de :has-text('...')/:has-text("...") em seletores Playwright.
    # Alternância de aspas simples/duplas em grupos separados; [^'"] evita
    # atravessar o fechamento da string (has-text gerado pelo sanitizer não
    # usa aspas escapadas dentro do literal).
    _HAS_TEXT_LITERAL_RE = re.compile(r""":has-text\(\s*(?:'([^']*)'|"([^"]*)")\s*\)""")

    def _extract_has_text_literal(self, selector):
        """Extrai o texto do ÚLTIMO :has-text('...') de um seletor — o mais
        interno/próximo do alvo, mesma convenção do JS do Nível 2.75 de
        _attempt_deterministic_click_recovery (que também varre e usa o
        último match). Retorna None quando o padrão não existe ou o literal
        é vazio/só espaços — nesses casos o tier de geometria ao vivo
        simplesmente não se aplica e a cadeia de fallback segue idêntica ao
        comportamento anterior (coordenada gravada continua como está)."""
        if not selector:
            return None
        matches = self._HAS_TEXT_LITERAL_RE.findall(str(selector))
        if not matches:
            return None
        single_quoted, double_quoted = matches[-1]
        text = (single_quoted or double_quoted).strip()
        return text or None

    def _click_by_live_geometry(self, page, option_text) -> bool:
        """Localiza um elemento de opção pelo texto e clica no centro do seu
        bounding rect atual (via JS), em vez de depender de coordenadas
        percentuais gravadas que ficam obsoletas quando o overlay rola/reflui
        de forma diferente da gravação original. Determinístico, sem LLM.

        Nível 1 (comportamento original, preservado byte-a-byte e tentado
        SEMPRE primeiro): procura o texto entre
        `[role='option'], .mat-option, li, .select-option` em TODO o
        documento. Cobre Angular Material (mat-select via role='option',
        mat-autocomplete via .mat-option) e listas/selects genéricos.

        Nível 2 (fallback adicional — só roda quando o Nível 1 não encontra
        nada, então nunca compete com nem regride o caminho já validado):
        alguns autocompletes renderizam as opções como `div` puro, sem
        classe/role reconhecível pelo Nível 1. Soltar um seletor `div`
        genérico no documento inteiro seria perigoso — casaria com uma
        fração enorme de qualquer página. Em vez disso, primeiro localiza um
        container que "parece" um overlay/painel/dropdown aberto (heurística
        de classe/role comum entre frameworks: overlay/panel/dropdown/menu/
        listbox, ou role listbox/menu/dialog — não exclusiva do Angular
        Material), restringe aos candidatos cujo texto realmente contém o
        alvo (distingue o painel certo quando há mais de um overlay "aberto"
        simultaneamente no DOM — caso real observado com 2 painéis
        cdk-overlay-pane coexistindo), prioriza o mais específico (texto mais
        curto) e só então busca QUALQUER elemento folha dentro DESSE
        container cujo texto bate — nunca no documento inteiro. Se nenhum
        container "parecer" aberto, ou nenhum candidato contiver o
        texto-alvo, ou nenhuma folha bater, retorna null e o método cai para
        False como sempre fez."""
        try:
            rect = page.evaluate(
                """(text) => {
                    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                    const target = norm(text);
                    const isVisible = e => {
                        const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    };

                    // Nivel 1: comportamento original, tentado sempre primeiro.
                    const sel = "[role='option'], .mat-option, li, .select-option";
                    const els = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                    let el = els.find(e => norm(e.textContent) === target)
                        || els.find(e => norm(e.textContent).includes(target));

                    // Nivel 2: fallback escopado a um container de overlay/painel
                    // aberto, só tentado quando o Nivel 1 não achou nada.
                    if (!el) {
                        const containerSel = "[class*='overlay'], [class*='panel'], [class*='dropdown'], [class*='menu'], [class*='listbox'], [role='listbox'], [role='menu'], [role='dialog']";
                        let containers = Array.from(document.querySelectorAll(containerSel))
                            .filter(c => isVisible(c) && !/backdrop/i.test(c.className || ''));

                        // Restringe aos containers cujo texto contém o alvo -- é
                        // o que distingue o painel certo quando mais de um
                        // overlay está "aberto" ao mesmo tempo no DOM.
                        const withMatch = containers.filter(c => norm(c.textContent).includes(target));
                        if (withMatch.length) containers = withMatch;

                        // Entre os candidatos restantes, prioriza o de texto mais
                        // curto (mais específico, mais próximo de ser o próprio
                        // painel de opções, não um wrapper amplo da página).
                        containers.sort((a, b) => norm(a.textContent).length - norm(b.textContent).length);

                        for (const container of containers) {
                            const leaves = Array.from(container.querySelectorAll('*'))
                                .filter(node => isVisible(node) && node.children.length === 0);
                            const found = leaves.find(e => norm(e.textContent) === target)
                                || leaves.find(e => norm(e.textContent).includes(target));
                            if (found) { el = found; break; }
                        }
                    }

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
                                timeout=5000, step_id=None, strict: bool = False) -> bool:
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

        is_flaky_step = self.flaky_step_ids.get(step_id, False)
        flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4

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
        # Re-semantização de `strict` (A5): este é o tier 3 (coordenada
        # gravada) — sob strict=True a cadeia deve parar nos tiers 1-2
        # (seletores determinísticos + geometria ao vivo), sem tentar
        # coordenada nem cognitivo. Antes desta guarda, `strict` não era
        # consultado aqui, contradizendo o contrato já aplicado em
        # click_resilient/fill_resilient.
        if not trigger_clicked and not strict and original_coords_trigger and len(original_coords_trigger) == 2:
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
        healed_via_fallback = None
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
        # Re-semantização de `strict` (A5): tier 3 (coordenada gravada) —
        # bloqueado sob strict=True, mesmo contrato do fallback do trigger
        # acima. A mecânica flaky (`not (is_flaky_step and attempt <= 3)`)
        # continua intocada, avaliada em paralelo (não substituída).
        if not option_clicked and not strict and original_coords_option and len(original_coords_option) == 2 and not (is_flaky_step and self.current_row_flaky_attempt <= 3):
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
                    healed_via_fallback = "coordinate"
                else:
                    print(f"[AEGIS RUNNER] Coordenada de fallback ({x}, {y}) não corresponde a '{option_text}' (encontrado: {normalized_hit!r}). Clique descartado.")
            except Exception as e:
                print(f"[AEGIS RUNNER] Falha ao clicar nas coordenadas da opção: {e}")

        # Se falhou, aciona o Cognitive Gateway se ativo (pulado em modo strict:
        # a opção certa depende do dropdown certo ter sido aberto/identificado
        # corretamente, e IA visual não confirma essa identidade, só "acha"
        # texto parecido na tela — mesmo risco de adivinhação do click_chained).
        if not option_clicked and (strict or is_flaky_step) and not flaky_healing_unlocked:
            print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ao selecionar '{option_text}' em '{dropdown_label}' (self-healing desativado para este passo).")
        elif not option_clicked and self.cognitive.is_active():
            print(f"[AEGIS RUNNER] Falha nas tentativas normais. Acionando Self-Healing Cognitivo para a opção...")
            option_target_description = f"Opção {option_text} do dropdown {dropdown_label}"
            option_selector_desc = f"[role='option']:has-text('{option_text}')"
            try:
                # Tenta localizar visualmente o texto da opção na tela — contrato
                # proposto→verificado (.specs/plano-cauda-longa-verificada.md
                # Seção 4.B1/A4/A1): propõe, gate de plausibilidade pré-clique,
                # clica só se plausível, e verifica o efeito pós-clique antes de
                # reportar HEALED.
                proposal = self.cognitive.self_healing_click(
                    page,
                    selector=option_selector_desc,
                    target_description=option_target_description,
                    original_coords=original_coords_option,
                    expected_effect=f"Após o clique, a opção '{option_text}' deve ser selecionada e o painel de opções deve fechar.",
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], option_target_description, original_selector=option_selector_desc):
                    before_snapshot = self._capture_click_effect_snapshot(page)
                    page.mouse.click(proposal["x"], proposal["y"])
                    time.sleep(0.2)
                    panel_closed = page.locator(self._OPEN_PANEL_SELECTOR).count() == 0
                    if self._verify_action_effect(page, before_snapshot, expected={"panel_closed_confirmed": panel_closed}):
                        option_clicked = True
                        healed_via_fallback = "visual_ai"
                    else:
                        print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva para a opção '{option_text}' não produziu efeito verificável (painel não fechou/valor não comitado).")
                elif proposal:
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva para a opção '{option_text}' rejeitada pelo gate de plausibilidade (pré-clique).")
            except Exception as ia_err:
                print(f"[COGNITIVE WARNING] Erro no self-healing cognitivo para opção: {ia_err}")

        if option_clicked:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.3)
            except Exception:
                pass
            if healed_via_fallback:
                self._log_step(step_id=step_id, action="select_option", selector=f"[role='option']:has-text('{option_text}')", target_description=f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", status="HEALED", healing_method=healed_via_fallback)
            else:
                self._log_step(step_id=step_id, action="select_option", selector=f"[role='option']:has-text('{option_text}')", target_description=f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", status="SUCCESS")
            return True
        else:
            msg = f"Não foi possível selecionar a opção '{option_text}' no dropdown '{dropdown_label}'."
            print(f"[AEGIS RUNNER] ❌ {msg}")
            self._log_step(step_id=step_id, action="select_option", selector=f"[role='option']:has-text('{option_text}')", target_description=f"Selecionar '{option_text}' no dropdown '{dropdown_label}'", status="FAILED", error_msg=msg)
            if is_flaky_step and self.current_row_flaky_attempt <= 3:
                raise FlakyStepFailure(step_id, f"[role='option']:has-text('{option_text}')", RuntimeError(msg))
            raise RuntimeError(msg)

    def select_option_native_resilient(self, page, selector, option_text, target_description, timeout=5000, step_id=None, strict: bool = False) -> bool:
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

            is_flaky_step = self.flaky_step_ids.get(step_id, False)
            flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4
            if (strict or is_flaky_step) and not flaky_healing_unlocked:
                if is_flaky_step and self.current_row_flaky_attempt <= 3:
                    self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                    raise FlakyStepFailure(step_id, selector, e)
                print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ao selecionar '{option_text}' em '{selector}' (self-healing desativado para este passo).")
                self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise e
            elif self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Falha padrão ao selecionar '{option_text}' em '{selector}'. Acionando localização visual por screenshot...")
                # Contrato proposto→verificado: propõe, gate de plausibilidade
                # pré-clique, clica só se plausível. A ação em si (o clique
                # visual não seleciona nada) é apenas revelar/focar o <select>
                # nativo — a verificação real é o próprio select_option()
                # abaixo: se ele levantar, cai em FAILED limpo (degrada sem
                # corromper, menor classe de risco entre os 6 call sites —
                # .specs/plano-cauda-longa-verificada.md Seção 4.B3).
                proposal = self.cognitive.self_healing_click(
                    page, selector, target_description,
                    expected_effect="O elemento <select> deve ficar visível/focado para permitir a seleção da opção.",
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], target_description, original_selector=selector):
                    try:
                        page.mouse.click(proposal["x"], proposal["y"])
                    except Exception:
                        pass
                    try:
                        page.locator(selector).first.select_option(label=option_text, timeout=timeout)
                        self._log_step(step_id=step_id, action="select_native", selector=selector, target_description=target_description, status="HEALED", healing_method="visual_ai")
                        return True
                    except Exception:
                        pass
                elif proposal:
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva para '{selector}' rejeitada pelo gate de plausibilidade (pré-clique).")
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

    def _reduce_parent_has_text(self, page, parent_selector: str, has_text: str, child_selector: str):
        """
        Recuperação determinística pra `parent.has_text` gravado com texto que
        cruza fronteira de elemento (recorder captura o innerText do container
        já colapsado em espaços e truncado em 40 chars — ex.:
        "Valor de Liquidação (R$) BRL Vencimento ", onde "(R$)", "BRL" e
        "Vencimento" são elementos irmãos): Playwright `filter(has_text=...)`
        nunca casa esse literal (0 match por construção, verificado live no
        piloto fimm_billing 2026-07-14), derrubando click_chained/fill_chained
        pra self-healing cognitivo em toda execução.

        Corta tokens do FIM do literal, um a um, e retorna o primeiro prefixo
        cujo CHILD resolvido através dos parents filtrados é EXATAMENTE 1
        elemento. A unicidade é exigida no ALVO (child), não no parent:
        containers aninhados da mesma classe (ex.: `.grid` dentro de `.grid`)
        fazem o mesmo texto casar 2+ parents ancestrais legitimamente (medido
        live: 2 parents, child único), enquanto a ambiguidade PERIGOSA — duas
        linhas irmãs com o mesmo prefixo, cada uma com seu child — aparece
        como child_count > 1 e aborta na hora em vez de arriscar a linha
        errada. Retorna None quando nenhuma redução com alvo único existe (a
        cadeia de fallback segue idêntica ao comportamento anterior).
        """
        tokens = (has_text or "").split()
        if len(tokens) < 2:
            return None
        for cut in range(1, len(tokens)):
            candidate = " ".join(tokens[:-cut])
            if len(candidate) < 3:
                return None
            try:
                child_count = int(
                    page.locator(parent_selector)
                    .filter(has_text=candidate)
                    .locator(child_selector)
                    .count()
                )
            except Exception:
                return None
            if child_count == 1:
                return candidate
            if child_count > 1:
                # Alvo ambíguo — prefixo mais curto só fica MAIS ambíguo. Aborta.
                return None
        return None

    def _retry_chained_with_reduced_parent(self, page, parent: dict, child_sel_clean: str,
                                           action: str, timeout: int, text_val: str = None,
                                           strategy: str = "DIRECT", delay_ms: int = 60) -> bool:
        """
        Retenta UMA vez o gesto encadeado (click ou fill) com o parent
        re-filtrado pelo has_text reduzido por `_reduce_parent_has_text`.
        Camada determinística — roda ANTES do self-healing cognitivo (e é
        permitida mesmo sob strict, mesma regra dos fallback_selectors: não é
        palpite, é o mesmo parent com filtro validado único no DOM ao vivo).
        Retorna True se o gesto completou; False devolve o fluxo pra cadeia
        de fallback existente, intacta.
        """
        reduced = self._reduce_parent_has_text(
            page, parent.get("selector", ""), parent.get("has_text"), child_sel_clean
        )
        if not reduced:
            return False
        print(
            f"[AEGIS RUNNER] Parent has_text '{parent.get('has_text')}' sem match "
            f"(texto cruza elementos?). Retentando com filtro reduzido único: '{reduced}'..."
        )
        try:
            # O child é resolvido pela UNIÃO dos parents filtrados (nunca
            # parent.first): containers aninhados fazem o prefixo casar 2+
            # parents ancestrais e o child pode não estar sob o PRIMEIRO da
            # lista — a unicidade já foi validada no child pelo redutor.
            target = (
                page.locator(parent["selector"])
                .filter(has_text=reduced)
                .locator(child_sel_clean)
                .first
            )
            if action == "click":
                target.wait_for(state="visible", timeout=timeout)
                target.scroll_into_view_if_needed(timeout=timeout)
                target.click(timeout=timeout, force=True)
                return True
            # fill
            if strategy == "HUMAN_LIKE":
                target.click(timeout=timeout)
                target.press("Control+A")
                target.press("Backspace")
                time.sleep(0.1)
                for char in (text_val or ""):
                    page.keyboard.type(char)
                    time.sleep(delay_ms / 1000.0)
                page.evaluate("""() => {
                    const el = document.activeElement;
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")
            else:
                try:
                    target.fill(text_val or "", timeout=timeout)
                except Exception as fill_err:
                    if "Malformed value" not in str(fill_err):
                        raise
                    # Input nativo com formato interno estrito (ex.:
                    # type="date" exige ISO no fill(), mas a UI localizada
                    # aceita dd/mm/aaaa digitado): preenche via teclado, do
                    # mesmo jeito que o gesto humano gravado fez.
                    print(f"[AEGIS RUNNER] fill() rejeitou o valor ({fill_err}). Digitando via teclado no mesmo alvo...")
                    target.click(timeout=timeout)
                    target.press("Control+A")
                    target.press("Backspace")
                    page.keyboard.type(text_val or "", delay=30)
            return True
        except Exception as retry_err:
            print(f"[AEGIS RUNNER] Retentativa com parent reduzido também falhou: {retry_err}")
            return False

    def click_chained(self, page, parent: dict, child: dict, target_description: str,
                      timeout: int = 5000, original_coords: tuple = None, step_id=None, strict: bool = False) -> bool:
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
        # Selector plano (sem os colchetes de log de has_text, que não são
        # sintaxe CSS válida) usado apenas nos níveis determinísticos de
        # _handle_click_failure — reaproveita child_sel_clean (relativizado)
        # em vez do child.selector bruto/absoluto gravado.
        query_selector = f"{parent.get('selector','')} >> {child_sel_clean}"

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
                    # Camada determinística: parent.has_text gravado com texto
                    # cruzando elementos (0 match por construção) — tenta o
                    # filtro reduzido único antes de escalar pra cadeia de
                    # falha (que termina em cognitivo/coordenada).
                    if parent.get("has_text") and self._retry_chained_with_reduced_parent(
                        page, parent, child_sel_clean, "click", timeout
                    ):
                        self._log_step(step_id=step_id, action="click_chained", selector=selector_full,
                                       target_description=target_description, status="HEALED",
                                       healing_method="parent_has_text_reduced")
                        self._register_healing_for_review(step_id, selector_full, "click", "parent_has_text_reduced")
                        return True
                    return self._handle_click_failure(
                        page,
                        query_selector,
                        target_description, timeout, e, original_coords, step_id=step_id, strict=strict,
                        identity_scoped=bool(parent.get("has_text")),
                        # Nível 3.5 (geometria DOM ao vivo por texto): extrai o
                        # literal do :has-text('...') do seletor do FILHO (o
                        # alvo real do clique — ex. div:has-text('Creta') de um
                        # painel de autocomplete). Tenta primeiro o seletor já
                        # relativizado (o que o runner de fato usa) e cai para
                        # o seletor bruto gravado caso a relativização tenha
                        # descartado o segmento com o texto. None quando não há
                        # texto extraível — o tier então não se aplica e a
                        # cadeia segue idêntica ao comportamento anterior.
                        live_text=(
                            self._extract_has_text_literal(child_sel_clean)
                            or self._extract_has_text_literal(child.get("selector", ""))
                        ),
                    )

        return False

    def fill_chained(self, page, parent: dict, child: dict, text_val: str,
                     target_description: str, strategy: str = "DIRECT",
                     delay_ms: int = 60, timeout: int = 5000, step_id=None, strict: bool = False) -> bool:
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
            # Camada determinística (antes de strict/cognitivo — mesma regra
            # dos fallback_selectors): parent.has_text cruzando elementos →
            # retenta com filtro reduzido validado único no DOM.
            if parent.get("has_text") and self._retry_chained_with_reduced_parent(
                page, parent, child_sel_clean, "fill", timeout,
                text_val=text_val, strategy=strategy, delay_ms=delay_ms
            ):
                self._log_step(step_id=step_id, action="fill_chained", selector=selector_full,
                               target_description=target_description, status="HEALED",
                               healing_method="parent_has_text_reduced")
                self._register_healing_for_review(step_id, selector_full, "fill", "parent_has_text_reduced")
                return True
            is_flaky_step = self.flaky_step_ids.get(step_id, False)
            flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4
            if (strict or is_flaky_step) and not flaky_healing_unlocked:
                if is_flaky_step and self.current_row_flaky_attempt <= 3:
                    self._log_step(step_id=step_id, action="fill_chained", selector=f"{parent_repr} >> {child_sel_clean}", target_description=target_description, status="FAILED", error_msg=str(e))
                    raise FlakyStepFailure(step_id, selector_full, e)
                print(f"[AEGIS RUNNER] [STRICT] Falha definitiva em '{selector_full}' (self-healing desativado para este passo, pai é identificado por has_text).")
            elif self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Acionando self-healing cognitivo para fill_chained...")
                # fill usa `propose_fill_target` (método análogo de fill, não
                # o de clique) — contrato proposto→verificado: propõe, gate
                # de plausibilidade pré-clique, foca o alvo proposto (clique
                # físico só pra garantir foco, não é o gesto verificado),
                # digita, e só reporta HEALED se o valor lido do campo bater
                # com o esperado (.specs/plano-cauda-longa-verificada.md
                # Seção 4.B3 — sem isso, `if clicked:` digitaria em
                # document.activeElement sem foco garantido, corrompendo o
                # dado silenciosamente).
                proposal = self.cognitive.propose_fill_target(
                    page, child_sel_clean, target_description,
                    expected_effect=f"O campo deve ficar focado e, após digitar, exibir o valor '{text_val}'.",
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], target_description, original_selector=child_sel_clean):
                    page.mouse.click(proposal["x"], proposal["y"])
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(text_val)
                    actual_value = page.evaluate(
                        "() => { const active = document.activeElement; "
                        "return active ? (active.value !== undefined ? active.value : active.textContent) : null; }"
                    )
                    if self._verify_action_effect(page, None, expected={"kind": "fill", "expected_value": text_val, "actual_value": actual_value}):
                        self._log_step(step_id=step_id, action="fill_chained", selector=f"{parent_repr} >> {child_sel_clean}", target_description=target_description, status="HEALED", healing_method="visual_ai")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Preenchimento cognitivo em fill_chained não confirmado pelo valor lido do campo.")
                elif proposal:
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva de preenchimento (fill_chained) rejeitada pelo gate de plausibilidade (pré-clique).")
            self._log_step(step_id=step_id, action="fill_chained", selector=f"{parent_repr} >> {child_sel_clean}", target_description=target_description, status="FAILED", error_msg=str(e))
            raise e

    def fill_resilient(self, page, selector, text_val, target_description,
                       strategy="DIRECT", delay_ms=60, timeout=5000, step_id=None, strict: bool = False) -> bool:
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
                self._recent_fills.append({'selector': selector, 'text_val': text_val, 'strategy': strategy, 'step_id': step_id, 'target_description': target_description})
            return res

        try:
            print(f"[AEGIS RUNNER] Tentando preenchimento físico em '{selector}'...")
            page.locator(selector).fill(text_val, timeout=timeout)
            self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="SUCCESS")
            self._recent_fills.append({'selector': selector, 'text_val': text_val, 'strategy': strategy, 'step_id': step_id, 'target_description': target_description})
            return True
        except Exception as e:
            # A3 (.specs/plano-cauda-longa-verificada.md Seção 4.A3): mesma
            # doutrina de verificação do click — o fallback pra '.first' só
            # fecha como HEALED quando o valor lido do campo confirma o
            # preenchimento, nunca mais SUCCESS silencioso na troca de alvo.
            if "strict mode violation" in str(e) or "resolved to" in str(e):
                try:
                    print(f"[AEGIS RUNNER] Múltiplos elementos encontrados para '{selector}'. Tentando preencher o primeiro...")
                    t2_fill_locator = page.locator(selector).first
                    t2_fill_locator.fill(text_val, timeout=timeout)
                    if self._verify_action_effect(page, None, expected={"kind": "fill", "expected_value": text_val, "locator": t2_fill_locator}):
                        self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="HEALED", healing_method="ambiguous_candidate_verified")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Preenchimento em fallback '.first' de '{selector}' não confirmado pelo valor lido do campo. Prosseguindo para a cadeia de recuperação existente...")
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

            # Nível 2.9 (M5): Fallback de seletores determinísticos gravados na captura
            # (mesma semântica de click_resilient/_handle_click_failure — ver comentário
            # lá). fill_resilient não tem parâmetro strict, então este nível roda sempre
            # que houver fallbacks disponíveis para o passo, antes da checagem flaky.
            fallback_selectors = self.fallback_selectors_by_step.get(step_id, []) if hasattr(self, "fallback_selectors_by_step") else []
            if fallback_selectors:
                fallback_resolved = False
                for fb_selector in fallback_selectors:
                    try:
                        print(f"[AEGIS RUNNER] [FALLBACK SELECTOR] Tentando preencher seletor alternativo gravado: '{fb_selector}'...")
                        page.locator(fb_selector).first.fill(text_val, timeout=2000)
                        # _log_step já registra needs_review via _register_healing_for_review
                        # quando status="HEALED" (Sensor F1) — não duplica a chamada aqui.
                        self._log_step(step_id=step_id, action="fill", selector=fb_selector, target_description=target_description, status="HEALED", healing_method="fallback_selector")
                        fallback_resolved = True
                        break
                    except Exception:
                        continue
                if fallback_resolved:
                    return True

            is_flaky_step = self.flaky_step_ids.get(step_id, False)
            flaky_healing_unlocked = is_flaky_step and self.current_row_flaky_attempt >= 4
            if (strict or is_flaky_step) and not flaky_healing_unlocked:
                if is_flaky_step and self.current_row_flaky_attempt <= 3:
                    self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                    raise FlakyStepFailure(step_id, selector, e)
                print(f"[AEGIS RUNNER] [STRICT] Falha definitiva ao preencher '{selector}' (self-healing desativado para este passo).")
                self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="FAILED", error_msg=str(e))
                raise e
            elif self.cognitive.is_active():
                print(f"[AEGIS RUNNER] Falha no preenchimento padrão de '{selector}'. Acionando localização visual por screenshot...")
                # Contrato proposto→verificado (fill_resilient é a rota de
                # fill DEFAULT — maior prioridade de risco, .specs/plano-
                # cauda-longa-verificada.md Seção 4.B3): propõe via
                # `propose_fill_target`, gate de plausibilidade pré-clique,
                # foca o alvo proposto, digita, e só reporta HEALED se o
                # valor lido do campo bater com o esperado.
                proposal = self.cognitive.propose_fill_target(
                    page, selector, target_description,
                    expected_effect=f"O campo deve ficar focado e, após digitar, exibir o valor '{text_val}'.",
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], target_description, original_selector=selector):
                    page.mouse.click(proposal["x"], proposal["y"])
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(text_val)
                    page.evaluate("() => { const active = document.activeElement; if (active) { active.dispatchEvent(new Event('input', { bubbles: true })); active.dispatchEvent(new Event('change', { bubbles: true })); } }")
                    actual_value = page.evaluate(
                        "() => { const active = document.activeElement; "
                        "return active ? (active.value !== undefined ? active.value : active.textContent) : null; }"
                    )
                    if self._verify_action_effect(page, None, expected={"kind": "fill", "expected_value": text_val, "actual_value": actual_value}):
                        self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="HEALED", healing_method="visual_ai")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Preenchimento cognitivo em '{selector}' não confirmado pelo valor lido do campo.")
                elif proposal:
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva de preenchimento para '{selector}' rejeitada pelo gate de plausibilidade (pré-clique).")
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

            # click(force=True) abaixo ignora a checagem de actionability nativa
            # do Playwright (inclusive "enabled") — necessário pra campos que o
            # Playwright julga erroneamente "não estáveis" (animação/transição
            # CSS). Efeito colateral: também ignora um campo genuinamente
            # desabilitado por busca assíncrona em andamento (ex.: auto-fill de
            # nome disparado pelo preenchimento do CPF, que deixa o campo
            # disabled por alguns segundos) — sem esperar isso, o robô digita
            # num campo bloqueado e o valor é sobrescrito/descartado quando a
            # resposta assíncrona chega. Poll limitado por is_enabled() antes
            # do force-click cobre esse caso sem reintroduzir o problema de
            # estabilidade que o force=True resolve.
            wait_budget_ms = min(timeout, 8000)
            waited_ms = 0
            while waited_ms < wait_budget_ms:
                try:
                    if element.is_enabled():
                        break
                except Exception:
                    pass
                page.wait_for_timeout(200)
                waited_ms += 200

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
                # fill_human_like é a rota de digitação DEFAULT sob
                # HUMAN_LIKE (não edge case) — mesma migração dos demais
                # fills: propõe, gate de plausibilidade pré-clique, foca,
                # digita, e só reporta HEALED com o valor verificado.
                proposal = self.cognitive.propose_fill_target(
                    page, selector, target_description,
                    expected_effect=f"O campo deve ficar focado e, após digitar, exibir o valor '{text_val}'.",
                )
                if proposal and self._hit_test_plausible(page, proposal["x"], proposal["y"], target_description, original_selector=selector):
                    import time as _t2
                    page.mouse.click(proposal["x"], proposal["y"])
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    for char in str(text_val):
                        page.keyboard.press(char)
                        _t2.sleep(delay_ms / 1000.0)
                    actual_value = page.evaluate(
                        "() => { const active = document.activeElement; "
                        "return active ? (active.value !== undefined ? active.value : active.textContent) : null; }"
                    )
                    if self._verify_action_effect(page, None, expected={"kind": "fill", "expected_value": text_val, "actual_value": actual_value}):
                        self._log_step(step_id=step_id, action="fill", selector=selector, target_description=target_description, status="HEALED", healing_method="visual_ai")
                        return True
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Preenchimento cognitivo HUMAN_LIKE em '{selector}' não confirmado pelo valor lido do campo.")
                elif proposal:
                    print(f"[AEGIS RUNNER] [VERIFY_REJECTED] Proposta cognitiva de preenchimento HUMAN_LIKE para '{selector}' rejeitada pelo gate de plausibilidade (pré-clique).")
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

        # Mapa step_id -> flaky derivado do plano de execução (default False se ausente)
        self.flaky_step_ids = {s['step_id']: s.get('flaky', False) for s in self.execution_plan['steps']} if self.execution_plan else {}
        # Mapa step_id -> fallback_selectors (M5): seletores alternativos gravados
        # na captura (cascata de estratégias distintas, validados por unicidade no
        # DOM no momento da gravação). Usado como novo nível determinístico na
        # cadeia de resiliência de click_resilient/fill_resilient, entre a
        # heurística determinística atual e o fallback cognitivo.
        self.fallback_selectors_by_step = {s['step_id']: s.get('fallback_selectors', []) for s in self.execution_plan['steps']} if self.execution_plan else {}
        # Tentativa atual da linha em execução para passos flaky. Valor default de
        # segurança; resetado por linha dentro do loop de run() por outra tarefa.
        self.current_row_flaky_attempt = 1

        print("\n" + "=" * 80)
        print("🛡️ AEGIS RUNNER LIBRARY: EXECUTANDO LOOP TRANSACIONAL EM LOTE")
        print("=" * 80)
        
        # 1. Carrega o dataset do projeto
        dataset = self._load_dataset()
        print(f"[AEGIS RUNNER] Total de transações carregadas: {len(dataset)}")
        
        reports = []
        
        # Inicia o Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless, slow_mo=slow_mo, channel=channel,
                args=[
                    "--disable-features=Translate,TranslateUI",
                    "--disable-translate",
                    "--lang=pt-BR",
                ]
            )
            context = browser.new_context(locale="pt-BR")
            page = None
            
            for idx, row in enumerate(dataset):
                row_id = row.get("id", str(idx + 1))
                # Reinicia o contador de tentativas flaky no início de cada linha do
                # dataset. O laço abaixo permite reiniciar a transação COMPLETA da
                # linha (página/contexto novo + histórico de steps do zero) até 3
                # vezes quando um passo flaky falha em modo strict; a 4ª tentativa
                # roda sem restart posterior (self-healing liberado internamente
                # pelos métodos resilientes).
                self.current_row_flaky_attempt = 1
                while self.current_row_flaky_attempt <= 4:
                    # Cria uma nova página para cada transação/tentativa para garantir isolamento
                    # total e evitar que erros/diálogos abertos/quedas de página afetem
                    # transações subsequentes.
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
                            break

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
                        # Achado real (.specs/relatorio-piloto-site-novo.md): sem
                        # `project.json` (raiz OU pasta do teste) com campo "url",
                        # esse fallback silencioso apontava o robô pro Portal
                        # Segura em outro projeto sem nenhum erro visível --
                        # confundível com "está tudo certo". Agora avisa alto.
                        target_url = "http://localhost:5173/?e2e=true" # Fallback local
                        print(
                            f"[AEGIS RUNNER] [WARNING] Nenhuma URL configurada (nem argumento, nem project.json "
                            f"em '{self.project_dir}' ou na raiz do projeto) — usando fallback hardcoded "
                            f"'{target_url}'. Confirme se este é o site pretendido; provavelmente falta "
                            f"o campo \"url\" no project.json do teste."
                        )
                        sys.stdout.flush()

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

                        # Transação da linha concluída (com ou sem bloqueio de negócio
                        # esperado) sem levantar exceção: encerra o laço de restart.
                        break

                    except FlakyStepFailure as flaky_err:
                        # Um passo marcado como flaky falhou em modo strict dentro das
                        # primeiras 3 tentativas da linha. Reinicia a transação completa
                        # da linha (nova página/contexto + histórico do zero) em vez de
                        # registrar falha definitiva.
                        if self.current_row_flaky_attempt < 4:
                            print(f"[AEGIS RUNNER] [FLAKY RETRY] Passo '{flaky_err.step_id}' falhou na tentativa {self.current_row_flaky_attempt} da linha {row_id}. Reiniciando transação da linha...")
                            self.current_row_flaky_attempt += 1
                            continue
                        # Defensivo/inalcançável por design: a lógica dos métodos
                        # resilientes garante que FlakyStepFailure só é levantada quando
                        # current_row_flaky_attempt <= 3 — na 4ª tentativa o passo flaky
                        # cai no self-healing em vez de relançar essa exceção. Mantido
                        # como rede de segurança para registrar a falha definitiva da
                        # linha exatamente como o bloco de exceção genérico abaixo faria.
                        e = flaky_err
                        self._mark_remaining_stopped()
                        duration = round(time.time() - start_time, 2)

                        failed_field = flaky_err.selector or "Unknown"
                        reports.append({
                            "id": row_id,
                            "aegis_scenario": scenario,
                            "status": "SYSTEM_FAILED",
                            "error_message": str(e).replace('\n', ' ').strip(),
                            "failed_field": failed_field,
                            "extracted_value": "None",
                            "duration_seconds": duration
                        })
                        print(f"[AEGIS_TRANSACTION] FAILED | {row_id}")
                        sys.stdout.flush()
                        break

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
                        break

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
