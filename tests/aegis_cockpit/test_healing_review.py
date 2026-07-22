import json
import os
import shutil
import unittest

from healing_review import (
    scan_needs_review,
    resolve_step_id,
    build_deterministic_proposal,
    enrich_needs_review,
    approve_proposal,
)


class TestHealingReviewCore(unittest.TestCase):
    """T-04: núcleo de aegis_cockpit/healing_review.py -- varredura,
    resolução de step_id, proposta determinística."""

    def setUp(self):
        self.test_dir = "fake_test_dir_healing_review"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _write_corrections(self, entries):
        path = os.path.join(self.test_dir, "correcoes_acumuladas.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=4, ensure_ascii=False)

    def _write_plan(self, steps):
        path = os.path.join(self.test_dir, "plano_execucao.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"steps": steps}, f, indent=4, ensure_ascii=False)

    def test_scan_groups_only_needs_review_entries(self):
        self._write_corrections([
            {"id": "c1", "action": "click", "failed_selector": "#a", "status": "needs_review"},
            {"id": "c2", "action": "click", "failed_selector": "#b", "status": "resolved"},
            {"id": "c3", "action": "fill", "failed_selector": "#c", "status": "pending"},
            {"id": "c4", "action": "click", "failed_selector": "#a", "status": "needs_review"},
        ])
        groups = scan_needs_review(self.test_dir)
        self.assertEqual(len(groups), 1)
        key = ("click", "#a")
        self.assertIn(key, groups)
        self.assertEqual(len(groups[key]), 2)

    def test_scan_no_file_returns_empty(self):
        groups = scan_needs_review(self.test_dir)
        self.assertEqual(groups, {})

    def test_resolve_step_id_valid(self):
        self.assertEqual(resolve_step_id({"step_id": "st_007"}), "st_007")

    def test_resolve_step_id_auto_prefixed_is_unresolved(self):
        self.assertIsNone(resolve_step_id({"step_id": "auto_3"}))

    def test_resolve_step_id_missing_is_unresolved(self):
        self.assertIsNone(resolve_step_id({}))
        self.assertIsNone(resolve_step_id({"step_id": ""}))
        self.assertIsNone(resolve_step_id({"step_id": None}))

    def test_deterministic_proposal_anchor_geometry_promotes_recorded_anchor(self):
        entry = {
            "step_id": "st_010",
            "action": "click",
            "failed_selector": "#btn-old",
            "healing_method": "anchor_geometry",
            "occurrences": 2,
        }
        plan_step = {"step_id": "st_010", "anchor": {"selector": "label:has-text('Nome')", "text": "Nome"}}
        proposal = build_deterministic_proposal(entry, plan_step)
        self.assertEqual(proposal["kind"], "deterministic")
        self.assertEqual(proposal["promoted_selector"], "label:has-text('Nome')")
        self.assertIn("#btn-old", proposal["root_cause"])
        self.assertIn("label:has-text('Nome')", proposal["proposed_fix"])

    def test_deterministic_proposal_fallback_selector_promotes_first_fallback(self):
        entry = {
            "step_id": "st_011",
            "action": "click",
            "failed_selector": "#sel-quebrado",
            "healing_method": "fallback_selector",
            "occurrences": 1,
        }
        plan_step = {"step_id": "st_011", "fallback_selectors": ["#alt-1", "#alt-2"]}
        proposal = build_deterministic_proposal(entry, plan_step)
        self.assertEqual(proposal["promoted_selector"], "#alt-1")

    def test_deterministic_proposal_parent_has_text_reduced_no_selector_but_still_deterministic(self):
        entry = {
            "step_id": "st_012",
            "action": "click_chained",
            "failed_selector": "#parent >> child",
            "healing_method": "parent_has_text_reduced",
            "occurrences": 1,
        }
        proposal = build_deterministic_proposal(entry, None)
        self.assertEqual(proposal["kind"], "deterministic")
        self.assertIsNone(proposal["promoted_selector"])
        self.assertTrue(proposal["proposed_fix"])

    def test_enrich_skips_unresolved_and_builds_deterministic_proposal(self):
        self._write_corrections([
            {
                "id": "c1", "step_id": "st_020", "action": "click", "failed_selector": "#a",
                "healing_method": "anchor_geometry", "occurrences": 1, "status": "needs_review",
            },
            {
                "id": "c2", "step_id": "auto_5", "action": "click", "failed_selector": "#b",
                "healing_method": "anchor_geometry", "occurrences": 1, "status": "needs_review",
            },
        ])
        self._write_plan([{"step_id": "st_020", "anchor": {"selector": ".x", "text": "X"}}])

        result = enrich_needs_review(self.test_dir, gateway=None)

        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["step_id"], "st_020")
        self.assertEqual(result["proposals"][0]["correction_id"], "c1")
        self.assertEqual(len(result["skipped_unresolved"]), 1)
        self.assertEqual(result["skipped_unresolved"][0]["id"], "c2")

    def test_enrich_zero_llm_for_deterministic_entries(self):
        # Nenhuma entrada deve exigir gateway quando todos os healing_method
        # sao deterministicos -- gateway=None nao pode quebrar nada aqui.
        self._write_corrections([
            {
                "id": "c1", "step_id": "st_030", "action": "click", "failed_selector": "#a",
                "healing_method": "fallback_selector", "occurrences": 1, "status": "needs_review",
            },
        ])
        self._write_plan([{"step_id": "st_030", "fallback_selectors": ["#alt"]}])
        result = enrich_needs_review(self.test_dir, gateway=None)
        self.assertEqual(result["proposals"][0]["kind"], "deterministic")

    def test_approve_proposal_flips_status_and_fills_fields(self):
        self._write_corrections([
            {
                "id": "c1", "step_id": "st_040", "action": "click", "failed_selector": "#a",
                "healing_method": "anchor_geometry", "occurrences": 1, "status": "needs_review",
                "root_cause": None, "proposed_fix": None, "qa_insight": None,
            },
        ])
        proposal = {"kind": "deterministic", "healing_method": "anchor_geometry",
                    "root_cause": "causa X", "proposed_fix": "fix Y"}

        ok = approve_proposal(self.test_dir, "c1", proposal)
        self.assertTrue(ok)

        with open(os.path.join(self.test_dir, "correcoes_acumuladas.json"), encoding="utf-8") as f:
            saved = json.load(f)
        entry = saved[0]
        self.assertEqual(entry["status"], "pending")
        self.assertEqual(entry["root_cause"], "causa X")
        self.assertEqual(entry["proposed_fix"], "fix Y")
        self.assertIn("deterministic", entry["qa_insight"])

    def test_approve_proposal_unknown_id_returns_false(self):
        self._write_corrections([{"id": "c1", "status": "needs_review"}])
        ok = approve_proposal(self.test_dir, "does-not-exist", {"root_cause": "x", "proposed_fix": "y"})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
