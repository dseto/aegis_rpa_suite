import os
import shutil
import unittest
from unittest.mock import MagicMock, patch

from runner import TransactionRunner


def _locator_router(close_selector_that_succeeds):
    def _router(sel):
        m = MagicMock()
        if sel == close_selector_that_succeeds:
            m.first.is_visible.return_value = True
            m.first.click.return_value = None
        else:
            m.first.is_visible.return_value = False
            m.first.click.return_value = None
        return m
    return _router


class TestUnmappedOverlayHandler(unittest.TestCase):
    """E3 (.specs/backlog-evolucao-agentica-design-time.md) -- handler
    determinístico de overlay não mapeado, Nível 2.85 de
    _attempt_deterministic_click_recovery."""

    def setUp(self):
        self.project_dir = "fake_project_unmapped_overlay"
        os.makedirs(self.project_dir, exist_ok=True)
        self.runner = TransactionRunner(project_dir=self.project_dir)

    def tearDown(self):
        if os.path.exists(self.project_dir):
            try:
                shutil.rmtree(self.project_dir)
            except Exception:
                pass

    def test_dismisses_unmapped_overlay_via_canonical_close_button_and_resolves(self):
        # Baseline do attempt (fora deste tier): sem overlay. Um overlay novo
        # aparece antes deste tier rodar (popup/banner não mapeado). Escape
        # sozinho (tentado por este próprio tier, apos 2.5/2.75 já terem
        # tentado e falhado) não resolve -- precisa do botão de fechar
        # canônico. Depois do dismiss, o clique original é reconfirmado com
        # baseline FRESCO (criterio d).
        page = MagicMock()
        page.locator.side_effect = _locator_router("[aria-label*='close' i]")

        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        self.runner._current_expected_effect = None  # passo não prevê abrir overlay

        snapshots = [
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.5 tier_before
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.5 effect_confirmed after (sem mudança -> ressalva bloqueia)
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.75 tier_before
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.75 effect_confirmed after (sem mudança -> ressalva bloqueia)
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # E3 probe_snapshot (overlay a mais confirmado)
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # E3 post_escape_snapshot (Escape sozinho não resolveu)
            {"url": "https://x/a", "domSize": 100, "overlays": 0},  # E3 tier_before pos-dismiss (fresco, overlay sumiu)
            {"url": "https://x/a", "domSize": 105, "overlays": 0},  # E3 effect_confirmed after (clique original confirmado)
        ]

        with patch.object(self.runner, "_capture_click_effect_snapshot", side_effect=snapshots), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_ov_001", identity_scoped=False, before_snapshot=click_effect_before_snapshot
            )

        self.assertTrue(recovered)
        self.assertEqual(method, "unmapped_overlay_dismissed")
        self.assertEqual(resolved_selector, "#sel")
        mock_register.assert_called_once_with("st_ov_001", "#sel", "click", "unmapped_overlay_dismissed")

    def test_expected_overlay_never_triggers_handler(self):
        # Criterio (b): expected_effect gravado do passo PREVÊ abrir overlay
        # (overlay_delta > 0) -- o overlay observado É o efeito esperado do
        # próprio clique, não ruído. O handler nunca deve disparar aqui.
        page = MagicMock()
        page.locator.side_effect = _locator_router("[aria-label*='close' i]")
        self.runner._current_expected_effect = {"url_changed": False, "dom_delta": 0, "overlay_delta": 1}

        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           side_effect=lambda *a, **k: {"url": "https://x/a", "domSize": 100, "overlays": 1}), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_ov_002", identity_scoped=False, before_snapshot=click_effect_before_snapshot
            )

        self.assertNotEqual(method, "unmapped_overlay_dismissed")
        for call in mock_register.call_args_list:
            self.assertNotIn("unmapped_overlay_dismissed", call.args)

    def test_identity_scoped_never_triggers_handler(self):
        # Criterio (c): caminho identity_scoped=True pula TODO o bloco
        # (2.5/2.75/2.85), mesma regra ja existente para os tiers vizinhos.
        page = MagicMock()
        page.locator.side_effect = _locator_router("[aria-label*='close' i]")
        self.runner._current_expected_effect = None

        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}

        with patch.object(self.runner, "_capture_click_effect_snapshot",
                           side_effect=lambda *a, **k: {"url": "https://x/a", "domSize": 100, "overlays": 1}), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_ov_003", identity_scoped=True, before_snapshot=click_effect_before_snapshot
            )

        self.assertNotEqual(method, "unmapped_overlay_dismissed")
        for call in mock_register.call_args_list:
            self.assertNotIn("unmapped_overlay_dismissed", call.args)

    def test_no_before_snapshot_never_triggers_handler(self):
        # Caminho por exceção (_handle_click_failure, before_snapshot=None):
        # sem baseline nao ha como provar "overlay a mais" -- handler nunca
        # dispara, mesmo com identity_scoped=False.
        page = MagicMock()
        page.locator.side_effect = _locator_router("[aria-label*='close' i]")
        self.runner._current_expected_effect = None

        with patch.object(self.runner, "_register_healing_for_review") as mock_register:
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_ov_004", identity_scoped=False, before_snapshot=None
            )

        self.assertNotEqual(method, "unmapped_overlay_dismissed")
        for call in mock_register.call_args_list:
            self.assertNotIn("unmapped_overlay_dismissed", call.args)

    def test_escape_alone_dismisses_without_needing_close_button(self):
        # Variante mais barata: Escape do proprio tier 2.85 ja resolve o
        # overlay -- nao deveria precisar escalar pro botao de fechar.
        page = MagicMock()
        close_button_calls = []

        def _router(sel):
            m = MagicMock()
            if sel not in ("#sel",):
                close_button_calls.append(sel)
            return m
        page.locator.side_effect = _router

        click_effect_before_snapshot = {"url": "https://x/a", "domSize": 100, "overlays": 0}
        self.runner._current_expected_effect = None

        snapshots = [
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.5 tier_before
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.5 after (bloqueado pela ressalva)
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.75 tier_before
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # tier2.75 after (bloqueado pela ressalva)
            {"url": "https://x/a", "domSize": 100, "overlays": 1},  # E3 probe_snapshot
            {"url": "https://x/a", "domSize": 100, "overlays": 0},  # E3 post_escape_snapshot -- Escape resolveu sozinho
            {"url": "https://x/a", "domSize": 100, "overlays": 0},  # E3 tier_before pos-dismiss
            {"url": "https://x/a", "domSize": 105, "overlays": 0},  # E3 effect_confirmed after
        ]

        with patch.object(self.runner, "_capture_click_effect_snapshot", side_effect=snapshots), \
             patch.object(self.runner, "_register_healing_for_review") as mock_register:
            recovered, method, resolved_selector = self.runner._attempt_deterministic_click_recovery(
                page, "#sel", "st_ov_005", identity_scoped=False, before_snapshot=click_effect_before_snapshot
            )

        self.assertTrue(recovered)
        self.assertEqual(method, "unmapped_overlay_dismissed")
        self.assertEqual(close_button_calls, [])  # nunca precisou do botão canônico
        mock_register.assert_called_once_with("st_ov_005", "#sel", "click", "unmapped_overlay_dismissed")


if __name__ == "__main__":
    unittest.main()
