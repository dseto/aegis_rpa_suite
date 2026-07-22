import json
import os
import shutil
import unittest
from unittest.mock import MagicMock

from healing_review import build_cognitive_proposal, enrich_needs_review


class TestHealingReviewCognitive(unittest.TestCase):
    """T-05: rota cognitiva de aegis_cockpit/healing_review.py -- casos sem
    resolução estrutural. Usa gateway._call_llm_api diretamente (não
    gateway.diagnose_failure, que exige page Playwright AO VIVO --
    indisponível numa revisão pós-hoc no Cockpit sem browser aberto)."""

    def setUp(self):
        self.test_dir = "fake_test_dir_healing_review_cognitive"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _write_corrections(self, entries):
        path = os.path.join(self.test_dir, "correcoes_acumuladas.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=4, ensure_ascii=False)

    def test_gateway_none_returns_manual_review_fallback(self):
        entry = {"step_id": "st_050", "action": "click", "failed_selector": "#x",
                  "healing_method": "click_no_effect_recovered"}
        proposal = build_cognitive_proposal(entry, gateway=None)
        self.assertEqual(proposal["kind"], "cognitive")
        self.assertIn("st_050", proposal["root_cause"])
        self.assertIn("manual", proposal["proposed_fix"].lower())

    def test_gateway_inactive_returns_manual_review_fallback(self):
        gateway = MagicMock()
        gateway.is_active.return_value = False
        entry = {"step_id": "st_051", "action": "click", "failed_selector": "#x",
                  "healing_method": "generic_only_expected_missing"}
        proposal = build_cognitive_proposal(entry, gateway=gateway)
        self.assertIn("manual", proposal["proposed_fix"].lower())
        gateway._call_llm_api.assert_not_called()

    def test_gateway_active_calls_llm_and_parses_diagnosis(self):
        gateway = MagicMock()
        gateway.is_active.return_value = True
        gateway._call_llm_api.return_value = '{"root_cause_summary": "site mudou o DOM", "actionable_fix": "usar novo seletor #y"}'
        gateway._clean_json_response.return_value = {
            "root_cause_summary": "site mudou o DOM",
            "actionable_fix": "usar novo seletor #y",
        }
        entry = {"step_id": "st_052", "action": "click", "failed_selector": "#x",
                  "healing_method": "click_no_effect_recovered"}

        proposal = build_cognitive_proposal(entry, gateway=gateway, screenshot_path="shot.png")

        gateway._call_llm_api.assert_called_once()
        call_args, call_kwargs = gateway._call_llm_api.call_args
        self.assertEqual(call_kwargs.get("image_path"), "shot.png")
        self.assertEqual(proposal["root_cause"], "site mudou o DOM")
        self.assertEqual(proposal["proposed_fix"], "usar novo seletor #y")

    def test_gateway_llm_error_falls_back_to_manual_review(self):
        gateway = MagicMock()
        gateway.is_active.return_value = True
        gateway._call_llm_api.side_effect = RuntimeError("timeout")
        entry = {"step_id": "st_053", "action": "click", "failed_selector": "#x",
                  "healing_method": "click_no_effect_recovered"}

        proposal = build_cognitive_proposal(entry, gateway=gateway)

        self.assertIn("manual", proposal["proposed_fix"].lower())

    def test_enrich_routes_deterministic_and_cognitive_correctly_with_zero_llm_for_deterministic(self):
        self._write_corrections([
            {
                "id": "c1", "step_id": "st_060", "action": "click", "failed_selector": "#a",
                "healing_method": "anchor_geometry", "occurrences": 1, "status": "needs_review",
            },
            {
                "id": "c2", "step_id": "st_061", "action": "click", "failed_selector": "#b",
                "healing_method": "click_no_effect_recovered", "occurrences": 1, "status": "needs_review",
            },
        ])
        plan_path = os.path.join(self.test_dir, "plano_execucao.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump({"steps": [{"step_id": "st_060", "anchor": {"selector": ".x", "text": "X"}}]}, f)

        gateway = MagicMock()
        gateway.is_active.return_value = True
        gateway._call_llm_api.return_value = "{}"
        gateway._clean_json_response.return_value = {"root_cause_summary": "c", "actionable_fix": "f"}

        result = enrich_needs_review(self.test_dir, gateway=gateway)

        by_step = {p["step_id"]: p for p in result["proposals"]}
        self.assertEqual(by_step["st_060"]["kind"], "deterministic")
        self.assertEqual(by_step["st_061"]["kind"], "cognitive")
        gateway._call_llm_api.assert_called_once()  # só para o passo cognitivo, nunca para o determinístico


if __name__ == "__main__":
    unittest.main()
