# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies and browser
pip install -r requirements.txt
playwright install chromium

# Start the Cockpit orchestrator UI (default port 8075)
python aegis_cockpit/cockpit.py

# Phase 1: Record a browser session (BlackBox)
python aegis_blackbox/recorder.py --url "https://target.url" --output-dir "projects/seu_projeto" --control-port 9900

# Phase 2: Sanitize telemetry (Sanitizer)
python aegis_sanitizer/sanitizer.py --project-dir projects/seu_projeto

# Phase 3: Validate dataset (Firewall)
python aegis_sanitizer/dataset_validator.py --dataset projects/seu_projeto/dataset_inicial.json --project-dir projects/seu_projeto

# Phase 4: Generate bot code (Code Generator — requires LLM API key)
python aegis_code_generator/code_generator.py --project-dir projects/seu_projeto

# Phase 5: Run the generated bot
python projects/seu_projeto/bot_producao.py

# Visual verification (compare recorder screenshot vs bot output)
python aegis_runner/verify_visual.py --project-dir projects/seu_projeto

# DevOps pipeline publish
python aegis_devops/publish_pipeline.py --project-slug seu_projeto

# Run tests
python aegis_runner/test_runner_integration.py
python aegis_runner/test_cognitive_fallback.py
```

## Architecture

The Aegis RPA Suite is a 5-phase pipeline for building resilient Playwright+Python web automation bots. Its core principle is **complete decoupling of design-time (IA-assisted) and run-time (deterministic, zero-LLM)** — bots execute without any runtime AI calls by default.

### Core Modules (Design-Time)

| Module | Role |
|---|---|
| `aegis_blackbox/recorder.py` | Injects JS listeners into a headed browser. Captures clicks, fills, selectors, and network payloads into `gravacao.json` + `dicionario.json`. |
| `aegis_sanitizer/sanitizer.py` | Deduplicates and classifies recorder telemetry (schema v2 — classifies, never deletes). Produces `relatorio.md` (human+LLM-readable), rewrites `gravacao.json` with every event tagged (`sanitizer_class`, `original_index`), and compiles `plano_execucao.json` (`st_`/`sup_` id spaces, `execution_hint`, `fidelity_summary`). |
| `aegis_sanitizer/dataset_validator.py` | Validates `dataset_inicial.json`/`.csv` against the data dictionary. Tolerant — only blocks critical structural errors. |
| `aegis_code_generator/code_generator.py` | Compiles `bot_producao.py` + `skills_lib.py`. Two flows: **new generation** (hybrid deterministic+cognitive by default, see `deterministic_emitter.py` below, with full-LLM as fallback/legacy path) and **surgical correction** (targeted fix of specific steps using `# [PASSO X]` anchors). Calls an LLM (Gemini/OpenRouter) only for cognitive slots or full-LLM generation; uses `AEGIS_COGNITIVE_CODER_MODEL` if set. |
| `aegis_code_generator/deterministic_emitter.py` | Zero-LLM emitter powering the hybrid new-generation flow — the inversion of `step_validator.py`'s checks: instead of rejecting a missing resilience pattern, it produces it mechanically. `classify_step` applies ten conservative conditions (C1-C10) per plan step (supported type, unambiguous dictionary binding, no Padrão Q dynamic token, `weak_selector` anchor present, outside the Padrão N menu heuristic, no pending correction targeting the step, `fill` not preceding an autocomplete panel, no dictionary `observed_value` hardcoded in the selector) and routes each step to `deterministic` (emitted directly via `emit_step_block`), `cognitive` (LLM slot placeholder), or `omit` (`sup_`/`skip` steps). `build_skeleton` assembles the function body plus the `generation_manifest.json` provenance map. |
| `aegis_mentor/skills/` | LLM skill prompts defining the resilience pattern catalog used during code generation. |

### Core Modules (Run-Time)

| Module | Role |
|---|---|
| `aegis_runner/runner.py` | `TransactionRunner` class: the deterministic execution engine. Iterates over a dataset, creates an isolated Playwright page per row, and runs registered scenario callbacks. Provides `click_resilient`, `fill_resilient`, `fill_human_like`, `select_option_resilient`, and `wait_for_selector`. Logs all steps to `[AEGIS_STEP]` and writes `historico_passos.json` + CSV report. |
| `aegis_runner/cognitive_fallback.py` | `CognitiveGateway`: optional LLM-powered self-healing layer. When `AEGIS_COGNITIVE_ENABLED=true`, it can visually locate elements via screenshot→LLM coordinate detection — `self_healing_click`/`propose_fill_target` return a **proposal** (`{x, y, reason, confidence}` or `None`; never click/type directly, see "Cauda Longa Verificada" below), diagnose failures multimodally (`diagnose_failure`), transcribe audio, and compare visual screenshots. Supports OpenRouter, LiteLLM, and any OpenAI-compatible endpoint. Loads `.env` from the project tree and framework root. |

### Orchestration

| Module | Role |
|---|---|
| `aegis_cockpit/cockpit.py` | Flask-like HTTP server (custom `http.server`). Serves the SPA frontend (`static/index.html`) and exposes a REST API for project/test management. Routes requests to `ProjectManager` and `ProcessManager`. |
| `aegis_cockpit/project_manager.py` | Manages the workspace: project CRUD, scenario CRUD, version history, corrections accumulation (`correcoes_acumuladas.json`), skill management, DevOps config. |
| `aegis_cockpit/process_manager.py` | Spawns child processes (Phase 1–5) via `subprocess.Popen`, streams stdout to WebSocket-like endpoints. Manages background pipeline execution. |

### DevOps Integration

| Module | Role |
|---|---|
| `aegis_devops/publisher.py` | Pushes code to Azure Repos via REST API (no local git binary needed). |
| `aegis_devops/junit_reporter.py` | Converts execution CSV reports to JUnit XML for Azure Test Plans. |
| `aegis_devops/publish_pipeline.py` | One-shot CLI to publish a project's pipeline YAML, variable groups, and test cases to Azure DevOps. |

### Project Structure (RPA Isolation)

Everything specific to an automated process lives under `projects/<slug>/`:

```
projects/<slug>/
├── .env                    # API keys and project-specific env vars
├── project.json            # Metadata (url, name, description)
├── skills/                 # Reusable skill blocks (login, address, etc.)
│   └── <skill_slug>/
├── tests/
│   └── <test_slug>/
│       ├── dataset_inicial.json   # Input data rows
│       ├── gravacao.json          # Cleaned recording telemetry
│       ├── dicionario.json        # Data dictionary
│       ├── relatorio.md           # Sanitized report
│       ├── bot_producao.py        # Generated bot (committed)
│       ├── skills_lib.py          # Compiled skills (committed)
│       ├── historico_passos.json  # Last execution audit trail
│       ├── correcoes_acumuladas.json  # Bug/fix tracking
│       └── executions/            # Historical runs with screenshots
```

**Critical rule:** Never create RPA-specific files in the framework root or inside core modules (`aegis_*`). The framework is a sealed engine. All project artifacts go into `projects/` or `telemetry_data/`.

## Configuration

### LLM / Cognitive Layer

All LLM configuration is done via environment variables, typically in a `.env` file at the project or framework root:

- `AEGIS_COGNITIVE_ENABLED=true` — enable self-healing and code generation
- `AEGIS_COGNITIVE_API_KEY` — API key for OpenRouter/LiteLLM
- `AEGIS_COGNITIVE_PROVIDER` — `openrouter` (default) or `litellm`
- `AEGIS_COGNITIVE_MODEL` — e.g., `google/gemini-2.5-flash` (general use)
- `AEGIS_COGNITIVE_CODER_MODEL` — optional dedicated model for Phase 4 code generation
- `AEGIS_COGNITIVE_BASE_URL` — override API base URL

### Hybrid Code Generation (Phase 4)

- `AEGIS_CODEGEN_HYBRID` — `true` (default) or `false`. When `true`, new-code generation runs the deterministic emitter first (`aegis_code_generator/deterministic_emitter.py`) and only calls the LLM for steps `classify_step` routes to `cognitive` (Padrão Q dynamic `has_text`, `optional`-emission decisions, Padrão N menu rewrites, fills preceding autocomplete, steps targeted by a pending correction) — a plan with zero cognitive slots makes zero LLM calls during new generation. Falls back to the full-LLM flow (whole file, previous behavior) when `false`, when the project has `skills_used`, when `plano_execucao.json` is missing, or when an LLM response doesn't cover every requested slot in a given attempt.
- `AEGIS_CODEGEN_FORCE_LLM_STEPS` — CSV of `step_id`s (e.g. `"st_004,st_017"`) forced down the cognitive/LLM path regardless of `classify_step`'s decision — for working around a misclassification in production without a code change.

### Runtime Flags

- `AEGIS_BROWSER_HEADLESS` — `true` (default) or `false` (headed/visible)
- `AEGIS_STEP_SCREENSHOTS` — `true` to capture a screenshot after each successful step
- `AEGIS_STEP_LOGS_REALTIME` — `false` to suppress `[AEGIS_STEP]` lines (large datasets)
- `AEGIS_FORCE_HUMAN_LIKE` — `true` to force keystroke-by-keystroke typing globally
- `AEGIS_EXECUTION_DIR` — output directory for execution artifacts (set by Cockpit)
- `AEGIS_EXECUTION_ID` — unique batch execution ID (set by Cockpit)

### Cockpit Config (`aegis_config.json` at project root)

```json
{
    "projects_dir": "C:\\Projetos\\aegis_rpa_suite\\projects",
    "telemetry_dir": "C:\\Projetos\\aegis_rpa_suite\\telemetry_data",
    "port": 8075
}
```

## Key Design Patterns

### Zero Hardcodes
All URLs, credentials, and API keys must be loaded via `os.getenv()`. Generated bots must raise `ValueError` if required env vars are missing. Use `.get(row_field, "")` with empty-string fallback for dataset field access.

### Step Tracking (`# [PASSO X]`)
Every automation step in generated code must be preceded by a comment like `# [PASSO X] Descrição do Passo`. The surgical correction flow (Phase 4) uses these as anchors to modify only failing steps without touching working code.

### Bot Execution Flow
Bots instantiate `TransactionRunner`, register scenario callbacks with `register_scenario()`, then call `runner.run()`. The runner creates an **isolated Playwright page per dataset row** — errors, dialogs, or crashes in one row never affect others.

### Resilience Catalog
The code generator's playbook (`aegis_mentor/skills/rpa-copilot-coder.md`) defines ~12 resilience patterns including Shadow DOM piercing (`>>`), network API interception for dynamic dropdowns, deadlock avoidance ordering, viewport evaluation for CDK overlays, async loader synchronization, date picker bypass, and file upload handling.

### Sanitizer Fidelity Contract (`plano_execucao.json` schema v2)
The Sanitizer no longer deletes anything — it classifies. Every event survives in `gravacao.json` (tagged with `sanitizer_class: {role, keep, reason}` and `original_index`, stamped before Padrão P's physical reordering); `plano_execucao.json` carries the full map of the recording using two disjoint id spaces: `st_NNN` for emittable steps (numbered in the exact same sequence the pipeline always produced — zero `step_id` drift for existing bots/`correcoes_acumuladas.json`) and `sup_NNN` for suppressed steps, merge-inserted into the array at their original physical position (never reordering the `st_` sequence). Each step carries `execution_hint`: absent or `"required"` (default — v1 plans behave identically), `"optional"`, or `"skip"`. The plan opens with `fidelity_summary` (`raw_events`, `steps_required`, `steps_optional`, `steps_suppressed`, `merges`). Merged/collapsed steps (duplicate clicks, dropdown pairs) keep their absorbed events in `merged_from`/`source_events`; suppressed steps carry `step_role` (`overlay_noise`, `stale_panel_click`, `redundant_refill`, `raw_duplicate_click`, `superseded_correction`, `phantom_click`) and `suppression_reason`. `step_validator.py`'s `validate_bot_against_plan` is hint-aware: `required` ids must appear as a subsequence in order; `optional`/`skip` ids are accepted if present and order-respecting; ids outside the plan are still `EXTRA_STEPS`. `code_generator.py` renders `sup_` steps compactly in the prompt (not full JSON) and instructs the LLM to emit one only when a pending correction or the flow genuinely needs it — always by reusing the existing `step_id`, never inventing one.

**Regra container_click (2026-07-14, piloto fimm_billing):** clique cujo seletor é tag pura de container estrutural (`nav`, `main`, `body`, `html`, `header`, `footer`, `aside`, `section` — `_GENERIC_CONTAINER_CLICK_TAGS` em `sanitizer.py`) com `confidence < 70` recebe `execution_hint: "optional"` + nota `container_click` em `sanitization_notes`. É clique de navegação em área "morta" (produto do `tagStrategy` do recorder), sem efeito de negócio — emitido, dispara `CLICK_NO_EFFECT` e escala pra self-healing caro em toda execução. Continua `st_NNN` (numeração intacta); o prompt de slots cognitivos instrui default "não emita". Gravações sem campo `confidence` nunca recebem o rebaixamento (retrocompat, mesma política do `weak_selector`).

**Âncora `:has-text` viável (emitter):** Playwright `:has-text()`/`filter(has_text=)` **nunca** casam texto que cruza fronteira de elemento — colapsar o `\n` do innerText em espaço fabrica seletor com 0 match por construção (verificado live, 2026-07-14). O recorder grava `text` como `innerText.substring(0, 50)` do alvo (`len == 50` é assinatura de truncamento, possivelmente no meio de palavra). `_viable_has_text_literal` (`deterministic_emitter.py`) reduz a um literal viável: primeira linha não vazia; linha única truncada descarta o último token; nada viável → `None`. Usado na emissão (`_emit_click`) E no C5 de `classify_step` (weak_selector sem material viável → slot cognitivo). **Gap conhecido:** `parent.has_text` de `click_chained`/`fill_chained` sofre da mesma doença — o recorder já grava colapsado em espaços + truncado em 40 chars (irrecuperável a jusante). Mitigação em runtime: `_reduce_parent_has_text`/`_retry_chained_with_reduced_parent` (`runner.py`) — no 0 match do filtro, corta tokens do fim exigindo CHILD único (unicidade no alvo, não no parent: containers aninhados casam 2+ parents legitimamente) e retenta o gesto antes de escalar pra cognitivo; permitida sob `strict` (não é palpite); `fill()` rejeitado com `Malformed value` (ex.: `input[type=date]` exige ISO) cai pra digitação via teclado no mesmo alvo. Resolução registra `HEALED`/`needs_review` com `healing_method="parent_has_text_reduced"` (Sensor F1). Fix na origem (captura) continua pendente.

### Hybrid Generation Manifest & Anti-Drift Restore
Every successful generation writes `code/generation_manifest.json` next to the bot: `generator_version` (`hybrid-1` or `full-llm`), `plan_checksum` (sha1 of the plan used for this generation — a re-sanitization that renumbers `step_id`s degrades any manifest-driven logic to a no-op instead of misfiring against a stale map), and a `provenance` entry per `step_id` (`deterministic`, `cognitive`, or `cognitive_patched` once a QA correction later touches a block that was originally emitted deterministically). The full-LLM route (flag off, `skills_used`, missing plan, or per-attempt fallback) always overwrites the manifest with `steps: {}`, so a stale hybrid manifest can never survive a non-hybrid regeneration. Inside the Ralph Loop, every retry attempt unconditionally re-splices the canonical form of any `deterministic` block that falls outside the current correction's target scope before re-validating — this is what stops a full-file reflection rewrite from silently "improving" (or corrupting) a block that was already correct by construction. The same restore also protects omission decisions: a cognitive slot whose manifest reason is `optional_omitted` (the LLM chose not to emit an optional step at slot-fill time) is restored to its canonical bloco-vazio if a later full-file reflection reintroduces real code for it — observed live (2026-07-14): the omitted `container_click` steps came back as real clicks on attempt 4 before this guard existed. The scoped-block splice also re-indents each returned block to the original block's indentation base (LLMs sometimes return blocks at column 0, which used to dedent code out of `execute_scenario_default` and abort the whole generation with `unexpected indent`). `CognitiveGateway.is_active()` is still required at the very start of generation even when the plan will resolve to zero cognitive slots — the hybrid path saves LLM calls, not the API-key/gateway requirement.

Two gaps found during the hybrid rollout's live-validation gate (H8) are deliberately out of scope and documented for future work in Section 8 of `.specs/plano-codegen-hibrido-deterministico.md`: (1) the Sanitizer doesn't yet emit dependent-autocomplete chains (e.g. Marca→Modelo→Versão) in the site's real fill→select dependency order, and `fill_human_like`'s unconditional `blur` can close a just-opened autocomplete panel — worked around per-project today via a `required_reopen` correction, not fixed at the source. (2) `EXTRA_STEPS` hard-fails a subsequent surgical QA cycle when a `required_reopen` step from an already-`applied` correction is still present in the bot — the validator's tolerance for reopen steps is keyed to the originating correction's pending/applied status, not to the step's own ongoing legitimacy.

### Self-Healing Fallback Chain — "Cauda Longa Verificada" doctrine (2026-07-15, `.specs/plano-cauda-longa-verificada.md`)

The rule is no longer "LLM yes/no" — it's "**verified** yes/no". No recovery tier (deterministic, geometry, recorded coordinate, or LLM) may report `HEALED`/`SUCCESS` without an observable post-condition (`_verify_action_effect`) confirming the action's real effect. `self_healing_click`/`propose_fill_target` no longer click/type — they return a proposal only; the runner gates it pre-action (`_hit_test_plausible` — `elementFromPoint` hit-test against `target_description`, rejects an implausible proposal *before* any physical action, zero side-effect cost) and verifies it post-action before accepting.

When `click_resilient` fails: (1) retry with Escape key to clear overlays → (2) multi-element heuristic (avoid `href="#"` anchors — **now itself verified**: with real ambiguity (2+ visible candidates) each candidate click is snapshotted and checked via `_verify_action_effect` before acceptance; verified resolution logs `healing_method="ambiguous_candidate_verified"`, not silent `SUCCESS`) → (2.9) `fallback_selectors` recorded at capture time (deterministic alternate selectors validated unique in the DOM when recorded — runs even under `strict=True` since it's not a guess) → (3) recorded coordinate fallback, **now verified and moved before the cognitive tier** (`_verify_action_effect` with the overlay caveat — see `CLICK_NO_EFFECT` below — is what makes this reorder safe; a stale coordinate landing on a CDK backdrop would otherwise trip the same generic-signal false-positive) → (4) `self_healing_click` via LLM vision, propose→gate→verify as above (blocked under `strict=True`, same as the coordinate tier — `strict=True` now means "tiers 1-2 only", not a global default flip; `strict=False` remains production default). The `.first` fallback on a Playwright "strict mode violation"/"resolved to" error (both click and fill) follows the same ambiguous-candidate verification as (2). `fill_resilient` follows the same shape: direct fill → multi-element first match (verified) → Escape clear + retry → `fallback_selectors` → LLM proposal + gate + type + verify.

Every tier that resolves a step via healing (LLM vision, coordinate, ambiguous candidate, or `fallback_selectors`) auto-registers a `needs_review` entry in `correcoes_acumuladas.json` (Sensor F1, `_register_healing_for_review` in `runner.py`) — dedup by `(action, failed_selector)` only suppresses while the pair is `needs_review`/`pending`; a pair already `resolved`/`applied` that regresses again always creates a fresh entry (regressions after a fix are never silently swallowed).

**Resolution telemetry** (aditive, `reports/telemetria_resolucao.json` written once at the end of `run()`'s batch): per-step `resolver_tier` (reuses `healing_method`, or `"identity"` for a direct `SUCCESS`) and `verify_result` in `historico_passos.json`; aggregate tier-resolution rate and `VERIFY_REJECTED` pre-click vs. post-click rate per execution — the number that validates adherence to the doctrine and informs future calibration.

**Closed Shadow DOM click (`shadowrootmode="closed"`, 2026-07-15, Portal Segura st_054):** no Playwright selector, `>>` piercing, or JS query can reach content inside a closed shadow root (`host.shadowRoot` is `null` externally; `elementFromPoint` and even `composedPath()` of a real click retarget to the HOST, never the inner element — all verified live). Selector-based tiers are therefore structurally dead for these targets; only a physical coordinate click works. Three primitives in `runner.py` handle this: `_is_closed_shadow_target` (pure heuristic: element under point has 0 children, empty `textContent`, non-trivial visible box, AND `target_description` mentions "shadow" — the description gate prevents relaxing verification for random empty divs), `_snap_to_closed_shadow_host` (radius search that corrects a recorded/AI-proposed coordinate that missed the host by a small margin — vision-model pixel guesses showed a consistent ~50px bias across runs, it's systematic, not noise), and `_probe_closed_shadow_click` (multi-point probing: the inner button's position within the host is unknowable from outside, and the host's geometric center can land on an inert inner element — confirmed live: center = dead status div, 75%-height band = the real button; probes proposed point → 75% → 50% → 25% → 87.5% bands of the live host bbox, each candidate click individually verified). Critical lesson (a first version approved `closed_shadow_click` unconditionally and produced a confirmed-live false `HEALED` that also masked a cascade — st_055-057 only "failed" because the flow never reached their screens): the real effect IS observable in light DOM (the app reflects internal state outside the shadow, e.g. success modal, domSize change) but with seconds of latency — so `kind="closed_shadow_click"` in `_verify_action_effect` uses `_poll_generic_effect_extended` (~6s polling, early-exit) and REJECTS when no signal changes; it never approves blindly. Wired into tiers 3 (recorded coordinate) and 4 (cognitive) of `_handle_unrecoverable_click`.

**Known gap (out of scope of the F1 phase above, tracked in `.specs/plano-cauda-longa-verificada.backlog.pending.md`):** `_attempt_deterministic_click_recovery`'s internal `_effect_confirmed` helper (Escape-retry/CDK-reposition/`fallback_selectors` tiers, both click and the fill-side `fallback_selectors` which has *no* verification at all today) calls `_click_effect_signals_changed` directly, bypassing `_verify_action_effect`'s overlay caveat — confirmed live against a real site (Fimm pilot, `st_007`): an ambiguous `fallback_selectors` match resolved via `.first`, the autocomplete panel never actually closed, but the step still logged `HEALED`. Not yet fixed.

### Passo Fantasma Detection (`CLICK_NO_EFFECT`)
`click_resilient` uses `force=True`, which skips Playwright's actionability check — a click on an element covered by an overlay can report `SUCCESS` with no real effect. The runner snapshots page state (URL, DOM node count ±2, overlay count, and className fingerprint of the clicked element + its direct siblings) before/after every click. When nothing changed, it no longer just logs and moves on: `click_resilient` now runs the same deterministic recovery chain used for exception-based failures (Escape+retry → reposition `.cdk-overlay-pane` + synthetic click → `fallback_selectors`) *before* closing the step, and only falls through to cognitive/coordinate fallback (blocked under `strict=True`) if none of those produce a real effect. A step recovered this way logs `HEALED` with `healing_method="click_no_effect_recovered"` and auto-registers `needs_review` via the same Sensor F1 hook as any other healing tier. Controlled by `AEGIS_CLICK_EFFECT_SENSOR` (default `true`) — `AEGIS_CLICK_EFFECT_REGISTER` no longer exists; recovery/registration is unconditional once the sensor is enabled.

### Enable-Timeout Detection (`ENABLE_TIMEOUT`)
Some clicks depend on a target that only becomes enabled after an async app-side validation (e.g. a submit button gated on a CPF lookup finishing). `_wait_for_known_disabled_button` (pre-click) and `_wait_if_wizard_transition_button` (post-click) poll any selector's enabled state (not a hardcoded list) up to a configurable timeout (default 15s). Before the physical click, `click_resilient` also tries a short (300-800ms) non-`force` click first — cheap coverage for transient overlays (toast/spinner) that a `disabled`-attribute check alone can't see. When the wait times out, `_recover_via_recent_fills` replays the buffered recent fills (`self._recent_fills`, a `deque(maxlen=30)` populated only by `fill_resilient`, never cleared per-click since the field that needs replay may be several steps back) with their original strategy, then re-checks enablement once; each buffered entry is presence-checked (`is_visible(timeout=500)`) first so a stale entry from an already-navigated screen is skipped instead of paying a full `fill_resilient` timeout. If the target still never enables, it falls through to the same `strict`/cognitive/coordinate decision used by any other click failure. `#btn-next-step` was removed from `_CLICK_EFFECT_EXCLUDED_SELECTORS` once this sensor covered it directly. When `_recover_via_recent_fills` does resolve the click, it auto-registers `needs_review` with `healing_method="enable_timeout_recovered"` via the same Sensor F1 hook (`_register_healing_for_review`), independent of whether the `CLICK_NO_EFFECT` sensor also fires for the same step.

## Testing

Tests live in `aegis_runner/test_*.py`, `aegis_sanitizer/test_*.py`, and `aegis_code_generator/test_*.py`:
- `aegis_runner/test_runner_integration.py` — integration tests for the TransactionRunner (mocked Playwright `page`/`locator`)
- `aegis_runner/test_cognitive_fallback.py` — tests for the CognitiveGateway
- `aegis_sanitizer/test_sanitizer_execution_plan.py` — plan generation, `weak_selector`, `fallback_selectors` propagation
- `aegis_code_generator/test_error_selector_config.py` — `error_message_selector` boilerplate parametrization
- `aegis_code_generator/test_weak_selector_enforcement.py` — `WEAK_SELECTOR_WITHOUT_ANCHOR` structural check
- `aegis_code_generator/test_dryrun_multirow.py` — multi-row dry-run harness

Run with plain `python <test_file>.py`. The project Python version requirement is `>=3.8`.

**Known gap:** `aegis_cockpit/cockpit.py` has no test suite in the repo. It's a large HTTP handler (correction lifecycle, step marking, project CRUD) that has caused real regressions when edited without a live re-check — see "Working Agreements" below.

## Working Agreements (lessons from the M1-M5 precision cycle, 2026-07)

Full writeup: `.specs/licoes-aprendidas-melhorias-precisao.md`. The short version, as rules:

1. **A change to selector/DOM/timing logic is not done until it's run against a real (even headless) browser.** Twice in this cycle, a fix passed the mocked unit suite and an inspection of the diff, and was still functionally broken — `document.querySelector()` choking on Playwright-only selector syntax (`:has-text()`), and a "found bug" that was actually a misread of which selector a `console.warn` referred to. Mocked tests prove the code path executes; they don't prove the selector/DOM assumption holds.
2. **If a symptom reappears after you already "fixed" it, suspect your own subsequent action first.** The `dataset_inicial.json`/`dicionario.json` key-mismatch bug looked like a sanitizer persistence bug on first read (trusted the success log without re-checking the file after a *later* action — a second recording — silently reverted it). Reproducing the pipeline from scratch in a clean folder settled it in minutes; trusting the log almost shipped a fix for the wrong module.
3. **A regressing unit test isn't automatically a bug to revert.** When `_capture_click_effect_snapshot` started calling `page.locator()` more than once (new 4th signal), an `assert_called_once_with` test broke — correctly, because the assertion encoded an implementation detail, not the actual contract. Fix the assertion (`assert_any_call`), don't roll back the feature to satisfy an overspecified test.
4. **Recorder overwrites `dicionario.json`/`dataset_inicial.json` unconditionally on every recording finish.** If a project has already been through Sanitizer's semantic-key translation (`usuario_login` instead of `username`), re-recording silently reverts to raw keys unless the field's selector still matches — the recorder now auto-preserves the semantic key by selector match and warns only for fields it couldn't match. Always re-run Sanitizer + Code Generator after any re-recording of an already-sanitized project, even when no warning fires.
5. **A validator error dict without `step_id`/`lineno` is structurally invisible to the code generator's scoped-edit targeting (`_surgical_correct` → `live_error_step_ids`, `aegis_code_generator/code_generator.py`).** Found 2026-07-11 chasing a Ralph Loop that burned all 15 attempts on the same two errors every time: `MISSING_PROJECT_DIR_ARG`/`RUNNER_INSTANTIATED_AT_MODULE_SCOPE` (a hallucinated stray `TransactionRunner(...)` call inside a function body, surviving `_normalize_boilerplate` because it only rebuilds the canonical `if __name__` block) and `HALLUCINATED_RUNNER_METHOD` — neither error dict carried a `step_id`, so the scoped-edit prompt kept re-sending the same block without ever including the fix the model needed to make. Same class of bug also hit `HALLUCINATED_DATASET_FIELD` (dataset field names). Fixed by: (a) attaching `lineno`/`linenos` to every AST-level error in `step_validator.py` that lacks a natural `step_id`, and mapping it to the containing `# [PASSO X]` block in `code_generator.py`; (b) adding deterministic (non-LLM) auto-fixes for the two worst offenders — `difflib`-based method-name rename and stray-`TransactionRunner`-call stripping — since the reflection loop alone couldn't get the model to stop reintroducing the same hallucination. A related, nastier variant: the scoped splice only guarantees byte-identity *outside* the target block — nothing validated the *content* the model returned, so a leaked top-level `def execute_scenario_default(...)` spliced mid-function silently shadowed the real one (Python binds the last `def`), passing AST checks but failing dry-run with zero scoping signal, oscillating forever between the error the duplicate caused and the one it masked. Fixed by rejecting any scoped-block response containing a column-0 `def`/`class` (falls back to full-file) plus a static duplicate-`execute_scenario_default` detector. **Takeaway:** any new AST-level check added to `step_validator.py` must carry `lineno` (or `step_id` if naturally available) in its error dict, or it will be silently unreachable by scoped correction the moment `pending_corrections` happens to already be scoped to some other step.

### Skills for harness engineering on this repo

Three project skills exist in `.claude/skills/` (mirrored in `.agents/skills/`), each validated live against a real site (Fimm Corporate pilot, 2026-07-09) before being trusted here. Use them proactively — don't hand-roll the equivalent workflow inline when one of these already covers it:

- **`aegis-live-pilot`** — use whenever validating the framework (or a change to it) against a **real site**: onboarding a new client project, checking for Angular-Material bias after a framework change, or any "does this actually work outside Portal Segura" question. Drives `AegisRecorder` for real (never fabricates `gravacao.json`), runs all 5 phases, measures real metrics, writes `.specs/relatorio-piloto-<slug>.md`. Requires the user to supply the URL — never invents one.
- **`aegis-regression-gate`** — use **after any change to `aegis_*` core code** (runner, sanitizer, recorder, code_generator, cockpit), before considering the change done. Runs the compiled reference bot (default `portal_segura/tests/001_teste`) N times without regenerating, compares against the saved baseline in `.specs/plans/*.baseline-*.md`, and gives an explicit APROVADO/REPROVADO verdict. Never regenerates the bot and never attempts a fix itself.
- **`aegis-pipeline-forensics`** — use when a bot **reads the wrong field or a step references something that doesn't exist**, or "this used to work" — before assuming it's a framework bug. Read-only: walks the artifact chain (`gravacao.json` → `dicionario.json` → `dataset_inicial.json` → `plano_execucao.json` → `bot_producao.py`) and reports exactly where it diverges, checking self-inflicted causes (re-recording, manual edits) before concluding it's a real bug.

None of the three has an eval suite (draft-and-adjust) and none modifies framework code — they measure, gate, or diagnose, never fix. If a session finds a real bug through one of them, treat that as a separate, explicit fix task.