"""Hook Stop gerado pelo harness-creator — NAO editar a mao.

Ao encerrar a sessao, verifica se ha alguma feature "em progresso" (passes
false + trabalho nao commitado tocando os files da feature) cuja
verificacao nunca rodou ou esta desatualizada, e devolve feedback ao agente
pedindo para rodar `harness verify <id>` antes de encerrar.

Schema de saida: hookSpecificOutput.additionalContext (Stop NAO bloqueia
via este caminho - o campo de bloqueio seria o `decision: "block"` de topo,
nao usado aqui de proposito).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FEATURE_LIST_FILE = ".harness/feature_list.json"
EVIDENCE_DIR = ".harness/evidence"


def compute_files_hash(files, target_dir):
    digest = hashlib.sha256()
    for rel_path in sorted(files):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\n")
        file_path = target_dir / rel_path
        if file_path.is_file():
            digest.update(file_path.read_bytes())
        else:
            digest.update(b"<missing>\n")
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def is_feature_in_progress(feature, target_dir):
    if feature.get("passes", False):
        return False

    files = feature.get("files") or []
    if not files:
        return False

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", *files],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def needs_verification(feature, target_dir):
    if not is_feature_in_progress(feature, target_dir):
        return False

    feature_id = feature.get("id", "")
    evidence_path = target_dir / EVIDENCE_DIR / (feature_id + ".json")
    if not evidence_path.is_file():
        return True

    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return True

    recorded_hash = evidence.get("files_hash")
    current_hash = compute_files_hash(feature.get("files") or [], target_dir)
    return recorded_hash != current_hash


def _load_features(cwd):
    path = cwd / FEATURE_LIST_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("features") or []


def build_feedback(cwd):
    pending_ids = []
    for feature in _load_features(cwd):
        if needs_verification(feature, cwd):
            pending_ids.append(feature.get("id", "?"))

    if not pending_ids:
        return None

    ids = ", ".join(pending_ids)
    return (
        "Feature(s) em progresso sem verificacao atualizada: " + ids + ". "
        "Rode `harness verify <id>` antes de encerrar a sessao para gravar "
        "a evidencia em .harness/evidence/<id>.json."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or ".")
    message = build_feedback(cwd)
    if message is None:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
