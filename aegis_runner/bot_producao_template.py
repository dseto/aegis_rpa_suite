import os
import sys
import time
from aegis_runner.runner import TransactionRunner

def execute_scenario_default(page, row):
    """
    [CENÁRIO PADRÃO]
    Rotina de negócio específica para preenchimento do cenário 'default'.
    Acesse os dados da transação via dicionário 'row' (ex: row["cpf_cliente"]).
    """
    # Exemplo de preenchimento resiliente:
    # page.locator("#username").fill(row["usuario_login"])
    # page.locator("#btn-submit").click(force=True)
    pass

def execute_scenario_custom(page, row):
    """
    [CENÁRIO CUSTOMIZADO]
    Rotina de negócio específica para preenchimento de fluxos alternativos/renovações.
    """
    pass

if __name__ == "__main__":
    # Resolve dinamicamente a pasta onde o próprio script do bot está localizado
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Inicializa o orquestrador genérico da biblioteca do AEGIS
    runner = TransactionRunner(
        project_dir=current_dir,
        error_message_selector=".toast-error, .alert-danger"  # Seletor de erro de negócio do portal
    )
    
    # Registra as rotinas de negócio para cada cenário do dataset
    runner.register_scenario("default", execute_scenario_default)
    runner.register_scenario("custom", execute_scenario_custom)
    
    # Dispara o loop transacional (headless=False para Microsoft Edge na máquina do usuário)
    runner.run(headless=False)
