"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Dispatcher único de fronteira (Edit/Write/MultiEdit/NotebookEdit/PowerShell/Bash) para
a superfície do contrato ativo (.harness/feature_list.json). Registrado com
matcher "*" (casa toda tool call — ver docstring de harness.boundary_guard,
seção "Matcher do hook e roteamento explícito", para a justificativa);
main() roteia explicitamente cada tool conhecida e aplica uma política
mínima de allow/deny-por-nome para tools desconhecidas (deploy single-user
interno, ver mesma seção). Gerado por
harness.boundary_guard.render_boundary_guard(); para mudar o
comportamento, edite o contrato/profile e rode a instalação novamente —
não edite este arquivo diretamente.

ORDEM DE AVALIAÇÃO (não reordenar): o runtime floor roda incondicionalmente
antes de qualquer checagem de contrato — mesmo sem .harness/feature_list.json
no repo, git push, comandos de rede do PowerShell e escrita em arquivo de
segredo (via Edit/Write, PowerShell ou redirecionamento/tee no Bash)
continuam DENY.

A faixa abaixo marcada "GERADO" vem de harness.boundary_guard via
inspect.getsource() (mesma lógica da versão importável, testável via
pytest direto) — não editada à mão nesta faixa.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- GERADO a partir de harness.boundary_guard (inspect.getsource) ---
_SHELL_SPLIT = re.compile('[\\s;&|()<>`$\\"\']+')
FLOOR_BASH_SEQUENCES = [['git', 'push'], ['curl'], ['wget'], ['npm', 'publish'], ['pip', 'upload'], ['twine', 'upload'], ['gh', 'release']]
def _tokenize_command(command: str) -> list[str]:
    return [t for t in _SHELL_SPLIT.split(command or "") if t]
def _has_sequence(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))
def is_floor_bash_command(command: str) -> bool:
    """True se `command` casa alguma sequência do runtime floor (git push,
    curl, wget, npm publish, pip upload, twine upload, gh release)."""
    tokens = _tokenize_command(command)
    return any(_has_sequence(tokens, seq) for seq in FLOOR_BASH_SEQUENCES)
def is_floor_secret_path(path: str) -> bool:
    """True se `path` é um arquivo de segredo do runtime floor (.env, .pem,
    id_rsa, ou nome contendo 'credentials')."""
    lower = (path or "").replace("\\", "/").lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )
def is_floor_bash_secret_redirect(command: str) -> bool:
    """True se `command` faz redirecionamento (`>`/`>>`) ou usa `tee` cujo
    ALVO casa `is_floor_secret_path` (correção do achado #3 do backlog de
    correção do issue #1: antes desta função, o floor de segredo só era
    checado no caminho Edit/Write — `_evaluate_bash` retornava `allow` sem
    olhar o alvo de nenhum redirecionamento).

    Escopo DELIBERADAMENTE restrito a redirecionamento/`tee` — não persegue
    escrita indireta via interpretador (`python -c "open('.env','w')..."`,
    `node -e ...`): custo desproporcional para o que este mecanismo cobre; a
    redireção é o caso comum e observável (foi o vetor citado no achado).

    Correção de bug (achado adversarial pós-implementação, validação Opus):
    a versão anterior extraía o alvo do `>`/`>>` com uma regex sobre o texto
    BRUTO do comando (`>>?\\s*([^\\s;&|<>]+)`), que CAPTURAVA as aspas junto
    do valor (`".env"` inteiro, aspas incluídas) — `is_floor_secret_path`
    exige sufixo exato (`.endswith(".env")`), então `".env"`/`'.env'` (com
    aspas) escapava do floor enquanto `.env` (sem aspas) era pego
    corretamente. `tee` já não tinha esse bug porque usava
    `_tokenize_command` (que trata aspas como separador, removendo-as). Fix:
    o ramo de redirecionamento agora tokeniza o comando (mesma função,
    mesma remoção de aspas) em vez de usar regex sobre o texto bruto —
    consistente com o ramo `tee` logo abaixo, e sem o furo de aspas.

    LIMITE ACEITO (não corrigido aqui — ver docstring do módulo, mesma
    lista de limitações assumidas do floor): a tokenização por
    `_tokenize_command` cobre o caso comum de aspas ENVOLVENDO o valor
    inteiro (`> ".env"`, `> '.env'`), mas NÃO reconstrói o shell parsing
    completo — concatenação de fragmentos entre aspas adjacentes (`>
    ".e"nv`, que o shell reagrupa em `.env` mas aqui vira dois tokens
    `.e`+`nv`, nenhum casando `is_floor_secret_path`) e ANSI-C quoting
    (`> $'\\x2eenv'`) ainda escapam. Mesma classe de risco residual que a
    escrita indireta via interpretador (`python -c "open('.env','w')"`):
    o floor cobre o vetor comum e observável, não é airtight contra um
    agente deliberadamente adversário ofuscando o alvo."""
    command = command or ""
    tokens = _tokenize_command(command)
    if ">" in command and any(is_floor_secret_path(tok) for tok in tokens):
        return True
    if "tee" in tokens:
        idx = tokens.index("tee")
        return any(is_floor_secret_path(tok) for tok in tokens[idx + 1:])
    return False
_PS_NETWORK_PATTERN = re.compile('(?i)\\b(invoke-webrequest|invoke-restmethod|iwr|irm)\\b')
_PS_WRITE_CMDLET_PATTERN = re.compile('(?i)\\b(set-content|out-file|add-content)\\b')
_PS_WRITEALLTEXT_PATTERN = re.compile('(?i)writealltext|writealllines|appendalltext|appendalllines')
def is_floor_powershell_network(command: str) -> bool:
    """True se `command` (PowerShell) casa o floor de rede/publicação:
    reusa `is_floor_bash_command` (git push/curl/wget/npm publish/pip
    upload/twine upload/gh release — tokenização genérica, independente de
    shell — NÃO duplicada aqui) e acrescenta os cmdlets de rede nativos do
    PowerShell que essa tokenização não reconhece como sequência fixa
    (`Invoke-WebRequest`/`Invoke-RestMethod` e os aliases `iwr`/`irm`)."""
    if is_floor_bash_command(command):
        return True
    return bool(_PS_NETWORK_PATTERN.search(command or ""))
def is_floor_powershell_secret_write(command: str) -> bool:
    """True se `command` (PowerShell) PARECE escrever em arquivo (via
    `Set-Content`/`Out-File`/`Add-Content`/redirecionamento `>`,`>>`/
    `[IO.File]::WriteAllText` e variantes — `WriteAllLines`/`AppendAllText`/
    `AppendAllLines`) E algum token do comando casa `is_floor_secret_path`.

    Heurística CONSERVADORA por design: escaneia TODOS os tokens do comando
    (não tenta parsing posicional exato do argumento de path — PowerShell
    aceita `-Path`, forma posicional, ou pipeline; um parser completo é fora
    de escopo). Prefere falso-deny a falso-allow neste caminho de floor de
    segredo — over-deny aqui é seguro (só gera fricção), nunca abre um
    bypass."""
    command = command or ""
    is_write = (
        _PS_WRITE_CMDLET_PATTERN.search(command) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(command) is not None
        or ">" in command
    )
    if not is_write:
        return False
    return any(is_floor_secret_path(tok) for tok in _tokenize_command(command))
DOCS_SURFACE_DIR_PREFIX = 'docs/'
DOCS_SURFACE_EXCLUDED_BASENAMES = {'claude.md', 'plans.md', 'agents.md', 'spec.md'}
DOCS_SURFACE_EXCLUDED_PATHS = {'.harness/harness.yaml'}
def _is_docs_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na allowlist fixa `docs/**`.

    Normaliza com `posixpath.normpath` ANTES de checar o prefixo `docs/` —
    protege contra um path que tente escapar de `docs/**` via segmentos
    `..` (ex.: `docs/../AGENTS.md` normaliza para `AGENTS.md`, que não
    começa com `docs/`). A exclusão por nome-base (`AGENTS.md`/`CLAUDE.md`/
    `Plans.md`/`spec.md`, case-insensitive) e por path exato
    (`.harness/harness.yaml`) é defense-in-depth adicional, redundante com a
    normalização acima no cenário atual, mas documentada explicitamente
    porque é a garantia que o backlog pede por escrito."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    if normalized in DOCS_SURFACE_EXCLUDED_PATHS:
        return False
    basename = normalized.rsplit("/", 1)[-1].lower()
    if basename in DOCS_SURFACE_EXCLUDED_BASENAMES:
        return False
    return normalized.startswith(DOCS_SURFACE_DIR_PREFIX)
WORK_DIR_PREFIX = '.harness/work/'
SCRATCH_DIR_PREFIX = '.harness/scratch/'
def _is_work_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na área de autoria de contrato
    `.harness/work/**`. Normaliza com `posixpath.normpath` ANTES do prefixo —
    `.harness/work/../../x.py` normaliza para `x.py`, que não começa com o
    prefixo (correção do furo de traversal do check anterior)."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.startswith(WORK_DIR_PREFIX)
def _is_scratch_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na área de scratch
    `.harness/scratch/**` — artefatos temporários de verificação, sempre
    graváveis, auto-ignorados pelo git. Mesma normalização anti-traversal de
    `_is_work_surface_path`."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.startswith(SCRATCH_DIR_PREFIX)
PROGRESS_FILE_NAME = 'claude-progress.md'
def _is_progress_file_path(path: str) -> bool:
    """True se `path` (já `/`-separado) é o `claude-progress.md` da RAIZ do
    repo — bookkeeping do próprio harness (o lifecycle, passo 12, manda o
    agente atualizá-lo a cada sessão; `runtime_audit` dá warning se ausente),
    sempre gravável. Match EXATO pós-`posixpath.normpath`, case-insensitive
    (filesystem Windows): um `claude-progress.md` dentro de subdiretório NÃO
    casa — só o canônico da raiz; a normalização cobre variantes como
    `docs/../claude-progress.md`. Correção do issue 3 do dogfood
    aegis_rpa_suite (guard negava escrita no arquivo que o próprio harness
    manda manter)."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.lower() == PROGRESS_FILE_NAME
SESSION_STATE_FILE = '.harness/compiled-state-session.json'
REPO_ROOT_STATE_KEY = 'repo_root'
_MAX_ROOT_SEARCH_DEPTH = 40
def _find_session_state_path(start_dir: Path | str) -> Path | None:
    """Sobe de `start_dir` até achar `SESSION_STATE_FILE`
    (`.harness/compiled-state-session.json`) ou até a raiz do filesystem —
    o que vier primeiro. Zero subprocess (ao contrário de `git rev-parse
    --show-toplevel`, a proposta original do issue: sem footgun de
    submódulo/worktree/repo-sem-git, e sem o custo de subprocess que o
    design deste módulo existe para evitar — docstring, linhas 3-8). Devolve
    o `Path` absoluto do arquivo se achar, `None` senão (inclui o caso de
    não achar dentro do limite de profundidade)."""
    current = Path(start_dir).resolve()
    for _ in range(_MAX_ROOT_SEARCH_DEPTH):
        candidate = current / SESSION_STATE_FILE
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None
def _read_repo_root_from_state(state_path: Path | str) -> str | None:
    """Lê a chave `REPO_ROOT_STATE_KEY` de `state_path`
    (`compiled-state-session.json`). Devolve a string gravada se presente,
    não-vazia e apontando para um diretório que ainda existe em disco;
    `None` em qualquer outro caso (arquivo ausente, JSON inválido, chave
    ausente/tipo errado, ou diretório que não existe mais) — fallback
    seguro, nunca lança: o chamador deve cair no `cwd` do payload sem
    quebrar (repos sem `compile-session` recente não podem quebrar)."""
    path = Path(state_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get(REPO_ROOT_STATE_KEY)
    if not isinstance(root, str) or not root:
        return None
    if not Path(root).is_dir():
        return None
    return root
def _resolve_repo_root_anchor(script_file: Path | str) -> str | None:
    """Orquestrador: acha `SESSION_STATE_FILE` subindo a partir do diretório
    de `script_file` (o próprio hook instalado, via `__file__` — sempre mora
    em `<repo_root>/.harness/hooks/boundary_guard.py`, então subir a partir
    dali sempre alcança a raiz real do repo, mesmo que o `cwd` do payload
    tenha derivado) e devolve o `repo_root` válido gravado lá, ou `None` se
    qualquer passo falhar. `main()` usa o retorno para substituir o `cwd`
    efetivo ANTES de `_resolve_path`/`_load_json` — âncora os dois de uma
    vez, já que ambos recebem o mesmo `cwd`."""
    state_path = _find_session_state_path(Path(script_file).resolve().parent)
    if state_path is None:
        return None
    return _read_repo_root_from_state(state_path)
def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
def _feature_passes_map(data: Any) -> dict[Any, bool]:
    result: dict[Any, bool] = {}
    if not isinstance(data, dict):
        return result
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("id")
        if fid is not None:
            result[fid] = feat.get("passes") is True
    return result
def _transitions_to_true(old_data: Any, new_data: Any) -> list[Any]:
    old_map = _feature_passes_map(old_data)
    new_map = _feature_passes_map(new_data)
    return [fid for fid, val in new_map.items() if val and not old_map.get(fid, False)]
def _read_last_commit_timestamp(cwd: Path | str | None) -> str | None:
    """Mesmo padrão de subprocess de `session_start.py::_read_git_log`:
    `git log -1 --format=%cI` (timestamp ISO8601 do committer). Retorna
    `None` se o comando falhar (sem commits, não é repo git, git ausente)."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output or None
def _evidence_freshness_problem(
    cwd: Path | str | None, feature_id: Any, commit_ts: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """`(None, evidence)` se a evidência de `feature_id` existe, é válida e
    (quando `commit_ts` fornecido) mais nova que ele; senão, `(problema,
    None)` descrevendo o problema. O dict de evidência é devolvido junto
    (mesmo objeto já parseado, sem reler o arquivo) para o chamador reusar na
    checagem do veto do revisor (comparação contra `evidencia.recorded_at`)."""
    base = Path(cwd) if cwd else Path(".")
    evidence_path = base / EVIDENCE_DIR_NAME / f"{feature_id}.json"
    if not evidence_path.is_file():
        return f"{feature_id}: sem evidência (.harness/evidence/{feature_id}.json não existe)", None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return f"{feature_id}: evidência inválida (JSON malformado)", None
    if not isinstance(evidence, dict) or evidence.get("feature_id") != feature_id:
        return f"{feature_id}: evidência inválida (feature_id não corresponde)", None
    recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
    if recorded_dt is None:
        return f"{feature_id}: evidência inválida (recorded_at ausente ou não-ISO8601)", None
    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and recorded_dt <= commit_dt:
            return (
                f"{feature_id}: evidência mais antiga que o último commit "
                f"(recorded_at={evidence.get('recorded_at')})"
            ), None
    return None, evidence
def _read_team_manifest(cwd: Path | str | None) -> dict[str, Any] | None:
    """Lê `.harness/team/manifest.json`; devolve o dict só se o arquivo
    existir e for JSON válido representando um objeto — ausência ou JSON
    inválido devolve `None` (time não compilado ou artefato corrompido: em
    ambos os casos a checagem do veto do revisor é pulada por inteiro,
    comportamento IDÊNTICO à Fase 3)."""
    base = Path(cwd) if cwd else Path(".")
    manifest_path = base / TEAM_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data
def _manifest_requires_review(manifest: dict[str, Any] | None) -> bool:
    """`True` só quando o manifesto declara AMBOS os papéis `producer` e
    `reviewer` — decisão do planejador: revisão obrigatória é por PROJETO,
    não por-tarefa."""
    if manifest is None:
        return False
    roles = manifest.get("roles")
    if not isinstance(roles, list):
        return False
    role_set = {r for r in roles if isinstance(r, str)}
    return "producer" in role_set and "reviewer" in role_set
def _feature_by_id(data: Any, feature_id: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    for feat in data.get("features") or []:
        if isinstance(feat, dict) and feat.get("id") == feature_id:
            return feat
    return None

# --- fim da faixa gerada ---

# --- comandos git locais sempre liberados quando há contrato ativo ---
FIXED_GIT_SEQUENCES = [
    ["git", "status"],
    ["git", "log"],
    ["git", "diff"],
    ["git", "add"],
    ["git", "commit"],
]

# --- subcomandos do proprio harness sempre liberados quando ha contrato
# ativo: a ferramenta que GERENCIA o contrato nao pode ficar presa no
# guard que ela mesma gerou. Cobre as duas formas de invocacao
# documentadas nas skills (python -m harness.cli) e o console-script real
# (harness). NAO inclui 'run' (orquestrador da era congelada, chama a
# API Anthropic — rede fora do floor — e nao estava na fricao relatada).
# 'task' entrou na correcao do issue 3 do dogfood aegis_rpa_suite: e o
# escape oficial documentado na skill plan (harness task add-file) para
# ampliar a superficie de uma tarefa — sem ele aqui, o guard fechava a
# porta E escondia a chave (o proprio deny message apontava um comando
# que o guard negava).
_HARNESS_SUBCOMMANDS = [
    "compile", "audit", "audit-runtime", "analyze", "preflight",
    "compile-contract", "compile-session", "verify", "team", "review",
    "supervise", "audit-team", "task",
]
FIXED_HARNESS_SEQUENCES = (
    [["harness", sub] for sub in _HARNESS_SUBCOMMANDS]
    + [["python", "-m", "harness.cli", sub] for sub in _HARNESS_SUBCOMMANDS]
)

FEATURE_LIST_PATH = ".harness/feature_list.json"
PROFILE_PATH = ".harness/repo-profile.json"
EVIDENCE_DIR_NAME = ".harness/evidence"
TEAM_MANIFEST_RELATIVE_PATH = ".harness/team/manifest.json"
REVIEW_DIR = ".harness/review"
# WORK_DIR_PREFIX (area de autoria de contrato) e SCRATCH_DIR_PREFIX (area de
# scratch para artefato temporario de verificacao) vem da faixa GERADA acima,
# junto com _is_work_surface_path/_is_scratch_surface_path (normalizacao
# anti-traversal) - fonte unica em harness.boundary_guard.

# package_manager.value (analyzer.py) -> comando de instalação EXATO. Mesmo
# mapeamento de harness.session_permissions/harness.templates: o valor bruto
# do profile (ex.: "npm") NUNCA vira um comando permitido por si só - isso
# liberaria qualquer subcomando ("npm run x", "npm exec"), nao so a instalacao.
INSTALL_COMMAND_BY_PACKAGE_MANAGER = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
}


def _glob_to_regex(glob):
    """Mesmo algoritmo de harness.verification.tdd_loop._glob_to_regex,
    copiado inline (o hook não pode importar a lib)."""
    escaped = re.escape(glob.replace("\\", "/"))
    escaped = escaped.replace(r"\*\*/", "(?:.*/)?")
    escaped = escaped.replace(r"\*\*", ".*")
    escaped = escaped.replace(r"\*", "[^/]*")
    escaped = escaped.replace(r"\?", "[^/]")
    return re.compile("^" + escaped + "$")


def _resolve_path(raw_path, cwd):
    path = (raw_path or "").replace("\\", "/")
    cwd_norm = (cwd or "").replace("\\", "/").rstrip("/")
    if cwd_norm and path.lower().startswith(cwd_norm.lower() + "/"):
        path = path[len(cwd_norm) + 1:]
    return path


def _split_shell_segments(command):
    """Segmenta a string do comando nos operadores de controle de shell
    (`;`, `&&`, `||`, `|`, `&` de background, newline `\n` e carriage-return
    `\r`), devolvendo a lista de sub-comandos nao-vazios. Respeita aspas e
    double-quotes de shell (operadores dentro de strings nao causam
    segmentacao). `&&`/`||` sao casados ANTES de `&`/`|` isolados para nao
    quebrar um `&&` em dois `&`."""
    if not command:
        return []
    result = []
    current = []
    in_single = False
    in_double = False
    escape_next = False
    i = 0
    while i < len(command):
        ch = command[i]
        if escape_next:
            current.append(ch)
            escape_next = False
        elif ch == "\\" and not in_single:
            escape_next = True
        elif ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif ch in ("&", "|", ";", "\n", "\r") and not in_single and not in_double:
            seg = "".join(current).strip()
            if seg:
                result.append(seg)
            current = []
            if ch == "&" and i + 1 < len(command) and command[i + 1] == "&":
                i += 1
            elif ch == "|" and i + 1 < len(command) and command[i + 1] == "|":
                i += 1
        else:
            current.append(ch)
        i += 1
    seg = "".join(current).strip()
    if seg:
        result.append(seg)
    return result


def _segment_prefixes_any(seg_tokens, sequences):
    """True se os tokens do segmento PREFIXAM (tokens[:n] == seq, nao mais
    'aparece em qualquer janela') alguma das sequencias permitidas."""
    for seq in sequences:
        if seq and seg_tokens[:len(seq)] == seq:
            return True
    return False


def _load_json(cwd, relative):
    base = cwd or "."
    path_str = relative
    try:
        import os
        full = os.path.join(base, relative)
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _profile_entry_value(profile, key):
    if not isinstance(profile, dict):
        return None
    entry = profile.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _profile_extra_value(profile, key):
    if not isinstance(profile, dict):
        return None
    extras = profile.get("extras")
    if not isinstance(extras, dict):
        return None
    entry = extras.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _collect_allowed_files(feature_list, cwd=None):
    """Devolve (literais_exatos, prefixos_de_diretorio, padroes_glob_compilados)
    a partir de `files[]` de todas as tarefas.

    NAO faz mais disco-walk para expandir glob: um `Write` cria arquivo que
    ainda nao existe no disco no momento em que o hook roda, entao casar glob
    so contra arquivos ja existentes nunca reconhece o proprio arquivo que a
    tarefa esta tentando criar (ex.: migration nova, teste novo). Em vez
    disso o candidato e casado direto contra o padrao em `_path_in_surface`.
    `cwd` mantido no parametro por compat de assinatura, sem uso.
    """
    literals = set()
    prefixes = []
    patterns = []

    for feat in (feature_list or {}).get("features", []) or []:
        for f in feat.get("files") or []:
            normalized = str(f).replace("\\", "/")
            if "*" in normalized or "?" in normalized:
                patterns.append(_glob_to_regex(normalized))
            elif normalized.endswith("/"):
                prefixes.append(normalized)
            else:
                literals.add(normalized)

    return literals, prefixes, patterns


def _path_in_surface(path, surface):
    literals, prefixes, patterns = surface
    if path in literals:
        return True
    if any(path.startswith(prefix) for prefix in prefixes):
        return True
    return any(pattern.match(path) for pattern in patterns)


def _collect_allowed_bash_commands(feature_list, profile):
    commands = []
    for feat in (feature_list or {}).get("features", []) or []:
        vc = feat.get("verify_cmd")
        if vc:
            commands.append(vc)
    for key in ("lint_command", "typecheck_command", "build_command"):
        value = _profile_extra_value(profile, key)
        if value:
            commands.append(value)
    package_manager_value = _profile_entry_value(profile, "package_manager")
    install_cmd = (
        INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager_value)
        if package_manager_value
        else None
    )
    if install_cmd:
        commands.append(install_cmd)
    return commands


def _is_test_diff(feature, cwd):
    """Equivalente standalone de harness.review.is_test_diff — o hook nao
    pode importar a lib, entao replica: casa feature['files'] contra o
    test_glob do repo-profile usando o _glob_to_regex ja copiado acima."""
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")
    if not test_glob:
        return False
    pattern = _glob_to_regex(test_glob)
    files = (feature or {}).get("files") or []
    for f in files:
        normalized = str(f).replace("\\", "/")
        if pattern.match(normalized):
            return True
    return False


def _load_review_record(cwd, feature_id):
    """Equivalente standalone de harness.review.load_review: devolve
    (record, problema). Arquivo ausente -> registro DEFAULT status='pending'
    (mesmo comportamento de load_review, sem gravar em disco); JSON invalido
    -> (None, problema)."""
    import os
    base = cwd or "."
    full = os.path.join(base, REVIEW_DIR, str(feature_id) + ".json")
    if not os.path.isfile(full):
        return {
            "feature_id": feature_id,
            "status": "pending",
            "iteration": 0,
            "max_iterations": 3,
            "history": [],
            "justification": None,
            "updated_at": "",
        }, None
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, str(feature_id) + ": registro de revisao invalido (JSON malformado)"
    if not isinstance(data, dict):
        return None, str(feature_id) + ": registro de revisao invalido (formato inesperado)"
    return data, None


def _review_gate_problem(cwd, feature_id, feature_data, commit_ts, evidence):
    record, load_problem = _load_review_record(cwd, feature_id)
    if load_problem:
        return load_problem

    status = record.get("status")
    if status != "approved":
        return (
            str(feature_id) + ": revisao pendente/rejeitada (status='" + str(status) + "') - "
            "rode harness review " + str(feature_id) + " approve antes"
        )

    review_dt = _parse_iso8601(record.get("updated_at"))
    if review_dt is None:
        return str(feature_id) + ": registro de revisao sem updated_at valido"

    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and review_dt <= commit_dt:
            return str(feature_id) + ": aprovacao mais antiga que o ultimo commit (updated_at=" + str(record.get("updated_at")) + ")"

    if evidence is not None:
        recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
        if recorded_dt is not None and review_dt < recorded_dt:
            return (
                str(feature_id) + ": aprovacao obsoleta - evidencia foi regravada depois da "
                "aprovacao (evidencia.recorded_at=" + str(evidence.get("recorded_at")) +
                ", review.updated_at=" + str(record.get("updated_at")) + ")"
            )

    if _is_test_diff(feature_data, cwd):
        justification = record.get("justification")
        if not justification or not str(justification).strip():
            return str(feature_id) + ": aprovacao de diff de teste sem justificativa registrada"

    return None


def _evaluate_feature_list_edit(tool_name, tool_input, cwd):
    base = cwd or "."
    import os
    full = os.path.join(base, FEATURE_LIST_PATH)
    if os.path.isfile(full):
        with open(full, "r", encoding="utf-8") as fh:
            current_text = fh.read()
    else:
        current_text = "{}"

    if tool_name == "Write":
        proposed_text = tool_input.get("content") or ""
    else:
        old_string = tool_input.get("old_string") or ""
        new_string = tool_input.get("new_string") or ""
        if old_string and old_string not in current_text:
            return "deny", (
                "feature_list.json: old_string do Edit nao foi encontrado no "
                "arquivo atual - se esta editando mais de uma feature no mesmo "
                "Edit, confira se o bloco bate exatamente com o conteudo atual; "
                "edite uma feature por vez se nao tiver certeza"
            )
        if tool_input.get("replace_all"):
            proposed_text = current_text.replace(old_string, new_string)
        else:
            proposed_text = current_text.replace(old_string, new_string, 1)

    try:
        old_data = json.loads(current_text) if current_text.strip() else {}
    except ValueError:
        old_data = {}
    try:
        new_data = json.loads(proposed_text)
    except ValueError as exc:
        return "deny", (
            "feature_list.json: edicao proposta produz JSON invalido (" + str(exc) + ") - "
            "edite uma feature por vez ou corrija a sintaxe antes de tentar de novo"
        )

    transitioned = _transitions_to_true(old_data, new_data)
    if not transitioned:
        return None

    commit_ts = _read_last_commit_timestamp(cwd)
    problems = []
    evidence_by_id = {}
    for fid in transitioned:
        problem, evidence = _evidence_freshness_problem(cwd, fid, commit_ts)
        if problem:
            problems.append(problem)
        else:
            evidence_by_id[fid] = evidence

    if problems:
        return "deny", (
            "feature-lock: transicao para passes:true sem evidencia fresca - "
            + "; ".join(problems)
            + " - rode harness verify <id> primeiro"
        )

    manifest = _read_team_manifest(cwd)
    review_required = _manifest_requires_review(manifest)
    if review_required:
        review_problems = []
        for fid in transitioned:
            problem = _review_gate_problem(
                cwd, fid, _feature_by_id(new_data, fid), commit_ts, evidence_by_id.get(fid)
            )
            if problem:
                review_problems.append(problem)
        if review_problems:
            return "deny", (
                "feature-lock: revisao do time (produtor-revisor) pendente/obsoleta - "
                + "; ".join(review_problems)
            )

    success_message = (
        "feature-lock: transicao para passes:true com evidencia fresca confirmada para "
        + ", ".join(str(fid) for fid in sorted(transitioned, key=str))
    )
    if review_required:
        success_message += " e revisao do time (produtor-revisor) aprovada"
    return "allow", success_message


def _evaluate_file(path, cwd):
    if is_floor_secret_path(path):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo (.env/.pem/id_rsa/"
            "credentials) e bloqueio incondicional, independente de contrato ativo"
        )

    if _is_work_surface_path(path):
        return "allow", (
            "area de autoria de contrato (.harness/work/**) sempre gravavel - "
            "permite planejar o proximo contrato sem replanejar o atual"
        )

    if _is_scratch_surface_path(path):
        return "allow", (
            "area de scratch (.harness/scratch/**) sempre gravavel - destino "
            "correto de artefato temporario de verificacao (screenshot, dump "
            "de rede, HTML de debug); auto-ignorada pelo git, apagavel a "
            "qualquer momento, nunca referencie de codigo"
        )

    if _is_progress_file_path(path):
        return "allow", (
            "claude-progress.md e bookkeeping do proprio harness (o lifecycle "
            "manda atualiza-lo a cada sessao) - sempre gravavel, mesmo padrao "
            "de .harness/work/** e docs/**"
        )

    if _is_docs_surface_path(path):
        return "allow", (
            "docs/** e superficie de documentacao dedicada (Item 4) - prosa nao "
            "quebra teste; AGENTS.md/CLAUDE.md/Plans.md/spec.md/.harness/harness.yaml "
            "permanecem protegidos (excluidos explicitamente desta allowlist)"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    surface = _collect_allowed_files(feature_list, cwd)
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")

    if test_glob:
        pattern = _glob_to_regex(test_glob)
        if pattern.match(path):
            if _path_in_surface(path, surface):
                return "allow", "arquivo de teste declarado em files[] de uma tarefa do contrato ativo"
            return "deny", (
                "arquivo de teste protegido: nenhuma tarefa do contrato ativo declara "
                "este arquivo em files[] - enfraquecimento de teste fora do escopo aprovado"
            )

    if _path_in_surface(path, surface):
        return "allow", "arquivo declarado em files[] de uma tarefa do contrato ativo"
    return "deny", (
        "arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este "
        "path em files[]); artefato temporario de verificacao (screenshot, dump, "
        "HTML de debug)? salve em .harness/scratch/ ; se o escopo mudou, replaneje "
        "via /harness-creator:plan"
    )


def _evaluate_bash(command, cwd):
    if is_floor_bash_command(command):
        return "deny", (
            "runtime floor: comando de push/publicacao/rede nao planejado - "
            "bloqueio incondicional, independente de contrato ativo"
        )

    if is_floor_bash_secret_redirect(command):
        return "deny", (
            "runtime floor: redirecionamento (>/>>/tee) para arquivo de segredo "
            "(.env/.pem/id_rsa/credentials) e bloqueio incondicional, independente "
            "de contrato ativo - escopo restrito a redirecionamento/tee, nao "
            "persegue escrita indireta via interpretador (python -c, node -e, etc.)"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    if "$(" in command or "`" in command:
        return "deny", (
            "command substitution ($(...) ou crase) nao permitido - cada "
            "sub-comando precisa ser declarado explicitamente na superficie do contrato"
        )

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = (
        FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES
        + [_tokenize_command(c) for c in allowed_commands]
    )

    # Allow assimetrico ao floor: o floor casa 'aparece em qualquer janela'
    # (intocado, acima); o allow segmenta o comando nos operadores de controle
    # e exige que CADA segmento prefixe alguma allowed_sequence - senao um
    # comando arbitrario colado com &&/;/| a um declarado escaparia.
    segments = _split_shell_segments(command)
    if segments and all(
        _segment_prefixes_any(_tokenize_command(seg), allowed_sequences) for seg in segments
    ):
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local)"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato "
        "(verify_cmd/lint/typecheck/build/install/git local); replaneje via "
        "/harness-creator:plan se precisar de outro comando"
    )


def _looks_like_ps_write_marker(tok):
    lower = tok.lower()
    return (
        _PS_WRITE_CMDLET_PATTERN.search(tok) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(tok) is not None
        or lower.startswith("-")
    )


def _extract_powershell_write_target(command):
    """Extrai o alvo de escrita de um comando PowerShell reconhecido como
    escrita (Set-Content/Out-File/Add-Content/redirecionamento >,>>/
    [IO.File]::WriteAllText e variantes), pra aplicar a MESMA logica de
    superficie de path do Edit/Write (_evaluate_file) sobre esse alvo.

    Heuristica por tokenizacao generica (reusa _tokenize_command, ja
    embutido pelo floor acima): devolve o primeiro token que NAO e o proprio
    cmdlet/marcador de escrita, NAO e uma flag (comeca com '-'), e TEM cara
    de path (contem '.', '/' ou '\\'). Nao e um parser completo de
    PowerShell - escopo documentado no Item 2 do backlog de correcao do
    issue #1. Devolve None se o comando nao parece um write reconhecido ou
    nenhum token com cara de path sobra apos excluir os marcadores."""
    if not command:
        return None
    is_write = (
        _PS_WRITE_CMDLET_PATTERN.search(command) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(command) is not None
        or ">" in command
    )
    if not is_write:
        return None
    for tok in _tokenize_command(command):
        if _looks_like_ps_write_marker(tok):
            continue
        if "." in tok or "/" in tok or "\\" in tok:
            return tok
    return None


def _evaluate_powershell(command, cwd):
    """Avaliador DEDICADO de PowerShell (Item 2 do backlog de correcao do
    issue #1) - deliberadamente NAO reusa _evaluate_bash: backtick e '$('
    sao sintaxe legitima e onipresente em PowerShell (escape/subexpressao),
    nao command smuggling, e PowerShell 5.1 nem suporta '&&'/'||'.

    Ordem: floor tool-agnostico PRIMEIRO (rede/publicacao, depois escrita em
    segredo - reusando is_floor_powershell_network/is_floor_powershell_secret_write,
    ja embutidos acima via inspect.getsource); depois, se ha um alvo de
    escrita reconhecido, a MESMA logica de superficie de path do Edit/Write
    (_evaluate_file, inclui docs/** do Item 4); senao, cai na mesma logica
    de superficie de COMANDO do Bash (verify_cmd/lint/build/install/git
    local/harness), sem as negacoes especificas de sintaxe Bash."""
    if is_floor_powershell_network(command):
        return "deny", (
            "runtime floor: comando de rede/publicacao (PowerShell) nao "
            "planejado - bloqueio incondicional, independente de contrato ativo"
        )

    if is_floor_powershell_secret_write(command):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo via PowerShell "
            "(.env/.pem/id_rsa/credentials) e bloqueio incondicional, "
            "independente de contrato ativo"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    target = _extract_powershell_write_target(command)
    if target is not None:
        path = _resolve_path(target, cwd)
        return _evaluate_file(path, cwd)

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = (
        FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES
        + [_tokenize_command(c) for c in allowed_commands]
    )

    segments = _split_shell_segments(command)
    if segments and all(
        _segment_prefixes_any(_tokenize_command(seg), allowed_sequences) for seg in segments
    ):
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local) - PowerShell"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato (PowerShell); "
        "replaneje via /harness-creator:plan se precisar de outro comando"
    )


# Tools read-only/utilitarias CONHECIDAS que passam sem analise de escrita
# (Item 1 do backlog de correcao do issue #1). Task e usado pelo proprio
# harness (subagentes) e NAO pode cair no branch de tool desconhecida.
_READONLY_ALLOWLIST_TOOLS = ("Read", "Glob", "Grep", "Task", "WebFetch", "TodoWrite")

# Tool NAO enumerada acima: politica MINIMA pra deploy single-user interno -
# nome com cara de escrita (contem write/create/edit, case-insensitive,
# cobre mcp__*__write*) nega por padrao; resto e allow LOGADO (risco
# residual assumido, documentado no docstring do modulo importavel).
_UNKNOWN_WRITE_NAME_PATTERN = re.compile(r"(?i)(write|create|edit)")


def main() -> None:
    try:
        import os

        data = json.load(sys.stdin)
        tool_name = data.get("tool_name") or ""
        tool_input = data.get("tool_input") or {}
        cwd = data.get("cwd") or ""
        # cwd ORIGINAL do payload, antes da troca pela ancora abaixo - e ele
        # que diz onde um file_path RELATIVO esta enraizado (ver
        # _absolutize_against_payload_cwd mais abaixo, Ressalva 3b).
        cwd_payload = cwd

        # Item 6 do backlog de correcao do issue #1 (deriva de cwd): se
        # compile-session gravou repo_root em compiled-state-session.json,
        # ancora o cwd EFETIVO usado por TODO o resto de main() (_resolve_path,
        # _load_json via _evaluate_file/_evaluate_bash/_evaluate_powershell, e
        # _evaluate_feature_list_edit) na raiz real do repo, em vez do cwd do
        # payload - que pode ter derivado (ex.: agente rodou cd frontend/ sem
        # voltar). __file__ e o proprio script instalado, que sempre mora em
        # <repo_root>/.harness/hooks/boundary_guard.py - subir a partir dali
        # sempre alcanca a raiz real, mesmo com cwd do payload derivado.
        # Fallback obrigatorio: sem state, sem a chave, JSON invalido, ou
        # diretorio que nao existe mais -> None, cwd do payload intocado
        # (comportamento atual, repos sem compile-session recente nao quebram).
        repo_root_anchor = _resolve_repo_root_anchor(__file__)
        if repo_root_anchor:
            cwd = repo_root_anchor

        def _absolutize_against_payload_cwd(raw_path):
            """Ressalva 3b (validacao Opus pos-implementacao do Item 6): a
            troca incondicional de cwd pela ancora acima resolve certo pra
            file_path ABSOLUTO (o caso comum - as tools de escrita do Claude
            Code mandam path absoluto), mas quebraria um file_path RELATIVO a
            um cwd derivado (ex.: shell preso em <repo>/frontend, tool manda
            'x.ts' querendo 'frontend/x.ts'): avaliar 'x.ts' bruto contra a
            raiz ancorada ('<repo>') daria falso-deny (fail-safe, nunca abre
            um bypass, mas e exatamente a classe de falso-deny que o Item 6
            quer eliminar). Fix: se raw_path for relativo, absolutiza-o
            contra cwd_payload (o cwd ORIGINAL do payload, capturado ANTES da
            troca pela ancora acima - e ele que diz onde um path relativo
            esta enraizado) antes de qualquer strip de prefixo pela ancora.
            Path absoluto passa inalterado. Zero subprocess - so os.path
            (stdlib), nenhuma logica de parsing nova."""
            if not raw_path or os.path.isabs(raw_path):
                return raw_path
            if not cwd_payload:
                return raw_path
            return os.path.normpath(os.path.join(cwd_payload, raw_path))

        if tool_name in ("Edit", "Write"):
            path = _resolve_path(
                _absolutize_against_payload_cwd(tool_input.get("file_path") or ""), cwd
            )
            special = None
            if path == FEATURE_LIST_PATH:
                special = _evaluate_feature_list_edit(tool_name, tool_input, cwd)
            if special is not None:
                decision, reason = special
            else:
                decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "MultiEdit":
            # MultiEdit e uma tool de escrita REAL do Claude Code (multiplas
            # edicoes old_string/new_string sobre um UNICO arquivo,
            # tool_input.file_path). Antes desta correcao (achado adversarial
            # pos-implementacao, validacao Opus) MultiEdit nao estava
            # roteada aqui e caia no ramo de tool desconhecida - o nome
            # contem "edit", entao era deny SEMPRE, mesmo dentro da
            # superficie aprovada (fail-safe, mas quebrava fluxo legitimo).
            # NAO tenta o caso especial de feature-lock (_evaluate_feature_list_edit
            # espera o formato de tool_input do Edit/Write simples, nao o
            # array `edits[]` do MultiEdit) - uma MultiEdit sobre
            # feature_list.json cai na superficie generica (hoje ja resulta
            # em deny, mesmo comportamento seguro-por-padrao documentado
            # para Edit/Write quando nao ha transicao para passes:true).
            path = _resolve_path(
                _absolutize_against_payload_cwd(tool_input.get("file_path") or ""), cwd
            )
            decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "NotebookEdit":
            # tool_input do NotebookEdit documentado (tools-reference do
            # Claude Code) usa o formato de path do Edit/Write; o campo
            # exato nao foi exposto pela doc publica consultada, entao
            # tentamos notebook_path (assumido) com fallback pra file_path -
            # qualquer um dos dois ainda passa pela MESMA avaliacao de
            # superficie/floor de _evaluate_file, sem enfraquecer nada.
            raw_path = tool_input.get("notebook_path") or tool_input.get("file_path") or ""
            path = _resolve_path(_absolutize_against_payload_cwd(raw_path), cwd)
            decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "PowerShell":
            command = tool_input.get("command") or ""
            decision, reason = _evaluate_powershell(command, cwd)
        elif tool_name == "Bash":
            command = tool_input.get("command") or ""
            decision, reason = _evaluate_bash(command, cwd)
        elif tool_name in _READONLY_ALLOWLIST_TOOLS:
            decision, reason = "allow", (
                "ferramenta read-only/utilitaria conhecida, fora do escopo de "
                "escrita do boundary_guard"
            )
        else:
            if _UNKNOWN_WRITE_NAME_PATTERN.search(tool_name):
                decision, reason = "deny", (
                    "tool desconhecida com nome de escrita (contem write/create/edit) - "
                    "boundary_guard nega por padrao ate ser roteada explicitamente; se "
                    "for uma tool read-only legitima, adicione-a a allowlist conhecida"
                )
            else:
                decision, reason = "allow", (
                    "tool desconhecida fora do padrao de nome de escrita conhecido - "
                    "allow-logado (politica minima de deploy single-user interno; "
                    "risco residual assumido, ver docstring de harness.boundary_guard)"
                )
    except Exception as exc:
        decision, reason = "deny", (
            "boundary_guard: erro interno ao avaliar a tool call (" + repr(exc) + ") - "
            "fail-closed por seguranca; corrija o payload/ambiente e tente de novo"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
