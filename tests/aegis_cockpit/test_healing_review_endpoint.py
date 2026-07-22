import io
import json
import os
import shutil
import unittest
from unittest.mock import patch

import cockpit
from project_manager import ProjectManager


def _make_handler():
    """Instancia AegisHTTPRequestHandler SEM passar pelo __init__ real de
    BaseHTTPRequestHandler (que espera uma conexão de socket de verdade) --
    padrão comum pra testar handlers HTTP: bypassa __init__ via __new__ e
    seta manualmente só o que do_GET/do_POST/_json/_read_body precisam."""
    handler = cockpit.AegisHTTPRequestHandler.__new__(cockpit.AegisHTTPRequestHandler)
    handler.rfile = io.BytesIO(b"")
    handler.wfile = io.BytesIO()
    handler.headers = {}
    handler.send_response = lambda code: None
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    return handler


def _get(handler, path):
    handler.path = path
    handler.wfile = io.BytesIO()
    handler.do_GET()
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def _post(handler, path, body_dict):
    body_bytes = json.dumps(body_dict).encode("utf-8")
    handler.path = path
    handler.headers = {"Content-Length": str(len(body_bytes))}
    handler.rfile = io.BytesIO(body_bytes)
    handler.wfile = io.BytesIO()
    handler.do_POST()
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


class TestHealingReviewEndpoint(unittest.TestCase):
    """T-06: fiação do endpoint em cockpit.py (GET /healing-review, POST
    /healing-review/<id>/approve) -- handler HTTP fino, lógica real em
    healing_review.py (T-04/T-05), exercitada aqui via dispatch real de
    do_GET/do_POST (sem mockar enrich_needs_review/approve_proposal)."""

    def setUp(self):
        self.root = "fake_cockpit_root_healing_review_endpoint"
        os.makedirs(self.root, exist_ok=True)
        self.fake_pm = ProjectManager(self.root)

        self.test_dir = os.path.join(self.fake_pm.projects_dir, "meu_projeto", "tests", "cenario_principal")
        os.makedirs(self.test_dir, exist_ok=True)

        self.patcher = patch.object(cockpit, "project_manager", self.fake_pm)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.root):
            try:
                shutil.rmtree(self.root)
            except Exception:
                pass

    def _write_corrections(self, entries):
        path = os.path.join(self.test_dir, "correcoes_acumuladas.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=4, ensure_ascii=False)

    def _write_plan(self, steps):
        path = os.path.join(self.test_dir, "plano_execucao.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"steps": steps}, f, indent=4, ensure_ascii=False)

    def test_get_healing_review_returns_deterministic_proposal(self):
        self._write_corrections([
            {
                "id": "c1", "step_id": "st_070", "action": "click", "failed_selector": "#a",
                "healing_method": "anchor_geometry", "occurrences": 1, "status": "needs_review",
            },
        ])
        self._write_plan([{"step_id": "st_070", "anchor": {"selector": ".x", "text": "X"}}])

        handler = _make_handler()
        response = _get(handler, "/api/projects/meu_projeto/tests/cenario_principal/healing-review")

        self.assertTrue(response["success"])
        self.assertEqual(len(response["proposals"]), 1)
        self.assertEqual(response["proposals"][0]["step_id"], "st_070")
        self.assertEqual(response["proposals"][0]["kind"], "deterministic")
        self.assertEqual(response["proposals"][0]["correction_id"], "c1")

    def test_get_healing_review_missing_scenario_404(self):
        handler = _make_handler()
        response = _get(handler, "/api/projects/meu_projeto/tests/nao-existe/healing-review")
        self.assertFalse(response["success"])

    def test_post_approve_flips_status_to_pending_via_real_dispatch(self):
        self._write_corrections([
            {
                "id": "c2", "step_id": "st_071", "action": "click", "failed_selector": "#b",
                "healing_method": "fallback_selector", "occurrences": 1, "status": "needs_review",
                "root_cause": None, "proposed_fix": None, "qa_insight": None,
            },
        ])
        self._write_plan([{"step_id": "st_071", "fallback_selectors": ["#alt"]}])

        handler = _make_handler()
        get_response = _get(handler, "/api/projects/meu_projeto/tests/cenario_principal/healing-review")
        proposal = get_response["proposals"][0]

        post_response = _post(
            handler,
            "/api/projects/meu_projeto/tests/cenario_principal/healing-review/c2/approve",
            proposal,
        )
        self.assertTrue(post_response["success"])

        with open(os.path.join(self.test_dir, "correcoes_acumuladas.json"), encoding="utf-8") as f:
            saved = json.load(f)
        entry = saved[0]
        self.assertEqual(entry["status"], "pending")
        self.assertTrue(entry["proposed_fix"])

    def test_post_approve_unknown_id_404(self):
        self._write_corrections([{"id": "c1", "status": "needs_review"}])
        handler = _make_handler()
        response = _post(
            handler,
            "/api/projects/meu_projeto/tests/cenario_principal/healing-review/does-not-exist/approve",
            {"root_cause": "x", "proposed_fix": "y", "kind": "deterministic", "healing_method": "anchor_geometry"},
        )
        self.assertFalse(response["success"])


if __name__ == "__main__":
    unittest.main()
