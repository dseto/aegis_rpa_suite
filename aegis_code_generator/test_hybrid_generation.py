"""
Testa a integração híbrida em `_generate_new_code` atrás de
`AEGIS_CODEGEN_HYBRID` (H4 do plano híbrido — Seção 2.3 de
.specs/plano-codegen-hibrido-deterministico.md).

Cobre os cenários do DoD:
  (T1 removido em H8 — cobria só "flag 'false' nunca invoca o motor híbrido",
   o próprio default antigo; deixou de fazer sentido como gate após o flip
   de AEGIS_CODEGEN_HYBRID para 'true'.)
  T2 - flag 'true' + fixture SEM slot cognitivo -> zero chamadas LLM, bot
     gerado passa todos os validadores + dry run, manifest 'hybrid-1'
     gravado.
  T3 (obrigatório, achado I7) - flag 'true' + fixture COM slot cognitivo
     -> resposta da LLM SPLICEADA no skeleton, UMA única chamada (prompt de
     slots, não o de arquivo inteiro), sem fallback full-LLM.
  T4 - fixture com step 'optional' onde o mock responde a convenção de
     bloco-vazio -> splice aceita, manifest registra 'optional_omitted',
     validadores PASS.
  T5 - mock respondendo sem um dos slots -> fallback full-LLM na mesma
     tentativa (segunda chamada ao gateway, com o prompt de arquivo
     inteiro).

Executar com: python aegis_code_generator/test_hybrid_generation.py
(sem pytest, seguindo o padrão dos demais testes do repositório)
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_code_generator.code_generator import CodeGeneratorService
from aegis_code_generator.step_validator import (
    validate_bot_structure, validate_bot_against_plan,
    validate_dataset_field_names, validate_resilience_patterns, dry_run_bot,
)

FRAMEWORK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Fixture SEM slot cognitivo: fill com binding único no dicionário (C4 OK) +
# click simples (sem parent/weak_selector/menu) -> ambos deterministic.
PLAN_NO_SLOTS = {
    "steps": [
        {"step_id": "st_001", "type": "fill", "description": "Preencher nome", "selector": "#nome"},
        {"step_id": "st_002", "type": "click", "description": "Clicar em enviar", "selector": "#enviar"},
    ]
}
DICIONARIO_NO_SLOTS = {
    "fields": {
        "nome_cliente": {"selector": "#nome", "fill_strategy": "DIRECT", "observed_value": "Fulano de Tal"},
    }
}

# Fixture COM UM slot cognitivo: st_001 deterministic (click simples) +
# st_002 cognitive via C5 (weak_selector sem nenhum material de ancoragem).
PLAN_ONE_SLOT = {
    "steps": [
        {"step_id": "st_001", "type": "click", "description": "Abrir formulário", "selector": "#abrir"},
        {
            "step_id": "st_002", "type": "click",
            "description": "Confirmar (seletor fraco sem ancoragem)",
            "selector": "button.btn-generico", "weak_selector": True,
        },
    ]
}
DICIONARIO_ONE_SLOT = {"fields": {}}

# Fixture com step 'optional' (cognitive via C2) + um deterministic.
PLAN_OPTIONAL_SLOT = {
    "steps": [
        {"step_id": "st_001", "type": "click", "description": "Abrir formulário", "selector": "#abrir"},
        {
            "step_id": "st_002", "type": "click", "description": "Fechar overlay residual",
            "selector": ".cdk-overlay-backdrop", "execution_hint": "optional",
        },
    ]
}
DICIONARIO_OPTIONAL_SLOT = {"fields": {}}


class FakeGateway:
    """
    Gateway falso: devolve as respostas da fila `responses` na ordem das
    chamadas (uma por `_call_llm_api`), nunca chama API de verdade. Registra
    todo `prompt` recebido em `self.prompts` para inspeção pelo teste.
    """

    def __init__(self, responses):
        self.provider = "fake"
        self.model = "fake-model"
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def _call_llm_api(self, prompt, force_json=False):
        self.calls += 1
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError(
                f"FakeGateway: chamada #{self.calls} inesperada — fila de respostas vazia."
            )
        return self.responses.pop(0)


def _make_project(plan: dict) -> str:
    """
    Cria um diretório de projeto temporário com `plano_execucao.json`
    gravado (único artefato de disco que `_generate_new_code` realmente lê
    via `self.plan_path`) e devolve o path.
    """
    tmp_dir = tempfile.mkdtemp(prefix="aegis_test_hybrid_")
    with open(os.path.join(tmp_dir, "plano_execucao.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    return tmp_dir


def _full_llm_response(code_body):
    return f"```python\n{code_body}\n```\n"


DEFAULT_FULL_LLM_BODY = (
    'def execute_scenario_default(page, row, runner):\n'
    '    # [PASSO 1] Abrir formulário\n'
    '    runner.click_resilient(page, selector="#abrir", target_description="Abrir formulário", step_id="st_001")\n'
)


def _call_generate_new_code(service, dict_data, gateway, correcoes_path, pending_corrections=None):
    return service._generate_new_code(
        bot_path="unused_bot_path.py",
        dict_data=dict_data,
        report_content="relatorio fake de telemetria",
        skills_info_prompt="",
        pending_corrections=pending_corrections or [],
        gateway=gateway,
        project_json_path="unused_project.json",
        code_dir="unused_code_dir",
        correcoes_acumuladas_path=correcoes_path,
    )


# ---------------------------------------------------------------------------
# T1 removido (H8 — flip do default de AEGIS_CODEGEN_HYBRID para 'true'):
# cobria apenas o detalhe de implementação "flag 'false' nunca invoca o motor
# híbrido", que era o próprio ponto de partida (default antigo), não um
# contrato a preservar após o flip. Ver .specs/plano-codegen-hibrido-deterministico.md.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# T2 — flag 'true' + fixture sem slot cognitivo: zero chamadas LLM, bot
# passa todos os validadores + dry run, manifest 'hybrid-1'.
# ---------------------------------------------------------------------------

def test_hybrid_zero_slots_zero_llm_calls_and_full_pipeline_pass():
    tmp_dir = _make_project(PLAN_NO_SLOTS)
    try:
        dict_path = os.path.join(tmp_dir, "dicionario.json")
        with open(dict_path, "w", encoding="utf-8") as f:
            json.dump(DICIONARIO_NO_SLOTS, f)

        service = CodeGeneratorService(project_dir=tmp_dir)
        gateway = FakeGateway([])  # qualquer chamada estoura AssertionError
        correcoes_path = os.path.join(tmp_dir, "correcoes_acumuladas.json")

        os.environ["AEGIS_CODEGEN_HYBRID"] = "true"
        try:
            result = _call_generate_new_code(service, DICIONARIO_NO_SLOTS, gateway, correcoes_path)
        finally:
            os.environ.pop("AEGIS_CODEGEN_HYBRID", None)

        assert gateway.calls == 0, "Zero slots cognitivos deveria significar ZERO chamadas LLM"
        assert result is not None

        manifest = service._hybrid_manifest
        assert manifest is not None
        assert manifest["generator_version"] == "hybrid-1"
        assert manifest["steps"]["st_001"]["provenance"] == "deterministic"
        assert manifest["steps"]["st_002"]["provenance"] == "deterministic"

        full_file = service._normalize_boilerplate(result)

        struct_result = validate_bot_structure(full_file)
        assert struct_result["status"] == "PASS", struct_result.get("errors")

        plan_result = validate_bot_against_plan(full_file, service.plan_path, [])
        assert plan_result["status"] == "PASS", plan_result.get("errors")

        field_result = validate_dataset_field_names(full_file, dict_path)
        assert field_result["status"] == "PASS", field_result.get("errors")

        pattern_result = validate_resilience_patterns(full_file, service.plan_path, dict_path)
        assert pattern_result["status"] == "PASS", pattern_result.get("errors")

        dryrun_result = dry_run_bot(full_file, FRAMEWORK_ROOT, dataset_dir=tmp_dir)
        assert dryrun_result["status"] == "PASS", dryrun_result.get("errors")

        # Simula o ponto de escrita de sucesso de generate() (Seção 2.4).
        code_dir = os.path.join(tmp_dir, "code")
        os.makedirs(code_dir, exist_ok=True)
        service._write_generation_manifest(code_dir, manifest)
        on_disk = service._load_generation_manifest(code_dir)
        assert on_disk["generator_version"] == "hybrid-1"

        print("[OK] test_hybrid_zero_slots_zero_llm_calls_and_full_pipeline_pass")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T3 (obrigatório, achado I7) — flag 'true' + fixture COM 1 slot cognitivo:
# resposta spliceada, UMA chamada (prompt de slots), sem fallback full-LLM.
# ---------------------------------------------------------------------------

def test_hybrid_one_slot_spliced_single_call_no_fallback():
    tmp_dir = _make_project(PLAN_ONE_SLOT)
    try:
        service = CodeGeneratorService(project_dir=tmp_dir)
        slot_response = (
            "# BEGIN_STEP st_002\n"
            '# [PASSO 2] Confirmar (seletor fraco sem ancoragem)\n'
            'runner.click_resilient(page, selector="button.btn-generico:has-text(\'Confirmar\')", '
            'target_description="Confirmar (seletor fraco sem ancoragem)", step_id="st_002")\n'
            "# END_STEP st_002"
        )
        gateway = FakeGateway([slot_response])
        correcoes_path = os.path.join(tmp_dir, "correcoes_acumuladas.json")

        os.environ["AEGIS_CODEGEN_HYBRID"] = "true"
        try:
            result = _call_generate_new_code(service, DICIONARIO_ONE_SLOT, gateway, correcoes_path)
        finally:
            os.environ.pop("AEGIS_CODEGEN_HYBRID", None)

        assert gateway.calls == 1, "Deveria haver EXATAMENTE 1 chamada ao gateway (prompt de slots)"
        assert "REGRAS OBRIGATÓRIAS PARA GERAÇÃO DO CÓDIGO" not in gateway.prompts[0], (
            "A chamada não deveria usar o prompt de arquivo inteiro — sinal de fallback full-LLM."
        )
        assert "st_002" in gateway.prompts[0]

        assert result is not None, "Esperava splice bem-sucedido, não fallback full-LLM"
        assert "button.btn-generico:has-text('Confirmar')" in result, "Resposta da LLM não foi spliceada no skeleton"
        assert 'step_id="st_001"' in result, "Bloco deterministic st_001 deveria continuar presente"

        manifest = service._hybrid_manifest
        assert manifest is not None
        assert manifest["steps"]["st_001"]["provenance"] == "deterministic"
        assert manifest["steps"]["st_002"]["provenance"] == "cognitive"
        assert manifest["steps"]["st_002"]["reason"] != "optional_omitted", (
            "Bloco preenchido com código real não deveria ser marcado optional_omitted"
        )

        print("[OK] test_hybrid_one_slot_spliced_single_call_no_fallback")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T4 — step 'optional' cujo mock responde a convenção de bloco-vazio: splice
# aceita, manifest registra 'optional_omitted', validadores PASS.
# ---------------------------------------------------------------------------

def test_hybrid_optional_slot_empty_block_convention():
    tmp_dir = _make_project(PLAN_OPTIONAL_SLOT)
    try:
        dict_path = os.path.join(tmp_dir, "dicionario.json")
        with open(dict_path, "w", encoding="utf-8") as f:
            json.dump(DICIONARIO_OPTIONAL_SLOT, f)

        service = CodeGeneratorService(project_dir=tmp_dir)
        empty_block_response = (
            "# BEGIN_STEP st_002\n"
            '# [PASSO 2] Fechar overlay residual\n'
            '# AEGIS_COGNITIVE_SLOT step_id="st_002" motivo="optional não emitido: overlay não aparece neste fluxo de teste"\n'
            "# END_STEP st_002"
        )
        gateway = FakeGateway([empty_block_response])
        correcoes_path = os.path.join(tmp_dir, "correcoes_acumuladas.json")

        os.environ["AEGIS_CODEGEN_HYBRID"] = "true"
        try:
            result = _call_generate_new_code(service, DICIONARIO_OPTIONAL_SLOT, gateway, correcoes_path)
        finally:
            os.environ.pop("AEGIS_CODEGEN_HYBRID", None)

        assert gateway.calls == 1
        assert result is not None, "Convenção de bloco-vazio deveria ser ACEITA pelo splice, não tratada como slot faltando"

        manifest = service._hybrid_manifest
        assert manifest is not None
        assert manifest["steps"]["st_002"]["provenance"] == "cognitive"
        assert manifest["steps"]["st_002"]["reason"] == "optional_omitted"

        full_file = service._normalize_boilerplate(result)
        struct_result = validate_bot_structure(full_file)
        assert struct_result["status"] == "PASS", struct_result.get("errors")

        plan_result = validate_bot_against_plan(full_file, service.plan_path, [])
        assert plan_result["status"] == "PASS", plan_result.get("errors")

        pattern_result = validate_resilience_patterns(full_file, service.plan_path, dict_path)
        assert pattern_result["status"] == "PASS", pattern_result.get("errors")

        dryrun_result = dry_run_bot(full_file, FRAMEWORK_ROOT, dataset_dir=tmp_dir)
        assert dryrun_result["status"] == "PASS", dryrun_result.get("errors")

        print("[OK] test_hybrid_optional_slot_empty_block_convention")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# T5 — resposta sem um dos slots -> fallback full-LLM na MESMA tentativa
# (segunda chamada ao gateway, agora com o prompt de arquivo inteiro).
# ---------------------------------------------------------------------------

def test_hybrid_missing_slot_falls_back_to_full_llm():
    tmp_dir = _make_project(PLAN_ONE_SLOT)
    try:
        service = CodeGeneratorService(project_dir=tmp_dir)
        malformed_response = "resposta sem os delimitadores BEGIN_STEP/END_STEP esperados"
        fallback_body = (
            'def execute_scenario_default(page, row, runner):\n'
            '    # [PASSO 1] Abrir formulário\n'
            '    runner.click_resilient(page, selector="#abrir", target_description="Abrir formulário", step_id="st_001")\n'
            '    # [PASSO 2] Confirmar\n'
            '    runner.click_resilient(page, selector="button.btn-generico", target_description="Confirmar", step_id="st_002")\n'
        )
        gateway = FakeGateway([malformed_response, _full_llm_response(fallback_body)])
        correcoes_path = os.path.join(tmp_dir, "correcoes_acumuladas.json")

        os.environ["AEGIS_CODEGEN_HYBRID"] = "true"
        try:
            result = _call_generate_new_code(service, DICIONARIO_ONE_SLOT, gateway, correcoes_path)
        finally:
            os.environ.pop("AEGIS_CODEGEN_HYBRID", None)

        assert gateway.calls == 2, "Esperava 1 chamada de slots (falha) + 1 chamada full-LLM de fallback"
        assert "st_002" in gateway.prompts[0], "Primeira chamada deveria ser o prompt de slots"
        assert "REGRAS OBRIGATÓRIAS PARA GERAÇÃO DO CÓDIGO" in gateway.prompts[1], (
            "Segunda chamada (fallback) deveria usar o prompt full-LLM de arquivo inteiro"
        )
        assert service._hybrid_manifest is None, (
            "Fallback full-LLM não deveria deixar um _hybrid_manifest órfão para trás"
        )
        assert "execute_scenario_default" in result
        print("[OK] test_hybrid_missing_slot_falls_back_to_full_llm")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_hybrid_zero_slots_zero_llm_calls_and_full_pipeline_pass()
    test_hybrid_one_slot_spliced_single_call_no_fallback()
    test_hybrid_optional_slot_empty_block_convention()
    test_hybrid_missing_slot_falls_back_to_full_llm()
    print("\nTodos os testes passaram.")
