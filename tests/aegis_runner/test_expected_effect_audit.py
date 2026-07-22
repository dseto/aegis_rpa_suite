import os
import shutil
import unittest
from unittest.mock import MagicMock, patch

from runner import TransactionRunner


class TestExpectedEffectSpecificStatus(unittest.TestCase):
    """E1.1 (auditoria B1) -- unidade isolada de _expected_effect_specific_status."""

    def setUp(self):
        self.project_dir = "fake_project_expected_effect_audit"
        os.makedirs(self.project_dir, exist_ok=True)
        self.runner = TransactionRunner(project_dir=self.project_dir)

    def tearDown(self):
        if os.path.exists(self.project_dir):
            try:
                shutil.rmtree(self.project_dir)
            except Exception:
                pass

    def test_no_expected_effect_recorded_returns_none(self):
        page = MagicMock()
        before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        # self.runner._current_expected_effect nunca setado (bot sem UTD) --
        # retrocompat: nada a auditar.
        result = self.runner._expected_effect_specific_status(page, before)
        self.assertIsNone(result)

    def test_no_before_snapshot_returns_none(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        result = self.runner._expected_effect_specific_status(page, None)
        self.assertIsNone(result)

    def test_specific_signal_matches_returns_true(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           return_value={"url": "https://x/b", "domSize": 100, "overlays": 0}):
            result = self.runner._expected_effect_specific_status(page, before)
        self.assertTrue(result)

    def test_specific_signal_missing_returns_false(self):
        # Nada do expected_effect gravado bate com o delta observado --
        # se o passo foi aprovado, foi só pelo genérico.
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 5, "overlay_delta": 0}
        before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           return_value={"url": "https://x/a", "domSize": 100, "overlays": 0}):
            result = self.runner._expected_effect_specific_status(page, before)
        self.assertFalse(result)

    def test_internal_error_is_conservative_never_marks(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        with patch.object(self.runner, "_capture_click_effect_snapshot", side_effect=RuntimeError("boom")):
            result = self.runner._expected_effect_specific_status(page, before)
        self.assertTrue(result)


class TestIdentityPathAudit(unittest.TestCase):
    """E1.1 -- caminho identity (_finalize_click_success), via _detect_click_no_effect."""

    def setUp(self):
        self.project_dir = "fake_project_expected_effect_identity"
        os.makedirs(self.project_dir, exist_ok=True)
        self.runner = TransactionRunner(project_dir=self.project_dir)

    def tearDown(self):
        if os.path.exists(self.project_dir):
            try:
                shutil.rmtree(self.project_dir)
            except Exception:
                pass

    def _step(self, step_id):
        return next(s for s in self.runner.steps_history if s["step_id"] == step_id)

    def test_identity_marks_and_registers_f1_when_generic_only(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 5, "overlay_delta": 0}
        before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_detect_click_no_effect", return_value=True), \
             patch.object(self.runner, "_capture_click_effect_snapshot",
                           return_value={"url": "https://x/a", "domSize": 100, "overlays": 0}), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            result = self.runner._finalize_click_success(
                page, "#sel", "desc", "st_id_001", False, None, before_snapshot, attempt=2
            )

        self.assertTrue(result)
        step = self._step("st_id_001")
        self.assertEqual(step["status"], "SUCCESS")
        self.assertEqual(step["verify_result"], "generic_only_expected_missing")
        mock_register.assert_called_once_with(
            "st_id_001", "#sel", "click", healing_method="generic_only_expected_missing"
        )

    def test_identity_no_mark_when_specific_confirmed(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_detect_click_no_effect", return_value=True), \
             patch.object(self.runner, "_capture_click_effect_snapshot",
                           return_value={"url": "https://x/b", "domSize": 100, "overlays": 0}), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            result = self.runner._finalize_click_success(
                page, "#sel", "desc", "st_id_002", False, None, before_snapshot, attempt=2
            )

        self.assertTrue(result)
        step = self._step("st_id_002")
        self.assertEqual(step["status"], "SUCCESS")
        self.assertIsNone(step["verify_result"])
        mock_register.assert_not_called()

    def test_identity_byte_identical_without_recorded_expected_effect(self):
        # Retrocompat (criterio d): bot sem anchor/expected_effect gravado
        # (caso real do bot de referencia Portal Segura, 0/66 passos) --
        # comportamento idêntico ao runner antes desta auditoria.
        page = MagicMock()
        before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_detect_click_no_effect", return_value=True), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            result = self.runner._finalize_click_success(
                page, "#sel", "desc", "st_id_003", False, None, before_snapshot, attempt=2
            )

        self.assertTrue(result)
        step = self._step("st_id_003")
        self.assertEqual(step["status"], "SUCCESS")
        self.assertIsNone(step["verify_result"])
        mock_register.assert_not_called()


class TestHealingTierAudit(unittest.TestCase):
    """E1.1 -- tiers de healing dentro de _attempt_deterministic_click_recovery
    (escape_retry/cdk_reposition/fallback_selector/anchor_geometry), via
    _effect_confirmed."""

    def setUp(self):
        self.project_dir = "fake_project_expected_effect_healing"
        os.makedirs(self.project_dir, exist_ok=True)
        self.runner = TransactionRunner(project_dir=self.project_dir)

    def tearDown(self):
        if os.path.exists(self.project_dir):
            try:
                shutil.rmtree(self.project_dir)
            except Exception:
                pass

    def _step(self, step_id):
        return next(s for s in self.runner.steps_history if s["step_id"] == step_id)

    def test_escape_retry_tier_marks_generic_only_when_expected_effect_never_checked(self):
        # O tier escape_retry aprova SEMPRE via _verify_generic_effect (nunca
        # passa o expected_effect gravado do passo para _verify_action_effect)
        # -- quando o passo tem expected_effect gravado, a aprovação aqui é
        # estruturalmente "só genérico" por construção.
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        tier_before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        effect_confirmed_after = {"url": "https://x/a", "domSize": 105, "overlays": 0}  # domSize +5 aprova o genérico
        audit_after = {"url": "https://x/a", "domSize": 100, "overlays": 0}  # nao bate com o expected_effect gravado

        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           side_effect=[tier_before, effect_confirmed_after, audit_after]):
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_heal_001", identity_scoped=False, before_snapshot=click_effect_before_snapshot
            )

        self.assertTrue(recovered)
        self.assertEqual(method, "escape_retry")
        self.assertTrue(self.runner._last_resolution_generic_only_expected_missing)

    def test_escape_retry_tier_no_mark_when_specific_signal_matches(self):
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        tier_before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        effect_confirmed_after = {"url": "https://x/b", "domSize": 100, "overlays": 0}  # url mudou -> genérico aprova
        audit_after = {"url": "https://x/b", "domSize": 100, "overlays": 0}  # url mudou -> bate com expected_effect gravado

        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           side_effect=[tier_before, effect_confirmed_after, audit_after]):
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_heal_002", identity_scoped=False, before_snapshot=click_effect_before_snapshot
            )

        self.assertTrue(recovered)
        self.assertEqual(method, "escape_retry")
        self.assertFalse(self.runner._last_resolution_generic_only_expected_missing)

    def test_click_no_effect_recovery_end_to_end_stamps_verify_result_on_healed_step(self):
        # Fiação completa: _finalize_click_success detecta CLICK_NO_EFFECT
        # (_detect_click_no_effect=False), escalona para
        # _attempt_deterministic_click_recovery (escape_retry resolve), e o
        # HEALED final em historico_passos.json carrega verify_result.
        page = MagicMock()
        self.runner._current_expected_effect = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}
        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        tier_before = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        effect_confirmed_after = {"url": "https://x/a", "domSize": 105, "overlays": 0}
        audit_after = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_detect_click_no_effect", return_value=False), \
             patch.object(self.runner, "_capture_click_effect_snapshot",
                           side_effect=[tier_before, effect_confirmed_after, audit_after]):
            result = self.runner._finalize_click_success(
                page, "#sel", "desc", "st_heal_003", False, None, click_effect_before_snapshot, attempt=2
            )

        self.assertTrue(result)
        step = self._step("st_heal_003")
        self.assertEqual(step["status"], "HEALED")
        self.assertEqual(step["resolver_tier"], "click_no_effect_recovered")
        self.assertEqual(step["verify_result"], "generic_only_expected_missing")


if __name__ == "__main__":
    unittest.main()
