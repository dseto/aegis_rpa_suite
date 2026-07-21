import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sanitizer import SanitizerService


class TestClassifyRawEventsNoEventLost(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_kept_events_are_not_tagged(self):
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
            {"type": "fill", "selector": "#input1", "value": "valor1"},
        ]
        result = self.service._classify_raw_events(events)

        self.assertEqual(len(result), 2)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])

    def test_returns_new_list_same_length_same_order_as_input(self):
        events = [
            {"type": "click", "selector": "#a"},
            {"type": "click", "selector": "#a"},  # R1
            {"type": "click", "selector": ".cdk-overlay-backdrop"},  # R2
        ]
        result = self.service._classify_raw_events(events)

        self.assertIsNot(result, events)
        self.assertEqual(len(result), len(events))
        self.assertEqual([e["selector"] for e in result], [e["selector"] for e in events])

    def test_no_event_ever_removed_across_all_four_rules_simultaneously(self):
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},          # 0: kept
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},          # 1: R1
            {"type": "click", "selector": "mat-autocomplete-panel-9"},          # 2: R3 (nenhum fill ainda)
            {"type": "click", "selector": ".cdk-overlay-backdrop"},             # 3: R2
            {"type": "fill", "selector": "#campo-marca", "value": "Fiat"},      # 4: kept
            {"type": "fill", "selector": "#campo-marca", "value": "Fiat"},      # 5: R4 (duplicado)
            {"type": "fill", "selector": "#campo-marca", "value": "Renault"},   # 6: kept (valor novo)
        ]

        result = self.service._classify_raw_events(events)

        self.assertEqual(len(result), 7)  # nenhum evento sumiu

        tagged_roles = [e["sanitizer_class"]["role"] for e in result if "sanitizer_class" in e]
        self.assertEqual(
            sorted(tagged_roles),
            sorted(["raw_duplicate_click", "stale_panel_click", "overlay_noise", "redundant_refill"]),
        )
        kept = [e for e in result if "sanitizer_class" not in e]
        self.assertEqual(len(kept), 3)
        for e in result:
            if "sanitizer_class" in e:
                self.assertFalse(e["sanitizer_class"]["keep"])
                self.assertIn("reason", e["sanitizer_class"])


class TestClassifyRawEventsR1ConsecutiveClicks(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_second_of_two_consecutive_identical_clicks_is_tagged(self):
        events = [
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
            {"type": "click", "selector": "#btn1", "text": "Botao 1"},
        ]
        result = self.service._classify_raw_events(events)

        self.assertNotIn("sanitizer_class", result[0])
        self.assertEqual(result[1]["sanitizer_class"]["role"], "raw_duplicate_click")
        self.assertFalse(result[1]["sanitizer_class"]["keep"])

    def test_third_of_three_consecutive_identical_clicks_is_also_tagged(self):
        # R1 compara contra o ULTIMO evento MANTIDO (nao o fisicamente
        # anterior) - os 3 cliques colapsam para 1 so mantido, igual ao
        # comportamento antigo baseado em `continue`.
        events = [
            {"type": "click", "selector": "#btn1"},
            {"type": "click", "selector": "#btn1"},
            {"type": "click", "selector": "#btn1"},
        ]
        result = self.service._classify_raw_events(events)

        self.assertEqual(len(result), 3)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertEqual(result[1]["sanitizer_class"]["role"], "raw_duplicate_click")
        self.assertEqual(result[2]["sanitizer_class"]["role"], "raw_duplicate_click")

    def test_consecutive_clicks_with_different_selectors_are_not_tagged(self):
        events = [
            {"type": "click", "selector": "#btn1"},
            {"type": "click", "selector": "#btn2"},
        ]
        result = self.service._classify_raw_events(events)

        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])

    def test_non_consecutive_identical_clicks_are_not_tagged_by_r1(self):
        # R1 so pega adjacencia (contra o ultimo MANTIDO); um clique igual
        # separado por outro evento no meio nao e pego por essa regra.
        events = [
            {"type": "click", "selector": "#btn1"},
            {"type": "fill", "selector": "#input1", "value": "x"},
            {"type": "click", "selector": "#btn1"},
        ]
        result = self.service._classify_raw_events(events)

        for e in result:
            self.assertNotIn("sanitizer_class", e)


class TestClassifyRawEventsR2OverlayNoise(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_generic_cdk_overlay_container_click_is_tagged(self):
        events = [{"type": "click", "selector": "#cdk-overlay-container > div.empty-panel"}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["sanitizer_class"]["role"], "overlay_noise")

    def test_backdrop_click_is_tagged(self):
        events = [{"type": "click", "selector": ".cdk-overlay-backdrop"}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["sanitizer_class"]["role"], "overlay_noise")

    def test_nenhum_resultado_in_selector_is_tagged(self):
        events = [{"type": "click", "selector": "div.aviso:has-text('Nenhum resultado')"}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["sanitizer_class"]["role"], "overlay_noise")

    def test_nenhum_resultado_in_text_is_tagged(self):
        events = [{"type": "click", "selector": "#painel-vazio", "text": "Nenhum resultado encontrado"}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["sanitizer_class"]["role"], "overlay_noise")

    def test_specific_option_click_inside_overlay_is_not_tagged(self):
        # Clique numa opcao especifica dentro do overlay e selecao real, nao
        # ruido de overlay/backdrop vazio - nao deve ser tagueado (mesma
        # excecao que existia no bloco original via `continue`).
        events = [{
            "type": "click",
            "selector": "#cdk-overlay-container #mat-select-panel-3 [role='option']:has-text('Diesel')",
        }]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])

    def test_has_text_selector_inside_overlay_container_is_not_tagged_by_generic_rule(self):
        events = [{
            "type": "click",
            "selector": "#cdk-overlay-container div:has-text('Alcool')",
        }]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])


class TestClassifyRawEventsR3StalePanelClick(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_autocomplete_panel_click_before_any_fill_is_tagged(self):
        events = [{"type": "click", "selector": "mat-autocomplete-panel-2 [role='option']"}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["sanitizer_class"]["role"], "stale_panel_click")

    def test_autocomplete_panel_click_after_a_prior_fill_is_not_tagged(self):
        events = [
            {"type": "fill", "selector": "#campo-marca", "value": "Fiat"},
            {"type": "click", "selector": "mat-autocomplete-panel-2"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])

    def test_autocomplete_panel_click_after_a_fill_that_was_itself_a_duplicate_is_still_not_tagged(self):
        # last_fill_selector so e atualizado quando o fill sobrevive (nao e
        # duplicado), mas o PRIMEIRO fill (sempre sobrevive) ja basta para
        # desarmar R3 nos cliques seguintes.
        events = [
            {"type": "fill", "selector": "#campo-marca", "value": "Fiat"},
            {"type": "fill", "selector": "#campo-marca", "value": "Fiat"},  # R4, duplicado
            {"type": "click", "selector": "mat-autocomplete-panel-2"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertEqual(result[1]["sanitizer_class"]["role"], "redundant_refill")
        self.assertNotIn("sanitizer_class", result[2])


class TestClassifyRawEventsR4RedundantRefill(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_duplicate_fill_same_scenario_selector_value_is_tagged(self):
        events = [
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "default"},
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "default"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertEqual(result[1]["sanitizer_class"]["role"], "redundant_refill")

    def test_change_event_type_is_also_covered_by_r4(self):
        events = [
            {"type": "change", "selector": "#select1", "value": "opt1"},
            {"type": "change", "selector": "#select1", "value": "opt1"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[1]["sanitizer_class"]["role"], "redundant_refill")

    def test_refill_with_different_value_is_not_tagged(self):
        events = [
            {"type": "fill", "selector": "#campo", "value": "abc"},
            {"type": "fill", "selector": "#campo", "value": "xyz"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])

    def test_same_selector_value_but_different_scenario_is_not_tagged(self):
        events = [
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "cenario_a"},
            {"type": "fill", "selector": "#campo", "value": "abc", "scenario": "cenario_b"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])

    def test_non_consecutive_duplicate_fill_is_still_tagged(self):
        # seen_fills cobre a gravacao inteira, nao so adjacencia.
        events = [
            {"type": "fill", "selector": "#campo", "value": "abc"},
            {"type": "click", "selector": "#outro-botao"},
            {"type": "fill", "selector": "#campo", "value": "abc"},
        ]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("sanitizer_class", result[0])
        self.assertNotIn("sanitizer_class", result[1])
        self.assertEqual(result[2]["sanitizer_class"]["role"], "redundant_refill")


class TestClassifyRawEventsOriginalIndexPreservation(unittest.TestCase):
    def setUp(self):
        self.telemetry_dir = tempfile.mkdtemp(prefix="aegis_sanitizer_test_")
        self.service = SanitizerService(telemetry_dir=self.telemetry_dir)

    def tearDown(self):
        shutil.rmtree(self.telemetry_dir, ignore_errors=True)

    def test_does_not_stamp_original_index_when_absent(self):
        # _classify_raw_events nunca cria original_index - so preserva o que
        # ja estiver presente (estampagem e feita em sanitize(), antes do
        # Padrao P, nao aqui).
        events = [{"type": "click", "selector": "#btn1"}]
        result = self.service._classify_raw_events(events)
        self.assertNotIn("original_index", result[0])

    def test_preserves_pre_existing_original_index_on_kept_event(self):
        events = [{"type": "click", "selector": "#btn1", "original_index": 42}]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[0]["original_index"], 42)

    def test_preserves_pre_existing_original_index_on_tagged_event(self):
        events = [
            {"type": "click", "selector": "#btn1", "original_index": 7},
            {"type": "click", "selector": "#btn1", "original_index": 8},
        ]
        result = self.service._classify_raw_events(events)
        self.assertEqual(result[1]["sanitizer_class"]["role"], "raw_duplicate_click")
        self.assertEqual(result[1]["original_index"], 8)

    def test_original_index_survives_padrao_p_style_physical_reordering(self):
        # Simula a composicao completa que sanitize() faz: estampagem de
        # original_index seguida da troca fisica de posicao do Padrao P
        # (aqui reproduzida manualmente, sem invocar sanitize() - o Padrao P
        # em si nao muda nesta tarefa). A lista fica fisicamente reordenada,
        # mas o original_index de cada evento deve continuar apontando para
        # a ordem GRAVADA (pre-inversao), nunca para a posicao fisica atual.
        ev_click = {"type": "click", "selector": "mat-option-autocomplete-trigger"}
        ev_fill = {"type": "fill", "selector": "#campo-marca", "value": "Fiat"}
        events = [ev_click, ev_fill]
        for i, ev in enumerate(events):
            ev["original_index"] = i
        # Padrao P inverteria fisicamente esse par (click de autocomplete
        # seguido de fill vira fill seguido de click).
        events[0], events[1] = events[1], events[0]

        result = self.service._classify_raw_events(events)

        self.assertEqual(len(result), 2)
        # Ordem fisica pos-inversao preservada - _classify_raw_events nunca
        # reordena nada.
        self.assertEqual(result[0]["selector"], "#campo-marca")
        self.assertEqual(result[1]["selector"], "mat-option-autocomplete-trigger")
        # original_index aponta para a ordem GRAVADA, nao para a posicao
        # fisica atual na lista.
        self.assertEqual(result[0]["original_index"], 1)
        self.assertEqual(result[1]["original_index"], 0)


if __name__ == "__main__":
    unittest.main()
