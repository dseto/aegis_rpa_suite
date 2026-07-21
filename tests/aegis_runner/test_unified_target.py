import pytest
from unittest.mock import MagicMock, patch
from aegis_runner.runner import TransactionRunner

class DummyLocator:
    def __init__(self, elements=None, text=""):
        self._elements = elements or []
        self._text = text

    def count(self):
        return len(self._elements)

    def nth(self, i):
        return DummyLocator([self._elements[i]])

    def bounding_box(self):
        if self._elements and "bbox" in self._elements[0]:
            return self._elements[0]["bbox"]
        return {"x": 100, "y": 100, "width": 50, "height": 20}

    @property
    def first(self):
        return DummyLocator([self._elements[0]] if self._elements else [])

class TestUnifiedTarget:
    def setup_method(self):
        self.runner = TransactionRunner("dummy_project")
        self.runner.flaky_step_ids = {}

    def test_verify_recorded_expected_effect_url_change(self):
        page = MagicMock()

        before = {"url": "http://example.com/start", "domSize": 100, "overlays": 0}
        expected = {"url_changed": True, "dom_delta": 0, "overlay_delta": 0}

        # After snapshot has different url
        with patch.object(self.runner, "_capture_click_effect_snapshot", return_value={"url": "http://example.com/end", "domSize": 100, "overlays": 0}):
            result = self.runner._verify_recorded_expected_effect(page, before, expected)
            assert result is True

    def test_verify_recorded_expected_effect_dom_delta(self):
        page = MagicMock()

        before = {"url": "http://example.com/start", "domSize": 100, "overlays": 0}
        expected = {"url_changed": False, "dom_delta": 5, "overlay_delta": 0}

        # After snapshot has bigger dom size
        with patch.object(self.runner, "_capture_click_effect_snapshot", return_value={"url": "http://example.com/start", "domSize": 106, "overlays": 0}):
            result = self.runner._verify_recorded_expected_effect(page, before, expected)
            assert result is True

    def test_verify_recorded_expected_effect_fallback(self):
        page = MagicMock()

        before = {"url": "http://example.com/start", "domSize": 100, "overlays": 0}
        expected = {"url_changed": False, "dom_delta": 5, "overlay_delta": 0}

        # Nothing changed according to specific expected_effect fields, but _verify_generic_effect approves it
        with patch.object(self.runner, "_capture_click_effect_snapshot", return_value={"url": "http://example.com/start", "domSize": 100, "overlays": 0}):
            with patch.object(self.runner, "_verify_generic_effect", return_value=True):
                result = self.runner._verify_recorded_expected_effect(page, before, expected)
                assert result is True

    def test_resolve_via_anchor_with_ambiguity(self):
        page = MagicMock()

        # Mock locator behavior
        def mock_locator(sel):
            if sel == ".my-label":
                return DummyLocator([
                    {"bbox": {"x": 10, "y": 10, "width": 50, "height": 20}},
                    {"bbox": {"x": 100, "y": 100, "width": 50, "height": 20}}  # Match the recorded anchor bbox
                ])
            return DummyLocator()

        page.locator.side_effect = mock_locator
        page.viewport_size = {"width": 1280, "height": 720}

        anchor = {
            "selector": ".my-label",
            "text": "Label",
            "anchor_bbox": {"x": 100, "y": 100, "w": 50, "h": 20},
            "dx": 50,
            "dy": 0
        }

        result = self.runner._resolve_via_anchor(page, anchor, "click")

        # Calculated target: anchor center (125, 110) + dx (50), dy (0) -> (175, 110)
        assert result is not None
        # It's returning a MagicMock evaluate_handle
        assert page.evaluate_handle.call_args[0][1] == [175, 110] or page.evaluate.call_args is not None

    def test_resolve_via_anchor_not_found(self):
        page = MagicMock()
        page.locator.return_value = DummyLocator()
        page.get_by_text.return_value = DummyLocator()

        anchor = {
            "selector": ".non-existent",
            "text": "Label",
        }

        result = self.runner._resolve_via_anchor(page, anchor, "click")
        assert result is None
