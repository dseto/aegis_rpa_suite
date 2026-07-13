"""
[SUBAGENTE 14] Testa as DUAS remediações da oscilação infinita do retry 3 do
gate H8 (assinatura `execute_scenario_default(runner, row)` errada, fora de
qualquer bloco `# [PASSO N]`, que o modo de correção escopado nunca alcança):

PARTE 1 — autofix determinístico da assinatura
  (a) `_rewrite_scenario_signature_to_canonical` corrige `(runner, row)` ->
      `(page, row, runner)` quando os nomes são subconjunto de
      {page, row, runner}, e o resultado passa em `validate_bot_structure`.
  (b) NÃO dispara quando os nomes divergem (ex.: `(pg, r)`) — cai no fluxo
      normal de correção via LLM (retorna o código intocado).

PARTE 2 — guard de lineno órfão no roteamento de `_surgical_correct`
  (c) um erro com `lineno` fora de qualquer bloco conhecido força o fluxo de
      ARQUIVO INTEIRO mesmo com `target_step_ids` não-vazio (modo escopado
      ignorado).
  (d) um erro com `lineno` DENTRO de um bloco conhecido continua no modo
      escopado normalmente (não regride o comportamento existente).

Executar com: python aegis_code_generator/test_signature_autofix_and_orphan_scope.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_code_generator.code_generator import CodeGeneratorService
from aegis_code_generator.step_validator import (
    validate_bot_structure,
    _validate_scenario_function_signature,
)


def _service():
    # project_dir vazio (temp): sem plano/dicionario/correcoes -> os ramos que
    # os leem viram no-op, isolando o teste no roteamento de _surgical_correct.
    return CodeGeneratorService(project_dir=tempfile.mkdtemp(prefix="aegis_sig_test_"))


# ─────────────────────────────────────────────────────────────────────────────
# PARTE 1 — autofix determinístico da assinatura
# ─────────────────────────────────────────────────────────────────────────────

_BOT_WRONG_ORDER = (
    "import os\n"
    "\n"
    "from aegis_runner.runner import TransactionRunner\n"
    "\n"
    "\n"
    "def execute_scenario_default(runner, row):\n"
    "    runner.click_resilient(page, selector=\"#ok\", target_description=\"ok\", step_id=\"st_001\")\n"
    "\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    pass\n"
)


def test_part1_autofix_rewrites_wrong_signature():
    service = _service()
    # Pré-condição: a assinatura errada é de fato flagrada pelo validador.
    pre_errors = {e["type"] for e in _validate_scenario_function_signature(_BOT_WRONG_ORDER)}
    assert "WRONG_SCENARIO_PARAM_ORDER" in pre_errors, pre_errors

    fixed = service._rewrite_scenario_signature_to_canonical(_BOT_WRONG_ORDER)
    assert fixed != _BOT_WRONG_ORDER, "Autofix deveria ter reescrito a assinatura"
    assert "def execute_scenario_default(page, row, runner):" in fixed, fixed

    post_errors = {e["type"] for e in _validate_scenario_function_signature(fixed)}
    assert "WRONG_SCENARIO_PARAM_ORDER" not in post_errors, post_errors
    assert "INVALID_SCENARIO_SIGNATURE" not in post_errors, post_errors
    # O corpo (única linha de runner) permanece intocado.
    assert 'step_id="st_001"' in fixed
    print("[OK] test_part1_autofix_rewrites_wrong_signature")


def test_part1_autofix_rewrites_short_signature():
    # INVALID_SCENARIO_SIGNATURE (< 2 params) com nome conhecido -> canônico.
    bot = (
        "import os\n"
        "\n"
        "\n"
        "def execute_scenario_default(page):\n"
        "    pass\n"
    )
    service = _service()
    fixed = service._rewrite_scenario_signature_to_canonical(bot)
    assert "def execute_scenario_default(page, row, runner):" in fixed, fixed
    post_errors = {e["type"] for e in _validate_scenario_function_signature(fixed)}
    assert "INVALID_SCENARIO_SIGNATURE" not in post_errors, post_errors
    print("[OK] test_part1_autofix_rewrites_short_signature")


def test_part1_autofix_skips_alien_names():
    bot = (
        "import os\n"
        "\n"
        "\n"
        "def execute_scenario_default(pg, r):\n"
        "    pass\n"
    )
    service = _service()
    fixed = service._rewrite_scenario_signature_to_canonical(bot)
    assert fixed == bot, "Nomes alienígenas NÃO devem ser reescritos cegamente — cai no fluxo de LLM"
    print("[OK] test_part1_autofix_skips_alien_names")


def test_part1_autofix_noop_when_already_canonical():
    bot = (
        "import os\n"
        "\n"
        "\n"
        "def execute_scenario_default(page, row, runner):\n"
        "    pass\n"
    )
    service = _service()
    assert service._rewrite_scenario_signature_to_canonical(bot) == bot
    print("[OK] test_part1_autofix_noop_when_already_canonical")


def test_part1_autofix_skips_varargs():
    bot = (
        "import os\n"
        "\n"
        "\n"
        "def execute_scenario_default(page, row, *args):\n"
        "    pass\n"
    )
    service = _service()
    assert service._rewrite_scenario_signature_to_canonical(bot) == bot, (
        "*args presente -> autofix não deve mexer (deixa pro fluxo de LLM)"
    )
    print("[OK] test_part1_autofix_skips_varargs")


# ─────────────────────────────────────────────────────────────────────────────
# PARTE 2 — guard de lineno órfão no roteamento de _surgical_correct
# ─────────────────────────────────────────────────────────────────────────────

# Bot com 2 blocos "# [PASSO N]". Linhas (1-based):
#   1: import os
#   2: (blank)
#   3: def execute_scenario_default(page, row, runner):
#   4:     # [PASSO 1] Preencher nome
#   5:     runner.fill_resilient(... step_id="st_001")
#   6:     # [PASSO 2] Clicar em enviar
#   7:     runner.click_resilient(... step_id="st_002")
_BOT_WITH_BLOCKS = (
    "import os\n"
    "\n"
    "def execute_scenario_default(page, row, runner):\n"
    "    # [PASSO 1] Preencher nome\n"
    "    runner.fill_resilient(page, selector=\"#nome\", text_val=row.get(\"nome\", \"\"), target_description=\"Nome\", step_id=\"st_001\")\n"
    "    # [PASSO 2] Clicar em enviar\n"
    "    runner.click_resilient(page, selector=\"#enviar\", target_description=\"Enviar\", step_id=\"st_002\")\n"
)

_CORRECTED_BLOCK_ST002 = (
    '    # [PASSO 2] Clicar em enviar\n'
    '    runner.click_resilient(page, selector="#enviar-novo", target_description="Enviar", step_id="st_002")'
)

_FULL_FILE_REPLACEMENT = (
    "import os\n"
    "\n"
    "def execute_scenario_default(page, row, runner):\n"
    "    # FULLFILE_SENTINEL\n"
    "    # [PASSO 1] Preencher nome\n"
    "    runner.fill_resilient(page, selector=\"#nome\", text_val=row.get(\"nome\", \"\"), target_description=\"Nome\", step_id=\"st_001\")\n"
    "    # [PASSO 2] Clicar em enviar\n"
    "    runner.click_resilient(page, selector=\"#enviar\", target_description=\"Enviar\", step_id=\"st_002\")\n"
)

_PENDING = [{
    "step_id": "st_002",
    "action": "click",
    "failed_selector": "#enviar",
    "root_cause": "seletor",
    "proposed_fix": "trocar seletor",
}]


class RoutingGateway:
    """Gateway que captura os prompts e responde conforme o modo detectado:
    prompt escopado (contém 'BEGIN_STEP') -> resposta BEGIN_STEP/END_STEP;
    prompt de arquivo inteiro -> bloco ```python completo."""

    def __init__(self):
        self.provider = "fake"
        self.model = "fake-model"
        self.prompts = []

    def _call_llm_api(self, prompt, force_json=False):
        self.prompts.append(prompt)
        if "BEGIN_STEP" in prompt:
            return f"# BEGIN_STEP st_002\n{_CORRECTED_BLOCK_ST002}\n# END_STEP st_002"
        return f"```python\n{_FULL_FILE_REPLACEMENT}\n```"

    @property
    def scoped_attempted(self):
        return any("BEGIN_STEP" in p for p in self.prompts)


def _run_surgical(service, gateway, current_diff):
    return service._surgical_correct(
        bot_path="__unused__.py",
        pending_corrections=_PENDING,
        gateway=gateway,
        project_json_path="__unused_project.json",
        code_dir="__unused_code_dir",
        correcoes_acumuladas_path="__unused_correcoes.json",
        current_code=_BOT_WITH_BLOCKS,
        current_diff=current_diff,
    )


def test_part2_orphan_lineno_forces_full_file():
    service = _service()
    gateway = RoutingGateway()
    # Erro com lineno=3 (a linha do 'def', fora de todo bloco # [PASSO N]) e
    # SEM step_id -> órfão. pending_corrections mira st_002 (bloco válido), então
    # target_step_ids é não-vazio — o guard deve MESMO ASSIM forçar arquivo inteiro.
    diff = {"errors": [{"type": "WRONG_SCENARIO_PARAM_ORDER", "lineno": 3}]}
    result = _run_surgical(service, gateway, diff)

    assert result is not None
    assert not gateway.scoped_attempted, (
        "Erro de lineno órfão deveria FORÇAR arquivo inteiro — modo escopado não deveria ser tentado"
    )
    assert "FULLFILE_SENTINEL" in result, "Resultado deveria vir do prompt de arquivo inteiro"
    print("[OK] test_part2_orphan_lineno_forces_full_file")


def test_part2_lineno_inside_block_stays_scoped():
    service = _service()
    gateway = RoutingGateway()
    # Erro com lineno=7 (a chamada de st_002, DENTRO do bloco # [PASSO 2]) e sem
    # step_id direto -> mapeia para st_002 via lineno. NÃO é órfão: modo escopado.
    diff = {"errors": [{"type": "HARDCODED_TEXT_VAL", "lineno": 7}]}
    result = _run_surgical(service, gateway, diff)

    assert result is not None
    assert gateway.scoped_attempted, "lineno dentro de bloco conhecido deveria manter o modo escopado"
    assert "#enviar-novo" in result, "Bloco st_002 corrigido deveria estar spliceado no resultado"
    assert "#nome" in result, "Bloco fora do escopo (st_001) não deveria mudar"
    assert "FULLFILE_SENTINEL" not in result, "Não deveria ter caído no fluxo de arquivo inteiro"
    print("[OK] test_part2_lineno_inside_block_stays_scoped")


def test_part2_compute_restore_scope_mirrors_flag():
    service = _service()
    # Espelho da detecção em _compute_restore_target_scope: erro órfão marca a flag.
    diff_orphan = {"errors": [{"type": "WRONG_SCENARIO_PARAM_ORDER", "lineno": 3}]}
    scope = service._compute_restore_target_scope(_PENDING, diff_orphan, _BOT_WITH_BLOCKS)
    assert "st_002" in scope, "step_id da correção pendente deveria continuar no escopo de restore"
    assert getattr(service, "_restore_scope_incomplete", None) is True, (
        "Erro órfão deveria marcar self._restore_scope_incomplete=True (paridade com _surgical_correct)"
    )

    diff_inside = {"errors": [{"type": "HARDCODED_TEXT_VAL", "lineno": 7}]}
    service._compute_restore_target_scope(_PENDING, diff_inside, _BOT_WITH_BLOCKS)
    assert service._restore_scope_incomplete is False, (
        "lineno dentro de bloco conhecido não deveria marcar escopo incompleto"
    )
    print("[OK] test_part2_compute_restore_scope_mirrors_flag")


if __name__ == "__main__":
    test_part1_autofix_rewrites_wrong_signature()
    test_part1_autofix_rewrites_short_signature()
    test_part1_autofix_skips_alien_names()
    test_part1_autofix_noop_when_already_canonical()
    test_part1_autofix_skips_varargs()
    test_part2_orphan_lineno_forces_full_file()
    test_part2_lineno_inside_block_stays_scoped()
    test_part2_compute_restore_scope_mirrors_flag()
    print("\nTodos os testes passaram.")
