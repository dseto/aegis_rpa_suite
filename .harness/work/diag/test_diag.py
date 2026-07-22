"""Diagnostico read-only: snapshot de processos (tasklist + CIM) gravado em
.harness/work/diag/proc_snapshot.txt. Nao mata nada, nao altera nada.
Criado para investigar o travamento do `harness verify T-07` (2026-07-22)."""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent / "proc_snapshot.txt"


def test_diag_proc_snapshot():
    chunks = []
    try:
        r = subprocess.run(
            ["tasklist", "/fo", "csv"],
            capture_output=True, text=True, timeout=60,
        )
        chunks.append("=== tasklist ===\n" + r.stdout + "\n" + r.stderr)
    except Exception as exc:  # pragma: no cover
        chunks.append(f"tasklist FAILED: {exc!r}")

    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \""
        "Name like '%python%' or Name like '%pytest%' or Name like '%cmd%'"
        " or Name like '%chrome%' or Name like '%node%' or Name like '%bash%'\""
        " | Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine"
        " | ConvertTo-Json -Depth 2"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=120,
        )
        chunks.append("=== cim python/cmd/chrome/node/bash ===\n" + r.stdout + "\n" + r.stderr)
    except Exception as exc:  # pragma: no cover
        chunks.append(f"cim FAILED: {exc!r}")

    OUT.write_text("\n\n".join(chunks), encoding="utf-8")
    assert OUT.is_file()
