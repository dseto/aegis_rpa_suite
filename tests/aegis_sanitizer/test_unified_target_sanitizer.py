import pytest
from aegis_sanitizer.sanitizer import SanitizerService

def test_sanitizer_propagates_anchor_and_expected_effect():
    sanitizer = SanitizerService(telemetry_dir="/dummy")

    # Test the static serializer
    step = sanitizer._serialize_plan_step({
        "step_id": "st_001",
        "type": "click",
        "anchor": {"dx": 10},
        "expected_effect": {"dom_delta": 5},
        "viewport": {"width": 1280}
    })

    assert "anchor" in step
    assert step["anchor"]["dx"] == 10
    assert "expected_effect" in step
    assert step["expected_effect"]["dom_delta"] == 5
    assert "viewport" in step
    assert step["viewport"]["width"] == 1280
