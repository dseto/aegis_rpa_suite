"""
Testes de aceitação para o comportamento hint-aware de step_validator.py
(campo 'execution_hint': 'required' ausente/explícito | 'optional' | 'skip'),
Seção 5 de .specs/plano-sanitizer-alta-fidelidade.md.

Duas frentes:
1. Retrocompatibilidade: um plano v1 (sem NENHUM 'execution_hint') precisa
   produzir o mesmo veredito PASS/FAIL — e, nos casos "limpos" (sem id extra/
   alucinado), a mesma composição de erros — do validador anterior à
   subsequência monotônica. Para provar isso mecanicamente (não só por
   inspeção), este arquivo embute uma cópia fiel do validate_bot_against_plan
   ANTERIOR a esta tarefa (_legacy_validate_bot_against_plan) e usa-a como
   oráculo de referência.
2. Matriz v2: comportamento novo dos hints 'optional'/'skip' em
   validate_bot_against_plan e validate_resilience_patterns.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from step_validator import (
    validate_bot_against_plan,
    validate_resilience_patterns,
    extract_step_ids_from_code,
    _validate_scenario_function_signature,
)


def _legacy_validate_bot_against_plan(bot_code, plan_path, pending_corrections=None):
    """
    Cópia fiel de validate_bot_against_plan tal como existia ANTES desta
    tarefa (igualdade posicional estrita entre planned_ids e code_ids, sem
    noção de execution_hint). Usada só como oráculo de referência nestes
    testes para provar que planos v1 preservam o veredito do validador
    antigo — não faz parte do código de produção.
    """
    if not os.path.exists(plan_path):
        return {"status": "FAIL", "total_errors": 1, "errors": [{"type": "PLAN_NOT_FOUND"}]}

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    planned_ids = [s["step_id"] for s in plan.get("steps", [])]
    code_ids = extract_step_ids_from_code(bot_code)

    if pending_corrections:
        planned_set_for_reopen = set(planned_ids)
        reopen_reqs = [
            (c["required_reopen"]["after_step_id"], c["step_id"])
            for c in pending_corrections
            if c.get("required_reopen") and c.get("step_id")
        ]
        for after_id, target_id in reopen_reqs:
            if after_id in code_ids and target_id in code_ids:
                after_pos = code_ids.index(after_id)
                target_pos = code_ids.index(target_id)
                if target_pos == after_pos + 2:
                    extra_id = code_ids[after_pos + 1]
                    if extra_id not in planned_set_for_reopen:
                        code_ids = code_ids[:after_pos + 1] + code_ids[after_pos + 2:]

    if not code_ids:
        return {"status": "FAIL", "total_errors": 1, "errors": [{"type": "NO_STEPS_FOUND"}]}

    errors = []

    if len(code_ids) != len(planned_ids):
        errors.append({
            "type": "COUNT_MISMATCH",
            "expected": len(planned_ids),
            "found": len(code_ids),
        })

    max_len = max(len(planned_ids), len(code_ids))
    for i in range(max_len):
        planned = planned_ids[i] if i < len(planned_ids) else None
        coded = code_ids[i] if i < len(code_ids) else None
        if planned != coded:
            errors.append({
                "type": "STEP_ID_MISMATCH",
                "position": i + 1,
                "expected_id": planned,
                "found_id": coded,
            })

    planned_set = set(planned_ids)
    code_set = set(code_ids)
    missing = sorted(planned_set - code_set)
    extra = sorted(code_set - planned_set)

    if missing:
        errors.append({"type": "MISSING_STEPS", "step_ids": missing})
    if extra:
        errors.append({"type": "EXTRA_STEPS", "step_ids": extra})

    return {
        "status": "PASS" if not errors else "FAIL",
        "total_errors": len(errors),
        "errors": errors,
    }


class _StepValidatorHintsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="aegis_step_validator_hints_test_")
        self.plan_path = os.path.join(self.tmp_dir, "plano_execucao.json")
        self.dicionario_path = os.path.join(self.tmp_dir, "dicionario.json")
        with open(self.dicionario_path, "w", encoding="utf-8") as f:
            json.dump({"fields": {}}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_plan(self, steps):
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump({"steps": steps}, f)

    @staticmethod
    def _bot_from_ids(step_ids):
        """Bot mínimo com uma chamada runner.click_resilient(step_id=...) por id,
        na ordem dada. O tipo de método não importa para validate_bot_against_plan
        (só extract_step_ids_from_code é exercitado)."""
        lines = [
            f'    runner.click_resilient(page, selector="#x", target_description="t", step_id="{sid}")'
            for sid in step_ids
        ]
        return "def execute_scenario_default(page, row, runner):\n" + "\n".join(lines) + "\n"


class TestV1BackwardCompatibility(_StepValidatorHintsTestBase):
    """Plano v1 = nenhum step tem 'execution_hint'. Checagem de retrocompatibilidade
    mais importante desta tarefa: o veredito (e, nos casos limpos, a composição de
    erros) precisa bater com o validador anterior (_legacy_validate_bot_against_plan)."""

    def test_exact_match_passes_like_legacy(self):
        steps = [{"step_id": f"st_{i:03d}", "type": "click"} for i in range(1, 4)]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_002", "st_003"])

        legacy = _legacy_validate_bot_against_plan(bot_code, self.plan_path)
        new = validate_bot_against_plan(bot_code, self.plan_path)

        self.assertEqual(legacy["status"], "PASS")
        self.assertEqual(new["status"], "PASS")
        self.assertEqual(new["errors"], [])

    def test_missing_required_step_fails_like_legacy(self):
        steps = [{"step_id": f"st_{i:03d}", "type": "click"} for i in range(1, 4)]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_003"])  # st_002 ausente

        legacy = _legacy_validate_bot_against_plan(bot_code, self.plan_path)
        new = validate_bot_against_plan(bot_code, self.plan_path)

        self.assertEqual(new["status"], legacy["status"])
        self.assertEqual(new["status"], "FAIL")

        legacy_types = {e["type"] for e in legacy["errors"]}
        new_types = {e["type"] for e in new["errors"]}
        self.assertIn("MISSING_STEPS", legacy_types)
        self.assertIn("MISSING_STEPS", new_types)
        self.assertIn("COUNT_MISMATCH", legacy_types)
        self.assertIn("COUNT_MISMATCH", new_types)

        legacy_missing = next(e for e in legacy["errors"] if e["type"] == "MISSING_STEPS")["step_ids"]
        new_missing = next(e for e in new["errors"] if e["type"] == "MISSING_STEPS")["step_ids"]
        self.assertEqual(new_missing, legacy_missing)

        # Caso "limpo" (sem id extra/duplicado): valores de COUNT_MISMATCH batem
        # também, não só o tipo do erro.
        legacy_count = next(e for e in legacy["errors"] if e["type"] == "COUNT_MISMATCH")
        new_count = next(e for e in new["errors"] if e["type"] == "COUNT_MISMATCH")
        self.assertEqual(new_count["expected"], legacy_count["expected"])
        self.assertEqual(new_count["found"], legacy_count["found"])

    def test_pure_reorder_fails_with_step_id_mismatch_only_like_legacy(self):
        """Caso mais importante de retrocompat prática: quando os únicos ids
        presentes no código são exatamente os do plano, só fora de ordem, tanto
        o validador antigo quanto o novo falham com error_types ==
        {'STEP_ID_MISMATCH'} — é literalmente essa condição
        (error_types.issubset({"STEP_ID_MISMATCH"})) que code_generator.py:603
        usa para disparar o reorder automático determinístico. Se esse conjunto
        divergisse aqui, o gatilho pararia de funcionar."""
        steps = [{"step_id": f"st_{i:03d}", "type": "click"} for i in range(1, 4)]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_003", "st_002"])

        legacy = _legacy_validate_bot_against_plan(bot_code, self.plan_path)
        new = validate_bot_against_plan(bot_code, self.plan_path)

        self.assertEqual(legacy["status"], "FAIL")
        self.assertEqual(new["status"], "FAIL")
        self.assertEqual({e["type"] for e in legacy["errors"]}, {"STEP_ID_MISMATCH"})
        self.assertEqual({e["type"] for e in new["errors"]}, {"STEP_ID_MISMATCH"})

    def test_hallucinated_extra_id_agrees_on_fail_verdict_like_legacy(self):
        """Id fora do plano: ambos os validadores falham (EXTRA_STEPS presente
        nos dois), mas o novo não gera mais o cascateamento de STEP_ID_MISMATCH
        espúrio que o id extra causava por deslocamento posicional no antigo —
        isso é a melhoria intencional desta tarefa, não uma regressão. Ver
        também TestV2HintMatrix.test_hallucinated_id_reports_extra_without_raising
        para a garantia de não-exceção."""
        steps = [{"step_id": f"st_{i:03d}", "type": "click"} for i in range(1, 3)]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_999_nao_planejado", "st_002"])

        legacy = _legacy_validate_bot_against_plan(bot_code, self.plan_path)
        new = validate_bot_against_plan(bot_code, self.plan_path)

        self.assertEqual(legacy["status"], "FAIL")
        self.assertEqual(new["status"], "FAIL")
        self.assertIn("EXTRA_STEPS", {e["type"] for e in legacy["errors"]})
        self.assertIn("EXTRA_STEPS", {e["type"] for e in new["errors"]})


class TestV2HintMatrix(_StepValidatorHintsTestBase):
    """Matriz de comportamento novo do plano v2 (execution_hint presente)."""

    def test_only_required_emitted_passes(self):
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "sup_001", "type": "click", "execution_hint": "skip"},
            {"step_id": "st_002", "type": "click", "execution_hint": "required"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_002"])  # sup_001 não emitido
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_optional_emitted_in_order_passes(self):
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "st_002", "type": "click", "execution_hint": "optional"},
            {"step_id": "st_003", "type": "click"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_002", "st_003"])
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_optional_not_emitted_also_passes(self):
        """optional é a critério da LLM — não emitir não é erro."""
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "st_002", "type": "click", "execution_hint": "optional"},
            {"step_id": "st_003", "type": "click"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_003"])
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_skip_emitted_in_order_passes(self):
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "sup_001", "type": "click", "execution_hint": "skip"},
            {"step_id": "st_002", "type": "click"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "sup_001", "st_002"])
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_order_violated_fails(self):
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "st_002", "type": "click", "execution_hint": "optional"},
            {"step_id": "st_003", "type": "click"},
        ]
        self._write_plan(steps)
        # st_002 (optional) emitido DEPOIS de st_003 — viola a ordem relativa do plano
        bot_code = self._bot_from_ids(["st_001", "st_003", "st_002"])
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("STEP_ID_MISMATCH", {e["type"] for e in result["errors"]})

    def test_required_missing_fails(self):
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "st_002", "type": "click"},
            {"step_id": "sup_001", "type": "click", "execution_hint": "skip"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001"])  # st_002 (required) ausente
        result = validate_bot_against_plan(bot_code, self.plan_path)
        self.assertEqual(result["status"], "FAIL")
        error_types = {e["type"] for e in result["errors"]}
        self.assertIn("MISSING_STEPS", error_types)
        missing_entry = next(e for e in result["errors"] if e["type"] == "MISSING_STEPS")
        self.assertEqual(missing_entry["step_ids"], ["st_002"])
        # sup_001 (skip, não emitido) não deve contar como faltando
        self.assertNotIn("sup_001", missing_entry["step_ids"])

    def test_hallucinated_id_reports_extra_without_raising(self):
        """Id inventado pela LLM, fora do plano inteiro (nem required, nem
        optional, nem skip): deve virar EXTRA_STEPS sem lançar exceção — e sem
        produzir STEP_ID_MISMATCH espúrio para os ids que estão corretamente
        ordenados ao redor dele."""
        steps = [
            {"step_id": "st_001", "type": "click"},
            {"step_id": "st_002", "type": "click", "execution_hint": "optional"},
            {"step_id": "st_003", "type": "click"},
        ]
        self._write_plan(steps)
        bot_code = self._bot_from_ids(["st_001", "st_999_alucinado", "st_002", "st_003"])

        try:
            result = validate_bot_against_plan(bot_code, self.plan_path)
        except Exception as exc:  # pragma: no cover - a falha É o teste
            self.fail(f"validate_bot_against_plan lançou exceção com id fora do plano: {exc!r}")

        self.assertEqual(result["status"], "FAIL")
        error_types = {e["type"] for e in result["errors"]}
        self.assertIn("EXTRA_STEPS", error_types)
        extra_entry = next(e for e in result["errors"] if e["type"] == "EXTRA_STEPS")
        self.assertEqual(extra_entry["step_ids"], ["st_999_alucinado"])
        self.assertNotIn("STEP_ID_MISMATCH", error_types)

    def test_reopen_position_accepts_legitimate_reintroduced_sup_id(self):
        """D6: a LLM pode reintroduzir um sup_NNN JÁ EXISTENTE no plano na posição
        de uma correção required_reopen, em vez de inventar um step_id novo tipo
        'st_010_reopen'. Isso não pode ser tratado como id desconhecido — o
        sup_005 é um id legítimo do plano (hint 'skip'), então deve passar
        normalmente pelo caminho EXTRA_STEPS/ordem como qualquer outro id
        pertencente ao plano."""
        steps = [
            {"step_id": "st_010", "type": "select"},
            {"step_id": "sup_005", "type": "click", "execution_hint": "skip",
             "step_role": "overlay_noise"},
            {"step_id": "st_011", "type": "click"},
        ]
        self._write_plan(steps)
        pending_corrections = [{
            "step_id": "st_011",
            "required_reopen": {"after_step_id": "st_010", "selector": "#combustivel"},
        }]
        bot_code = self._bot_from_ids(["st_010", "sup_005", "st_011"])
        result = validate_bot_against_plan(bot_code, self.plan_path, pending_corrections)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_reopen_position_still_tolerates_invented_label_not_in_plan(self):
        """Comportamento pré-existente, não alterado nesta tarefa: se a LLM
        inventar um step_id qualquer (fora do plano) exatamente nessa posição,
        a tolerância de required_reopen ainda o engole silenciosamente — o
        conteúdo real é responsabilidade de validate_required_reopen_patterns,
        não deste validador."""
        steps = [
            {"step_id": "st_010", "type": "select"},
            {"step_id": "st_011", "type": "click"},
        ]
        self._write_plan(steps)
        pending_corrections = [{
            "step_id": "st_011",
            "required_reopen": {"after_step_id": "st_010", "selector": "#combustivel"},
        }]
        bot_code = self._bot_from_ids(["st_010", "st_010_reopen", "st_011"])
        result = validate_bot_against_plan(bot_code, self.plan_path, pending_corrections)
        self.assertEqual(result["status"], "PASS", result["errors"])


class TestValidateResiliencePatternsHints(unittest.TestCase):
    """validate_resilience_patterns: guard de execution_hint imediatamente
    antes do loop principal (Seção 5.2)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="aegis_resilience_hints_test_")
        self.plan_path = os.path.join(self.tmp_dir, "plano_execucao.json")
        self.dicionario_path = os.path.join(self.tmp_dir, "dicionario.json")
        with open(self.dicionario_path, "w", encoding="utf-8") as f:
            json.dump({"fields": {}}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_plan(self, steps):
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump({"steps": steps}, f)

    def _run(self, bot_code):
        return validate_resilience_patterns(bot_code, self.plan_path, self.dicionario_path)

    def test_skip_step_not_emitted_is_not_checked(self):
        """Step 'select' suprimido (skip) e NÃO emitido pela LLM: nada a checar,
        não deve cobrar select_option_resilient de uma chamada que não existe."""
        self._write_plan([
            {"step_id": "sup_001", "type": "select", "dropdown_label": "Combustivel",
             "option_text": "Alcool", "execution_hint": "skip"},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    pass
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_skip_step_emitted_is_still_checked(self):
        """Se a LLM emitiu o step suprimido mesmo assim (reintroduziu o
        step_id), ele é cobrado pelos mesmos padrões de um step required."""
        self._write_plan([
            {"step_id": "sup_001", "type": "select", "dropdown_label": "Combustivel",
             "option_text": "Alcool", "execution_hint": "skip"},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    runner.click_resilient(page, selector="#combustivel", target_description="t", step_id="sup_001")
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("MISSING_SELECT_OPTION_RESILIENT", {e["type"] for e in result["errors"]})

    def test_optional_step_not_emitted_is_not_checked(self):
        self._write_plan([
            {"step_id": "st_001", "type": "select", "dropdown_label": "Combustivel",
             "option_text": "Alcool", "execution_hint": "optional"},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    pass
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_v1_plan_without_hint_field_keeps_current_behavior(self):
        """Plano v1 (nenhum step tem 'execution_hint'): o guard novo nunca
        dispara (step.get('execution_hint') é sempre None), então um step do
        tipo select sem select_option_resilient continua falhando exatamente
        como antes desta tarefa."""
        self._write_plan([
            {"step_id": "st_001", "type": "select", "dropdown_label": "Combustivel",
             "option_text": "Alcool"},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    runner.click_resilient(page, selector="#combustivel", target_description="t", step_id="st_001")
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("MISSING_SELECT_OPTION_RESILIENT", {e["type"] for e in result["errors"]})


class TestScenarioFunctionSignatureLineno(unittest.TestCase):
    """[SUBAGENTE 13]: INVALID_SCENARIO_SIGNATURE e WRONG_SCENARIO_PARAM_ORDER
    (_validate_scenario_function_signature) precisam carregar 'lineno' — sem
    isso o erro fica invisível para o mecanismo de escopo cirúrgico do
    code_generator.py (live_error_step_ids / _compute_restore_target_scope),
    causando oscilação infinita do Ralph Loop (ver CLAUDE.md, working
    agreement nº 5, e o retry 3 do gate H8)."""

    def test_invalid_scenario_signature_carries_correct_lineno(self):
        bot_code = (
            "import os\n"
            "\n"
            "\n"
            "def execute_scenario_default(page):\n"
            "    pass\n"
        )
        errors = _validate_scenario_function_signature(bot_code)
        invalid_sig_errors = [e for e in errors if e["type"] == "INVALID_SCENARIO_SIGNATURE"]
        self.assertEqual(len(invalid_sig_errors), 1, errors)
        # linha 4 (1-based) é onde 'def execute_scenario_default(page):' está declarada
        self.assertEqual(invalid_sig_errors[0]["lineno"], 4)

    def test_wrong_scenario_param_order_carries_correct_lineno(self):
        bot_code = (
            "import os\n"
            "import sys\n"
            "\n"
            "\n"
            "def execute_scenario_default(runner, row, page):\n"
            "    pass\n"
        )
        errors = _validate_scenario_function_signature(bot_code)
        wrong_order_errors = [e for e in errors if e["type"] == "WRONG_SCENARIO_PARAM_ORDER"]
        self.assertEqual(len(wrong_order_errors), 1, errors)
        # linha 5 (1-based) é onde 'def execute_scenario_default(runner, row, page):' está declarada
        self.assertEqual(wrong_order_errors[0]["lineno"], 5)


if __name__ == "__main__":
    unittest.main()
