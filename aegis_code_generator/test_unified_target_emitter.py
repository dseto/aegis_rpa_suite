import pytest
from aegis_code_generator.deterministic_emitter import emit_step_block

def test_emit_step_block_with_anchor_and_expected_effect():
    step = {
        "step_id": "st_001",
        "type": "click",
        "selector": ".my-btn",
        "description": "Click btn",
        "anchor": {"dx": 10, "dy": 20, "selector": ".label"},
        "expected_effect": {"dom_delta": 5},
        "viewport": {"width": 1280, "height": 720}
    }

    code = emit_step_block(step, dicionario={})
    assert "anchor={'dx': 10, 'dy': 20, 'selector': '.label'}" in code
    assert "expected_effect={'dom_delta': 5}" in code
    assert "viewport={'width': 1280, 'height': 720}" in code

    step_fill = {
        "step_id": "st_002",
        "type": "fill",
        "selector": ".my-input",
        "description": "Fill input",
        "anchor": {"dx": 5, "dy": -5, "selector": ".label2"},
        "expected_effect": {"value_changed": True}
    }

    code_fill = emit_step_block(step_fill, dicionario={})
    assert "anchor={'dx': 5, 'dy': -5, 'selector': '.label2'}" in code_fill
    assert "expected_effect={'value_changed': True}" in code_fill
