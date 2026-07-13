import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from step_validator import validate_resilience_patterns


class TestWeakSelectorEnforcement(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="aegis_weak_selector_test_")
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

    def test_weak_step_without_anchor_fails(self):
        self._write_plan([
            {"step_id": "st_001", "type": "click", "selector": "#btn-generic", "weak_selector": True},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Clique sem ancoragem
    runner.click_resilient(page, selector="#btn-generic", target_description="Botao", step_id="st_001")
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "FAIL")
        error_types = {e["type"] for e in result["errors"]}
        self.assertIn("WEAK_SELECTOR_WITHOUT_ANCHOR", error_types)

    def test_weak_step_with_only_original_coords_fails(self):
        self._write_plan([
            {"step_id": "st_001", "type": "click", "selector": "#btn-generic", "weak_selector": True},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Clique com coords mas sem ancoragem de texto
    runner.click_resilient(page, selector="#btn-generic", target_description="Botao",
                            original_coords=(0.5, 0.5), step_id="st_001")
'''
        result = self._run(bot_code)
        self.assertEqual(result["status"], "FAIL")
        error_types = {e["type"] for e in result["errors"]}
        self.assertIn("WEAK_SELECTOR_WITHOUT_ANCHOR", error_types)

    def test_weak_step_with_has_text_in_selector_passes(self):
        self._write_plan([
            {"step_id": "st_001", "type": "click", "selector": "#btn-generic", "weak_selector": True},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Clique ancorado via has-text embutido no seletor
    runner.click_resilient(page, selector="#btn-generic:has-text(\\'Confirmar\\')",
                            target_description="Botao", step_id="st_001")
'''
        result = self._run(bot_code)
        error_types = {e["type"] for e in result["errors"]}
        self.assertNotIn("WEAK_SELECTOR_WITHOUT_ANCHOR", error_types)

    def test_weak_step_with_click_chained_parent_passes(self):
        self._write_plan([
            {"step_id": "st_001", "type": "click", "selector": "#btn-generic", "weak_selector": True},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Clique ancorado via click_chained com parent
    runner.click_chained(page, parent={"selector": "#container", "has_text": "Confirmar"},
                          child={"selector": "#btn-generic"},
                          target_description="Botao", step_id="st_001")
'''
        result = self._run(bot_code)
        error_types = {e["type"] for e in result["errors"]}
        self.assertNotIn("WEAK_SELECTOR_WITHOUT_ANCHOR", error_types)

    def test_step_without_flag_and_without_anchor_passes(self):
        self._write_plan([
            {"step_id": "st_001", "type": "click", "selector": "#btn-generic"},
        ])
        bot_code = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Clique sem flag weak_selector, nao precisa de ancoragem
    runner.click_resilient(page, selector="#btn-generic", target_description="Botao", step_id="st_001")
'''
        result = self._run(bot_code)
        error_types = {e["type"] for e in result["errors"]}
        self.assertNotIn("WEAK_SELECTOR_WITHOUT_ANCHOR", error_types)


if __name__ == "__main__":
    unittest.main()
