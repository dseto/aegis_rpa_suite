"""Hook SessionStart gerado pelo harness-creator — NAO editar a mao.

Injeta contexto no inicio da sessao: resumo do progresso
(claude-progress.md), a feature ativa/pendente (.harness/feature_list.json)
e o `git log` recente, para o agente nascer sabendo onde parou.

Schema de saida: hookSpecificOutput.additionalContext (SessionStart nao
bloqueia nada, ao contrario de PreToolUse que usa permissionDecision).
"""
import json
import subprocess
import sys
from pathlib import Path


def _read_feature_summary(cwd: Path) -> str:
    path = cwd / ".harness" / "feature_list.json"
    if not path.is_file():
        return "Nenhum contrato ativo (.harness/feature_list.json nao encontrado)."
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return "Nenhum contrato ativo (.harness/feature_list.json invalido)."

    features = data.get("features") or []
    if not features:
        return "Nenhuma feature pendente (contrato sem features)."

    for feature in features:
        if not feature.get("passes", False):
            fid = feature.get("id", "?")
            desc = feature.get("desc") or feature.get("description") or feature.get("title") or ""
            label = f"Feature ativa/pendente: {fid}"
            if desc:
                label += f" - {desc}"
            return label

    return "Nenhuma feature pendente (todas as features do contrato ja passam)."


def _read_progress(cwd: Path) -> str | None:
    path = cwd / "claude-progress.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    tail = lines[-20:]
    joined = "\n".join(tail).strip()
    return joined or None


def _read_git_log(cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-n", "5", "--oneline"],
            cwd=str(cwd),
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


def build_context(cwd: Path) -> str:
    parts = ["## Estado da sessao anterior (injetado pelo harness)"]
    parts.append(_read_feature_summary(cwd))

    progress = _read_progress(cwd)
    if progress:
        parts.append("### Progresso recente (claude-progress.md)\n" + progress)

    git_log = _read_git_log(cwd)
    if git_log:
        parts.append("### git log -n 5 --oneline\n" + git_log)

    return "\n\n".join(parts)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or ".")
    context = build_context(cwd)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
