"""
Regressão da fiação do Unified Target Descriptor (kwarg -> self._current_* ->
tier de âncora dispara -> verificação). Escrito depois de 2 rodadas de review
em que a feature ficou completa em superfície (captura, propagação, emissão)
mas morta em runtime porque nenhum teste exercitava esse caminho ponta a
ponta -- os testes anteriores (test_unified_target.py) só cobriam
_resolve_via_anchor e _verify_recorded_expected_effect isoladamente, com
self._current_anchor setado manualmente, nunca através do kwarg público.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from runner import TransactionRunner


class TestUnifiedTargetWiring(unittest.TestCase):
    def setUp(self):
        self.project_dir = "fake_project_wiring"
        os.makedirs(self.project_dir, exist_ok=True)
        self.runner = TransactionRunner(project_dir=self.project_dir)
        self.runner.realtime_logs = False
        self.anchor = {"selector": ".lbl", "text": "Rótulo", "dx": 10, "dy": 5, "anchor_bbox": {}}
        self.expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        self.viewport = {"width": 1280, "height": 720}

    def tearDown(self):
        if os.path.exists(self.project_dir):
            import shutil
            shutil.rmtree(self.project_dir)

    # --- Item 1: fiação kwarg -> self._current_* ------------------------

    def test_click_resilient_wires_current_attrs_from_kwargs(self):
        page = MagicMock()
        page.locator.return_value.all.return_value = []
        with patch.object(self.runner, "_handle_unrecoverable_click", return_value=True):
            self.runner.click_resilient(
                page, "#foo", "Descrição do alvo", step_id="st_1",
                anchor=self.anchor, expected_effect=self.expected_effect, viewport=self.viewport,
            )
        self.assertEqual(self.runner._current_anchor, self.anchor)
        self.assertEqual(self.runner._current_expected_effect, self.expected_effect)
        self.assertEqual(self.runner._current_viewport, self.viewport)
        self.assertEqual(self.runner._current_target_description, "Descrição do alvo")

    def test_click_resilient_wires_none_when_kwargs_absent(self):
        """Um step sem anchor gravado zera o estado -- não vaza a âncora de um
        step anterior que passou por aqui na mesma instância do runner."""
        page = MagicMock()
        page.locator.return_value.all.return_value = []
        self.runner._current_anchor = {"stale": True}
        with patch.object(self.runner, "_handle_unrecoverable_click", return_value=True):
            self.runner.click_resilient(page, "#foo", "Descrição", step_id="st_1")
        self.assertIsNone(self.runner._current_anchor)

    def test_fill_resilient_wires_current_attrs_from_kwargs(self):
        page = MagicMock()
        page.locator.return_value.first.get_attribute.return_value = None
        page.locator.return_value.fill.side_effect = RuntimeError("timeout")
        page.keyboard.press.side_effect = RuntimeError("no-op")
        self.runner.fallback_selectors_by_step = {}
        self.runner.flaky_step_ids = {}
        self.runner.current_row_flaky_attempt = 0
        self.runner.cognitive = MagicMock()
        self.runner.cognitive.is_active.return_value = False
        with self.assertRaises(Exception):
            self.runner.fill_resilient(
                page, "#campo", "valor", "Descrição do campo", step_id="st_2",
                anchor=self.anchor, expected_effect=self.expected_effect, viewport=self.viewport,
            )
        self.assertEqual(self.runner._current_anchor, self.anchor)
        self.assertEqual(self.runner._current_viewport, self.viewport)

    def test_select_option_resilient_wires_current_attrs_from_kwargs(self):
        page = MagicMock()
        page.locator.return_value.filter.return_value.first.count.return_value = 0
        page.locator.return_value.first.is_visible.return_value = False
        page.locator.return_value.count.return_value = 0
        self.runner.flaky_step_ids = {}
        self.runner.current_row_flaky_attempt = 0
        self.runner.cognitive = MagicMock()
        self.runner.cognitive.is_active.return_value = False
        with patch.object(self.runner, "_resolve_via_anchor", return_value=None), \
             patch.object(self.runner, "_click_by_live_geometry", return_value=False), \
             self.assertRaises(RuntimeError):
            self.runner.select_option_resilient(
                page, "Uso do Veículo", "Comercial", step_id="st_3",
                anchor=self.anchor, expected_effect=self.expected_effect, viewport=self.viewport,
            )
        self.assertEqual(self.runner._current_anchor, self.anchor)
        self.assertEqual(self.runner._current_viewport, self.viewport)

    # --- Item 3: except de _verify_recorded_expected_effect não quebra --

    def test_verify_recorded_expected_effect_exception_falls_back_generic_no_nameerror(self):
        page = MagicMock()
        with patch.object(self.runner, "_capture_click_effect_snapshot", side_effect=RuntimeError("boom")):
            with patch.object(self.runner, "_verify_generic_effect", return_value=True) as generic:
                result = self.runner._verify_recorded_expected_effect(
                    page, {"url": "a", "domSize": 1, "overlays": 0}, self.expected_effect
                )
        self.assertTrue(result)
        # Regressão do bug: o except chamava `expected` (inexistente nesse
        # escopo) em vez de `expected_effect`, disparando NameError.
        generic.assert_called_once()
        self.assertEqual(generic.call_args[0][2], self.expected_effect)

    # --- Item 1 (cadeia de clique): o tier 2.95 dispara de fato quando ---
    # --- self._current_anchor está setado, e usa o MESMO seletor para ---
    # --- baseline e confirmação (regressão do mismatch anchor_geometry) -

    def test_click_recovery_anchor_tier_fires_and_uses_consistent_selector(self):
        page = MagicMock()
        target_handle = MagicMock()
        self.runner._current_anchor = self.anchor
        self.runner._current_viewport = self.viewport

        captured_selectors = []

        def fake_capture(page_arg, selector=None):
            captured_selectors.append(selector)
            return {"url": "a", "domSize": 10, "overlays": 0}

        with patch.object(self.runner, "_resolve_via_anchor", return_value=target_handle), \
             patch.object(self.runner, "_capture_click_effect_snapshot", side_effect=fake_capture), \
             patch.object(self.runner, "_verify_action_effect", return_value=True), \
             patch.object(self.runner, "_register_healing_for_review") as register_f1:
            result = self.runner._attempt_deterministic_click_recovery(
                page, "#original-selector", "st_4", identity_scoped=True,
                before_snapshot={"url": "a", "domSize": 9, "overlays": 0},
            )

        self.assertEqual(result[0], True)
        self.assertEqual(result[1], "anchor_geometry")
        target_handle.click.assert_called_once()
        register_f1.assert_called_once_with("st_4", "#original-selector", "click", "anchor_geometry")
        # Baseline (antes) e confirmação (depois) devem consultar o MESMO
        # seletor -- o da âncora gravada -- e não um rótulo literal
        # diferente, que zeraria o fingerprint de um lado só.
        self.assertEqual(len(set(captured_selectors)), 1)
        self.assertEqual(captured_selectors[0], self.anchor["selector"])

    # --- select_option_resilient: tier de âncora abre o trigger quando ---
    # --- os seletores conhecidos falham (alvo de maior valor da spec) --

    def test_select_option_anchor_tier_opens_trigger_when_known_selectors_fail(self):
        page = MagicMock()

        # Nenhum seletor conhecido de trigger encontra/abre painel.
        row_filter_locator = MagicMock()
        row_filter_locator.count.return_value = 0
        page.locator.return_value.filter.return_value.first = row_filter_locator

        known_trigger_locator = MagicMock()
        known_trigger_locator.click.side_effect = RuntimeError("not found")

        panel_locator = MagicMock()
        # Todos os seletores conhecidos de trigger falham no click() em si
        # (except Exception: continue) -- nunca chegam a consultar o painel.
        # A primeira consulta real ao painel é a do tier de âncora, logo
        # depois do clique via anchor_target: sempre "aberto".
        panel_locator.count.return_value = 1

        def locator_side_effect(sel):
            if "cdk-overlay-pane" in sel or "mat-select-panel" in sel:
                return panel_locator
            if ".mat-row" in sel:
                return page.locator.return_value
            m = MagicMock()
            m.first = known_trigger_locator
            return m

        page.locator.side_effect = locator_side_effect

        anchor_target = MagicMock()
        self.runner.flaky_step_ids = {}
        self.runner.current_row_flaky_attempt = 0
        self.runner.cognitive = MagicMock()
        self.runner.cognitive.is_active.return_value = False

        with patch.object(self.runner, "_resolve_via_anchor", return_value=anchor_target), \
             patch.object(self.runner, "_click_option_with_fallback", return_value=True), \
             patch.object(self.runner, "_register_healing_for_review") as register_f1:
            self.runner.select_option_resilient(
                page, "Uso do Veículo", "Comercial/Representação", step_id="st_5",
                anchor=self.anchor, viewport=self.viewport,
            )

        anchor_target.click.assert_called_once()
        register_f1.assert_any_call("st_5", "anchor:Uso do Veículo", "select_option", "anchor_geometry")


if __name__ == "__main__":
    unittest.main()
