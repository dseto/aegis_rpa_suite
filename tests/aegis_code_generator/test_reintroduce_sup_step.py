"""
Testa a rota determinística de reintrodução de `sup_` via correção pendente
`reintroduce_step_id` (H6 do plano híbrido — Seção 3.1 de
.specs/plano-codegen-hibrido-deterministico.md).

Cobre os cenários do DoD (teste 4.1(3) do plano + requisitos da tarefa H6):
  T1 - unidade: `_apply_deterministic_sup_reintroductions` insere o bloco do
       `sup_` reintroduzido na posição relativa correta (entre os vizinhos
       certos do plano), sempre com wrapper try/except não-fatal.
  T2 - idempotência: chamar de novo sobre o código já reintroduzido não
       duplica o bloco.
  T3 - vizinho anterior ausente (sup_ é o primeiro step do plano) -> insere
       ANTES do próximo vizinho emitido.
  T4 - `reintroduce_step_id` inexistente no plano -> no-op, sem crash.
  T5 - `reintroduce_step_id` de tipo não suportado pelo emissor -> no-op,
       sem crash (ValueError de `emit_step_block` é engolida).
  T6 (integração, teste central do DoD) - `_generate_new_code`/`_generate_new_code_hybrid`
       de ponta a ponta, geração híbrida SEM slots cognitivos (zero chamadas
       LLM) + correção `reintroduce_step_id: "sup_003"` -> bot final contém
       o bloco de `sup_003` na posição relativa correta,
       `validate_bot_against_plan` retorna PASS, e o manifest registra
       `sup_003` com `provenance: "deterministic"` e `reason` citando a
       reintrodução.

Executar com: python aegis_code_generator/test_reintroduce_sup_step.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aegis_code_generator.code_generator import CodeGeneratorService
from aegis_code_generator.step_validator import validate_bot_against_plan

FRAMEWORK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Plano com 2 sup_ (um antes de tudo, um no meio) intercalados com 2 steps
# emitíveis simples (click, sem parent/weak_selector/menu -> deterministic
# por construção, zero slot cognitivo).
PLAN_REINTRODUCE = {
    "steps": [
        {
            "step_id": "sup_000", "type": "click", "execution_hint": "skip",
            "description": "Fechar popup inicial (ruído)", "selector": "#popup-close",
        },
        {
            "step_id": "st_001", "type": "click",
            "description": "Abrir formulário", "selector": "#abrir",
        },
        {
            "step_id": "sup_003", "type": "click", "execution_hint": "skip",
            "description": "Fechar overlay residual", "selector": ".cdk-overlay-backdrop",
        },
        {
            "step_id": "st_002", "type": "click",
            "description": "Confirmar", "selector": "#confirmar",
        },
    ]
}
DICIONARIO_REINTRODUCE = {"fields": {}}

# Código já com st_001/st_002 emitidos (simula o skeleton pós-build, ANTES
# de qualquer reintrodução) — usado pelos testes unitários T1-T5.
BASE_CODE = (
    'def execute_scenario_default(page, row, runner):\n'
    '    # [PASSO 1] Abrir formulário\n'
    '    runner.click_resilient(page, selector="#abrir", target_description="Abrir formulário", step_id="st_001")\n'
    '    # [PASSO 2] Confirmar\n'
    '    runner.click_resilient(page, selector="#confirmar", target_description="Confirmar", step_id="st_002")\n'
)


class FakeGateway:
    """Gateway falso: qualquer chamada nesta suíte estoura (zero slots cognitivos esperados)."""

    def __init__(self):
        self.provider = "fake"
        self.model = "fake-model"
        self.calls = 0

    def _call_llm_api(self, prompt, force_json=False):
        self.calls += 1
        raise AssertionError("FakeGateway: nenhuma chamada LLM era esperada nesta suíte (zero slots cognitivos).")


def _make_project(plan: dict) -> str:
    tmp_dir = tempfile.mkdtemp(prefix="aegis_test_reintro_")
    with open(os.path.join(tmp_dir, "plano_execucao.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return tmp_dir


# ---------------------------------------------------------------------------
# T1 - inserção no meio (vizinho anterior emitido presente: st_001).
# ---------------------------------------------------------------------------

def test_reintroduce_middle_position_and_wrapper():
    service = CodeGeneratorService(project_dir="unused_project_dir")
    pending = [{"status": "pending", "reintroduce_step_id": "sup_003", "qa_insight": "Overlay residual"}]

    new_code, reintroduced = service._apply_deterministic_sup_reintroductions(
        BASE_CODE, pending, PLAN_REINTRODUCE, DICIONARIO_REINTRODUCE
    )

    assert "sup_003" in reintroduced
    assert reintroduced["sup_003"]["provenance"] == "deterministic"
    assert "reintrodu" in reintroduced["sup_003"]["reason"], (
        "Reason do manifest deveria citar a reintrodução."
    )

    assert 'step_id="sup_003"' in new_code
    assert "try:" in new_code and "except Exception as _opt_err:" in new_code
    assert "Passo opcional sup_003 pulado (não-fatal)" in new_code

    pos_st001 = new_code.index('step_id="st_001"')
    pos_sup003 = new_code.index('step_id="sup_003"')
    pos_st002 = new_code.index('step_id="st_002"')
    assert pos_st001 < pos_sup003 < pos_st002, (
        "sup_003 deveria ficar entre st_001 e st_002 (ordem relativa do plano)."
    )
    print("[OK] test_reintroduce_middle_position_and_wrapper")


# ---------------------------------------------------------------------------
# T2 - idempotência: reintroduzir de novo sobre o código já reintroduzido
# não duplica o bloco.
# ---------------------------------------------------------------------------

def test_reintroduce_is_idempotent():
    service = CodeGeneratorService(project_dir="unused_project_dir")
    pending = [{"reintroduce_step_id": "sup_003"}]

    code_v1, reintroduced_v1 = service._apply_deterministic_sup_reintroductions(
        BASE_CODE, pending, PLAN_REINTRODUCE, DICIONARIO_REINTRODUCE
    )
    assert reintroduced_v1

    code_v2, reintroduced_v2 = service._apply_deterministic_sup_reintroductions(
        code_v1, pending, PLAN_REINTRODUCE, DICIONARIO_REINTRODUCE
    )
    assert reintroduced_v2 == {}, "Segunda chamada não deveria reintroduzir de novo (idempotência)."
    assert code_v2 == code_v1, "Código não deveria mudar numa chamada repetida (sem duplicar bloco)."
    assert code_v2.count('step_id="sup_003"') == 1
    print("[OK] test_reintroduce_is_idempotent")


# ---------------------------------------------------------------------------
# T3 - sup_ é o primeiro step do plano (sem vizinho anterior emitido) ->
# insere ANTES do próximo vizinho emitido (st_001).
# ---------------------------------------------------------------------------

def test_reintroduce_first_step_inserts_before_next_neighbor():
    service = CodeGeneratorService(project_dir="unused_project_dir")
    pending = [{"reintroduce_step_id": "sup_000"}]

    new_code, reintroduced = service._apply_deterministic_sup_reintroductions(
        BASE_CODE, pending, PLAN_REINTRODUCE, DICIONARIO_REINTRODUCE
    )

    assert "sup_000" in reintroduced
    pos_sup000 = new_code.index('step_id="sup_000"')
    pos_st001 = new_code.index('step_id="st_001"')
    assert pos_sup000 < pos_st001, "sup_000 (primeiro step do plano) deveria vir ANTES de st_001."
    print("[OK] test_reintroduce_first_step_inserts_before_next_neighbor")


# ---------------------------------------------------------------------------
# T4 - reintroduce_step_id inexistente no plano -> no-op, sem crash.
# ---------------------------------------------------------------------------

def test_reintroduce_nonexistent_step_id_is_noop():
    service = CodeGeneratorService(project_dir="unused_project_dir")
    pending = [{"reintroduce_step_id": "sup_999"}]

    new_code, reintroduced = service._apply_deterministic_sup_reintroductions(
        BASE_CODE, pending, PLAN_REINTRODUCE, DICIONARIO_REINTRODUCE
    )

    assert reintroduced == {}
    assert new_code == BASE_CODE, "Código não deveria mudar quando o id reintroduzido não existe no plano."
    print("[OK] test_reintroduce_nonexistent_step_id_is_noop")


# ---------------------------------------------------------------------------
# T5 - reintroduce_step_id de tipo não suportado pelo emissor determinístico
# (ex.: 'filechooser') -> no-op, sem crash (ValueError engolida).
# ---------------------------------------------------------------------------

def test_reintroduce_unsupported_type_is_noop():
    service = CodeGeneratorService(project_dir="unused_project_dir")
    plan_unsupported = {
        "steps": [
            {
                "step_id": "sup_005", "type": "filechooser", "execution_hint": "skip",
                "description": "Upload de arquivo (ruído)",
            },
        ]
    }
    pending = [{"reintroduce_step_id": "sup_005"}]

    new_code, reintroduced = service._apply_deterministic_sup_reintroductions(
        BASE_CODE, pending, plan_unsupported, DICIONARIO_REINTRODUCE
    )

    assert reintroduced == {}
    assert new_code == BASE_CODE
    print("[OK] test_reintroduce_unsupported_type_is_noop")


# ---------------------------------------------------------------------------
# T6 (teste central do DoD - 4.1(3) do plano) - integração de ponta a ponta
# via `_generate_new_code` (rota híbrida, zero slots cognitivos): bot final
# contém sup_003 na posição relativa correta, validate_bot_against_plan PASS,
# manifest registra provenance 'deterministic' com reason citando a
# reintrodução.
# ---------------------------------------------------------------------------

def test_end_to_end_hybrid_generation_reintroduces_sup_and_passes_plan_validation():
    tmp_dir = _make_project(PLAN_REINTRODUCE)
    try:
        dict_path = os.path.join(tmp_dir, "dicionario.json")
        with open(dict_path, "w", encoding="utf-8") as f:
            json.dump(DICIONARIO_REINTRODUCE, f)

        service = CodeGeneratorService(project_dir=tmp_dir)
        gateway = FakeGateway()
        correcoes_path = os.path.join(tmp_dir, "correcoes_acumuladas.json")
        pending_corrections = [
            {"status": "pending", "reintroduce_step_id": "sup_003", "qa_insight": "Overlay residual precisa ser fechado"}
        ]

        os.environ["AEGIS_CODEGEN_HYBRID"] = "true"
        try:
            result = service._generate_new_code(
                bot_path="unused_bot_path.py",
                dict_data=DICIONARIO_REINTRODUCE,
                report_content="relatorio fake de telemetria",
                skills_info_prompt="",
                pending_corrections=pending_corrections,
                gateway=gateway,
                project_json_path="unused_project.json",
                code_dir="unused_code_dir",
                correcoes_acumuladas_path=correcoes_path,
            )
        finally:
            os.environ.pop("AEGIS_CODEGEN_HYBRID", None)

        assert gateway.calls == 0, "Zero slots cognitivos no plano -> zero chamadas LLM, mesmo com reintrodução"
        assert result is not None

        assert 'step_id="sup_003"' in result
        assert "Passo opcional sup_003 pulado (não-fatal)" in result
        pos_st001 = result.index('step_id="st_001"')
        pos_sup003 = result.index('step_id="sup_003"')
        pos_st002 = result.index('step_id="st_002"')
        assert pos_st001 < pos_sup003 < pos_st002

        manifest = service._hybrid_manifest
        assert manifest is not None
        assert manifest["steps"]["sup_003"]["provenance"] == "deterministic"
        assert "reintrodu" in manifest["steps"]["sup_003"]["reason"]

        full_file = service._normalize_boilerplate(result)
        plan_result = validate_bot_against_plan(full_file, service.plan_path, [])
        assert plan_result["status"] == "PASS", plan_result.get("errors")

        print("[OK] test_end_to_end_hybrid_generation_reintroduces_sup_and_passes_plan_validation")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_reintroduce_middle_position_and_wrapper()
    test_reintroduce_is_idempotent()
    test_reintroduce_first_step_inserts_before_next_neighbor()
    test_reintroduce_nonexistent_step_id_is_noop()
    test_reintroduce_unsupported_type_is_noop()
    test_end_to_end_hybrid_generation_reintroduces_sup_and_passes_plan_validation()
    print("\nTodos os testes passaram.")
