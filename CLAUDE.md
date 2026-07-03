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
python aegis_sanitizer/code_generator.py --project-dir projects/seu_projeto

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
| `aegis_sanitizer/sanitizer.py` | Deduplicates and filters recorder telemetry. Produces `relatorio.md` (human+LLM-readable) and rewrites clean `gravacao.json`. |
| `aegis_sanitizer/dataset_validator.py` | Validates `dataset_inicial.json`/`.csv` against the data dictionary. Tolerant — only blocks critical structural errors. |
| `aegis_sanitizer/code_generator.py` | Compiles `bot_producao.py` + `skills_lib.py` via LLM (Gemini/OpenRouter). Two flows: **new generation** (from scratch) and **surgical correction** (targeted fix of specific steps using `# [PASSO X]` anchors). Uses `AEGIS_COGNITIVE_CODER_MODEL` if set. |
| `aegis_mentor/skills/` | LLM skill prompts defining the resilience pattern catalog used during code generation. |

### Core Modules (Run-Time)

| Module | Role |
|---|---|
| `aegis_runner/runner.py` | `TransactionRunner` class: the deterministic execution engine. Iterates over a dataset, creates an isolated Playwright page per row, and runs registered scenario callbacks. Provides `click_resilient`, `fill_resilient`, `fill_human_like`, `select_option_resilient`, and `wait_for_selector`. Logs all steps to `[AEGIS_STEP]` and writes `historico_passos.json` + CSV report. |
| `aegis_runner/cognitive_fallback.py` | `CognitiveGateway`: optional LLM-powered self-healing layer. When `AEGIS_COGNITIVE_ENABLED=true`, it can visually locate elements via screenshot→LLM coordinate detection (`self_healing_click`), diagnose failures multimodally (`diagnose_failure`), transcribe audio, and compare visual screenshots. Supports OpenRouter, LiteLLM, and any OpenAI-compatible endpoint. Loads `.env` from the project tree and framework root. |

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

### Self-Healing Fallback Chain
When `click_resilient` fails: (1) retry with Escape key to clear overlays → (2) multi-element heuristic (avoid `href="#"` anchors) → (3) `self_healing_click` via LLM vision → (4) recorded coordinate fallback. For `fill_resilient`: (1) direct fill → (2) multi-element first match → (3) Escape clear + retry → (4) LLM visual location + keyboard type.

## Testing

Tests live in `aegis_runner/test_*.py`:
- `test_runner_integration.py` — integration tests for the TransactionRunner
- `test_cognitive_fallback.py` — tests for the CognitiveGateway

Run with plain `python <test_file>.py`. The project Python version requirement is `>=3.8`.