import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sanitizer import SanitizerService


class TestWriteExecutionPlanFlakyPreservation(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)
        self.plan_path = os.path.join(self.telemetry_dir, "plano_execucao.json")

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def _read_plan(self):
        with open(self.plan_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_first_generation_no_old_plan_no_flaky(self):
        # (a) Sem plano antigo, nenhum step deve sair com flaky=True.
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
            {"type": "fill", "selector": "#input1", "value": "valor1"},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        for step in plan["steps"]:
            self.assertNotIn("flaky", step)

    def test_preserves_flaky_by_type_selector_even_when_position_shifts(self):
        # (b) Plano antigo com um step flaky=True. Ao regenerar com um novo
        # step inserido ANTES dele (deslocando o step_id posicional), o
        # merge deve continuar encontrando o step certo via (type, selector),
        # não via step_id.
        old_plan = {
            "version": "1.0",
            "test_dir": os.path.basename(self.telemetry_dir),
            "generated_at": "2026-01-01T00:00:00",
            "total_steps": 1,
            "steps": [
                {
                    "step_id": "st_001",
                    "type": "click",
                    "selector": "#btn-flaky",
                    "description": "Botao instavel",
                    "flaky": True,
                }
            ],
        }
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump(old_plan, f)

        # Novo conjunto de eventos: um step NOVO inserido antes do step
        # flaky original, deslocando sua posição (era st_001, agora sera st_002).
        events = [
            {"type": "click", "selector": "#btn-new", "text": "Botao Novo"},
            {"type": "click", "selector": "#btn-flaky", "text": "Botao instavel"},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        steps_by_selector = {s["selector"]: s for s in plan["steps"]}

        # O step flaky agora esta na posicao 2 (st_002), nao mais na 1.
        flaky_step = steps_by_selector["#btn-flaky"]
        self.assertEqual(flaky_step["step_id"], "st_002")
        self.assertTrue(flaky_step.get("flaky"))

        # O step novo, inserido antes, nao deve ter herdado flaky.
        new_step = steps_by_selector["#btn-new"]
        self.assertNotIn("flaky", new_step)

    def test_flaky_step_removed_from_new_events_does_not_propagate(self):
        # (c) Step flaky no plano antigo cujo (type, selector) nao existe
        # mais nos eventos novos: nao deve propagar nada, sem erro.
        old_plan = {
            "version": "1.0",
            "test_dir": os.path.basename(self.telemetry_dir),
            "generated_at": "2026-01-01T00:00:00",
            "total_steps": 1,
            "steps": [
                {
                    "step_id": "st_001",
                    "type": "click",
                    "selector": "#btn-removed",
                    "description": "Botao removido",
                    "flaky": True,
                }
            ],
        }
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump(old_plan, f)

        events = [
            {"type": "click", "selector": "#btn-other", "text": "Outro botao"},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        self.assertEqual(len(plan["steps"]), 1)
        self.assertNotIn("flaky", plan["steps"][0])

    def test_malformed_old_plan_does_not_break_generation(self):
        # (d) Plano antigo malformado (JSON invalido) nao deve quebrar a
        # geracao do plano novo, e nenhum flaky deve ser herdado.
        with open(self.plan_path, "w", encoding="utf-8") as f:
            f.write("{ isso nao e json valido ][")

        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
        ]
        # Nao deve lancar excecao.
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        self.assertEqual(len(plan["steps"]), 1)
        self.assertNotIn("flaky", plan["steps"][0])


class TestWriteExecutionPlanWeakSelectorFlag(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)
        self.plan_path = os.path.join(self.telemetry_dir, "plano_execucao.json")

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def _read_plan(self):
        with open(self.plan_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_confidence_below_70_marks_weak_selector(self):
        events = [
            {"type": "click", "selector": "#btn-weak", "text": "Botao fraco", "confidence": 40},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertTrue(step.get("weak_selector"))

    def test_confidence_100_does_not_mark_weak_selector(self):
        events = [
            {"type": "click", "selector": "#btn-strong", "text": "Botao forte", "confidence": 100},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertNotIn("weak_selector", step)

    def test_missing_confidence_does_not_mark_weak_selector(self):
        # Gravacao antiga, sem o campo `confidence` no evento: nao deve
        # receber a flag (nunca usar default 40 aqui).
        events = [
            {"type": "click", "selector": "#btn-old", "text": "Botao antigo"},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertNotIn("weak_selector", step)


class TestWriteExecutionPlanFallbackSelectors(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)
        self.plan_path = os.path.join(self.telemetry_dir, "plano_execucao.json")

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def _read_plan(self):
        with open(self.plan_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_event_with_two_fallbacks_propagates_both(self):
        events = [
            {
                "type": "click",
                "selector": "#btn1",
                "text": "Botao 1",
                "fallback_selectors": ["[data-testid='btn1']", ".btn-primary"],
            },
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertEqual(step.get("fallback_selectors"), ["[data-testid='btn1']", ".btn-primary"])

    def test_fallback_with_dynamic_token_in_has_text_is_sanitized(self):
        events = [
            {
                "type": "click",
                "selector": "#btn1",
                "text": "Botao 1",
                "fallback_selectors": ["div:has-text('PRO-80935')"],
            },
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        fallbacks = step.get("fallback_selectors")
        self.assertIsNotNone(fallbacks)
        self.assertNotIn("PRO-80935", fallbacks[0])

    def test_fallback_duplicate_of_primary_is_removed(self):
        events = [
            {
                "type": "click",
                "selector": "#btn1",
                "text": "Botao 1",
                "fallback_selectors": ["#btn1", "[data-testid='btn1']"],
            },
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertEqual(step.get("fallback_selectors"), ["[data-testid='btn1']"])

    def test_event_without_fallback_field_produces_step_without_field(self):
        # Gravacoes antigas, identicas ao comportamento atual.
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        step = plan["steps"][0]
        self.assertNotIn("fallback_selectors", step)

    def test_dropdown_pair_with_fallbacks_collapses_without_fallback_field(self):
        # Par abridor+opcao com fallback_selectors: o colapso em "select" nao
        # deve quebrar, e o step colapsado nao deve carregar fallback_selectors
        # (fora de escopo na v1).
        events = [
            {
                "type": "click",
                "selector": "mat-select:has-text('Combustivel')",
                "text": "Combustivel",
                "fallback_selectors": ["#combustivel-trigger"],
            },
            {
                "type": "click",
                "selector": "[role='option']:has-text('Alcool')",
                "text": "Alcool",
                "fallback_selectors": ["#opt-alcool"],
            },
        ]
        self.service._write_execution_plan(events)

        plan = self._read_plan()
        self.assertEqual(len(plan["steps"]), 1)
        step = plan["steps"][0]
        self.assertEqual(step["type"], "select")
        self.assertNotIn("fallback_selectors", step)


if __name__ == "__main__":
    unittest.main()
