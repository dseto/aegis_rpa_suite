"""
Testa a parametrização do 'error_message_selector' no boilerplate canônico
gerado por CodeGeneratorService._normalize_boilerplate().

Cobre:
  1. Projeto COM 'error_message_selector' customizado em project.json ->
     o bloco __main__ gerado usa o seletor customizado.
  2. Projeto SEM o campo -> o bloco __main__ gerado é byte-idêntico ao
     boilerplate histórico (".toast-error, .alert-danger").

Executar com: python aegis_code_generator/test_error_selector_config.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_code_generator.code_generator import CodeGeneratorService

DEFAULT_SELECTOR = ".toast-error, .alert-danger"

# Corpo mínimo de bot válido (uma função de cenário) usado como entrada
# para _normalize_boilerplate em ambos os casos.
SAMPLE_BOT_CODE = '''
import os
import sys
from playwright.sync_api import Page

def execute_scenario_default(page: Page, row, runner):
    print("ola")

if __name__ == "__main__":
    pass
'''


def _generate_main_block(error_message_selector_override):
    """
    Instancia o CodeGeneratorService sem passar por generate() (que exige
    Gateway/LLM configurados) e ajusta apenas o atributo que generate()
    normalmente popularia a partir de project.json.
    """
    service = CodeGeneratorService(project_dir=os.path.dirname(os.path.abspath(__file__)))
    if error_message_selector_override is not None:
        service.error_message_selector = error_message_selector_override
    normalized = service._normalize_boilerplate(SAMPLE_BOT_CODE)
    return normalized


def test_custom_selector_from_project_json():
    custom_selector = "#meu-erro-custom, .aviso-falha"
    normalized = _generate_main_block(custom_selector)
    expected_line = (
        f'runner = TransactionRunner(project_dir=project_dir, '
        f'error_message_selector="{custom_selector}")'
    )
    assert expected_line in normalized, (
        f"Esperava a linha customizada no __main__ gerado.\n"
        f"Esperado conter: {expected_line}\n"
        f"Código gerado:\n{normalized}"
    )
    assert DEFAULT_SELECTOR not in normalized, (
        "O seletor default vazou no __main__ mesmo com override customizado."
    )
    print("[OK] test_custom_selector_from_project_json")


def test_default_selector_when_field_absent():
    # Sem passar override: simula projeto SEM 'error_message_selector' em
    # project.json. CodeGeneratorService.__init__ não define o atributo
    # (só generate() o faz), então _normalize_boilerplate deve cair no
    # default via getattr(self, "error_message_selector", DEFAULT).
    service = CodeGeneratorService(project_dir=os.path.dirname(os.path.abspath(__file__)))
    assert not hasattr(service, "error_message_selector"), (
        "Pré-condição do teste inválida: atributo já existia antes de generate()."
    )
    normalized = service._normalize_boilerplate(SAMPLE_BOT_CODE)

    expected_line = (
        f'runner = TransactionRunner(project_dir=project_dir, '
        f'error_message_selector="{DEFAULT_SELECTOR}")'
    )
    assert expected_line in normalized, (
        f"Esperava a linha default (byte-idêntica ao boilerplate histórico) no __main__.\n"
        f"Esperado conter: {expected_line}\n"
        f"Código gerado:\n{normalized}"
    )
    print("[OK] test_default_selector_when_field_absent")


if __name__ == "__main__":
    test_custom_selector_from_project_json()
    test_default_selector_when_field_absent()
    print("\nTodos os testes passaram.")
