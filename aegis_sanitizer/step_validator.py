"""
Validador AST para bot_producao.py

Verifica se o código gerado implementa exatamente os passos do plano_execucao.json:
- step_ids presentes e na ordem correta
- Contagem de passos corresponde
- Não valida tipos de método (decisão do LLM) nem seletores
"""

import ast
import json
import os
from typing import List, Dict, Any, Optional


# Métodos do runner que devem conter step_id
RUNNER_METHODS = {
    "click_resilient",
    "fill_resilient",
    "fill_human_like",
    "select_option_resilient",
    "click_chained",
    "fill_chained",
    "click_by_coordinates",
}


def extract_step_ids_from_code(code: str) -> List[str]:
    """
    Extrai step_ids em ordem de aparição no código fonte.

    Faz parse AST de bot_producao.py e encontra todas as chamadas
    runner.metodo(step_id="...") ou self.metodo(step_id="...").
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    # ast.walk() faz BFS, NAO ordem do codigo fonte — chamadas em ramos irmaos
    # (if/elif/else) em profundidades diferentes saem fora de ordem. Por isso
    # coletamos (lineno, col, step_id) e ordenamos explicitamente por posicao.
    found = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in RUNNER_METHODS:
            continue

        step_id_value = None
        for kw in node.keywords:
            if kw.arg == "step_id":
                if isinstance(kw.value, ast.Constant):
                    step_id_value = kw.value.value
                elif hasattr(ast, 'Str') and isinstance(kw.value, ast.Str):
                    step_id_value = kw.value.s
                break

        if step_id_value:
            found.append((node.lineno, node.col_offset, step_id_value))

    found.sort(key=lambda t: (t[0], t[1]))

    # Colapsa execucoes consecutivas do MESMO step_id (ramos mutuamente
    # exclusivos de if/elif/else representando um unico passo logico).
    step_ids = []
    for _, _, sid in found:
        if not step_ids or step_ids[-1] != sid:
            step_ids.append(sid)

    return step_ids


def validate_bot_structure(bot_code: str) -> Dict[str, Any]:
    """
    Valida a estrutura do bot — proíbe padrões que violam o SDK Aegis.

    Verificações:
    - CRÍTICO: sem import asyncio, sem await, sem classes customizadas
    - CRÍTICO: TransactionRunner importado e usado corretamente
    - CRÍTICO: page passado como argumento em chamadas de runner
    - CRÍTICO: text_val (não value) em fill_resilient
    - ALTO: sem acesso direto ao DOM (page.click, page.fill, locator.click)
    - ALTO: import do playwright.sync_api (não async_api)
    - ALTO: funções obrigatórias (execute_scenario_default, register_scenario, runner.run)
    - MÉDIO: sem gerenciamento manual de browser
    """
    errors = []

    # ── CRÍTICO: sintaxe válida (gate obrigatório — sem isso, checks AST abaixo seriam silenciosamente pulados) ──
    try:
        ast.parse(bot_code)
    except SyntaxError as syntax_err:
        return {
            "status": "FAIL",
            "total_errors": 1,
            "errors": [{
                "type": "SYNTAX_ERROR",
                "detail": f"Código Python inválido: {syntax_err.msg} (linha {syntax_err.lineno}, col {syntax_err.offset}). "
                          f"Corrija a sintaxe antes de qualquer outra validação."
            }]
        }

    # ── CRÍTICO: import asyncio (TransactionRunner é sync) ──
    if "import asyncio" in bot_code or "from asyncio" in bot_code:
        errors.append({
            "type": "FORBIDDEN_ASYNCIO",
            "detail": "Código importa asyncio. TransactionRunner é síncrono. Remova 'import asyncio' e use funções sync (def, não async def)."
        })

    # ── CRÍTICO: await em chamadas de runner (indica async def) ──
    if "await runner." in bot_code:
        errors.append({
            "type": "FORBIDDEN_AWAIT_RUNNER",
            "detail": "Código usa 'await runner.xxx()'. TransactionRunner é síncrono. Remova 'await' e use chamadas diretas: runner.click_resilient(page, ...)."
        })

    # ── CRÍTICO: classes customizadas de runner ──
    forbidden_class_patterns = [
        "class ResilientRunner",
        "class BotRunner",
        "class CustomRunner",
        "class AutomationRunner",
        "class RpaRunner",
    ]
    for pattern in forbidden_class_patterns:
        if pattern in bot_code:
            errors.append({
                "type": "FORBIDDEN_CUSTOM_CLASS",
                "pattern": pattern,
                "detail": f"Código contém classe customizada proibida: '{pattern}'. Use TransactionRunner do SDK Aegis."
            })
            break

    # ── CRÍTICO: asyncio.run() standalone ──
    if "asyncio.run(" in bot_code:
        errors.append({
            "type": "FORBIDDEN_ASYNCIO_RUN",
            "detail": "Código usa asyncio.run() — bot standalone proibido. Use TransactionRunner.run()."
        })

    # ── CRÍTICO: csv.DictReader manual ──
    if "csv.DictReader" in bot_code or ("import csv" in bot_code and "open(" in bot_code):
        errors.append({
            "type": "FORBIDDEN_MANUAL_CSV",
            "detail": "Código abre/manipula CSV manualmente. TransactionRunner gerencia o dataset automaticamente via dataset_inicial.json."
        })

    # ── CRÍTICO: async_playwright manual ──
    if "async_playwright" in bot_code:
        errors.append({
            "type": "FORBIDDEN_MANUAL_BROWSER",
            "detail": "Código gerencia browser manualmente com async_playwright(). TransactionRunner gerencia o browser."
        })

    # ── CRÍTICO: Obrigatório import TransactionRunner ──
    if "from aegis_runner.runner import TransactionRunner" not in bot_code and \
       "from aegis_runner.runner import" not in bot_code:
        errors.append({
            "type": "MISSING_TRANSACTION_RUNNER",
            "detail": "Código não importa TransactionRunner do SDK Aegis. O import é obrigatório."
        })

    # ── ALTO: import playwright.async_api em vez de sync_api ──
    if "playwright.async_api" in bot_code:
        errors.append({
            "type": "FORBIDDEN_ASYNC_API",
            "detail": "Código importa 'playwright.async_api'. TransactionRunner é síncrono. Use 'from playwright.sync_api import Page'."
        })

    # ── ALTO: acesso direto ao DOM bypassando runner ──
    # Só reporta se NÃO houver chamadas de runner (runner.click_resilient etc.)
    # Bots válidos podem usar page.locator() para operações auxiliares (ex: ler input_value)
    has_runner_calls = any(
        f"runner.{m}" in bot_code or f"runner.{m}(" in bot_code
        for m in RUNNER_METHODS
    )
    if not has_runner_calls:
        if "page.click(" in bot_code or "page.fill(" in bot_code:
            errors.append({
                "type": "FORBIDDEN_DIRECT_DOM",
                "detail": "Código usa page.click()/page.fill() diretamente sem nenhuma chamada ao runner. "
                          "Toda interação principal deve ser feita através dos métodos do runner."
            })

    # ── ALTO: browser.close() manual ──
    if "browser.close()" in bot_code or "await browser.close()" in bot_code:
        errors.append({
            "type": "FORBIDDEN_BROWSER_CLOSE",
            "detail": "Código fecha browser manualmente. TransactionRunner gerencia o ciclo de vida do browser."
        })

    # ── ALTO: page.goto() manual em bot standalone (runner gerencia navegação) ──
    # Só reporta se bot é standalone (sem TransactionRunner) — bots SDK podem precisar de goto
    if "page.goto(" in bot_code and not has_runner_calls:
        errors.append({
            "type": "FORBIDDEN_PAGE_GOTO",
            "detail": "Código navega manualmente com page.goto() em bot standalone. Use TransactionRunner que gerencia navegação."
        })

    # ── ALTO: função execute_scenario_default ausente ──
    if "def execute_scenario_default" not in bot_code:
        errors.append({
            "type": "MISSING_EXECUTE_FUNCTION",
            "detail": "Código não define 'execute_scenario_default(page, row, runner)'. Esta função é o entry point do robô."
        })

    # ── ALTO: registro e execução ──
    if "register_scenario" not in bot_code:
        errors.append({
            "type": "MISSING_REGISTER_SCENARIO",
            "detail": "Código não chama 'runner.register_scenario()'. O cenário deve ser registrado antes de runner.run()."
        })

    if "runner.run()" not in bot_code and ".run(" not in bot_code:
        errors.append({
            "type": "MISSING_RUNNER_RUN",
            "detail": "Código não chama 'runner.run()'. O robô nunca será executado sem esta chamada."
        })

    # ── ALTO: bloco if __name__ == "__main__": ausente ──
    if 'if __name__ == "__main__":' not in bot_code and "__name__" not in bot_code:
        errors.append({
            "type": "MISSING_MAIN_BLOCK",
            "detail": "Código não tem bloco 'if __name__ == \"__main__\":'. O robô não executa sem entry point."
        })

    # ── CRÍTICO: AST-level — page passado para métodos do runner, contrato de chamadas, async def ──
    ast_errors = _validate_runner_call_contract(bot_code)
    errors.extend(ast_errors)

    # ── CRÍTICO: AST-level — TransactionRunner instanciado corretamente ──
    ctor_errors = _validate_transaction_runner_constructor(bot_code)
    errors.extend(ctor_errors)

    # ── CRÍTICO: AST-level — imports fantasma de aegis_runner (LLM alucina módulos/símbolos) ──
    import_errors = _validate_aegis_imports(bot_code)
    errors.extend(import_errors)

    # ── CRÍTICO: AST-level — ordem de parâmetros de execute_scenario_default ──
    sig_errors = _validate_scenario_function_signature(bot_code)
    errors.extend(sig_errors)

    # ── CRÍTICO: AST-level — project_dir precisa subir da pasta 'code/' ──
    dir_errors = _validate_project_dir_resolution(bot_code)
    errors.extend(dir_errors)

    return {
        "status": "PASS" if not errors else "FAIL",
        "total_errors": len(errors),
        "errors": errors
    }


def _validate_runner_call_contract(bot_code: str) -> List[Dict[str, Any]]:
    """
    Validacao AST: verifica contrato das chamadas aos metodos do runner.

    - page deve ser primeiro argumento posicional
    - fill_resilient/fill_human_like usam text_val= (nao value=)
    - text_val= deve referenciar row (nao string literal hardcoded)
    - Nenhuma funcao async def (TransactionRunner eh sincrono)
    """
    errors = []
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return []

    # Track whether we've already flagged async def (once is enough)
    async_def_found = False

    for node in ast.walk(tree):
        # ── CRITICO: async def (TransactionRunner nao suporta async) ──
        if isinstance(node, ast.AsyncFunctionDef) and not async_def_found:
            async_def_found = True
            errors.append({
                "type": "FORBIDDEN_ASYNC_DEF",
                "function": node.name,
                "detail": f"Funcao '{node.name}' definida como 'async def'. "
                          f"TransactionRunner eh sincrono e nao executa corrotinas. Use 'def' (sem async)."
            })

        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue

        # ── CRITICO: metodo alucinado — chamada em objeto chamado 'runner' que nao existe no SDK ──
        if (isinstance(node.func.value, ast.Name) and node.func.value.id == "runner"
                and node.func.attr not in RUNNER_METHODS
                and node.func.attr not in ("register_scenario", "run")):
            errors.append({
                "type": "HALLUCINATED_RUNNER_METHOD",
                "method": node.func.attr,
                "detail": f"'runner.{node.func.attr}(...)' nao existe no SDK TransactionRunner. "
                          f"Metodos validos: {sorted(RUNNER_METHODS)} + register_scenario/run. "
                          f"Este metodo foi provavelmente alucinado."
            })
            continue

        if node.func.attr not in RUNNER_METHODS:
            continue

        method_name = node.func.attr

        # Verifica se 'page' eh primeiro argumento posicional
        if not node.args:
            errors.append({
                "type": "MISSING_PAGE_ARG",
                "method": method_name,
                "detail": f"Chamada runner.{method_name}() nao passa 'page' como primeiro argumento. "
                          f"Ex: runner.{method_name}(page, selector=..., ...)."
            })

        # Verifica keywords proibidas e hardcoded values
        for kw in node.keywords:
            # keyword value= proibido (deve ser text_val=)
            if kw.arg == "value":
                errors.append({
                    "type": "FORBIDDEN_VALUE_KWARG",
                    "method": method_name,
                    "detail": f"Chamada runner.{method_name}() usa 'value='. Use 'text_val=' (nome correto do parametro)."
                })
                break

            # text_val= deve referenciar row, nao ser string literal
            if kw.arg == "text_val":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    errors.append({
                        "type": "HARDCODED_TEXT_VAL",
                        "method": method_name,
                        "detail": f"Chamada runner.{method_name}() usa text_val com string literal "
                                  f"'{kw.value.value[:50]}'. Use row.get('chave', '') para valores dinamicos."
                    })

    return errors


def validate_bot_against_plan(
    bot_code: str, plan_path: str, pending_corrections: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compara step_ids do código gerado com plano_execucao.json.

    Valida: step_ids presentes, ordem correta, contagem.
    NÃO valida: tipo de método, seletores, comentários.

    Corações com campo 'required_reopen' pedem uma chamada de sincronização
    extra entre after_step_id e step_id (ex.: page.fill de re-disparo). A LLM
    ignora repetidamente a instrução de não rotular essa chamada com step_id
    (inventa nomes como 'st_023_reopen', 'st_023_re_trigger' mesmo quando
    proibido explicitamente) — em vez de brigar com esse comportamento a cada
    retry, toleramos aqui UM step_id extra nessa posição exata e delegamos a
    checagem de conteúdo real (chamada certa, seletor certo, posição certa)
    para validate_required_reopen_patterns, que não depende de step_id nenhum.
    """
    if not os.path.exists(plan_path):
        return {
            "status": "FAIL",
            "total_errors": 1,
            "errors": [{
                "type": "PLAN_NOT_FOUND",
                "detail": f"Arquivo de plano não encontrado: {plan_path}"
            }]
        }

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    planned_ids = [s["step_id"] for s in plan.get("steps", [])]
    code_ids = extract_step_ids_from_code(bot_code)

    if pending_corrections:
        planned_set_for_reopen = set(planned_ids)
        reopen_reqs = [
            (c["required_reopen"]["after_step_id"], c["step_id"])
            for c in pending_corrections
            if c.get("required_reopen") and c.get("step_id")
        ]
        for after_id, target_id in reopen_reqs:
            if after_id in code_ids and target_id in code_ids:
                after_pos = code_ids.index(after_id)
                target_pos = code_ids.index(target_id)
                if target_pos == after_pos + 2:
                    extra_id = code_ids[after_pos + 1]
                    if extra_id not in planned_set_for_reopen:
                        code_ids = code_ids[:after_pos + 1] + code_ids[after_pos + 2:]

    if not code_ids:
        return {
            "status": "FAIL",
            "total_errors": 1,
            "errors": [{
                "type": "NO_STEPS_FOUND",
                "detail": "Nenhum step_id encontrado no código. Verifique se as chamadas usam step_id=."
            }]
        }

    errors = []

    if len(code_ids) != len(planned_ids):
        errors.append({
            "type": "COUNT_MISMATCH",
            "expected": len(planned_ids),
            "found": len(code_ids),
            "detail": f"Esperado {len(planned_ids)} passos, encontrado {len(code_ids)}"
        })

    max_len = max(len(planned_ids), len(code_ids))
    for i in range(max_len):
        planned = planned_ids[i] if i < len(planned_ids) else None
        coded = code_ids[i] if i < len(code_ids) else None

        if planned != coded:
            errors.append({
                "type": "STEP_ID_MISMATCH",
                "position": i + 1,
                "expected_id": planned,
                "found_id": coded,
                "detail": f"Posição {i+1}: esperado {planned}, encontrado {coded}"
            })

    planned_set = set(planned_ids)
    code_set = set(code_ids)
    missing = sorted(planned_set - code_set)
    extra = sorted(code_set - planned_set)

    if missing:
        errors.append({
            "type": "MISSING_STEPS",
            "step_ids": missing,
            "detail": f"Passos no plano mas ausentes no código: {missing}"
        })
    if extra:
        errors.append({
            "type": "EXTRA_STEPS",
            "step_ids": extra,
            "detail": f"Passos no código mas ausentes no plano: {extra}"
        })

    return {
        "status": "PASS" if not errors else "FAIL",
        "total_errors": len(errors),
        "errors": errors
    }


def _validate_transaction_runner_constructor(bot_code: str) -> List[Dict[str, Any]]:
    """
    Validacao AST: garante que TransactionRunner(...) eh instanciado com
    'project_dir' como keyword argument, e que a instanciacao ocorre dentro
    do bloco 'if __name__ == "__main__":' (nao no escopo global do modulo).
    """
    errors = []
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_transaction_runner_call = (
            (isinstance(func, ast.Name) and func.id == "TransactionRunner") or
            (isinstance(func, ast.Attribute) and func.attr == "TransactionRunner")
        )
        if not is_transaction_runner_call:
            continue

        has_project_dir = any(kw.arg == "project_dir" for kw in node.keywords)
        if not has_project_dir:
            errors.append({
                "type": "MISSING_PROJECT_DIR_ARG",
                "detail": "TransactionRunner(...) instanciado sem 'project_dir='. "
                          "Ex: TransactionRunner(project_dir=project_dir, ...) dentro do bloco if __name__."
            })

    # Verifica se a instanciacao esta no escopo global do modulo (fora de qualquer funcao/if __main__)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            is_ctor = (
                (isinstance(func, ast.Name) and func.id == "TransactionRunner") or
                (isinstance(func, ast.Attribute) and func.attr == "TransactionRunner")
            )
            if is_ctor:
                errors.append({
                    "type": "RUNNER_INSTANTIATED_AT_MODULE_SCOPE",
                    "detail": "TransactionRunner(...) instanciado no escopo global do modulo, fora do bloco "
                              "'if __name__ == \"__main__\":'. Isso executa na importacao e quebra sem project_dir resolvido."
                })

    return errors


def _validate_project_dir_resolution(bot_code: str) -> List[Dict[str, Any]]:
    """
    Validacao AST: bot_producao.py sempre mora em '<test_dir>/code/', mas
    dataset_inicial.json, dicionario.json e plano_execucao.json ficam em
    '<test_dir>/' (um nivel acima). Se o codigo resolver project_dir como
    apenas o diretorio do proprio arquivo (ex: Path(__file__).parent ou
    os.path.dirname(os.path.abspath(__file__)) sem subir um nivel quando
    dentro de 'code/'), o runner nao encontra o dataset em runtime — um erro
    invisivel para dry run com mocks, so aparece rodando de verdade.
    """
    errors = []
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return []

    main_block = None
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                main_block = node
                break
    if main_block is None:
        return []

    for stmt in main_block.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "project_dir" for t in stmt.targets
        ):
            source = ast.get_source_segment(bot_code, stmt.value) or ""
            if "code" not in source:
                errors.append({
                    "type": "PROJECT_DIR_MISSING_CODE_FOLDER_CLIMB",
                    "detail": f"'project_dir = {source}' nao sobe da pasta 'code/' para o diretorio do teste. "
                              f"bot_producao.py sempre executa de dentro de '<test_dir>/code/', mas dataset_inicial.json "
                              f"fica em '<test_dir>/'. Use: "
                              f"current_dir = os.path.dirname(os.path.abspath(__file__)); "
                              f"project_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) == \"code\" else current_dir"
                })
            break

    return errors


def _validate_scenario_function_signature(bot_code: str) -> List[Dict[str, Any]]:
    """
    Validacao AST: garante que 'execute_scenario_default' tem a assinatura exata
    esperada pelo runner: (page, row, runner) — nessa ordem.

    O runner chama o callback posicionalmente como self.scenarios[scenario](page, row, self).
    Se a ordem dos parametros do bot divergir, os objetos ficam trocados dentro da funcao
    (ex: 'runner' vira Page, 'page' vira o dict row), causando AttributeError silencioso
    e confuso em runtime (ex: "'Page' object has no attribute 'fill_resilient'").
    """
    errors = []
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return []

    expected_order = ["page", "row", "runner"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "execute_scenario_default":
            continue

        param_names = [arg.arg for arg in node.args.args]

        if len(param_names) < 2:
            errors.append({
                "type": "INVALID_SCENARIO_SIGNATURE",
                "detail": f"'execute_scenario_default' tem {len(param_names)} parametro(s): {param_names}. "
                          f"Esperado: (page, row, runner) — o runner chama posicionalmente nessa ordem."
            })
            continue

        # Compara os primeiros N parametros com a ordem esperada (runner aceita 2 ou 3 params)
        actual_prefix = param_names[:len(expected_order)]
        expected_prefix = expected_order[:len(actual_prefix)]

        if actual_prefix != expected_prefix:
            errors.append({
                "type": "WRONG_SCENARIO_PARAM_ORDER",
                "found_order": param_names,
                "detail": f"'execute_scenario_default' declarado como ({', '.join(param_names)}), "
                          f"mas o runner chama o callback posicionalmente como (page, row, runner). "
                          f"A ordem dos parametros DEVE ser exatamente (page, row, runner), pois a chamada "
                          f"eh posicional e nomes trocados causam objetos trocados em runtime."
            })

    return errors


def _validate_aegis_imports(bot_code: str) -> List[Dict[str, Any]]:
    """
    Validacao AST: unico import permitido do namespace aegis_runner eh
    'from aegis_runner.runner import TransactionRunner'.

    O LLM nao tem visibilidade real do codigo-fonte do framework e recorrentemente
    aluciona modulos/simbolos que nao existem (ex: aegis_runner.utilities,
    aegis_runner.helpers, get_config, etc). Qualquer outro import de aegis_runner.*
    eh garantidamente uma alucinacao que quebra em ModuleNotFoundError/ImportError.
    """
    errors = []
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "aegis_runner.runner":
                names = [alias.name for alias in node.names]
                if names != ["TransactionRunner"]:
                    errors.append({
                        "type": "FORBIDDEN_AEGIS_IMPORT",
                        "detail": f"'from aegis_runner.runner import {', '.join(names)}' invalido. "
                                  f"Unico simbolo importavel de aegis_runner.runner eh 'TransactionRunner'."
                    })
            elif module.startswith("aegis_runner"):
                errors.append({
                    "type": "FORBIDDEN_AEGIS_IMPORT",
                    "detail": f"'from {module} import ...' invalido — modulo nao existe ou nao eh publico. "
                              f"Unico import permitido do framework eh "
                              f"'from aegis_runner.runner import TransactionRunner'."
                })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("aegis_runner") and alias.name != "aegis_runner.runner":
                    errors.append({
                        "type": "FORBIDDEN_AEGIS_IMPORT",
                        "detail": f"'import {alias.name}' invalido — modulo nao existe ou nao eh publico. "
                                  f"Unico import permitido do framework eh "
                                  f"'from aegis_runner.runner import TransactionRunner'."
                    })

    return errors


def validate_dataset_field_names(bot_code: str, dicionario_path: str) -> Dict[str, Any]:
    """
    Valida que toda chamada `row.get("campo", ...)` usa uma chave que realmente
    existe em dicionario.json.

    Motivo: o LLM alucina nomes de campo plausíveis (ex: 'email_acesso' em vez
    de 'email_login' do dicionário) — o bot roda sem lançar exceção, mas
    preenche string vazia silenciosamente em produção. Isso é um defeito
    "código-causado" tão grave quanto um erro de sintaxe, só que invisível
    para qualquer validação AST estrutural.
    """
    try:
        with open(dicionario_path, "r", encoding="utf-8") as f:
            dicionario = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"status": "PASS", "total_errors": 0, "errors": []}

    valid_fields = set(dicionario.get("fields", {}).keys())
    if not valid_fields:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    errors = []
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "row"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        field_name = node.args[0].value
        if field_name not in valid_fields and field_name not in seen:
            seen.add(field_name)
            errors.append({
                "type": "HALLUCINATED_DATASET_FIELD",
                "field": field_name,
                "detail": f"'row.get(\"{field_name}\", ...)' usa campo inexistente no dicionario.json. "
                          f"Campos validos: {sorted(valid_fields)}. Este nome foi provavelmente alucinado — "
                          f"use exatamente a chave do dicionario."
            })

    return {
        "status": "FAIL" if errors else "PASS",
        "total_errors": len(errors),
        "errors": errors
    }


def validate_resilience_patterns(bot_code: str, plan_path: str, dicionario_path: str) -> Dict[str, Any]:
    """
    Valida que o código usa os padrões de resiliência exigidos por cada passo
    do plano: click_chained/fill_chained quando há 'parent', select_option_resilient
    quando o passo é do tipo 'select', original_coords* quando há coords
    gravadas, e strategy="HUMAN_LIKE" (ou fill_human_like) quando o dicionário
    marca o campo como HUMAN_LIKE.

    Motivo: essas regras já existem no prompt/playbook, mas o LLM as ignora sem
    nenhuma validação mecânica pegando isso.
    """
    if not os.path.exists(plan_path):
        return {"status": "PASS", "total_errors": 0, "errors": []}

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    dicionario = {}
    if os.path.exists(dicionario_path):
        try:
            with open(dicionario_path, "r", encoding="utf-8") as f:
                dicionario = json.load(f)
        except json.JSONDecodeError:
            dicionario = {}

    human_like_selectors = {
        field.get("selector")
        for field in dicionario.get("fields", {}).values()
        if field.get("fill_strategy") == "HUMAN_LIKE"
    }

    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    calls_by_step: Dict[str, List[Dict[str, Any]]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method_name = node.func.attr
        if method_name not in RUNNER_METHODS:
            continue
        step_id = None
        kwargs: Dict[str, Any] = {}
        dict_kwargs = set()
        dict_contents: Dict[str, Dict[str, Any]] = {}
        for kw in node.keywords:
            if kw.arg is None:
                continue
            if kw.arg == "step_id" and isinstance(kw.value, ast.Constant):
                step_id = kw.value.value
            if isinstance(kw.value, ast.Constant):
                kwargs[kw.arg] = kw.value.value
            else:
                kwargs[kw.arg] = True
                if isinstance(kw.value, ast.Dict):
                    dict_kwargs.add(kw.arg)
                    literal_dict = {}
                    for dk, dv in zip(kw.value.keys, kw.value.values):
                        if isinstance(dk, ast.Constant) and isinstance(dv, ast.Constant):
                            literal_dict[dk.value] = dv.value
                    dict_contents[kw.arg] = literal_dict
        if step_id is None:
            continue
        calls_by_step.setdefault(step_id, []).append({
            "method": method_name, "kwargs": kwargs, "dict_kwargs": dict_kwargs, "dict_contents": dict_contents
        })

    def kwarg_present(step_id, method, kwarg_name):
        for call in calls_by_step.get(step_id, []):
            if call["method"] == method and kwarg_name in call["kwargs"]:
                return True
        return False

    def kwarg_is_dict_literal(step_id, method, kwarg_name):
        for call in calls_by_step.get(step_id, []):
            if call["method"] == method and kwarg_name in call["dict_kwargs"]:
                return True
        return False

    def kwarg_equals(step_id, methods, kwarg_name, value):
        for call in calls_by_step.get(step_id, []):
            if call["method"] in methods and call["kwargs"].get(kwarg_name) == value:
                return True
        return False

    def any_call(step_id, methods):
        return any(call["method"] in methods for call in calls_by_step.get(step_id, []))

    errors = []
    for step in plan.get("steps", []):
        step_id = step["step_id"]
        step_type = step.get("type")

        if step_type == "select":
            if not any_call(step_id, ("select_option_resilient",)):
                errors.append({
                    "type": "MISSING_SELECT_OPTION_RESILIENT",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' (dropdown '{step.get('dropdown_label', '')}' -> "
                              f"'{step.get('option_text', '')}') deve usar runner.select_option_resilient(...), "
                              f"não click_resilient separado para abridor e opção."
                })
                continue

            coords_trigger = step.get("coords_trigger")
            if coords_trigger and not kwarg_present(step_id, "select_option_resilient", "original_coords_trigger"):
                errors.append({
                    "type": "MISSING_ORIGINAL_COORDS",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' tem coordenadas gravadas do abridor do dropdown "
                              f"({coords_trigger}) e deve passar "
                              f"original_coords_trigger=({coords_trigger[0]}, {coords_trigger[1]}) "
                              f"em select_option_resilient(...) como fallback de self-healing."
                })

            coords_option = step.get("coords_option")
            if coords_option and not kwarg_present(step_id, "select_option_resilient", "original_coords_option"):
                errors.append({
                    "type": "MISSING_ORIGINAL_COORDS",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' tem coordenadas gravadas da opção do dropdown "
                              f"({coords_option}) e deve passar "
                              f"original_coords_option=({coords_option[0]}, {coords_option[1]}) "
                              f"em select_option_resilient(...) como fallback de self-healing."
                })
            continue

        parent = step.get("parent")
        if parent:
            chained_method = "click_chained" if step_type == "click" else "fill_chained"
            has_kwargs = kwarg_present(step_id, chained_method, "parent") and kwarg_present(step_id, chained_method, "child")
            if not has_kwargs:
                errors.append({
                    "type": "MISSING_CHAINED_LOCATOR",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' tem elemento pai identificado na gravação "
                              f"(parent='{parent.get('selector', '')}') e deve usar "
                              f"runner.{chained_method}(parent=..., child=..., ...) em vez de "
                              f"seletor absoluto direto."
                })
            elif not (kwarg_is_dict_literal(step_id, chained_method, "parent") and kwarg_is_dict_literal(step_id, chained_method, "child")):
                # click_chained/fill_chained chamam parent.get('selector')/child.get('selector')
                # internamente (runner.py:647-659) — se vier string em vez de dict, quebra em
                # runtime com AttributeError, e isso não é pego nem por AST superficial nem
                # pelo dry run (que usa runner fake sem essa lógica interna).
                errors.append({
                    "type": "INVALID_CHAINED_LOCATOR_SHAPE",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' chama runner.{chained_method}(...) mas parent=/child= "
                              f"devem ser dicts, ex.: parent={{'selector': '{parent.get('selector', '')}'}}, "
                              f"child={{'selector': '...'}} — não strings simples. "
                              f"({chained_method} chama parent.get('selector') internamente e quebra com string.)"
                })
            else:
                plan_has_text = parent.get("has_text")
                if plan_has_text:
                    code_parent_dict = {}
                    for call in calls_by_step.get(step_id, []):
                        if call["method"] == chained_method:
                            code_parent_dict = call.get("dict_contents", {}).get("parent", {})
                            break
                    code_has_text = code_parent_dict.get("has_text")
                    code_selector = code_parent_dict.get("selector") or ""
                    has_text_ok = (code_has_text == plan_has_text) or (plan_has_text in code_selector)
                    if not has_text_ok:
                        errors.append({
                            "type": "MISSING_PARENT_HAS_TEXT",
                            "step_id": step_id,
                            "detail": f"Passo '{step_id}' tem parent.has_text='{plan_has_text}' gravado no "
                                      f"plano (usado para distinguir entre múltiplos elementos que casam com "
                                      f"o seletor genérico do pai '{parent.get('selector', '')}'), mas a "
                                      f"chamada runner.{chained_method}(...) não aplica esse filtro — nem via "
                                      f"parent={{'selector': '{parent.get('selector', '')}', 'has_text': "
                                      f"'{plan_has_text}'}} nem embutindo o texto diretamente no seletor "
                                      f"(ex.: parent={{'selector': \"{parent.get('selector', '')}:has-text('{plan_has_text}')\"}}). "
                                      f"Sem esse filtro o robô pode interagir com o elemento errado quando "
                                      f"mais de um elemento casa com o seletor do pai."
                        })

        coords = step.get("coords")
        if coords:
            # original_coords só existe em click_resilient/click_chained/click_by_coordinates
            # — fill_resilient e fill_chained não têm esse parâmetro (runner.py:766,702),
            # e coords só é gravado para eventos "click" (sanitizer.py), então essa
            # checagem nunca precisa cobrir os métodos de fill.
            coord_ok = any(
                kwarg_present(step_id, m, "original_coords")
                for m in ("click_resilient", "click_chained", "click_by_coordinates")
            )
            if not coord_ok:
                errors.append({
                    "type": "MISSING_ORIGINAL_COORDS",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' tem coordenadas gravadas ({coords}) e deve passar "
                              f"original_coords=({coords[0]}, {coords[1]}) como fallback de self-healing."
                })

        if step_type == "fill" and step.get("selector") in human_like_selectors:
            human_like_ok = (
                kwarg_equals(step_id, ("fill_resilient", "fill_chained"), "strategy", "HUMAN_LIKE") or
                any_call(step_id, ("fill_human_like",))
            )
            if not human_like_ok:
                errors.append({
                    "type": "MISSING_HUMAN_LIKE_STRATEGY",
                    "step_id": step_id,
                    "detail": f"Passo '{step_id}' preenche campo com detecção anti-bot "
                              f"(keydown/keyup) segundo dicionario.json — deve usar "
                              f"strategy=\"HUMAN_LIKE\" ou runner.fill_human_like(...)."
                })

    return {
        "status": "FAIL" if errors else "PASS",
        "total_errors": len(errors),
        "errors": errors
    }


def validate_required_wait_patterns(bot_code: str, pending_corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Valida sincronizacoes assincronas pedidas explicitamente via
    correcoes_acumuladas.json (campo 'required_wait' em uma correcao pendente):
    exige um loop (for/while) ANTES da chamada do step_id alvo, referenciando
    o valor literal de bloqueio informado.

    Motivo: correcoes em prosa pedindo esse tipo de espera se mostraram
    reproduzivelmente ignoradas pela LLM (mesmo com temperature baixa e
    reformulacoes diferentes) — sem uma checagem mecanica, o Ralph Loop nao
    tem como saber que a correcao nao foi aplicada.

    Campo opcional 'must_reference' em required_wait: string literal adicional
    que tambem precisa aparecer dentro do MESMO loop. Motivo (achado
    reproduzido em producao): a checagem de 'blocking_value' sozinha pode ser
    satisfeita por um loop tecnicamente presente mas semanticamente inutil —
    ex.: 'while page.locator(<seletor do alvo final>).text_content() ==
    \"Avancar\":' nunca e verdadeiro (o alvo final nunca tem esse texto), entao
    o loop nunca executa, mas passa na checagem por conter o literal certo.
    'must_reference' forca o loop a tambem mencionar algo inequivoco do
    elemento correto (ex.: o seletor do botao que realmente carrega o valor de
    bloqueio), tornando muito mais dificil "enganar" o validador sem resolver
    o problema de fato.

    Campo opcional 'must_call' em required_wait: nome de metodo (ex.: "click")
    que precisa aparecer como chamada (obj.click(...)) DENTRO do mesmo loop.
    Motivo (2o achado reproduzido em producao, mesmo alvo do must_reference):
    mesmo referenciando o seletor certo, a LLM escreveu
    'while page.locator("#btn-next-step").text_content() == "Avancar":
    time.sleep(0.5)' — sem nenhum re-clique. Isso e uma espera passiva pura;
    quando o botao trava mostrando 'Avancar' de verdade (erro transitorio da
    API), esse loop nunca sai (loop infinito) porque nada torna a clicar nele.
    'must_call' fecha essa lacuna exigindo que o loop realmente EXECUTE uma
    acao de recuperacao (ex.: next_btn.click()), nao so observe passivamente.
    """
    requirements = [
        (c.get("step_id"), c["required_wait"])
        for c in pending_corrections
        if c.get("required_wait") and c.get("step_id")
    ]
    if not requirements:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    errors = []
    for step_id, wait_spec in requirements:
        blocking_value = wait_spec.get("blocking_value")
        must_reference = wait_spec.get("must_reference")
        must_references = [must_reference] if isinstance(must_reference, str) else (must_reference or [])
        must_call = wait_spec.get("must_call")

        target_lineno = None
        containing_func = None
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr not in RUNNER_METHODS:
                    continue
                has_step_id = any(
                    kw.arg == "step_id" and isinstance(kw.value, ast.Constant) and kw.value.value == step_id
                    for kw in node.keywords
                )
                if has_step_id:
                    target_lineno = node.lineno
                    containing_func = func
                    break
            if target_lineno is not None:
                break

        if target_lineno is None:
            continue  # step ausente já é coberto por outro validador (plano)

        # Resolve variaveis simples atribuidas a partir de locators (ex.:
        # `next_btn = page.locator("#btn-next-step")`) para os literais que
        # carregam. Sem isso, hoisting de locator (pratica de codigo boa e
        # comum) faz o literal ficar ANTES do loop, fora do subtree do AST do
        # loop, e o validador reporta falso-negativo mesmo com codigo correto.
        var_literals: Dict[str, List[str]] = {}
        for stmt in ast.walk(containing_func):
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                lits = [n.value for n in ast.walk(stmt.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                if lits:
                    var_literals.setdefault(stmt.targets[0].id, []).extend(lits)

        found_wait = False
        found_reference = not must_references
        found_call = not must_call
        best_refs_found = set()
        for node in ast.walk(containing_func):
            if not isinstance(node, (ast.For, ast.While)):
                continue
            if node.lineno >= target_lineno:
                continue
            has_blocking_value = False
            refs_found = set()
            has_call = not must_call
            for sub in ast.walk(node):
                literal_candidates = []
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    literal_candidates.append(sub.value)
                elif isinstance(sub, ast.Name) and sub.id in var_literals:
                    literal_candidates.extend(var_literals[sub.id])
                if any(val == blocking_value for val in literal_candidates):
                    has_blocking_value = True
                for val in literal_candidates:
                    for ref in must_references:
                        if ref in val:
                            refs_found.add(ref)
                if must_call and isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == must_call:
                    has_call = True
            has_reference = len(refs_found) == len(must_references)
            if has_blocking_value:
                best_refs_found |= refs_found
            if has_blocking_value and has_reference and has_call:
                found_wait = True
                found_reference = True
                found_call = True
                break
            if has_blocking_value:
                found_wait = True
                if has_reference:
                    found_reference = True
                if has_call:
                    found_call = True

        if not found_wait:
            errors.append({
                "type": "MISSING_ASYNC_WAIT_PATTERN",
                "step_id": step_id,
                "detail": f"Passo '{step_id}' precisa de um loop (for/while) IMEDIATAMENTE ANTES "
                          f"da chamada do passo, checando repetidamente (nao usar time.sleep fixo) "
                          f"ate o valor do campo deixar de ser igual a '{blocking_value}'. "
                          f"Esta instrucao ja foi fornecida e foi ignorada — adicione o loop de "
                          f"polling agora."
            })
        elif not found_reference:
            missing_refs = [r for r in must_references if r not in best_refs_found]
            errors.append({
                "type": "MISSING_ASYNC_WAIT_PATTERN",
                "step_id": step_id,
                "detail": f"Passo '{step_id}' tem um loop contendo '{blocking_value}', mas esse loop "
                          f"nao referencia TODOS os literais obrigatorios {must_references} (faltando: "
                          f"{missing_refs}) — ou seja, o loop provavelmente esta checando so o elemento "
                          f"ERRADO e/ou nao verifica se o elemento ALVO do proprio passo ja apareceu, "
                          f"fazendo a condicao de saida nunca corresponder ao estado real (ou sair cedo "
                          f"demais, antes do erro transitorio ter chance de ocorrer, ou nunca sair). "
                          f"Reescreva o loop para referenciar CADA UM destes literais dentro do mesmo "
                          f"loop: {must_references}."
            })
        elif not found_call:
            errors.append({
                "type": "MISSING_ASYNC_WAIT_PATTERN",
                "step_id": step_id,
                "detail": f"Passo '{step_id}' tem um loop referenciando {must_references} e "
                          f"'{blocking_value}', mas o loop nao chama '.{must_call}(...)' — ou seja, "
                          f"o loop so espera passivamente e nunca tenta se recuperar do estado de "
                          f"erro/travado (se o valor '{blocking_value}' voltar a aparecer por um erro "
                          f"transitorio, o loop nunca sai, pois nada re-executa a acao). Adicione uma "
                          f"chamada '.{must_call}(...)' no elemento de gatilho, DENTRO do loop, "
                          f"condicionada ao estado atual (ex.: clicar de novo somente se o elemento "
                          f"estiver habilitado e com o texto de bloqueio)."
            })

    return {
        "status": "FAIL" if errors else "PASS",
        "total_errors": len(errors),
        "errors": errors
    }


def validate_required_reopen_patterns(bot_code: str, pending_corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Valida re-disparos de campo exigidos explicitamente via correcoes_acumuladas.json
    (campo 'required_reopen' em uma correcao pendente): exige uma chamada
    (runner.fill_resilient/fill_chained/fill_human_like ou page.fill) referenciando
    o selector alvo, posicionada estritamente ENTRE a chamada de after_step_id e a
    chamada de step_id (o passo que depende do reabertura).

    Motivo: mesma classe de problema do required_wait — uma instrucao em prosa pedindo
    para "reabrir"/"re-disparar" um campo apos outro ser selecionado se mostrou
    reproduzivelmente perdida pela LLM em reescritas sucessivas do arquivo inteiro.
    Sem checagem mecanica, o Ralph Loop marca a correcao como aplicada mesmo quando
    o codigo gerado nunca reflete a exigencia.
    """
    requirements = [
        (c.get("step_id"), c["required_reopen"])
        for c in pending_corrections
        if c.get("required_reopen") and c.get("step_id")
    ]
    if not requirements:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    errors = []
    for step_id, reopen_spec in requirements:
        after_step_id = reopen_spec.get("after_step_id")
        selector = reopen_spec.get("selector")

        target_lineno = None
        after_lineno = None
        containing_func = None
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            local_target = None
            local_after = None
            for node in ast.walk(func):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr not in RUNNER_METHODS:
                    continue
                call_step_id = next(
                    (kw.value.value for kw in node.keywords
                     if kw.arg == "step_id" and isinstance(kw.value, ast.Constant)),
                    None
                )
                if call_step_id == step_id:
                    local_target = node.lineno
                elif call_step_id == after_step_id:
                    local_after = node.lineno
            if local_target is not None:
                target_lineno = local_target
                after_lineno = local_after
                containing_func = func
                break

        if target_lineno is None or after_lineno is None:
            continue  # passo ausente já é coberto por outro validador (plano)

        found_reopen = False
        for node in ast.walk(containing_func):
            if not isinstance(node, ast.Call):
                continue
            if not (after_lineno < node.lineno < target_lineno):
                continue
            for arg_node in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str) and selector in arg_node.value:
                    found_reopen = True
                    break
            if found_reopen:
                break

        if not found_reopen:
            errors.append({
                "type": "MISSING_REOPEN_PATTERN",
                "step_id": step_id,
                "detail": f"Passo '{step_id}' precisa de uma chamada (ex.: page.fill(...) ou "
                          f"runner.fill_resilient(...)) referenciando o seletor '{selector}' "
                          f"posicionada IMEDIATAMENTE ANTES da chamada do passo '{step_id}' e DEPOIS "
                          f"da chamada do passo '{after_step_id}', para forcar o campo a re-disparar "
                          f"seu autocomplete/validacao com o estado ja atualizado. Esta instrucao ja "
                          f"foi fornecida e foi ignorada — adicione a chamada de re-disparo agora, sem "
                          f"remover nem reordenar nenhuma chamada existente."
            })

    return {
        "status": "FAIL" if errors else "PASS",
        "total_errors": len(errors),
        "errors": errors
    }


def validate_required_method_patterns(bot_code: str, pending_corrections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Valida chamadas de metodo exigidas explicitamente via correcoes_acumuladas.json
    (campo 'required_method' em uma correcao pendente): exige que a chamada do
    step_id indicado use exatamente o metodo runner.<required_method>(...).

    Motivo: mesma classe de problema do required_wait/required_reopen — uma
    correcao em prosa (proposed_fix) pedindo para trocar o metodo/seletor de um
    passo (ex.: click_resilient num host de Shadow DOM fechado por
    click_by_coordinates) se mostrou reproduzivelmente perdida pela LLM em
    reescritas sucessivas do arquivo inteiro durante o Ralph Loop: nenhum
    validador estrutural pre-existente rejeita o metodo antigo (ele e
    sintaticamente valido, tem step_id, nao e alucinado), entao o loop converge
    e marca a correcao como "applied" mesmo quando o codigo gerado nunca
    reflete a exigencia.
    """
    requirements = [
        (c.get("step_id"), c["required_method"])
        for c in pending_corrections
        if c.get("required_method") and c.get("step_id")
    ]
    if not requirements:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    calls_by_step_id = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        call_step_id = next(
            (kw.value.value for kw in node.keywords
             if kw.arg == "step_id" and isinstance(kw.value, ast.Constant)),
            None
        )
        if call_step_id:
            calls_by_step_id[call_step_id] = node.func.attr

    errors = []
    for step_id, required_method in requirements:
        actual_method = calls_by_step_id.get(step_id)
        if actual_method is None:
            continue  # passo ausente já é coberto por outro validador (plano)
        if actual_method != required_method:
            errors.append({
                "type": "MISSING_REQUIRED_METHOD",
                "step_id": step_id,
                "detail": f"Passo '{step_id}' precisa chamar runner.{required_method}(...), mas o "
                          f"código gerado usa runner.{actual_method}(...) em vez disso. Esta troca de "
                          f"método já foi solicitada explicitamente numa correção anterior e foi "
                          f"ignorada — substitua a chamada de '{step_id}' por runner.{required_method}(...) "
                          f"agora, sem alterar nenhum outro passo."
            })

    return {
        "status": "FAIL" if errors else "PASS",
        "total_errors": len(errors),
        "errors": errors
    }


def _extract_step_id_from_stmt(stmt: ast.stmt) -> Optional[str]:
    """Retorna o step_id (string) de qualquer chamada runner.<metodo>(..., step_id="stX") dentro do statement."""
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            for kw in node.keywords:
                if kw.arg == "step_id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    return kw.value.value
    return None


def reorder_steps_to_match_plan(bot_code: str, planned_ids: List[str]) -> str:
    """
    Reordena FISICAMENTE os blocos de statement (comentário + chamada) dentro de
    'execute_scenario_default' para bater com a ordem exata do plano.

    Motivo: o LLM embaralha a ordem dos step_ids recorrentemente mesmo com
    instrução explícita no prompt (falha de compliance observada em produção,
    30+ tentativas sem convergir). Confiar no LLM para uma tarefa puramente
    mecânica (ordenação) é frágil — corrigimos deterministicamente via AST.

    Estratégia conservadora: agrupa statements de nível superior em blocos,
    onde cada bloco termina no primeiro statement que contém um step_id
    identificável (statements auxiliares sem step_id, ex: `cpf_atual = ...`
    lido antes de um `if`, são anexados ao bloco do próximo step_id — eles
    fazem parte da lógica daquele passo). Se sobrarem statements finais sem
    nenhum step_id associável, aborta sem alterar nada — não arrisca
    corromper lógica que não entendemos.
    """
    try:
        tree = ast.parse(bot_code)
    except SyntaxError:
        return bot_code

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute_scenario_default":
            func_node = node
            break
    if func_node is None or not func_node.body:
        return bot_code

    body = func_node.body
    start_idx = 0
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        start_idx = 1

    step_stmts = body[start_idx:]
    if not step_stmts:
        return bot_code

    # Agrupa: statements sem step_id se anexam ao proximo statement que tiver um.
    groups = []
    pending = []
    for stmt in step_stmts:
        sid = _extract_step_id_from_stmt(stmt)
        pending.append(stmt)
        if sid is not None:
            groups.append({"step_id": sid, "stmts": pending})
            pending = []
    if pending:
        # statements finais sem step_id associavel — nao sabemos onde eles pertencem.
        return bot_code

    step_ids = [g["step_id"] for g in groups]
    target_order = sorted(step_ids, key=lambda s: (planned_ids.index(s) if s in planned_ids else 1_000_000))
    if step_ids == target_order:
        return bot_code

    lines = bot_code.split("\n")

    blocks = []
    for g in groups:
        first_stmt = g["stmts"][0]
        last_stmt = g["stmts"][-1]
        stmt_start_line = first_stmt.lineno  # 1-based
        stmt_end_line = last_stmt.end_lineno  # 1-based inclusive

        # Anexa comentarios contiguos imediatamente acima do bloco (ex: "# [PASSO X] ...")
        idx = stmt_start_line - 2  # 0-based index da linha logo acima do statement
        block_start_idx = stmt_start_line - 1  # 0-based, default: statement começa em si mesmo
        while idx >= 0 and lines[idx].strip().startswith("#"):
            block_start_idx = idx
            idx -= 1

        block_text = "\n".join(lines[block_start_idx:stmt_end_line])
        blocks.append({"step_id": g["step_id"], "start": block_start_idx, "end": stmt_end_line, "text": block_text})

    overall_start = min(b["start"] for b in blocks)
    overall_end = max(b["end"] for b in blocks)

    def sort_key(b):
        try:
            return planned_ids.index(b["step_id"])
        except ValueError:
            return 1_000_000

    sorted_blocks = sorted(blocks, key=sort_key)
    new_body_text = "\n".join(b["text"] for b in sorted_blocks)

    new_lines = lines[:overall_start] + new_body_text.split("\n") + lines[overall_end:]
    reordered_code = "\n".join(new_lines)

    # Só aceita o resultado se ainda for Python válido — caso contrário, aborta com seguranca.
    try:
        ast.parse(reordered_code)
    except SyntaxError:
        return bot_code

    return reordered_code


def dry_run_bot(bot_code: str, project_root: str, timeout: int = 30, dataset_dir: str = None) -> Dict[str, Any]:
    """
    Executa 'execute_scenario_default' em sandbox isolado (subprocess), com
    TransactionRunner e Page mockados, para pegar QUALQUER erro em tempo de
    execucao que a analise estatica (AST) nao cobre: NameError de variavel
    inexistente, AttributeError de metodo alucinado, TypeError de assinatura
    errada, FileNotFoundError de leitura de arquivo hardcoded, etc.

    Isso fecha a classe inteira de "alucinacao do LLM" sem precisar catalogar
    cada erro especifico manualmente — se o codigo faz algo que nao existe,
    o dry run estoura o erro real do Python.

    NAO abre browser real nem executa runner.run() — chama so a funcao de
    cenario com objetos fake, entao eh rapido (~1-2s) e seguro para rodar
    a cada tentativa do Ralph Loop.
    """
    import subprocess
    import sys as _sys

    # Usa a primeira linha real do dataset em vez de {{}} — row.get(...) com
    # dict vazio sempre retorna "" e nunca exercita datetime.strptime/regex/
    # conversoes que so quebram com um valor de verdade (bug real ja visto
    # em producao: strptime("03/07/2026", "%Y-%m-%d") so falha com dado real).
    real_row = {}
    if dataset_dir:
        for fname in ("dataset_inicial.json",):
            fpath = os.path.join(dataset_dir, fname)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        rows = json.load(f)
                    if isinstance(rows, list) and rows:
                        real_row = rows[0]
                except (OSError, json.JSONDecodeError):
                    pass
                break

    harness = f'''
import sys
sys.path.insert(0, {project_root!r})

from unittest.mock import MagicMock

class _FakeRunner:
    def __getattr__(self, name):
        return MagicMock(return_value=True)
    # Assinaturas reais (nao *a, **kw) para pegar kwargs alucinados
    # (ex: scenario_id= em vez de scenario_name=) que so aparecem
    # dentro do bloco "if __name__ == '__main__':" do bot.
    def register_scenario(self, scenario_name, callback):
        pass
    def run(self, url=None, headless=True, slow_mo=50, channel="msedge"):
        pass
    def click_resilient(self, page, selector, target_description, timeout=5000, validate_navigation=False, original_coords=None, step_id=None):
        return True
    def fill_resilient(self, page, selector, text_val, target_description, strategy="DIRECT", delay_ms=60, timeout=5000, step_id=None):
        return True
    def fill_human_like(self, page, selector, text_val, target_description=None, delay_ms=60, timeout=5000, step_id=None):
        return True
    def select_option_resilient(self, page, dropdown_label, option_text, original_coords_trigger=None, original_coords_option=None, timeout=5000, step_id=None):
        return True
    def click_chained(self, page, parent, child, target_description, timeout=5000, original_coords=None, step_id=None):
        return True
    def fill_chained(self, page, parent, child, text_val, target_description, strategy="DIRECT", delay_ms=60, timeout=5000, step_id=None):
        return True
    def wait_for_selector(self, page, selector, state="visible", timeout=10000, target_description=None):
        return True

import aegis_runner.runner as _rm

def _fake_transaction_runner(*a, project_dir=None, **kw):
    if project_dir is None and not a:
        raise TypeError("TransactionRunner requer 'project_dir' (obrigatorio no SDK real)")
    return _FakeRunner()

_rm.TransactionRunner = _fake_transaction_runner

bot_ns = {{"__name__": "__aegis_dry_run__", "__file__": {os.path.join(project_root, "bot_producao.py")!r}}}
bot_source = {bot_code!r}

try:
    exec(compile(bot_source, "bot_producao.py", "exec"), bot_ns)
except Exception as e:
    print("DRYRUN_IMPORT_ERROR::" + type(e).__name__ + "::" + str(e))
    sys.exit(1)

fn = bot_ns.get("execute_scenario_default")
if fn is None:
    print("DRYRUN_ERROR::MISSING_ENTRYPOINT::execute_scenario_default nao definida")
    sys.exit(1)

fake_page = MagicMock()
fake_row = {real_row!r}
fake_runner = _FakeRunner()

try:
    fn(fake_page, fake_row, fake_runner)
except Exception as e:
    print("DRYRUN_RUNTIME_ERROR::" + type(e).__name__ + "::" + str(e))
    sys.exit(1)

# Executa tambem o bloco de entry point (if __name__ == "__main__") para
# pegar kwargs alucinados em register_scenario()/TransactionRunner()/run()
# que só existem nesse bloco e nunca rodariam so testando a funcao de cenario.
main_block_src = bot_source.replace('if __name__ == "__main__":', "if True:", 1).replace(
    "if __name__ == '__main__':", "if True:", 1
)
try:
    exec(compile(main_block_src, "bot_producao.py", "exec"), dict(bot_ns))
except Exception as e:
    print("DRYRUN_RUNTIME_ERROR::" + type(e).__name__ + "::" + str(e))
    sys.exit(1)

print("DRYRUN_OK")
'''

    # Harness vai pra um arquivo temporário em vez de "-c harness": bots grandes
    # (ex.: 90+ passos) fazem o comando ultrapassar o limite de linha de comando
    # do CreateProcess no Windows (WinError 206 - nome de arquivo/comando muito
    # grande), quebrando o dry run de forma totalmente não relacionada ao
    # conteúdo do bot.
    import tempfile
    harness_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(harness)
            harness_path = tmp.name

        try:
            result = subprocess.run(
                [_sys.executable, harness_path],
                capture_output=True, text=True, timeout=timeout, cwd=project_root
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "FAIL",
                "total_errors": 1,
                "errors": [{
                    "type": "DRYRUN_TIMEOUT",
                    "detail": f"Dry run excedeu {timeout}s — possível loop infinito ou I/O bloqueante no bot."
                }]
            }
    finally:
        if harness_path and os.path.exists(harness_path):
            os.remove(harness_path)

    output = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if "DRYRUN_OK" in output:
        return {"status": "PASS", "total_errors": 0, "errors": []}

    last_line = output.splitlines()[-1] if output else ""
    if "::" in last_line:
        parts = last_line.split("::", 2)
        tag, exc_type, exc_msg = (parts + ["", "", ""])[:3]

        # TypeError de kwarg errado em register_scenario/run nao diz qual e a
        # assinatura certa — sem isso o LLM fica repetindo o mesmo erro (visto
        # em producao: 10 tentativas seguidas com o mesmo kwarg invalido).
        hint = ""
        if "register_scenario" in exc_msg and "unexpected keyword argument" in exc_msg:
            hint = " Assinatura correta: runner.register_scenario(scenario_name=\"default\", callback=execute_scenario_default) — apenas esses 2 parametros existem."
        elif exc_type == "TypeError" and "_FakeRunner.run(" in exc_msg and "unexpected keyword argument" in exc_msg:
            hint = " Assinatura correta: runner.run(url=None, headless=True, slow_mo=50, channel=\"msedge\")."
        elif "unexpected keyword argument" in exc_msg and "TransactionRunner" in exc_msg:
            hint = " Assinatura correta: TransactionRunner(project_dir=project_dir) — apenas project_dir e aceito."
        elif "unexpected keyword argument" in exc_msg and "fill_resilient" in exc_msg:
            hint = " Assinatura correta: runner.fill_resilient(page, selector, text_val, target_description, strategy=\"DIRECT\", delay_ms=60, timeout=5000, step_id=None). Nao existe 'original_coords_selector' nem 'original_coords' neste metodo."
        elif "unexpected keyword argument" in exc_msg and "click_resilient" in exc_msg:
            hint = " Assinatura correta: runner.click_resilient(page, selector, target_description, timeout=5000, validate_navigation=False, original_coords=None, step_id=None)."
        elif "unexpected keyword argument" in exc_msg and "select_option_resilient" in exc_msg:
            hint = " Assinatura correta: runner.select_option_resilient(page, dropdown_label, option_text, original_coords_trigger=None, original_coords_option=None, timeout=5000, step_id=None)."

        return {
            "status": "FAIL",
            "total_errors": 1,
            "errors": [{
                "type": tag.replace("DRYRUN_", "DRYRUN_") or "DRYRUN_UNKNOWN_ERROR",
                "exception_type": exc_type,
                "detail": f"{exc_type}: {exc_msg}{hint} (detectado em execução sandbox real, não análise estática)"
            }]
        }

    return {
        "status": "FAIL",
        "total_errors": 1,
        "errors": [{
            "type": "DRYRUN_UNKNOWN_FAILURE",
            "detail": f"Dry run falhou sem output esperado. stdout={output!r} stderr={stderr[-500:]!r}"
        }]
    }


def _self_test() -> None:
    """
    Smoke test executado no import do módulo: garante que os validadores
    rodam sem exceções internas (NameError, AttributeError, typos) antes
    de serem usados pelo Ralph Loop em produção.
    """
    dummy_bot = '''
from aegis_runner.runner import TransactionRunner

def execute_scenario_default(page, row, runner):
    runner.fill_resilient(page, selector="#x", text_val=row.get("y", ""), target_description="t", step_id="st_001")
    runner.click_resilient(page, selector="#z", target_description="t", step_id="st_002")

if __name__ == "__main__":
    runner = TransactionRunner(project_dir=".")
    runner.register_scenario("default", execute_scenario_default)
    runner.run()
'''
    dummy_plan = {"steps": [{"step_id": "st_001"}, {"step_id": "st_002"}]}

    try:
        struct_result = validate_bot_structure(dummy_bot)
        assert struct_result["status"] == "PASS", f"validate_bot_structure self-test falhou: {struct_result['errors']}"

        code_ids = extract_step_ids_from_code(dummy_bot)
        assert code_ids == ["st_001", "st_002"], f"extract_step_ids_from_code self-test falhou: {code_ids}"

        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(dummy_plan, f)
            tmp_path = f.name
        try:
            plan_result = validate_bot_against_plan(dummy_bot, tmp_path)
            assert plan_result["status"] == "PASS", f"validate_bot_against_plan self-test falhou: {plan_result['errors']}"
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise RuntimeError(
            f"[STEP_VALIDATOR SELF-TEST FALHOU] Bug interno detectado em step_validator.py: {e}. "
            f"O Ralph Loop não pode ser confiável até este bug ser corrigido."
        ) from e


_self_test()
