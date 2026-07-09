import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Precisamos importar aegis_runner.runner dentro do subprocess do harness,
# entao a raiz do repo (que contem o pacote aegis_runner) precisa estar no
# path usado como project_root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from step_validator import dry_run_bot


VALID_BOT_SOURCE = '''
def execute_scenario_default(page, row, runner):
    # [PASSO 1] Passo trivial que nao depende do conteudo da linha
    valor = row.get("nome", "")
    return valor
'''


def _bot_source_breaks_on_third_row():
    # Bot que só quebra quando o campo 'data' tem um valor real cujo formato
    # nao bate com o esperado por strptime — reproduz o bug real citado no
    # backlog (strptime só falha com dado de verdade, nao com "" default).
    return '''
import datetime

def execute_scenario_default(page, row, runner):
    # [PASSO 1] Parse de data no formato errado, so quebra com valor real
    data_str = row.get("data", "")
    if data_str:
        datetime.datetime.strptime(data_str, "%Y-%m-%d")
    return True
'''


class TestDryRunMultiRow(unittest.TestCase):
    def setUp(self):
        self.project_root = tempfile.mkdtemp(prefix="aegis_dryrun_test_")
        self.dataset_dir = tempfile.mkdtemp(prefix="aegis_dryrun_dataset_")

    def tearDown(self):
        shutil.rmtree(self.project_root, ignore_errors=True)
        shutil.rmtree(self.dataset_dir, ignore_errors=True)

    def _write_dataset(self, rows):
        path = os.path.join(self.dataset_dir, "dataset_inicial.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        return path

    def test_fails_on_third_row_reports_row_id(self):
        # Linhas 1 e 2 tem 'data' vazio ou em formato compativel; a linha 3
        # (id=3) tem um valor real em formato errado ("03/07/2026" nao bate
        # com "%Y-%m-%d") que so estoura quando exercitado de verdade.
        rows = [
            {"id": 1, "data": ""},
            {"id": 2, "data": "2026-01-01"},
            {"id": 3, "data": "03/07/2026"},
        ]
        self._write_dataset(rows)

        result = dry_run_bot(
            _bot_source_breaks_on_third_row(),
            project_root=REPO_ROOT,
            timeout=30,
            dataset_dir=self.dataset_dir,
        )

        self.assertEqual(result["status"], "FAIL")
        detail = result["errors"][0]["detail"]
        self.assertIn("id=3", detail)
        self.assertIn("ValueError", result["errors"][0].get("exception_type", "") or detail)

    def test_processes_at_most_cap_within_timeout(self):
        # Dataset de 100 linhas validas: o dry run deve respeitar o teto
        # AEGIS_DRYRUN_MAX_ROWS (setado aqui para um valor baixo) e terminar
        # dentro do timeout, sem tentar processar as 100 linhas.
        rows = [{"id": i, "nome": f"linha-{i}"} for i in range(1, 101)]
        self._write_dataset(rows)

        old_env = os.environ.get("AEGIS_DRYRUN_MAX_ROWS")
        os.environ["AEGIS_DRYRUN_MAX_ROWS"] = "5"
        try:
            result = dry_run_bot(
                VALID_BOT_SOURCE,
                project_root=REPO_ROOT,
                timeout=30,
                dataset_dir=self.dataset_dir,
            )
        finally:
            if old_env is None:
                os.environ.pop("AEGIS_DRYRUN_MAX_ROWS", None)
            else:
                os.environ["AEGIS_DRYRUN_MAX_ROWS"] = old_env

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["total_errors"], 0)

    def test_valid_bot_passes_dryrun_ok(self):
        rows = [
            {"id": 1, "nome": "Fulano"},
            {"id": 2, "nome": "Beltrano"},
        ]
        self._write_dataset(rows)

        result = dry_run_bot(
            VALID_BOT_SOURCE,
            project_root=REPO_ROOT,
            timeout=30,
            dataset_dir=self.dataset_dir,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["total_errors"], 0)


if __name__ == "__main__":
    unittest.main()
