"""
Testes unitários dos emissores puros de aegis_sanitizer/deterministic_emitter.py
(Seção 2.1 do plano `.specs/plano-codegen-hibrido-deterministico.md`) e da
linha de corte determinístico x cognitivo `classify_step`/`build_skeleton`
(Seção 2.2/2.3/2.4, tarefa H2 — "SUBAGENTE 04").

Cada emissor é testado isoladamente. Onde faz sentido, o bloco emitido é
colado dentro de uma função e parseado via `ast` para provar que o resultado
é sintaticamente válido e que a chamada/estrutura esperada realmente aparece
na árvore — não só por substring.

A segunda metade deste arquivo (`TestClassifyStepConditions`,
`TestRoundTripGoldens`) é o GATE CENTRAL do plano (Seção 4.1): prova que
`build_skeleton`, quando emite deterministicamente, produz código que passa
por TODOS os validadores existentes de `step_validator.py` — contra os três
goldens de `.specs/golden/` (v1 puro, v2 rico, fixture sintética da matriz).
"""

import ast
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deterministic_emitter import (
    _emit_click,
    _emit_fill,
    _emit_select,
    _emit_select_native,
    _emit_async_guard,
    _emit_optional_wrapper,
    emit_step_block,
    classify_step,
    build_skeleton,
    EmissionDecision,
)
import deterministic_emitter as _de_module
from code_generator import CodeGeneratorService
from step_validator import (
    validate_bot_structure,
    validate_bot_against_plan,
    validate_resilience_patterns,
    validate_dataset_field_names,
    dry_run_bot,
    reorder_steps_to_match_plan,
    extract_step_ids_from_code,
)

# Raiz do framework — precisa estar em project_root do dry_run_bot pra
# 'import aegis_runner.runner' resolver dentro do subprocess do harness
# (mesma convenção de aegis_sanitizer/test_dryrun_multirow.py).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(REPO_ROOT, ".specs", "golden")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_wrapped(indented_body: str):
    """Cola `indented_body` (já indentado a 4 espaços) dentro de uma função
    e retorna a árvore ast — dispara se o resultado não for sintaticamente
    válido."""
    code = "def execute_scenario_default(page, row, runner):\n" + indented_body + "\n"
    return ast.parse(code)


def _calls_named(tree, method_name):
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == method_name
    ]


class TestEmitClick(unittest.TestCase):
    def test_parent_produces_click_chained_with_dict_literals(self):
        step = {
            "step_id": "st_003",
            "type": "click",
            "selector": "#app div",
            "description": "Clicar na área do aplicativo",
            "parent": {"selector": "#app", "has_text": None},
        }
        code = _emit_click(step)
        self.assertIn("runner.click_chained(", code)
        self.assertIn('parent={"selector": "#app", "has_text": None}', code)
        self.assertIn('child={"selector": "#app div"}', code)
        self.assertIn('step_id="st_003"', code)

        indented = "\n".join("    " + line for line in code.split("\n"))
        tree = _parse_wrapped(indented)
        calls = _calls_named(tree, "click_chained")
        self.assertEqual(len(calls), 1)
        # parent/child devem ser ast.Dict (não strings) — INVALID_CHAINED_LOCATOR_SHAPE
        kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertIsInstance(kwargs["parent"], ast.Dict)
        self.assertIsInstance(kwargs["child"], ast.Dict)

    def test_coords_produce_original_coords_kwarg(self):
        step = {
            "step_id": "st_004",
            "type": "click",
            "selector": "#btn-login",
            "description": "Clicar no botão",
            "coords": [0.4625, 0.7642163661581137],
        }
        code = _emit_click(step)
        self.assertIn("runner.click_resilient(", code)
        self.assertIn("original_coords=(0.4625, 0.7642163661581137)", code)
        self.assertIn('step_id="st_004"', code)

    def test_weak_selector_with_text_gets_has_text_anchor(self):
        step = {
            "step_id": "st_001",
            "type": "click",
            "selector": "#btn-generic",
            "description": "Clique genérico",
            "weak_selector": True,
            "text": "Confirmar",
        }
        code = _emit_click(step)
        self.assertIn(":has-text('Confirmar')", code)
        self.assertIn('selector="#btn-generic:has-text(\'Confirmar\')"', code)

    def test_weak_selector_without_text_leaves_selector_untouched(self):
        step = {
            "step_id": "st_002",
            "type": "click",
            "selector": "#btn-generic",
            "description": "Clique genérico sem material de ancoragem",
            "weak_selector": True,
        }
        code = _emit_click(step)
        self.assertNotIn(":has-text(", code)

    def test_weak_selector_with_parent_has_text_does_not_double_anchor_child(self):
        step = {
            "step_id": "st_050",
            "type": "click",
            "selector": "table #grid-tbody tr button:has-text('Cláusulas')",
            "description": "Clicar no botão 'Cláusulas'",
            "weak_selector": True,
            "text": "Cláusulas",
            "parent": {"selector": ".mat-row", "has_text": "RCV - Danos Morais"},
        }
        code = _emit_click(step)
        self.assertIn('"has_text": "RCV - Danos Morais"', code)
        # child já vem com :has-text no seletor gravado; não deve duplicar.
        self.assertEqual(code.count(":has-text("), 1)


class TestEmitFill(unittest.TestCase):
    def test_human_like_strategy_from_field(self):
        step = {
            "step_id": "st_006",
            "type": "fill",
            "selector": "label:has-text('CPF do Cliente') ~ input",
            "description": "Preencher o campo 'CPF do Cliente'",
        }
        field = {"semantic_key": "cpf_cliente", "fill_strategy": "HUMAN_LIKE"}
        code = _emit_fill(step, field)
        self.assertIn('strategy="HUMAN_LIKE"', code)
        self.assertIn('row.get("cpf_cliente", "")', code)
        self.assertIn("runner.fill_resilient(", code)

    def test_direct_strategy_default(self):
        step = {"step_id": "st_001", "type": "fill", "selector": "#username", "description": "Preencher e-mail"}
        field = {"semantic_key": "email_login", "fill_strategy": "DIRECT"}
        code = _emit_fill(step, field)
        self.assertIn('strategy="DIRECT"', code)
        self.assertIn('row.get("email_login", "")', code)

    def test_missing_fill_strategy_defaults_to_direct(self):
        step = {"step_id": "st_020", "type": "fill", "selector": "input[placeholder='Pesquisar Marca...']",
                "description": "Preencher marca"}
        field = {"semantic_key": "marca_veiculo"}
        code = _emit_fill(step, field)
        self.assertIn('strategy="DIRECT"', code)

    def test_parent_produces_fill_chained(self):
        step = {
            "step_id": "st_057",
            "type": "fill",
            "selector": "input",
            "description": "Preencher o campo de input com o código PIX",
            "parent": {"selector": ".pix-copia-cola-container", "has_text": "Copiar Código"},
        }
        field = {"semantic_key": "codigo_copia_cola_pix", "fill_strategy": "DIRECT"}
        code = _emit_fill(step, field)
        self.assertIn("runner.fill_chained(", code)
        self.assertIn('parent={"selector": ".pix-copia-cola-container", "has_text": "Copiar Código"}', code)
        self.assertIn('child={"selector": "input"}', code)


class TestEmitSelect(unittest.TestCase):
    def test_select_with_coords_trigger_and_option(self):
        step = {
            "step_id": "st_010",
            "type": "select",
            "dropdown_label": "Sexo",
            "coords_trigger": [0.4890625, 0.6879334257975035],
            "coords_option": [0.475, 0.7891816920943134],
        }
        field = {"semantic_key": "genero_cliente"}
        code = _emit_select(step, field)
        self.assertIn("runner.select_option_resilient(", code)
        self.assertIn("original_coords_trigger=(0.4890625, 0.6879334257975035)", code)
        self.assertIn("original_coords_option=(0.475, 0.7891816920943134)", code)
        self.assertIn('row.get("genero_cliente", "")', code)
        self.assertIn('dropdown_label="Sexo"', code)
        self.assertNotIn("Feminino", code)  # nunca literal do plano

    def test_select_without_coords_omits_kwargs(self):
        step = {"step_id": "st_011", "type": "select", "dropdown_label": "Estado Civil"}
        field = {"semantic_key": "estado_civil_cliente"}
        code = _emit_select(step, field)
        self.assertNotIn("original_coords_trigger", code)
        self.assertNotIn("original_coords_option", code)


class TestEmitSelectNative(unittest.TestCase):
    def test_binds_by_selector_not_trigger_selector(self):
        # Steps select_native reais carregam 'selector' normal, SEM
        # trigger_selector (achado R1 do plano) — o emissor deve usar
        # apenas step['selector'].
        step = {
            "step_id": "st_008",
            "type": "select_native",
            "selector": "#role",
            "description": "Preencher o cargo 'QA'",
            "trigger_selector": None,
        }
        field = {"semantic_key": "cargo_profissional"}
        code = _emit_select_native(step, field)
        self.assertIn("runner.select_option_native_resilient(", code)
        self.assertIn('selector="#role"', code)
        self.assertIn('row.get("cargo_profissional", "")', code)
        self.assertNotIn("trigger_selector", code)


class TestAsyncGuard(unittest.TestCase):
    def test_triggers_for_cpf(self):
        self.assertIn("time.sleep(2.0)", _emit_async_guard({}, {"semantic_key": "cpf_cliente"}))

    def test_triggers_for_cnpj(self):
        self.assertIn("time.sleep(2.0)", _emit_async_guard({}, {"semantic_key": "cnpj_empresa"}))

    def test_triggers_for_cep(self):
        self.assertIn("time.sleep(2.0)", _emit_async_guard({}, {"semantic_key": "cep_pernoite"}))

    def test_does_not_trigger_for_nome(self):
        self.assertEqual("", _emit_async_guard({}, {"semantic_key": "nome_cliente"}))

    def test_does_not_trigger_without_field(self):
        self.assertEqual("", _emit_async_guard({}, None))


class TestOptionalWrapper(unittest.TestCase):
    def test_wraps_call_in_try_except_and_prints_error(self):
        step = {"step_id": "sup_003"}
        inner = (
            "runner.click_resilient(\n"
            "    page,\n"
            '    selector=".cdk-overlay-backdrop",\n'
            '    target_description="Fechar overlay",\n'
            '    step_id="sup_003"\n'
            ")"
        )
        wrapped = _emit_optional_wrapper(inner, step)
        self.assertTrue(wrapped.startswith("try:"))
        self.assertIn("except Exception as _opt_err:", wrapped)
        self.assertIn("sup_003", wrapped)
        self.assertIn("{_opt_err}", wrapped)

        indented = "\n".join("    " + line for line in wrapped.split("\n"))
        tree = _parse_wrapped(indented)
        func = tree.body[0]
        try_nodes = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
        self.assertEqual(len(try_nodes), 1)
        calls_in_try = [
            n for n in ast.walk(try_nodes[0])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "click_resilient"
        ]
        self.assertEqual(len(calls_in_try), 1)
        # o except deve sempre imprimir o erro (nunca engolir silenciosamente)
        handler = try_nodes[0].handlers[0]
        handler_calls = [n for n in ast.walk(handler) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(c.func, ast.Name) and c.func.id == "print" for c in handler_calls))


class TestEmitStepBlock(unittest.TestCase):
    def _dicionario(self):
        return {
            "fields": {
                "email_login": {"selector": "#username", "fill_strategy": "DIRECT"},
                "cpf_cliente": {
                    "selector": "label:has-text('CPF do Cliente') ~ input",
                    "fill_strategy": "HUMAN_LIKE",
                },
                "nome_cliente": {
                    "selector": "label:has-text('Nome Completo') ~ input",
                    "fill_strategy": "HUMAN_LIKE",
                },
                "cargo_profissional": {"selector": "#role", "fill_strategy": "DIRECT"},
                "genero_cliente": {"selector": "label:has-text('Sexo') ~ div", "fill_strategy": "DIRECT"},
            }
        }

    def test_fill_step_dispatch_and_anchor(self):
        step = {"step_id": "st_001", "type": "fill", "selector": "#username", "description": "Preencher e-mail"}
        block = emit_step_block(step, self._dicionario())
        self.assertIn("# [PASSO 1] Preencher e-mail", block)
        self.assertIn("runner.fill_resilient(", block)
        self.assertIn('row.get("email_login", "")', block)
        # bloco inteiro deve ser válido dentro do corpo da função (indentação
        # de 4 espaços já aplicada por emit_step_block).
        _parse_wrapped(block)

    def test_async_guard_appended_after_cpf_fill(self):
        step = {
            "step_id": "st_006",
            "type": "fill",
            "selector": "label:has-text('CPF do Cliente') ~ input",
            "description": "Preencher CPF",
        }
        block = emit_step_block(step, self._dicionario())
        self.assertIn("time.sleep(2.0)", block)
        self.assertIn('strategy="HUMAN_LIKE"', block)
        _parse_wrapped(block)

    def test_no_async_guard_for_non_matching_key(self):
        step = {
            "step_id": "st_008",
            "type": "fill",
            "selector": "label:has-text('Nome Completo') ~ input",
            "description": "Preencher nome",
        }
        block = emit_step_block(step, self._dicionario())
        self.assertNotIn("time.sleep(2.0)", block)

    def test_select_native_dispatch_binds_by_selector(self):
        step = {
            "step_id": "st_008",
            "type": "select_native",
            "selector": "#role",
            "description": "Preencher cargo",
            "trigger_selector": None,
        }
        block = emit_step_block(step, self._dicionario())
        self.assertIn("runner.select_option_native_resilient(", block)
        self.assertIn('row.get("cargo_profissional", "")', block)
        _parse_wrapped(block)

    def test_select_dispatch_binds_by_trigger_selector(self):
        step = {
            "step_id": "st_010",
            "type": "select",
            "selector": "",
            "trigger_selector": "label:has-text('Sexo') ~ div",
            "dropdown_label": "Sexo",
            "description": "Selecionar sexo",
        }
        block = emit_step_block(step, self._dicionario())
        self.assertIn("runner.select_option_resilient(", block)
        self.assertIn('row.get("genero_cliente", "")', block)
        _parse_wrapped(block)

    def test_click_dispatch_no_field_resolution_needed(self):
        step = {"step_id": "st_004", "type": "click", "selector": "#btn-login", "description": "Clicar no botão"}
        block = emit_step_block(step, self._dicionario())
        self.assertIn("runner.click_resilient(", block)
        _parse_wrapped(block)

    def test_optional_step_wraps_in_try_except(self):
        step = {
            "step_id": "sup_003",
            "type": "click",
            "selector": ".cdk-overlay-backdrop",
            "description": "Fechar overlay residual",
            "execution_hint": "optional",
        }
        block = emit_step_block(step, {"fields": {}})
        self.assertIn("try:", block)
        self.assertIn("except Exception as _opt_err:", block)
        self.assertIn("sup_003", block)
        tree = _parse_wrapped(block)
        func = tree.body[0]
        try_nodes = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
        self.assertEqual(len(try_nodes), 1)
        calls_in_try = _calls_named(try_nodes[0], "click_resilient")
        self.assertEqual(len(calls_in_try), 1)

    def test_unsupported_type_raises(self):
        step = {"step_id": "st_099", "type": "filechooser", "description": "Upload de arquivo"}
        with self.assertRaises(ValueError):
            emit_step_block(step, {"fields": {}})


# =============================================================================
# classify_step — tabela de casos C1-C10 (Seção 2.2 do plano; teste "CL" da
# Seção 4.1). Usa a fixture da matriz (.specs/golden/synthetic_hybrid_matrix)
# para os casos que ela cobre e casos inline para os que ela deliberadamente
# não cobre (README da fixture: Padrão N/C6 e pending_corrections/C8 ficam
# fora da matriz lettered [a]-[h]).
# =============================================================================

def _next_emittable_step(steps, index):
    """
    Mesma definição usada por build_skeleton/_render_plan_for_prompt: o
    próximo step cujo execution_hint não é 'skip'.
    """
    for step in steps[index + 1:]:
        if step.get("execution_hint") != "skip":
            return step
    return None


class TestClassifyStepConditionsMatrixFixture(unittest.TestCase):
    """Um caso por step da fixture .specs/golden/synthetic_hybrid_matrix — cada
    step foi desenhado (ver README.md da fixture) para reprovar/passar
    exatamente UMA condição C1-C10 de forma isolada e legível."""

    @classmethod
    def setUpClass(cls):
        matrix_dir = os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix")
        cls.plan = _load_json(os.path.join(matrix_dir, "plano_execucao.json"))
        cls.dicionario = _load_json(os.path.join(matrix_dir, "dicionario.json"))
        cls.steps = cls.plan["steps"]

    def _classify(self, step_id):
        index = next(i for i, s in enumerate(self.steps) if s["step_id"] == step_id)
        step = self.steps[index]
        next_step = _next_emittable_step(self.steps, index)
        return classify_step(step, self.dicionario, None, next_step)

    def test_st_001_optional_is_cognitive_via_C2(self):
        decision = self._classify("st_001")
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C2", decision.reason)

    def test_st_002_parent_has_text_is_deterministic(self):
        decision = self._classify("st_002")
        self.assertEqual(decision.kind, "deterministic")

    def test_sup_001_skip_is_omit_via_C2(self):
        decision = self._classify("sup_001")
        self.assertEqual(decision.kind, "omit")
        self.assertIn("C2", decision.reason)

    def test_st_003_select_binds_via_trigger_selector_is_deterministic(self):
        decision = self._classify("st_003")
        self.assertEqual(decision.kind, "deterministic")

    def test_st_004_select_native_binds_via_selector_is_deterministic(self):
        decision = self._classify("st_004")
        self.assertEqual(decision.kind, "deterministic")

    def test_st_005_padrao_q_is_cognitive_via_C3(self):
        decision = self._classify("st_005")
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C3", decision.reason)

    def test_st_006_business_value_in_selector_is_cognitive_via_C10(self):
        # RT4 (Seção 4.1 item 4): a célula obrigatória do caso C10/B1.
        decision = self._classify("st_006")
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C10", decision.reason)
        self.assertIn("Curitiba", decision.reason)

    def test_st_007_static_widget_text_passes_C10_is_deterministic(self):
        # Teste negativo de C10: :has-text(...) presente, mas o literal não
        # casa nenhum observed_value — não é bloqueio genérico de autocomplete.
        decision = self._classify("st_007")
        self.assertEqual(decision.kind, "deterministic")

    def test_st_008_weak_selector_with_parent_has_text_anchor_is_deterministic(self):
        decision = self._classify("st_008")
        self.assertEqual(decision.kind, "deterministic")

    def test_st_009_weak_selector_without_anchor_is_cognitive_via_C5(self):
        decision = self._classify("st_009")
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C5", decision.reason)


class TestClassifyStepConditionsInline(unittest.TestCase):
    """Condições que a fixture da matriz deliberadamente não cobre (C1, C4
    ambíguo/duplicado, C6, C8, C9) — casos mínimos construídos inline."""

    def test_c1_unsupported_type_is_cognitive(self):
        step = {"step_id": "st_900", "type": "filechooser", "description": "Upload"}
        decision = classify_step(step, {"fields": {}})
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C1", decision.reason)

    def test_c4_fill_zero_matches_is_cognitive(self):
        step = {"step_id": "st_901", "type": "fill", "selector": "#nao-mapeado", "description": "Campo sem binding"}
        decision = classify_step(step, {"fields": {}})
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C4", decision.reason)

    def test_c4_fill_two_matches_is_cognitive(self):
        # Dois fields do dicionário casam o mesmo selector — binding ambíguo.
        dicionario = {
            "fields": {
                "campo_a": {"selector": "#ambiguo"},
                "campo_b": {"selector": "#ambiguo"},
            }
        }
        step = {"step_id": "st_902", "type": "fill", "selector": "#ambiguo", "description": "Campo ambíguo"}
        decision = classify_step(step, dicionario)
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C4", decision.reason)

    def test_c4_fill_resolves_via_selector_original_fallback(self):
        dicionario = {"fields": {"campo_a": {"selector": "#original"}}}
        step = {
            "step_id": "st_903", "type": "fill", "selector": "#novo-depois-de-heal",
            "selector_original": "#original", "description": "Campo com selector atualizado",
        }
        decision = classify_step(step, dicionario)
        self.assertEqual(decision.kind, "deterministic")

    def test_c6_menu_heuristic_selector_is_cognitive(self):
        step = {"step_id": "st_904", "type": "click", "selector": "#menu-item-3", "description": "Item de menu"}
        decision = classify_step(step, {"fields": {}})
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C6", decision.reason)

    def test_c8_step_id_targeted_by_pending_correction_is_cognitive(self):
        step = {"step_id": "st_905", "type": "click", "selector": "#btn", "description": "Passo com correção pendente"}
        pending = [{"step_id": "st_905", "required_wait": {"blocking_value": "Avançar"}}]
        decision = classify_step(step, {"fields": {}}, pending)
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C8", decision.reason)

    def test_c8_after_step_id_of_required_reopen_is_cognitive(self):
        step = {"step_id": "st_906", "type": "click", "selector": "#btn", "description": "Passo anterior ao reabertura"}
        pending = [{"step_id": "st_907", "required_reopen": {"after_step_id": "st_906", "selector": "#x"}}]
        decision = classify_step(step, {"fields": {}}, pending)
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C8", decision.reason)

    def test_c9_fill_immediately_before_select_is_cognitive(self):
        dicionario = {"fields": {"campo_busca": {"selector": "input[placeholder='Buscar...']"}}}
        step = {"step_id": "st_908", "type": "fill", "selector": "input[placeholder='Buscar...']", "description": "Busca"}
        next_step = {"step_id": "st_909", "type": "select", "trigger_selector": "div"}
        decision = classify_step(step, dicionario, None, next_step)
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C9", decision.reason)

    def test_c9_fill_immediately_before_autocomplete_click_is_cognitive(self):
        dicionario = {"fields": {"campo_busca": {"selector": "input[placeholder='Buscar...']"}}}
        step = {"step_id": "st_910", "type": "fill", "selector": "input[placeholder='Buscar...']", "description": "Busca"}
        next_step = {"step_id": "st_911", "type": "click", "selector": "#mat-autocomplete-panel-x div:has-text('Y')"}
        decision = classify_step(step, dicionario, None, next_step)
        self.assertEqual(decision.kind, "cognitive")
        self.assertIn("C9", decision.reason)

    def test_c9_fill_not_followed_by_autocomplete_is_unaffected(self):
        step = {"step_id": "st_912", "type": "fill", "selector": "#a"}
        next_step = {"step_id": "st_913", "type": "fill", "selector": "#b"}
        decision = classify_step(step, {"fields": {"campo_a": {"selector": "#a"}}}, None, next_step)
        self.assertEqual(decision.kind, "deterministic")

    def test_flaky_field_is_pass_through_and_does_not_affect_classification(self):
        base_step = {"step_id": "st_914", "type": "click", "selector": "#btn", "description": "Passo"}
        flaky_step = dict(base_step, flaky=True)
        self.assertEqual(classify_step(base_step, {"fields": {}}).kind, classify_step(flaky_step, {"fields": {}}).kind)


# =============================================================================
# Round-trip (Seção 4.1 do plano) — o gate central. build_skeleton, com TODOS
# os steps forçados a deterministic ONDE POSSÍVEL (bypass de classify_step via
# monkeypatch, sugerido explicitamente pelo enunciado da tarefa), tem que
# produzir um arquivo que passa com ZERO erros em TODOS os validadores de
# step_validator.py, para os três goldens: v1 puro, v2 rico e a fixture da
# matriz.
#
# "Onde possível" (documentado, não é escolha arbitrária do teste): alguns
# steps são GENUINAMENTE impossíveis de forçar sem produzir código quebrado
# por construção — forçá-los violaria um validador que não tem nada a ver com
# julgamento humano, só com a FALTA de informação que o emissor precisaria:
#   - tipo não suportado pelo emissor (nenhum no nosso inventário de goldens);
#   - binding C4 ausente/ambíguo para fill/select/select_native — forçar
#     produziria row.get("", "") -> HALLUCINATED_DATASET_FIELD;
#   - weak_selector sem NENHUM material de ancoragem (C5) — forçar produziria
#     WEAK_SELECTOR_WITHOUT_ANCHOR;
#   - valor de negócio embutido no seletor (C10) — forçar seria o próprio bug
#     B1 que este plano existe para prevenir, e violaria o teste negativo
#     global desta mesma seção;
#   - valor de negócio em parent.has_text sob Padrão Q (has_text_original
#     presente + observed_value do dicionário por substring no residual, a
#     mesma detecção do check Q-b) — forçar emitiria o literal gravado
#     (nome/CPF de cliente) e reprovaria em HARDCODED_PARENT_HAS_TEXT, a
#     variante do bug B1 para parent.has_text (Seção 3.3 emendada do plano).
# Todas as outras condições (C3 Padrão Q com residual estático, C6 Padrão N,
# C8 pending_corrections, C9 autocomplete) são "julgamento", não
# "impossibilidade": forçá-las ainda produz código que MECANICAMENTE passa
# nos validadores atuais (ex.: Padrão Q SEM valor de negócio no residual
# forçado emite o has_text JÁ SANITIZADO — que é literalmente o que
# MISSING_PARENT_HAS_TEXT compara — mesmo sendo a escolha "errada" do ponto de
# vista de fidelidade dinâmica que motiva a política real ser conservadora).
#
# Os step_ids abaixo são GENUINAMENTE impossíveis nestes goldens específicos
# (achado empírico, verificado por inspeção): os goldens reais têm 4 selects
# com trigger_selector genérico "div" que não resolve ao field certo (0 ou N
# matches), 3 clicks de autocomplete com valor de negócio no seletor (C10,
# o próprio caso B1 do plano) e, no golden v2, 1 click de Padrão Q com valor
# de negócio no residual de parent.has_text (st_062 — a 4ª categoria acima;
# no golden v1 o MESMO st_062 não tem has_text_original, então o gatilho Q-b
# não dispara e ele continua forçável — ver scope-note da Seção 3.3). Como
# são 'required' (sem execution_hint), e o round-trip não invoca LLM nenhuma
# para preencher esses slots cognitivos, a comparação contra o plano usa uma
# CÓPIA do plano com esses ids rebaixados para 'optional' — acomodação
# exclusiva de TESTE (não muda a política real de classify_step, que continua
# os classificando 'cognitive' normalmente; em produção esses slots seriam
# preenchidos pela LLM, não omitidos).
_KNOWN_COGNITIVE_ONLY_STEP_IDS = {
    "real_portal_segura_001": {
        "st_011", "st_017", "st_031", "st_048",  # C4: trigger_selector "div" genérico, 0 matches
        "st_023", "st_024", "st_025",  # C10: valor de negócio no seletor (Hyundai/Creta/...)
    },
    "real_portal_segura_001_v2": {
        "st_011", "st_017", "st_031", "st_048",
        "st_023", "st_024", "st_025",
        "st_062",  # Padrão Q com valor de negócio no residual de parent.has_text (Q-b/HARDCODED_PARENT_HAS_TEXT)
    },
    "synthetic_hybrid_matrix": {
        "st_006",  # C10: 'Curitiba' é observed_value de cidade_cliente
        "st_009",  # C5: weak_selector sem nenhum material de ancoragem
    },
}


def _force_classify_where_possible(step, dicionario=None, pending_corrections=None, next_step=None):
    """
    Classificador de TESTE (nunca usado em produção): bypassa C3/C6/C8/C9
    (julgamento) e força 'deterministic' sempre que possível, mas respeita as
    impossibilidades genuínas documentadas acima (C1 tipo, C4 binding, C5
    material, C10 valor de negócio) — forçar essas quebraria um validador ou o
    próprio teste negativo de C10.
    """
    dicionario = dicionario or {}
    hint = step.get("execution_hint")
    step_type = step.get("type")

    if hint == "skip":
        return EmissionDecision("omit", "forced-test: C2 skip")

    if step_type not in _de_module._SUPPORTED_TYPES:
        return EmissionDecision("cognitive", "forced-test: C1 tipo não suportado (genuinamente impossível)")

    if step_type in ("fill", "select_native"):
        matches = _de_module._count_field_matches(dicionario, step.get("selector"))
        if matches == 0:
            matches = _de_module._count_field_matches(dicionario, step.get("selector_original"))
        if matches != 1:
            return EmissionDecision("cognitive", "forced-test: C4 binding ausente/ambíguo (genuinamente impossível)")
    elif step_type == "select":
        matches = _de_module._count_field_matches(dicionario, step.get("trigger_selector"))
        if matches != 1:
            return EmissionDecision("cognitive", "forced-test: C4 binding ausente/ambíguo (genuinamente impossível)")

    parent = step.get("parent") or {}
    selector = step.get("selector") or ""
    text = step.get("text")
    if step.get("weak_selector"):
        has_material = bool(parent.get("has_text")) or bool(text) or (":has-text(" in selector)
        if not has_material:
            return EmissionDecision("cognitive", "forced-test: C5 sem material de ancoragem (genuinamente impossível)")

    observed_values = _de_module._collect_observed_values(dicionario)
    if observed_values:
        literals = _de_module._extract_has_text_literals(selector)
        if any(lit in observed_values for lit in literals):
            return EmissionDecision("cognitive", "forced-test: C10 valor de negócio no seletor (genuinamente impossível)")
        if isinstance(text, str) and text in observed_values:
            return EmissionDecision("cognitive", "forced-test: C10 valor de negócio no texto (genuinamente impossível)")
        # 4ª categoria de impossibilidade genuína (Seção 3.3 emendada do
        # plano): Padrão Q com valor de negócio no residual de
        # parent.has_text — MESMA detecção do gatilho Q-b do validador
        # (has_text_original presente + observed_value >=3 chars por
        # SUBSTRING no residual). Forçar deterministic emitiria o literal
        # gravado e reprovaria em HARDCODED_PARENT_HAS_TEXT.
        plan_has_text = parent.get("has_text")
        if parent.get("has_text_original") and isinstance(plan_has_text, str):
            if any(len(v) >= 3 and v in plan_has_text for v in observed_values):
                return EmissionDecision(
                    "cognitive",
                    "forced-test: Padrão Q com valor de negócio em parent.has_text (genuinamente impossível)",
                )

    return EmissionDecision("deterministic", "forced-test: forçado (bypassa C3/C6/C8/C9)")


class TestRoundTripGoldens(unittest.TestCase):
    GOLDEN_CASES = [
        (
            "real_portal_segura_001",
            os.path.join(GOLDEN_DIR, "real_portal_segura_001", "plano_execucao.json"),
            os.path.join(GOLDEN_DIR, "real_portal_segura_001", "dicionario.json"),
        ),
        (
            "real_portal_segura_001_v2",
            os.path.join(GOLDEN_DIR, "real_portal_segura_001_v2", "plano_execucao.json"),
            # real_portal_segura_001_v2/ não tem dicionario.json próprio — é a
            # MESMA gravação/dicionário re-sanitizado (ver META.md daquele
            # golden), então usa o dicionário do golden v1 irmão.
            os.path.join(GOLDEN_DIR, "real_portal_segura_001", "dicionario.json"),
        ),
        (
            "synthetic_hybrid_matrix",
            os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix", "plano_execucao.json"),
            os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix", "dicionario.json"),
        ),
    ]

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aegis_rt_test_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self._tmpdir, ignore_errors=True))
        self.service = CodeGeneratorService(self._tmpdir)

    def _build_forced_skeleton(self, plan, dicionario):
        with mock.patch.object(_de_module, "classify_step", side_effect=_force_classify_where_possible):
            skeleton, manifest = build_skeleton(plan, dicionario)
        return skeleton, manifest

    def _write_json(self, name, data):
        path = os.path.join(self._tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def test_round_trip_zero_errors_against_all_validators(self):
        for name, plan_path, dic_path in self.GOLDEN_CASES:
            with self.subTest(golden=name):
                plan = _load_json(plan_path)
                dicionario = _load_json(dic_path)

                skeleton, manifest = self._build_forced_skeleton(plan, dicionario)
                bot_code = self.service._normalize_boilerplate(skeleton)

                # Cópia de plano SÓ para validação (rebaixa os ids
                # genuinamente-impossíveis documentados acima para
                # 'optional') — ver comentário longo antes desta classe.
                plan_copy = copy.deepcopy(plan)
                cognitive_only_ids = _KNOWN_COGNITIVE_ONLY_STEP_IDS.get(name, set())
                for step in plan_copy["steps"]:
                    if step["step_id"] in cognitive_only_ids:
                        step["execution_hint"] = "optional"

                plan_copy_path = self._write_json(f"{name}_plan_copy.json", plan_copy)
                dic_copy_path = self._write_json(f"{name}_dicionario.json", dicionario)

                struct_result = validate_bot_structure(bot_code)
                self.assertEqual(struct_result["status"], "PASS", struct_result["errors"])

                plan_result = validate_bot_against_plan(bot_code, plan_copy_path)
                self.assertEqual(plan_result["status"], "PASS", plan_result["errors"])

                resilience_result = validate_resilience_patterns(bot_code, plan_copy_path, dic_copy_path)
                self.assertEqual(resilience_result["status"], "PASS", resilience_result["errors"])

                dataset_result = validate_dataset_field_names(bot_code, dic_copy_path)
                self.assertEqual(dataset_result["status"], "PASS", dataset_result["errors"])

                dryrun_result = dry_run_bot(bot_code, REPO_ROOT, timeout=60)
                self.assertEqual(dryrun_result["status"], "PASS", dryrun_result["errors"])

    def test_negative_no_deterministic_block_hardcodes_observed_value(self):
        """
        Teste negativo global (Seção 4.1 item 4): NENHUM bloco emitido
        deterministicamente, em NENHUM round-trip, pode conter
        :has-text(<literal>) cujo literal case um observed_value do
        dicionário correspondente — varredura sobre a saída inteira, não só
        sobre os step_ids conhecidos de C10 (pega qualquer regressão futura
        de C10 por qualquer rota).
        """
        for name, plan_path, dic_path in self.GOLDEN_CASES:
            with self.subTest(golden=name):
                plan = _load_json(plan_path)
                dicionario = _load_json(dic_path)
                observed_values = _de_module._collect_observed_values(dicionario)

                skeleton, manifest = self._build_forced_skeleton(plan, dicionario)
                bot_code = self.service._normalize_boilerplate(skeleton)

                blocks = self.service._parse_step_blocks(bot_code)
                self.assertIsNotNone(blocks)
                violations = []
                for block in blocks:
                    step_id = block["step_id"]
                    provenance = manifest["steps"].get(step_id, {}).get("provenance")
                    if provenance != "deterministic":
                        continue
                    literals = _de_module._extract_has_text_literals(block["text"])
                    for literal in literals:
                        if literal in observed_values:
                            violations.append((step_id, literal))
                self.assertEqual(violations, [], f"Bloco(s) deterministic com valor de negócio hardcoded: {violations}")

    # ------------------------------------------------------------------
    # Célula obrigatória da matriz (Seção 4.1 + Seção 3.3 emendada do
    # plano): Padrão Q com valor de negócio no residual de parent.has_text
    # (forma do st_062 do golden v2) forçado a deterministic DEVE reprovar
    # com HARDCODED_PARENT_HAS_TEXT, e o detail DEVE nomear as chaves
    # derivadas — trava o contrato da mensagem prescritiva (a estrutura de
    # retry do code_generator só vê o JSON do erro; o detail É a instrução
    # de correção da tentativa seguinte).
    # ------------------------------------------------------------------

    _PADRAO_Q_STEP_FIXTURE = {
        "step_id": "st_062",
        "type": "click",
        "selector": "#proposal-content table tr button:has-text('Ver')",
        "description": "Clicar no botão da linha do cliente.",
        "scenario": "default",
        "text": "Ver",
        "parent": {
            "selector": ".mat-row",
            "has_text": "daniel setttt 22401666818 FIPE",
            "has_text_original": "PRO-80935 daniel setttt 22401666818 FIPE",
        },
        "sanitization_notes": ["padrao_q: removido token 'PRO-80935'"],
    }

    def _validate_forced_deterministic(self, plan, dicionario, tag):
        """Força TODOS os steps a deterministic (bypass total, inclusive da
        4ª categoria do helper de teste) e roda validate_resilience_patterns
        sobre o skeleton resultante."""
        forced = EmissionDecision("deterministic", "forced-test: deterministic incondicional (célula Q-b)")
        with mock.patch.object(
            _de_module, "classify_step",
            side_effect=lambda *a, **kw: forced,
        ):
            skeleton, _manifest = build_skeleton(plan, dicionario)
        bot_code = self.service._normalize_boilerplate(skeleton)
        plan_path = self._write_json(f"{tag}_plan.json", plan)
        dic_path = self._write_json(f"{tag}_dicionario.json", dicionario)
        return validate_resilience_patterns(bot_code, plan_path, dic_path)

    def test_padrao_q_business_value_forced_deterministic_fails_hardcoded_parent_has_text(self):
        plan = {"steps": [copy.deepcopy(self._PADRAO_Q_STEP_FIXTURE)]}
        dicionario = {"fields": {
            "nome_cliente": {"selector": "#nome", "observed_value": "daniel setttt"},
            "cpf_cliente": {"selector": "#cpf", "observed_value": "22401666818"},
        }}

        result = self._validate_forced_deterministic(plan, dicionario, "padrao_q_cell")
        self.assertEqual(result["status"], "FAIL")
        hardcoded = [e for e in result["errors"] if e["type"] == "HARDCODED_PARENT_HAS_TEXT"]
        self.assertEqual(len(hardcoded), 1, result["errors"])
        error = hardcoded[0]
        self.assertEqual(error["step_id"], "st_062")
        # Chaves derivadas mecanicamente (observed_value ⊂ residual) nomeadas
        # no detail + forma f-string com row.get(...) prescrita.
        self.assertIn("nome_cliente", error["detail"])
        self.assertIn("cpf_cliente", error["detail"])
        self.assertIn("row.get", error["detail"])
        self.assertIn(
            "{row.get('nome_cliente', '')} {row.get('cpf_cliente', '')} FIPE",
            error["detail"],
        )

    def test_padrao_q_dynamic_composition_passes_under_qb_trigger(self):
        """Contrapartida da célula acima: sob o MESMO gatilho Q-b, a
        composição dinâmica (f-string com row.get) é a ÚNICA prova válida —
        e passa."""
        plan = {"steps": [copy.deepcopy(self._PADRAO_Q_STEP_FIXTURE)]}
        dicionario = {"fields": {
            "nome_cliente": {"selector": "#nome", "observed_value": "daniel setttt"},
            "cpf_cliente": {"selector": "#cpf", "observed_value": "22401666818"},
        }}
        dynamic_code = (
            "def execute_scenario_default(runner, page, row):\n"
            "    # [PASSO 62] Clicar no botão da linha do cliente.\n"
            "    runner.click_chained(\n"
            "        page,\n"
            "        parent={\"selector\": \".mat-row\", \"has_text\": "
            "f\"{row.get('nome_cliente', '')} {row.get('cpf_cliente', '')} FIPE\"},\n"
            "        child={\"selector\": \"#proposal-content table tr button:has-text('Ver')\"},\n"
            "        target_description=\"Clicar no botão da linha do cliente.\",\n"
            "        step_id=\"st_062\"\n"
            "    )\n"
        )
        plan_path = self._write_json("padrao_q_dynamic_plan.json", plan)
        dic_path = self._write_json("padrao_q_dynamic_dicionario.json", dicionario)
        result = validate_resilience_patterns(dynamic_code, plan_path, dic_path)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_padrao_q_ambiguous_match_degrades_to_generic_detail(self):
        """Degradação (Seção 3.3, correção rodada 4): mais de uma chave com o
        MESMO observed_value ('2026' pode ser ano_modelo E ano_fabricacao) ⇒
        o detail degrada para a proibição genérica de hardcode, SEM nomear
        chave (não adivinhe qual)."""
        step = copy.deepcopy(self._PADRAO_Q_STEP_FIXTURE)
        step["parent"]["has_text"] = "2026 FIPE"
        step["parent"]["has_text_original"] = "PRO-80935 2026 FIPE"
        plan = {"steps": [step]}
        dicionario = {"fields": {
            "ano_modelo": {"selector": "#ano-modelo", "observed_value": "2026"},
            "ano_fabricacao": {"selector": "#ano-fab", "observed_value": "2026"},
        }}

        result = self._validate_forced_deterministic(plan, dicionario, "padrao_q_ambiguous")
        self.assertEqual(result["status"], "FAIL")
        hardcoded = [e for e in result["errors"] if e["type"] == "HARDCODED_PARENT_HAS_TEXT"]
        self.assertEqual(len(hardcoded), 1, result["errors"])
        error = hardcoded[0]
        self.assertEqual(error["step_id"], "st_062")
        # Mensagem genérica: proibição de hardcode + forma row.get, sem
        # nomear NENHUMA das chaves ambíguas.
        self.assertIn("PROIBIDO", error["detail"])
        self.assertIn("row.get", error["detail"])
        self.assertNotIn("ano_modelo", error["detail"])
        self.assertNotIn("ano_fabricacao", error["detail"])

    def test_optional_step_wrapper_survives_reorder_as_a_unit(self):
        """
        RT2 (Seção 4.1 item 2): fixture com step 'optional' emitido via
        _emit_optional_wrapper -> mesmos validadores PASS +
        reorder_steps_to_match_plan sobre uma versão embaralhada reordena o
        Try como unidade sem quebrar sintaxe.
        """
        steps = [
            {"step_id": "st_001", "type": "click", "selector": "#a", "description": "Passo 1"},
            {
                "step_id": "sup_001", "type": "click", "selector": ".overlay",
                "description": "Fechar overlay opcional", "execution_hint": "optional",
            },
            {"step_id": "st_002", "type": "click", "selector": "#b", "description": "Passo 2"},
        ]
        planned_ids = [s["step_id"] for s in steps]

        # Plano correto (ordem canônica) — valida que passa em todos os
        # validadores relevantes.
        plan = {"steps": steps}
        skeleton, manifest = self._build_forced_skeleton(plan, {"fields": {}})
        bot_code = self.service._normalize_boilerplate(skeleton)
        self.assertEqual(manifest["steps"]["sup_001"]["provenance"], "deterministic")

        plan_path = self._write_json("optional_plan.json", plan)
        struct_result = validate_bot_structure(bot_code)
        self.assertEqual(struct_result["status"], "PASS", struct_result["errors"])
        plan_result = validate_bot_against_plan(bot_code, plan_path)
        self.assertEqual(plan_result["status"], "PASS", plan_result["errors"])

        # Versão embaralhada (plano com a mesma composição, ordem diferente)
        # — simula a LLM/reflection reescrevendo o arquivo fora de ordem.
        scrambled_plan = {"steps": [steps[2], steps[1], steps[0]]}
        scrambled_skeleton, _ = self._build_forced_skeleton(scrambled_plan, {"fields": {}})
        scrambled_bot_code = self.service._normalize_boilerplate(scrambled_skeleton)
        self.assertNotEqual(
            extract_step_ids_from_code(scrambled_bot_code), planned_ids,
            "pré-condição do teste: a versão embaralhada precisa estar fora de ordem",
        )

        reordered_code = reorder_steps_to_match_plan(scrambled_bot_code, planned_ids)
        # Não pode quebrar sintaxe.
        tree = ast.parse(reordered_code)
        self.assertEqual(extract_step_ids_from_code(reordered_code), planned_ids)

        try_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
        self.assertEqual(len(try_nodes), 1, "o Try do step optional precisa sobreviver ao reorder como bloco único")
        calls_in_try = [
            n for n in ast.walk(try_nodes[0])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "click_resilient"
        ]
        self.assertEqual(len(calls_in_try), 1)
        has_step_id_sup_001 = any(
            kw.arg == "step_id" and isinstance(kw.value, ast.Constant) and kw.value.value == "sup_001"
            for kw in calls_in_try[0].keywords
        )
        self.assertTrue(has_step_id_sup_001)

    def test_manifest_has_plan_checksum_and_per_step_provenance(self):
        matrix_dir = os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix")
        plan = _load_json(os.path.join(matrix_dir, "plano_execucao.json"))
        dicionario = _load_json(os.path.join(matrix_dir, "dicionario.json"))

        skeleton, manifest = build_skeleton(plan, dicionario)

        self.assertEqual(manifest["generator_version"], "hybrid-1")
        self.assertIn("generated_at", manifest)
        self.assertIn("plan_checksum", manifest)
        self.assertTrue(manifest["plan_checksum"])

        # sup_001 (omit) nunca entra no manifest.
        self.assertNotIn("sup_001", manifest["steps"])
        # st_002 (deterministic real, sem forçar) entra com provenance certo.
        self.assertEqual(manifest["steps"]["st_002"]["provenance"], "deterministic")
        self.assertIn("block_sha1", manifest["steps"]["st_002"])
        # st_006 (cognitive real via C10) entra com provenance cognitive e reason citando C10.
        self.assertEqual(manifest["steps"]["st_006"]["provenance"], "cognitive")
        self.assertIn("C10", manifest["steps"]["st_006"]["reason"])
        self.assertNotIn("block_sha1", manifest["steps"]["st_006"])

    def test_build_skeleton_step_anchor_numbering_is_sequential_and_unique(self):
        matrix_dir = os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix")
        plan = _load_json(os.path.join(matrix_dir, "plano_execucao.json"))
        dicionario = _load_json(os.path.join(matrix_dir, "dicionario.json"))

        skeleton, _manifest = build_skeleton(plan, dicionario)
        anchors = [
            line.strip() for line in skeleton.split("\n")
            if line.strip().startswith("# [PASSO ")
        ]
        numbers = [int(a.split("[PASSO ")[1].split("]")[0]) for a in anchors]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_cognitive_placeholder_is_parseable_by_step_id_in_block_regex(self):
        """
        Achado I7 da rodada 2 do plano: o placeholder cognitivo PRECISA
        satisfazer _STEP_ID_IN_BLOCK_RE (code_generator.py:1127) — sem essa
        forma exata (step_id="...") o modo escopado nunca encontraria o slot.
        """
        matrix_dir = os.path.join(GOLDEN_DIR, "synthetic_hybrid_matrix")
        plan = _load_json(os.path.join(matrix_dir, "plano_execucao.json"))
        dicionario = _load_json(os.path.join(matrix_dir, "dicionario.json"))

        skeleton, manifest = build_skeleton(plan, dicionario)
        self.assertEqual(manifest["steps"]["st_006"]["provenance"], "cognitive")

        bot_code = self.service._normalize_boilerplate(skeleton)
        blocks = self.service._parse_step_blocks(bot_code)
        self.assertIsNotNone(blocks)
        st_006_block = next(b for b in blocks if b["step_id"] == "st_006")
        self.assertIn("AEGIS_COGNITIVE_SLOT", st_006_block["text"])
        self.assertIn("pass", st_006_block["text"])


if __name__ == "__main__":
    unittest.main()
