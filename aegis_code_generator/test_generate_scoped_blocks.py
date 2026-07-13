"""
Testa `_generate_scoped_blocks` — o núcleo compartilhado de prompt/parse/
splice extraído de `_surgical_correct_scoped` (H3 do plano híbrido, Seção
5.3: `.specs/plano-codegen-hibrido-deterministico.md`). Refatoração
mecânica: `_surgical_correct_scoped` vira um caller fino de
`_generate_scoped_blocks(mode="correct")`, com comportamento externo
byte-idêntico ao anterior.

Cobre:
  1. Resposta bem-formada (par BEGIN_STEP/END_STEP) -> splice correto,
     resto do arquivo intocado.
  2. Resposta malformada (sem par BEGIN/END) -> None.
  3. Resposta com 'def' em coluna 0 vazado no bloco -> None (guard de
     corrupção estrutural preexistente).
  4. Bloco optional (try/except) cujo except NÃO reimprime o erro -> None
     (ast-lint NOVO desta tarefa, Seção 7 do plano).
  5. Bloco optional com wrapper try/except válido -> aceito normalmente
     (o ast-lint não deve reprovar o template canônico).
  6. Equivalência: `_surgical_correct_scoped` retorna exatamente o mesmo
     resultado que uma chamada direta a `_generate_scoped_blocks(mode="correct")`
     para uma fixture de correção escopada simples.

Executar com: python aegis_code_generator/test_generate_scoped_blocks.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_code_generator.code_generator import CodeGeneratorService


# Bot mínimo com 3 blocos "# [PASSO N]" já anexados a step_id via
# step_id="st_XXX" na chamada real do runner (contrato de _parse_step_blocks).
EXISTING_CODE = '''def execute_scenario_default(page, row, runner):
    # [PASSO 1] Preencher nome
    runner.fill_resilient(page, selector="#nome", text_val=row.get("nome", ""), target_description="Nome", step_id="st_001")
    # [PASSO 2] Clicar em enviar
    runner.click_resilient(page, selector="#enviar", target_description="Enviar", step_id="st_002")
    # [PASSO 3] Fechar overlay opcional
    try:
        runner.click_resilient(page, selector=".overlay", target_description="Fechar overlay", step_id="st_003")
    except Exception as _opt_err:
        print(f"[BOT] Passo opcional st_003 pulado (nao-fatal): {_opt_err}")
'''

PLAN_STEPS = [
    {"step_id": "st_001", "type": "fill", "description": "Preencher nome", "selector": "#nome"},
    {"step_id": "st_002", "type": "click", "description": "Clicar em enviar", "selector": "#enviar"},
    {
        "step_id": "st_003", "type": "click", "description": "Fechar overlay opcional",
        "selector": ".overlay", "execution_hint": "optional",
    },
]

CORRECTED_BLOCK_ST002 = (
    '    # [PASSO 2] Clicar em enviar\n'
    '    runner.click_resilient(page, selector="#enviar-novo", target_description="Enviar", step_id="st_002")'
)


class FakeGateway:
    """Gateway falso: devolve response_text fixo, nunca chama API de verdade."""

    def __init__(self, response_text):
        self.provider = "fake"
        self.model = "fake-model"
        self.response_text = response_text
        self.calls = 0

    def _call_llm_api(self, prompt, force_json=False):
        self.calls += 1
        return self.response_text


def _service():
    return CodeGeneratorService(project_dir=os.path.dirname(os.path.abspath(__file__)))


def _scoped_plan_for(target_step_ids):
    service = _service()
    scoped_plan = service._build_scoped_edit_plan(EXISTING_CODE, target_step_ids)
    return service, scoped_plan


def _well_formed_response(step_id, block_text):
    return f"# BEGIN_STEP {step_id}\n{block_text}\n# END_STEP {step_id}"


def test_well_formed_response_splices_correctly():
    service, scoped_plan = _scoped_plan_for(["st_002"])
    assert scoped_plan is not None, "Pré-condição: bloco st_002 deve ser localizável"
    gateway = FakeGateway(_well_formed_response("st_002", CORRECTED_BLOCK_ST002))

    result = service._generate_scoped_blocks(
        scoped_plan, ["st_002"], "Corrija o seletor do botão", PLAN_STEPS, gateway, ""
    )

    assert result is not None, "Esperava splice bem-sucedido"
    assert "#enviar-novo" in result, "Bloco corrigido não foi spliceado no resultado"
    assert "#nome" in result, "Bloco st_001 (fora do escopo) não deveria mudar"
    assert 'step_id="st_003"' in result, "Bloco st_003 (fora do escopo) não deveria mudar"
    assert gateway.calls == 1, "Gateway deveria ter sido chamado exatamente uma vez"
    print("[OK] test_well_formed_response_splices_correctly")


def test_malformed_response_missing_begin_end_returns_none():
    service, scoped_plan = _scoped_plan_for(["st_002"])
    gateway = FakeGateway("resposta sem os delimitadores esperados")

    result = service._generate_scoped_blocks(
        scoped_plan, ["st_002"], "Corrija algo", PLAN_STEPS, gateway, ""
    )

    assert result is None, "Resposta malformada deveria retornar None"
    print("[OK] test_malformed_response_missing_begin_end_returns_none")


def test_response_with_column_zero_def_returns_none():
    service, scoped_plan = _scoped_plan_for(["st_002"])
    leaked_block = (
        '    # [PASSO 2] Clicar em enviar\n'
        'def execute_scenario_default(page, row, runner):\n'
        '    runner.click_resilient(page, selector="#enviar", target_description="Enviar", step_id="st_002")'
    )
    gateway = FakeGateway(_well_formed_response("st_002", leaked_block))

    result = service._generate_scoped_blocks(
        scoped_plan, ["st_002"], "Corrija algo", PLAN_STEPS, gateway, ""
    )

    assert result is None, "def em coluna 0 vazada na resposta deveria ser rejeitada"
    print("[OK] test_response_with_column_zero_def_returns_none")


def test_optional_block_except_without_print_returns_none():
    service, scoped_plan = _scoped_plan_for(["st_003"])
    assert scoped_plan is not None
    bad_optional_block = (
        '    # [PASSO 3] Fechar overlay opcional\n'
        '    try:\n'
        '        runner.click_resilient(page, selector=".overlay", target_description="Fechar overlay", step_id="st_003")\n'
        '    except Exception as _opt_err:\n'
        '        pass'
    )
    gateway = FakeGateway(_well_formed_response("st_003", bad_optional_block))

    result = service._generate_scoped_blocks(
        scoped_plan, ["st_003"], "Corrija o overlay", PLAN_STEPS, gateway, ""
    )

    assert result is None, "except sem print deveria ser rejeitado pelo ast-lint novo"
    print("[OK] test_optional_block_except_without_print_returns_none")


def test_optional_block_with_valid_wrapper_is_accepted():
    service, scoped_plan = _scoped_plan_for(["st_003"])
    good_optional_block = (
        '    # [PASSO 3] Fechar overlay opcional\n'
        '    try:\n'
        '        runner.click_resilient(page, selector=".overlay-novo", target_description="Fechar overlay", step_id="st_003")\n'
        '    except Exception as _opt_err:\n'
        '        print(f"[BOT] Passo opcional st_003 pulado (nao-fatal): {_opt_err}")'
    )
    gateway = FakeGateway(_well_formed_response("st_003", good_optional_block))

    result = service._generate_scoped_blocks(
        scoped_plan, ["st_003"], "Corrija o overlay", PLAN_STEPS, gateway, ""
    )

    assert result is not None, "wrapper opcional válido (template canônico) não deveria ser rejeitado"
    assert ".overlay-novo" in result
    print("[OK] test_optional_block_with_valid_wrapper_is_accepted")


def test_surgical_correct_scoped_equivalence():
    """
    _surgical_correct_scoped (agora um caller fino de _generate_scoped_blocks
    com mode="correct") deve continuar retornando exatamente o mesmo
    resultado que uma chamada direta ao núcleo extraído, para a mesma
    fixture de correção escopada simples.
    """
    service, scoped_plan = _scoped_plan_for(["st_002"])
    gateway_direct = FakeGateway(_well_formed_response("st_002", CORRECTED_BLOCK_ST002))
    gateway_via_wrapper = FakeGateway(_well_formed_response("st_002", CORRECTED_BLOCK_ST002))

    direct_result = service._generate_scoped_blocks(
        scoped_plan, ["st_002"], "Corrija o seletor do botão", PLAN_STEPS,
        gateway_direct, "", mode="correct",
    )
    wrapper_result = service._surgical_correct_scoped(
        scoped_plan, ["st_002"], "Corrija o seletor do botão", PLAN_STEPS,
        gateway_via_wrapper, "",
    )

    assert direct_result == wrapper_result, (
        "Wrapper _surgical_correct_scoped deveria produzir resultado idêntico "
        "ao núcleo _generate_scoped_blocks extraído"
    )
    assert wrapper_result is not None
    assert "#enviar-novo" in wrapper_result
    print("[OK] test_surgical_correct_scoped_equivalence")


if __name__ == "__main__":
    test_well_formed_response_splices_correctly()
    test_malformed_response_missing_begin_end_returns_none()
    test_response_with_column_zero_def_returns_none()
    test_optional_block_except_without_print_returns_none()
    test_optional_block_with_valid_wrapper_is_accepted()
    test_surgical_correct_scoped_equivalence()
    print("\nTodos os testes passaram.")
