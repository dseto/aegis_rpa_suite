"""
Testa a política anti-drift do Ralph Loop (`_restore_deterministic_blocks`)
e o ciclo de vida do manifest de proveniência (H5 do plano híbrido, Seções
2.4 e 5.2 de `.specs/plano-codegen-hibrido-deterministico.md`).

Cobre os 9 cenários do DoD:
  1. Bloco adulterado FORA do escopo -> restaurado à forma canônica.
  2. Bloco adulterado DENTRO do escopo -> preservado (não restaurado).
  3. Bloco AUSENTE (âncora removida) -> ignorado sem erro.
  4. `after_step_id` de `required_reopen` pendente -> poupado (via
     `_compute_restore_target_scope` + `_restore_deterministic_blocks`).
  5. Manifest stale (`plan_checksum` divergente) -> no-op.
  6. Sem manifest -> no-op.
  7. Erro de ORDEM/CONTAGEM apontando bloco restaurado -> NÃO dispara
     fail-fast.
  8. Erro de CONTEÚDO em bloco restaurado na mesma tentativa -> dispara
     `RuntimeError`.
  9. Rota full-LLM grava manifest `{'generator_version': 'full-llm', 'steps': {}}`.

Executar com: python aegis_code_generator/test_restore_deterministic_blocks.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_code_generator.code_generator import CodeGeneratorService
from aegis_code_generator.deterministic_emitter import (
    emit_step_block,
    _plan_checksum,
    _STEP_ANCHOR_RENUMBER_RE,
)


# ---------------------------------------------------------------------------
# Fixtures compartilhadas
# ---------------------------------------------------------------------------

STEPS = [
    {"step_id": "st_001", "type": "click", "description": "Abrir menu", "selector": "#menu"},
    {"step_id": "st_002", "type": "fill", "description": "Preencher nome", "selector": "#nome"},
    {"step_id": "st_003", "type": "click", "description": "Confirmar", "selector": "#confirmar"},
]
PLAN = {"steps": STEPS}
DICIONARIO = {"fields": {"nome_usuario": {"selector": "#nome", "fill_strategy": "DIRECT"}}}

# Um plano "diferente" (mesmos steps, mas serializado com um campo a mais)
# só para produzir um plan_checksum divergente — usado no cenário de
# manifest stale.
STALE_PLAN = {"steps": STEPS, "extra_marker": "outra-sanitizacao"}


def _service():
    return CodeGeneratorService(project_dir=os.path.dirname(os.path.abspath(__file__)))


def _canonical_block(step, dicionario, label):
    """Bloco canônico de `step`, com a âncora '# [PASSO N]' renumerada pra
    `label` — a mesma forma que `build_skeleton` produziria no arquivo."""
    canonical = emit_step_block(step, dicionario)
    return _STEP_ANCHOR_RENUMBER_RE.sub(rf"\1# [PASSO {label}]", canonical, count=1)


def _build_bot_code(steps, dicionario, tamper=None):
    """
    Monta um bot_code sintético com um bloco '# [PASSO N]' canônico por
    step (via emit_step_block real), numerado sequencialmente (1, 2, 3...)
    como build_skeleton faria. `tamper` é um dict step_id -> texto de bloco
    substituto (simula drift introduzido pela LLM em alguma tentativa do
    Ralph Loop). Um valor de `tamper` sem nenhuma linha '# [PASSO ...]'
    simula uma âncora REMOVIDA (bloco "ausente" pro parser).
    """
    tamper = tamper or {}
    blocks = []
    for i, step in enumerate(steps, start=1):
        step_id = step["step_id"]
        if step_id in tamper:
            blocks.append(tamper[step_id])
        else:
            blocks.append(_canonical_block(step, dicionario, str(i)))
    body = "\n".join(blocks)
    return f"def execute_scenario_default(page, row, runner):\n{body}\n"


def _manifest_for(steps, plan, provenance_map=None):
    provenance_map = provenance_map or {}
    steps_manifest = {}
    for step in steps:
        sid = step["step_id"]
        steps_manifest[sid] = {
            "provenance": provenance_map.get(sid, "deterministic"),
            "reason": "C1-C10 satisfeitas",
            "block_sha1": "irrelevante-so-telemetria",
        }
    return {
        "generator_version": "hybrid-1",
        "generated_at": "2026-07-12T00:00:00+00:00",
        "plan_checksum": _plan_checksum(plan),
        "steps": steps_manifest,
    }


TAMPERED_ST001 = (
    "    # [PASSO 1] Abrir menu\n"
    '    runner.click_resilient(\n'
    '        page,\n'
    '        selector="#menu-alterado-pela-llm",\n'
    '        target_description="Abrir menu",\n'
    '        step_id="st_001"\n'
    "    )"
)

# Simula uma âncora REMOVIDA num rewrite full-file: nenhuma linha
# '# [PASSO ...]' presente pra este trecho -> _parse_step_blocks nunca vê
# este step como um bloco independente.
MISSING_ANCHOR_ST001 = (
    '    runner.click_resilient(page, selector="#menu", '
    'target_description="Abrir menu", step_id="st_001")'
)


# ---------------------------------------------------------------------------
# 1. Bloco adulterado FORA do escopo -> restaurado
# ---------------------------------------------------------------------------

def test_drifted_block_outside_scope_is_restored():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO, tamper={"st_001": TAMPERED_ST001})
    manifest = _manifest_for(STEPS, PLAN)

    new_code, restored = service._restore_deterministic_blocks(
        bot_code, manifest, set(), PLAN, DICIONARIO
    )

    assert restored == ["st_001"], f"Esperava restaurar st_001, obteve {restored}"
    assert "#menu-alterado-pela-llm" not in new_code, "Drift não foi revertido"
    assert 'selector="#menu"' in new_code, "Forma canônica não foi re-spliceada"
    print("[OK] test_drifted_block_outside_scope_is_restored")


# ---------------------------------------------------------------------------
# 2. Bloco adulterado DENTRO do escopo -> preservado
# ---------------------------------------------------------------------------

def test_drifted_block_inside_scope_is_preserved():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO, tamper={"st_001": TAMPERED_ST001})
    manifest = _manifest_for(STEPS, PLAN)

    new_code, restored = service._restore_deterministic_blocks(
        bot_code, manifest, {"st_001"}, PLAN, DICIONARIO
    )

    assert restored == [], f"st_001 está no target_scope — não deveria ser restaurado, obteve {restored}"
    assert "#menu-alterado-pela-llm" in new_code, "Correção legítima dentro do escopo foi revertida indevidamente"
    print("[OK] test_drifted_block_inside_scope_is_preserved")


# ---------------------------------------------------------------------------
# 3. Bloco AUSENTE -> ignorado sem erro
# ---------------------------------------------------------------------------

def test_missing_block_is_ignored_without_error():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO, tamper={"st_001": MISSING_ANCHOR_ST001})
    manifest = _manifest_for(STEPS, PLAN)

    # Não deve levantar exceção nenhuma.
    new_code, restored = service._restore_deterministic_blocks(
        bot_code, manifest, set(), PLAN, DICIONARIO
    )

    assert "st_001" not in restored, "Bloco ausente não deveria entrar em 'restored'"
    # st_002/st_003 continuam presentes e canônicos (nenhum efeito colateral).
    assert 'step_id="st_002"' in new_code
    assert 'step_id="st_003"' in new_code
    print("[OK] test_missing_block_is_ignored_without_error")


# ---------------------------------------------------------------------------
# 4. after_step_id de required_reopen pendente -> poupado
# ---------------------------------------------------------------------------

def test_reopen_after_step_id_is_spared():
    service = _service()
    # st_002 está drifted; a correção pendente mira st_003 mas exige um
    # re-disparo cujo 'after_step_id' é st_002 — o bloco de st_002 precisa
    # ficar de fora do restore (Seção 5.2, achado M1).
    bot_code = _build_bot_code(
        STEPS, DICIONARIO,
        tamper={"st_002": (
            '    # [PASSO 2] Preencher nome\n'
            '    runner.fill_resilient(\n'
            '        page,\n'
            '        selector="#nome",\n'
            '        text_val=row.get("nome_usuario", ""),\n'
            '        target_description="Preencher nome",\n'
            '        strategy="DIRECT",\n'
            '        step_id="st_002"\n'
            '    )\n'
            '    runner.fill_resilient(page, selector="#nome", text_val=row.get("nome_usuario", ""), '
            'target_description="Re-disparo", strategy="DIRECT", step_id="st_002")'
        )},
    )
    manifest = _manifest_for(STEPS, PLAN)
    pending_corrections = [
        {"step_id": "st_003", "required_reopen": {"after_step_id": "st_002"}}
    ]

    target_scope = service._compute_restore_target_scope(pending_corrections, None, bot_code)
    assert "st_002" in target_scope, "after_step_id do required_reopen deveria entrar no target_scope"
    assert "st_003" in target_scope, "step_id da própria correção deveria entrar no target_scope"

    new_code, restored = service._restore_deterministic_blocks(
        bot_code, manifest, target_scope, PLAN, DICIONARIO
    )
    assert "st_002" not in restored, "Bloco de after_step_id foi restaurado — reverteria o re-disparo exigido"
    assert "Re-disparo" in new_code, "Re-disparo do required_reopen foi apagado indevidamente"
    print("[OK] test_reopen_after_step_id_is_spared")


# ---------------------------------------------------------------------------
# 5. Manifest stale (plan_checksum divergente) -> no-op
# ---------------------------------------------------------------------------

def test_stale_plan_checksum_is_noop():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO, tamper={"st_001": TAMPERED_ST001})
    # Manifest carimbado contra STALE_PLAN (checksum diferente do PLAN atual).
    manifest = _manifest_for(STEPS, STALE_PLAN)

    new_code, restored = service._restore_deterministic_blocks(
        bot_code, manifest, set(), PLAN, DICIONARIO
    )

    assert restored == [], "plan_checksum divergente deveria degradar pra no-op"
    assert new_code == bot_code, "Código não deveria ser tocado em manifest stale"
    print("[OK] test_stale_plan_checksum_is_noop")


# ---------------------------------------------------------------------------
# 6. Sem manifest -> no-op
# ---------------------------------------------------------------------------

def test_no_manifest_is_noop():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO, tamper={"st_001": TAMPERED_ST001})

    new_code, restored = service._restore_deterministic_blocks(
        bot_code, None, set(), PLAN, DICIONARIO
    )

    assert restored == [], "Sem manifest, restore deveria ser no-op"
    assert new_code == bot_code
    print("[OK] test_no_manifest_is_noop")


# ---------------------------------------------------------------------------
# 7. Erro de ORDEM/CONTAGEM apontando bloco restaurado -> NÃO dispara fail-fast
# ---------------------------------------------------------------------------

def test_order_error_on_restored_block_does_not_trigger_failfast():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO)  # tudo canônico, sem drift
    restored = ["st_001"]
    errors = [
        {"type": "STEP_ID_MISMATCH", "position": 1, "expected_id": "st_001", "found_id": "st_002"},
        {"type": "COUNT_MISMATCH", "expected": 3, "found": 3},
        {"type": "MISSING_STEPS", "step_ids": ["st_001"]},
        {"type": "EXTRA_STEPS", "step_ids": ["st_001"]},
    ]

    # Não deve levantar RuntimeError.
    service._enforce_restore_fail_fast(errors, restored, bot_code)
    print("[OK] test_order_error_on_restored_block_does_not_trigger_failfast")


# ---------------------------------------------------------------------------
# 8. Erro de CONTEÚDO em bloco restaurado na mesma tentativa -> RuntimeError
# ---------------------------------------------------------------------------

def test_content_error_on_restored_block_triggers_failfast():
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO)
    restored = ["st_001"]
    errors = [
        {"type": "MISSING_ORIGINAL_COORDS", "step_id": "st_001", "detail": "..."},
    ]

    raised = False
    try:
        service._enforce_restore_fail_fast(errors, restored, bot_code)
    except RuntimeError as e:
        raised = True
        assert "st_001" in str(e)
        assert "deterministic_emitter" in str(e)
    assert raised, "Erro de CONTEÚDO em bloco restaurado deveria disparar RuntimeError"
    print("[OK] test_content_error_on_restored_block_triggers_failfast")


def test_content_error_via_lineno_on_restored_block_triggers_failfast():
    """Mesma checagem, mas o erro só carrega 'lineno' (típico de erros
    AST-level de validate_bot_structure) em vez de 'step_id' — precisa
    resolver via _parse_step_blocks."""
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO)
    blocks = service._parse_step_blocks(bot_code)
    st_001_block = next(b for b in blocks if b["step_id"] == "st_001")
    lineno_inside_block = st_001_block["start"] + 2  # 1-based, dentro do bloco

    restored = ["st_001"]
    errors = [
        {"type": "HALLUCINATED_RUNNER_METHOD", "lineno": lineno_inside_block, "detail": "..."},
    ]

    raised = False
    try:
        service._enforce_restore_fail_fast(errors, restored, bot_code)
    except RuntimeError:
        raised = True
    assert raised, "Erro de CONTEÚDO resolvido via lineno deveria disparar RuntimeError"
    print("[OK] test_content_error_via_lineno_on_restored_block_triggers_failfast")


def test_content_error_on_non_restored_block_does_not_trigger_failfast():
    """Erro de conteúdo, mas em um bloco que NÃO foi restaurado nesta
    tentativa -> não é bug do emissor, segue o fluxo normal."""
    service = _service()
    bot_code = _build_bot_code(STEPS, DICIONARIO)
    restored = ["st_002"]  # st_001 não foi restaurado
    errors = [
        {"type": "MISSING_ORIGINAL_COORDS", "step_id": "st_001", "detail": "..."},
    ]

    service._enforce_restore_fail_fast(errors, restored, bot_code)  # não deve levantar
    print("[OK] test_content_error_on_non_restored_block_does_not_trigger_failfast")


# ---------------------------------------------------------------------------
# 9. Rota full-LLM grava manifest {'generator_version': 'full-llm', 'steps': {}}
# ---------------------------------------------------------------------------

def test_full_llm_route_writes_empty_manifest():
    service = _service()

    # Sem manifest pré-existente -> payload full-llm vazio.
    payload = service._finalize_generation_manifest(None, set(), reason="n/a")
    assert payload == {"generator_version": "full-llm", "steps": {}}

    # Manifest pré-existente sem 'steps' (ou vazio) -> mesmo resultado.
    payload2 = service._finalize_generation_manifest({"steps": {}}, set(), reason="n/a")
    assert payload2 == {"generator_version": "full-llm", "steps": {}}

    tmp_dir = tempfile.mkdtemp(prefix="aegis_test_manifest_")
    try:
        service._write_generation_manifest(tmp_dir, payload)
        manifest_path = os.path.join(tmp_dir, "generation_manifest.json")
        assert os.path.exists(manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk == {"generator_version": "full-llm", "steps": {}}

        # _load_generation_manifest deve conseguir ler de volta.
        loaded = service._load_generation_manifest(tmp_dir)
        assert loaded == {"generator_version": "full-llm", "steps": {}}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("[OK] test_full_llm_route_writes_empty_manifest")


def test_finalize_manifest_patches_legitimate_correction_when_manifest_preexists():
    """
    Quando UM manifest com steps já existia (bot híbrido de um run
    anterior), a correção legítima de um step em target_scope vira
    'cognitive_patched' em vez de ser descartada silenciosamente.
    """
    service = _service()
    existing = _manifest_for(STEPS, PLAN)  # todos 'deterministic'

    patched = service._finalize_generation_manifest(existing, {"st_002"}, reason="corrigido por QA")

    assert patched["steps"]["st_002"]["provenance"] == "cognitive_patched"
    assert patched["steps"]["st_002"]["reason"] == "corrigido por QA"
    # Steps fora do target_scope permanecem 'deterministic'.
    assert patched["steps"]["st_001"]["provenance"] == "deterministic"
    assert patched["steps"]["st_003"]["provenance"] == "deterministic"
    # Não muta o dict original.
    assert existing["steps"]["st_002"]["provenance"] == "deterministic"
    print("[OK] test_finalize_manifest_patches_legitimate_correction_when_manifest_preexists")


if __name__ == "__main__":
    test_drifted_block_outside_scope_is_restored()
    test_drifted_block_inside_scope_is_preserved()
    test_missing_block_is_ignored_without_error()
    test_reopen_after_step_id_is_spared()
    test_stale_plan_checksum_is_noop()
    test_no_manifest_is_noop()
    test_order_error_on_restored_block_does_not_trigger_failfast()
    test_content_error_on_restored_block_triggers_failfast()
    test_content_error_via_lineno_on_restored_block_triggers_failfast()
    test_content_error_on_non_restored_block_does_not_trigger_failfast()
    test_full_llm_route_writes_empty_manifest()
    test_finalize_manifest_patches_legitimate_correction_when_manifest_preexists()
    print("\nTodos os testes passaram.")
