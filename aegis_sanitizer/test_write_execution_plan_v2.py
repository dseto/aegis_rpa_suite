import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sanitizer import SanitizerService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(REPO_ROOT, ".specs", "golden", "synthetic_r1_merge_case")


def _classify_and_write(service, raw_events, dataset_rows=None):
    """
    Reproduz a composição feita por sanitize() (sanitizer.py, bloco entre o
    Padrão P e a chamada de _write_execution_plan): estampagem de
    original_index -> _classify_raw_events -> _write_execution_plan. Chama
    as funções REAIS (T1 + T2), não uma reimplementação paralela do
    algoritmo — o que está sob teste é a composição de verdade.
    """
    for i, ev in enumerate(raw_events):
        ev.setdefault("original_index", i)
    classified = service._classify_raw_events(raw_events)
    service._write_execution_plan(classified, dataset_rows or [])
    with open(os.path.join(service.telemetry_dir, "plano_execucao.json"), "r", encoding="utf-8") as f:
        return json.load(f)


class TestWriteExecutionPlanV2SyntheticR1MergeCase(unittest.TestCase):
    """
    DoD (a): roda o caso sintético de T0b
    (.specs/golden/synthetic_r1_merge_case/) e compara com o golden
    plano_execucao_esperado.json.

    Comparação pelos campos NORMATIVOS listados no README.md da fixture
    ("Campos normativos vs. ilustrativos"): sequência de step_id,
    execution_hint (valor efetivo), step_role, type, selector, merged_from
    (original_index dos absorvidos), original_index dos sup_, e
    fidelity_summary — não byte-a-byte, já que description/
    suppression_reason/coords/etc. são ilustrativos por design (o próprio
    README pede resiliência a reformulação de texto nesses campos).
    """

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def _load_fixture(self):
        with open(os.path.join(FIXTURE_DIR, "gravacao.json"), "r", encoding="utf-8") as f:
            raw = json.load(f)
        with open(os.path.join(FIXTURE_DIR, "plano_execucao_esperado.json"), "r", encoding="utf-8") as f:
            expected = json.load(f)
        return raw["events"], expected

    def test_matches_golden_normative_fields(self):
        raw_events, expected = self._load_fixture()

        plan = _classify_and_write(self.service, raw_events)

        self.assertEqual(plan["version"], "2.0")
        self.assertEqual(len(plan["steps"]), len(expected["steps"]))

        for got, exp in zip(plan["steps"], expected["steps"]):
            self.assertEqual(got["step_id"], exp["step_id"])
            self.assertEqual(
                got.get("execution_hint", "required"),
                exp.get("execution_hint", "required"),
                f"execution_hint efetivo diverge em {exp['step_id']}",
            )
            self.assertEqual(got.get("step_role"), exp.get("step_role"), exp["step_id"])
            self.assertEqual(got["type"], exp["type"], exp["step_id"])
            self.assertEqual(got["selector"], exp["selector"], exp["step_id"])
            self.assertEqual(
                [m["original_index"] for m in got.get("merged_from", [])],
                [m["original_index"] for m in exp.get("merged_from", [])],
                f"merged_from diverge em {exp['step_id']}",
            )
            if exp["step_id"].startswith("sup_"):
                self.assertEqual(
                    got.get("original_index"), exp.get("original_index"),
                    f"original_index do sup_ diverge em {exp['step_id']}",
                )

        self.assertEqual(plan["fidelity_summary"], expected["fidelity_summary"])
        self.assertEqual(plan["total_steps"], expected["total_steps"])
        self.assertEqual(plan["total_recorded_steps"], expected["total_recorded_steps"])

    def test_st_appears_before_sup_matching_golden_order(self):
        # Reforça especificamente a ORDEM (não só o conteúdo): st_001 antes
        # de sup_001. Isso só sai certo se position_anchor considerar
        # merged_from (não só o original_index isolado do step raiz) — ver
        # README.md da fixture, seção "Por que sup_001 aparece DEPOIS de
        # st_001 (não antes)".
        raw_events, _ = self._load_fixture()

        plan = _classify_and_write(self.service, raw_events)
        ids = [s["step_id"] for s in plan["steps"]]
        self.assertEqual(ids, ["st_001", "sup_001"])

    def test_merged_from_points_to_the_absorbed_event_not_the_survivor(self):
        raw_events, _ = self._load_fixture()
        plan = _classify_and_write(self.service, raw_events)

        st_001 = next(s for s in plan["steps"] if s["step_id"] == "st_001")
        self.assertEqual(st_001["selector"], "span.mat-button-wrapper")
        self.assertEqual(st_001["original_index"], 2)
        self.assertEqual(len(st_001["merged_from"]), 1)
        self.assertEqual(st_001["merged_from"][0]["original_index"], 0)
        self.assertEqual(st_001["merged_from"][0]["selector"], "#btn-abrir-modal")


class TestWriteExecutionPlanV2SuppressionRoles(unittest.TestCase):
    """DoD (b): supressão R2/R3/R4 vira sup_ com execution_hint: 'skip'."""

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_r1_raw_duplicate_click_becomes_sup_with_skip_hint(self):
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1", "business_description": "Clicar"},
            {"type": "click", "selector": "#btn1", "text": "Botao 1", "business_description": "Clicar"},
        ]
        plan = _classify_and_write(self.service, events)

        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]
        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["execution_hint"], "skip")
        self.assertEqual(sups[0]["step_role"], "raw_duplicate_click")

    def test_r2_overlay_noise_becomes_sup_with_skip_hint(self):
        events = [
            {"type": "click", "selector": "#btn-abrir", "text": "Abrir", "business_description": "Abrir"},
            {"type": "click", "selector": ".cdk-overlay-backdrop"},
            {"type": "click", "selector": "#btn-confirmar", "text": "Confirmar", "business_description": "Confirmar"},
        ]
        plan = _classify_and_write(self.service, events)

        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]
        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["execution_hint"], "skip")
        self.assertEqual(sups[0]["step_role"], "overlay_noise")
        self.assertEqual(sups[0]["type"], "click")
        self.assertEqual(sups[0]["selector"], ".cdk-overlay-backdrop")

        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual([s["selector"] for s in sts], ["#btn-abrir", "#btn-confirmar"])
        for s in sts:
            self.assertNotIn("execution_hint", s)
            self.assertNotIn("step_role", s)

    def test_r3_stale_panel_click_becomes_sup(self):
        events = [
            {"type": "click", "selector": "mat-autocomplete-panel-2 [role='option']", "text": "Opcao"},
        ]
        plan = _classify_and_write(self.service, events)
        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]
        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["step_role"], "stale_panel_click")
        self.assertEqual(sups[0]["execution_hint"], "skip")

    def test_r4_redundant_refill_becomes_sup(self):
        events = [
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "default"},
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "default"},
        ]
        plan = _classify_and_write(self.service, events)
        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]
        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["step_role"], "redundant_refill")
        self.assertEqual(sups[0]["execution_hint"], "skip")
        self.assertEqual(sups[0]["type"], "fill")

    def test_suppression_reason_and_step_role_are_inherited_verbatim_from_sanitizer_class(self):
        events = [{"type": "click", "selector": ".cdk-overlay-backdrop"}]
        for i, e in enumerate(events):
            e.setdefault("original_index", i)
        classified = self.service._classify_raw_events(events)
        expected_role = classified[0]["sanitizer_class"]["role"]
        expected_reason = classified[0]["sanitizer_class"]["reason"]

        self.service._write_execution_plan(classified, [])
        with open(os.path.join(self.telemetry_dir, "plano_execucao.json"), "r", encoding="utf-8") as f:
            plan = json.load(f)

        self.assertEqual(plan["steps"][0]["step_role"], expected_role)
        self.assertEqual(plan["steps"][0]["suppression_reason"], expected_reason)


class TestWriteExecutionPlanV2FidelitySummary(unittest.TestCase):
    """DoD (c): fidelity_summary bate com as contagens reais."""

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_counts_match_a_mixed_scenario(self):
        events = [
            {"type": "click", "selector": "#a", "text": "A"},            # 0: kept -> st_
            {"type": "click", "selector": "#a", "text": "A"},            # 1: R1 -> sup_
            {"type": "click", "selector": "#b", "text": "B"},            # 2: kept -> st_
            {"type": "click", "selector": ".cdk-overlay-backdrop"},      # 3: R2 -> sup_
            {"type": "fill", "selector": "#c", "value": "x"},            # 4: kept -> st_
        ]
        plan = _classify_and_write(self.service, events)

        fs = plan["fidelity_summary"]
        self.assertEqual(fs["raw_events"], 5)
        self.assertEqual(fs["steps_suppressed"], 2)
        self.assertEqual(fs["steps_required"] + fs["steps_optional"], plan["total_steps"])
        self.assertEqual(
            fs["steps_required"] + fs["steps_optional"] + fs["steps_suppressed"],
            len(plan["steps"]),
        )
        self.assertEqual(plan["total_recorded_steps"], 5)

    def test_merges_counts_operations_not_absorbed_events(self):
        # 3 cliques consecutivos no MESMO widget fisico via `parent` (nao
        # via selector identico - selector identico seria pego por R1 em
        # _classify_raw_events ANTES de chegar em _merge_consecutive_clicks,
        # e o cenario deixaria de exercitar o merge; ver
        # .specs/golden/synthetic_r1_merge_case/README.md, que usa a mesma
        # estrategia de "parent igual, selector diferente" para isolar o
        # merge de R1). Deve virar 1 UNICA operacao de merge (absorve 2),
        # nao "2" (uma por evento absorvido) - e o merged_from resultante
        # deve conter os 2 absorvidos mesmo cruzando 2 rodadas de fusao.
        events = [
            {"type": "click", "selector": "#widget-a", "text": "Confirmar",
             "parent": {"selector": "div.wrap", "has_text": "Confirmar"}},
            {"type": "click", "selector": "#widget-b", "text": "Confirmar",
             "parent": {"selector": "div.wrap", "has_text": "Confirmar"}},
            {"type": "click", "selector": "#widget-c", "text": "Confirmar",
             "parent": {"selector": "div.wrap", "has_text": "Confirmar"}},
        ]
        plan = _classify_and_write(self.service, events)
        self.assertEqual(plan["fidelity_summary"]["steps_suppressed"], 0)
        self.assertEqual(plan["fidelity_summary"]["merges"], 1)
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(len(plan["steps"][0]["merged_from"]), 2)
        self.assertEqual(
            {m["original_index"] for m in plan["steps"][0]["merged_from"]},
            {0, 1},
        )


class TestWriteExecutionPlanV2NoSanitizerClassBackcompat(unittest.TestCase):
    """
    DoD (d): uma lista de eventos em que NENHUM tem o campo
    sanitizer_class (equivalente a uma gravação inteira sem nenhum evento
    capturado por R1-R4) ainda gera um plano v2 válido, com todos os steps
    como st_NNN/execution_hint ausente e nenhum sup_.
    """

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_all_steps_required_when_nothing_tagged(self):
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
            {"type": "fill", "selector": "#input1", "value": "valor1"},
        ]
        for e in events:
            self.assertNotIn("sanitizer_class", e)

        self.service._write_execution_plan(events, [])
        with open(os.path.join(self.telemetry_dir, "plano_execucao.json"), "r", encoding="utf-8") as f:
            plan = json.load(f)

        self.assertEqual(len(plan["steps"]), 2)
        for s in plan["steps"]:
            self.assertTrue(s["step_id"].startswith("st_"))
            self.assertNotIn("execution_hint", s)
            self.assertNotIn("sup_", s["step_id"])
        self.assertEqual(plan["fidelity_summary"]["steps_suppressed"], 0)
        self.assertEqual(plan["version"], "2.0")

    def test_does_not_crash_without_original_index_stamped(self):
        # _write_execution_plan chamado direto (sem passar por sanitize()),
        # igual a suite de testes legada test_sanitizer_execution_plan.py —
        # nenhum evento tem original_index. Deve degradar graciosamente
        # (fallback pela posicao na lista), nao lancar ValueError em min([]).
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
        ]
        self.assertNotIn("original_index", events[0])
        try:
            self.service._write_execution_plan(events, [])
        except ValueError as e:
            self.fail(f"_write_execution_plan lançou ValueError sem original_index: {e}")


class TestWriteExecutionPlanV2SchemaInvariant(unittest.TestCase):
    """
    Sanity-check opcional citado na Seção 3 do plano: step_id.startswith
    ('sup_') <=> execution_hint == 'skip'. Não é regra de negócio nova, só
    uma checagem estrutural de que os dois espaços de id nunca vazam um
    para o outro.
    """

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_sup_and_skip_are_equivalent(self):
        events = [
            {"type": "click", "selector": "#a", "text": "A"},
            {"type": "click", "selector": "#a", "text": "A"},  # R1 -> sup_
            {"type": "click", "selector": "#b", "text": "B"},
        ]
        plan = _classify_and_write(self.service, events)
        self.assertGreaterEqual(len(plan["steps"]), 2)
        for s in plan["steps"]:
            is_sup = s["step_id"].startswith("sup_")
            is_skip = s.get("execution_hint") == "skip"
            self.assertEqual(is_sup, is_skip, s)


class TestWriteExecutionPlanV2ChainSuppression(unittest.TestCase):
    """
    Cobertura extra (além do DoD mínimo) para as duas funções da cadeia
    renomeadas que agora também produzem sup_: _mark_superseded_selects e
    _mark_phantom_pretrigger_clicks. Nenhum golden exercita esses 2
    caminhos (o T0b só cobre R1×merge; o dataset real não revela quantos
    selects/phantom clicks existiam porque golden v1 só mostra
    sobreviventes) — testado aqui isoladamente para não deixar a lógica
    sem cobertura nenhuma.
    """

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_superseded_select_correction_becomes_sup_with_superseded_by(self):
        events = [
            {
                "type": "click", "selector": "mat-select:has-text('Combustivel')",
                "text": "Combustivel", "parent": {"selector": ".mat-form-field-wrapper", "has_text": "Combustivel Selecione"},
            },
            {
                "type": "click", "selector": "[role='option']:has-text('Diesel')",
                "text": "Diesel",
            },
            {
                "type": "click", "selector": "mat-select:has-text('Combustivel')",
                "text": "Combustivel", "parent": {"selector": ".mat-form-field-wrapper", "has_text": "Combustivel Diesel"},
            },
            {
                "type": "click", "selector": "[role='option']:has-text('Alcool')",
                "text": "Alcool",
            },
        ]
        plan = _classify_and_write(self.service, events)

        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]

        self.assertEqual(len(sts), 1)
        self.assertEqual(sts[0]["option_text"], "Alcool")

        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["step_role"], "superseded_correction")
        self.assertEqual(sups[0]["option_text"], "Diesel")
        self.assertEqual(sups[0]["superseded_by"], sts[0]["step_id"])
        self.assertEqual(sups[0]["execution_hint"], "skip")

    def test_phantom_pretrigger_click_becomes_sup_without_superseded_by(self):
        # Distancia entre o clique fantasma (evento 0) e o trigger do select
        # (evento 1) precisa ficar ENTRE os dois limiares: > 0.02 (senao
        # _merge_consecutive_clicks funde os dois primeiro, via o criterio
        # de coordenadas de ultimo recurso de same_widget(), e o cenario
        # nunca chega em _mark_phantom_pretrigger_clicks) e < 0.05 (o
        # limiar que _mark_phantom_pretrigger_clicks usa pra reconhecer o
        # mesmo clique fisico). dist(0.30,0.50 ; 0.33,0.50) = 0.03.
        events = [
            {
                "type": "click", "selector": "span.trigger-inner", "text": "",
                "x_percent": 0.30, "y_percent": 0.50,
            },
            {
                "type": "click", "selector": "mat-select:has-text('Estado')",
                "text": "Estado", "x_percent": 0.33, "y_percent": 0.50,
            },
            {
                "type": "click", "selector": "[role='option']:has-text('SP')",
                "text": "SP", "x_percent": 0.33, "y_percent": 0.60,
            },
        ]
        plan = _classify_and_write(self.service, events)

        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        sups = [s for s in plan["steps"] if s["step_id"].startswith("sup_")]

        self.assertEqual(len(sts), 1)
        self.assertEqual(sts[0]["type"], "select")

        self.assertEqual(len(sups), 1)
        self.assertEqual(sups[0]["step_role"], "phantom_click")
        self.assertEqual(sups[0]["selector"], "span.trigger-inner")
        self.assertNotIn("superseded_by", sups[0])
        self.assertEqual(sups[0]["execution_hint"], "skip")

    def test_composite_select_gets_step_role_and_source_events(self):
        events = [
            {"type": "click", "selector": "mat-select:has-text('UF')", "text": "UF"},
            {"type": "click", "selector": "[role='option']:has-text('RJ')", "text": "RJ"},
        ]
        plan = _classify_and_write(self.service, events)
        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual(len(sts), 1)
        self.assertEqual(sts[0]["step_role"], "composite_select")
        self.assertEqual(sts[0]["source_events"], [0, 1])


class TestWriteExecutionPlanV2ContainerClickOptional(unittest.TestCase):
    """
    Regra container_click (achado do piloto fimm_billing, 2026-07-14):
    clique cujo seletor é tag pura de container estrutural (produto do
    tagStrategy do recorder) com confidence < 70 é ruído de navegação —
    rebaixado a execution_hint='optional' (continua st_NNN, numeração
    intacta; a decisão de emitir passa ao slot cognitivo via C2).
    """

    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_low_confidence_container_click_becomes_optional(self):
        events = [
            {"type": "click", "selector": "#btn-login", "text": "Entrar", "confidence": 90},
            {
                "type": "click",
                "selector": "nav",
                "tag": "NAV",
                "text": "TREASURY & LIQUIDITY\nCash Position\nWire Transfers\n",
                "confidence": 40,
            },
            {"type": "click", "selector": "a:has-text('Billing Engine')", "text": "Billing Engine", "confidence": 75},
        ]
        plan = _classify_and_write(self.service, events)
        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual(len(sts), 3)

        nav_step = next(s for s in sts if s["selector"] == "nav")
        self.assertEqual(nav_step.get("execution_hint"), "optional")
        self.assertTrue(nav_step.get("weak_selector"))
        self.assertTrue(
            any("container_click" in n for n in nav_step.get("sanitization_notes", [])),
            "nota container_click ausente",
        )
        # Numeração st_ intacta — optional não vira sup_.
        self.assertEqual([s["step_id"] for s in sts], ["st_001", "st_002", "st_003"])
        self.assertEqual(plan["fidelity_summary"]["steps_optional"], 1)
        self.assertEqual(plan["fidelity_summary"]["steps_required"], 2)

        # Os outros cliques não recebem hint.
        for s in sts:
            if s["selector"] != "nav":
                self.assertNotIn("execution_hint", s)

    def test_container_click_without_confidence_field_is_untouched(self):
        # Retrocompatibilidade: gravação antiga (sem campo confidence) nunca
        # recebe o rebaixamento — mesma política do weak_selector.
        events = [{"type": "click", "selector": "main", "tag": "MAIN", "text": "Painel"}]
        plan = _classify_and_write(self.service, events)
        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual(len(sts), 1)
        self.assertNotIn("execution_hint", sts[0])

    def test_high_confidence_container_selector_is_untouched(self):
        events = [{"type": "click", "selector": "nav", "tag": "NAV", "text": "Menu", "confidence": 80}]
        plan = _classify_and_write(self.service, events)
        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual(len(sts), 1)
        self.assertNotIn("execution_hint", sts[0])

    def test_non_container_low_confidence_click_is_untouched(self):
        # weak_selector sim, optional não — tag genérica fora da lista de
        # containers estruturais (ex.: 'label') não é ruído de navegação.
        events = [{"type": "click", "selector": "label", "tag": "LABEL", "text": "Aceito", "confidence": 40}]
        plan = _classify_and_write(self.service, events)
        sts = [s for s in plan["steps"] if s["step_id"].startswith("st_")]
        self.assertEqual(len(sts), 1)
        self.assertTrue(sts[0].get("weak_selector"))
        self.assertNotIn("execution_hint", sts[0])


if __name__ == "__main__":
    unittest.main()
