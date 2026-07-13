"""
aegis_code_generator/deterministic_emitter.py

Emissores puros do motor de geração híbrido do Code Generator (Fase 4).
Ver `.specs/plano-codegen-hibrido-deterministico.md` (Seções 2.1 e 3.2).

Cada `_emit_*` espelha o check correspondente de
`step_validator.validate_resilience_patterns` (aegis_code_generator/step_validator.py:774)
no sentido contrário: em vez de COBRAR o padrão de resiliência exigido para um
step, o emissor PRODUZ o código que já satisfaz esse padrão por construção.

Escopo desta tarefa (H1 do plano): SOMENTE os emissores puros e
`emit_step_block`. `classify_step`, `build_skeleton` e o manifest de
proveniência são de uma tarefa posterior (H2) e não existem aqui.

Convenções de formatação:
- Toda string literal Python emitida usa `json.dumps(..., ensure_ascii=False)`
  — sempre aspas duplas, nunca aspas simples. Isso importa em particular para
  `step_id="..."`: `code_generator.py:1127` (`_STEP_ID_IN_BLOCK_RE`) exige
  literalmente aspas duplas ao redor do valor para reconhecer a âncora do
  bloco no fluxo de correção cirúrgica — `repr()` produziria aspas simples
  para a maioria dos valores e quebraria esse regex silenciosamente.
- Todo bloco emitido começa com o comentário-âncora `# [PASSO N] <descrição>`
  — `code_generator.py:1126` (`_STEP_ANCHOR_RE`) exige literalmente
  `# [PASSO ...]`. `N` é derivado do sufixo numérico do `step_id` (ex.:
  "st_023" -> 23); a numeração sequencial "oficial" do arquivo inteiro é
  responsabilidade de `build_skeleton` (tarefa futura), que pode renumerar a
  âncora por cima sem depender de nada deste módulo.
- Os emissores de chamada (`_emit_click`/`_emit_fill`/`_emit_select`/
  `_emit_select_native`) retornam texto "cru", relativo à coluna 0 (a própria
  chamada começa em `runner.metodo(` sem indentação, e os argumentos
  seguintes usam 4 espaços a mais). `emit_step_block` é o único responsável
  por aplicar a indentação final (nível de corpo de função) e por embrulhar
  em `try/except` quando o step é `optional` — isso mantém cada emissor
  testável isoladamente sem premissas sobre onde o bloco vai parar.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Helpers de formatação (privados)
# ---------------------------------------------------------------------------

def _fmt_str(value: Optional[str]) -> str:
    """
    Formata `value` como literal de string Python válido, sempre com aspas
    duplas (nunca aspas simples) — contrato exigido por `step_id="..."` (ver
    docstring do módulo). `None` vira o literal `None` (sem aspas).
    """
    if value is None:
        return "None"
    return json.dumps(str(value), ensure_ascii=False)


def _fmt_coords(coords) -> str:
    """Formata um par (x, y) gravado no plano como tupla Python literal."""
    x, y = coords[0], coords[1]
    return f"({x!r}, {y!r})"


def _fmt_parent_dict(parent: Dict[str, Any]) -> str:
    """
    Formata o dict `parent` no shape exigido por click_chained/fill_chained
    (runner.py:1628-1646, 1696-1716) — sempre com as chaves 'selector' e
    'has_text' (mesmo quando has_text é None), espelhando o formato usado
    pelo bot de referência (bot_producao.py:46: parent={"selector": "#app",
    "has_text": None}).
    """
    selector = parent.get("selector", "")
    has_text = parent.get("has_text")
    return f'{{"selector": {_fmt_str(selector)}, "has_text": {_fmt_str(has_text)}}}'


def _fmt_child_dict(selector: str) -> str:
    """Formata o dict `child` — sempre só a chave 'selector'."""
    return f'{{"selector": {_fmt_str(selector)}}}'


_STEP_NUM_RE = re.compile(r"(\d+)$")


def _step_number(step_id: str) -> str:
    """
    Deriva o número exibido em '# [PASSO N]' a partir do sufixo numérico do
    step_id (ex.: 'st_023' -> '23', 'sup_003' -> '3'). Sem dígitos, cai de
    volta para o próprio step_id.
    """
    match = _STEP_NUM_RE.search(step_id or "")
    if match:
        return str(int(match.group(1)))
    return step_id or "?"


def _indent_block(text: str, spaces: int) -> str:
    """Aplica `spaces` de indentação a cada linha não-vazia de `text`."""
    prefix = " " * spaces
    return "\n".join((prefix + line) if line.strip() else line for line in text.split("\n"))


def _apply_has_text_anchor(selector: str, text: Optional[str]) -> str:
    """
    Compõe `selector:has-text('texto')` — a forma de ancoragem mecânica que
    `WEAK_SELECTOR_WITHOUT_ANCHOR` aceita (step_validator.py:1048,
    verificado contra test_weak_selector_enforcement.py). O texto é
    normalizado (espaços/quebras de linha colapsados) e aspas simples
    internas são escapadas para não fechar o `:has-text(...)` prematuramente.
    """
    normalized = " ".join(str(text or "").split())
    escaped = normalized.replace("'", "\\'")
    return f"{selector}:has-text('{escaped}')"


# ---------------------------------------------------------------------------
# Resolução de binding step -> chave semântica do dicionário
# ---------------------------------------------------------------------------

def _find_field_by_selector(dicionario: Optional[Dict[str, Any]], selector: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Procura em dicionario['fields'] o field cujo 'selector' casa
    exatamente com `selector`. Retorna uma cópia do field com a chave
    semântica anexada em 'semantic_key' (os fields do dicionario.json não
    carregam a própria chave — ela só existe como chave do dict `fields`).
    """
    if not selector or not dicionario:
        return None
    fields = dicionario.get("fields", {}) or {}
    for key, field in fields.items():
        if field.get("selector") == selector:
            resolved = dict(field)
            resolved["semantic_key"] = key
            return resolved
    return None


def _resolve_field_for_fill_or_select_native(step: Dict[str, Any], dicionario: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Binding de 'fill' e 'select_native': fields[*].selector == step.selector,
    com fallback para step.selector_original (achado R1 da revisão do plano —
    select_native nasce de um evento 'fill' em <select>, sanitizer.py:1469-
    1471, e carrega 'selector' normal, NUNCA 'trigger_selector').
    """
    field = _find_field_by_selector(dicionario, step.get("selector"))
    if field is None:
        field = _find_field_by_selector(dicionario, step.get("selector_original"))
    return field


def _resolve_field_for_select(step: Dict[str, Any], dicionario: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Binding de 'select' (dropdown customizado/composite): fields[*].selector
    == step.trigger_selector — os steps 'select' reais têm 'selector': ""
    (achado I2 da revisão do plano).
    """
    return _find_field_by_selector(dicionario, step.get("trigger_selector"))


# ---------------------------------------------------------------------------
# Emissores por tipo
# ---------------------------------------------------------------------------

def _emit_click(step: Dict[str, Any]) -> str:
    """
    Emite `runner.click_resilient(...)` ou, se o step tem 'parent',
    `runner.click_chained(parent={...}, child={...}, ...)`. Inclui
    `original_coords=...` quando o step tem 'coords' gravadas. Quando o step
    é `weak_selector` e não há `parent.has_text` para ancorar, mas há um
    campo 'text' do step, compõe `:has-text(...)` no seletor operacional
    (child, se houver parent, senão o seletor direto).
    """
    step_id = step["step_id"]
    description = step.get("description", "")
    selector = step.get("selector", "")
    parent = step.get("parent")
    coords = step.get("coords")
    weak_selector = bool(step.get("weak_selector"))
    text = step.get("text")

    if parent:
        parent_has_text = parent.get("has_text")
        child_selector = selector
        if weak_selector and not parent_has_text and text and ":has-text(" not in child_selector:
            child_selector = _apply_has_text_anchor(child_selector, text)

        lines = [
            "runner.click_chained(",
            "    page,",
            f"    parent={_fmt_parent_dict(parent)},",
            f"    child={_fmt_child_dict(child_selector)},",
            f"    target_description={_fmt_str(description)},",
        ]
        if coords:
            lines.append(f"    original_coords={_fmt_coords(coords)},")
        lines.append(f"    step_id={_fmt_str(step_id)}")
        lines.append(")")
        return "\n".join(lines)

    final_selector = selector
    if weak_selector and text and ":has-text(" not in final_selector:
        final_selector = _apply_has_text_anchor(final_selector, text)

    lines = [
        "runner.click_resilient(",
        "    page,",
        f"    selector={_fmt_str(final_selector)},",
        f"    target_description={_fmt_str(description)},",
    ]
    if coords:
        lines.append(f"    original_coords={_fmt_coords(coords)},")
    lines.append(f"    step_id={_fmt_str(step_id)}")
    lines.append(")")
    return "\n".join(lines)


def _emit_fill(step: Dict[str, Any], field: Optional[Dict[str, Any]]) -> str:
    """
    Emite `runner.fill_resilient(...)` ou, se o step tem 'parent',
    `runner.fill_chained(parent={...}, child={...}, ...)`. `text_val` sempre
    resolve para `row.get("<chave>", "")` — `field` já vem resolvido pelo
    chamador (ver `_resolve_field_for_fill_or_select_native`); NUNCA um
    literal do plano. `strategy` é "HUMAN_LIKE" quando
    `field.get('fill_strategy') == 'HUMAN_LIKE'`, senão "DIRECT" — datas
    passam o valor de `row` direto, sem conversão (default seguro por
    construção, nenhum tratamento especial necessário aqui).
    """
    step_id = step["step_id"]
    description = step.get("description", "")
    selector = step.get("selector", "")
    parent = step.get("parent")
    key = (field or {}).get("semantic_key", "")
    strategy = "HUMAN_LIKE" if (field or {}).get("fill_strategy") == "HUMAN_LIKE" else "DIRECT"
    text_val_expr = f'row.get({_fmt_str(key)}, "")'

    if parent:
        lines = [
            "runner.fill_chained(",
            "    page,",
            f"    parent={_fmt_parent_dict(parent)},",
            f"    child={_fmt_child_dict(selector)},",
            f"    text_val={text_val_expr},",
            f"    target_description={_fmt_str(description)},",
            f'    strategy="{strategy}",',
            f"    step_id={_fmt_str(step_id)}",
            ")",
        ]
        return "\n".join(lines)

    lines = [
        "runner.fill_resilient(",
        "    page,",
        f"    selector={_fmt_str(selector)},",
        f"    text_val={text_val_expr},",
        f"    target_description={_fmt_str(description)},",
        f'    strategy="{strategy}",',
        f"    step_id={_fmt_str(step_id)}",
        ")",
    ]
    return "\n".join(lines)


def _emit_select(step: Dict[str, Any], field: Optional[Dict[str, Any]]) -> str:
    """
    Emite `runner.select_option_resilient(...)` (dropdown customizado). O
    `option_text` sempre resolve para `row.get("<chave>", "")` — a chave vem
    do binding via `trigger_selector` (ver `_resolve_field_for_select`);
    literal do plano NUNCA é aceitável aqui (mesma proibição de hoje). Inclui
    `original_coords_trigger`/`original_coords_option` quando presentes no
    step.
    """
    step_id = step["step_id"]
    dropdown_label = step.get("dropdown_label", "")
    key = (field or {}).get("semantic_key", "")
    option_text_expr = f'row.get({_fmt_str(key)}, "")'
    coords_trigger = step.get("coords_trigger")
    coords_option = step.get("coords_option")

    lines = [
        "runner.select_option_resilient(",
        "    page,",
        f"    dropdown_label={_fmt_str(dropdown_label)},",
        f"    option_text={option_text_expr},",
    ]
    if coords_trigger:
        lines.append(f"    original_coords_trigger={_fmt_coords(coords_trigger)},")
    if coords_option:
        lines.append(f"    original_coords_option={_fmt_coords(coords_option)},")
    lines.append(f"    step_id={_fmt_str(step_id)}")
    lines.append(")")
    return "\n".join(lines)


def _emit_select_native(step: Dict[str, Any], field: Optional[Dict[str, Any]]) -> str:
    """
    Emite `runner.select_option_native_resilient(...)` (elemento <select>
    HTML nativo). Mesma regra de `option_text` de `_emit_select` — chave via
    dicionário, nunca literal.
    """
    step_id = step["step_id"]
    description = step.get("description", "")
    selector = step.get("selector", "")
    key = (field or {}).get("semantic_key", "")
    option_text_expr = f'row.get({_fmt_str(key)}, "")'

    lines = [
        "runner.select_option_native_resilient(",
        "    page,",
        f"    selector={_fmt_str(selector)},",
        f"    option_text={option_text_expr},",
        f"    target_description={_fmt_str(description)},",
        f"    step_id={_fmt_str(step_id)}",
        ")",
    ]
    return "\n".join(lines)


_ASYNC_GUARD_KEY_RE = re.compile(r"cpf|cnpj|cep", re.IGNORECASE)


def _emit_async_guard(step: Dict[str, Any], field: Optional[Dict[str, Any]]) -> str:
    """
    Retorna uma linha `time.sleep(2.0)` (para ser emitida logo após o fill)
    quando a chave semântica do field casa a heurística determinística de
    campo com validação assíncrona (CPF/CNPJ/CEP — mesma regra da regra 8 do
    prompt atual). Retorna string vazia caso contrário ou se não há field
    resolvido.
    """
    if not field:
        return ""
    key = field.get("semantic_key", "") or ""
    if _ASYNC_GUARD_KEY_RE.search(key):
        return "time.sleep(2.0)  # Aguarda validação assíncrona do campo"
    return ""


def _emit_optional_wrapper(inner: str, step: Dict[str, Any]) -> str:
    """
    Envelopa `inner` (uma ou mais chamadas runner, já relativas à coluna 0)
    em um bloco try/except não-fatal — template canônico da Seção 3.2 do
    plano. O `except` SEMPRE imprime o erro (nunca falha silenciosamente).
    """
    step_id = step["step_id"]
    indented_inner = _indent_block(inner, 4)
    return (
        "try:\n"
        f"{indented_inner}\n"
        "except Exception as _opt_err:\n"
        f'    print(f"[BOT] Passo opcional {step_id} pulado (não-fatal): {{_opt_err}}")'
    )


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def emit_step_block(step: Dict[str, Any], dicionario: Optional[Dict[str, Any]]) -> str:
    """
    Orquestra a emissão do bloco completo de um step: resolve o field (para
    fill/select_native/select), despacha para o emissor do tipo, aplica
    `_emit_async_guard` (só para 'fill') e, se `execution_hint == 'optional'`,
    o wrapper try/except. Todo bloco começa com o comentário-âncora
    `# [PASSO N] <descrição>` e é retornado já indentado ao nível de corpo de
    função (4 espaços).
    """
    step_type = step.get("type")
    step_id = step["step_id"]
    description = step.get("description", "")

    field: Optional[Dict[str, Any]] = None

    if step_type == "click":
        inner = _emit_click(step)
    elif step_type == "fill":
        field = _resolve_field_for_fill_or_select_native(step, dicionario)
        inner = _emit_fill(step, field)
    elif step_type == "select_native":
        field = _resolve_field_for_fill_or_select_native(step, dicionario)
        inner = _emit_select_native(step, field)
    elif step_type == "select":
        field = _resolve_field_for_select(step, dicionario)
        inner = _emit_select(step, field)
    else:
        raise ValueError(
            f"Tipo de step '{step_type}' (step_id={step_id!r}) não é suportado pelo "
            f"emissor determinístico — este step nunca deveria chegar a emit_step_block "
            f"(classify_step deveria tê-lo marcado 'cognitive')."
        )

    body = inner
    if step_type == "fill":
        async_guard = _emit_async_guard(step, field)
        if async_guard:
            body = f"{inner}\n{async_guard}"

    if step.get("execution_hint") == "optional":
        body = _emit_optional_wrapper(body, step)

    anchor = f"# [PASSO {_step_number(step_id)}] {description}"
    full_block = f"{anchor}\n{body}"
    return _indent_block(full_block, 4)


# ---------------------------------------------------------------------------
# Linha de corte determinístico x cognitivo (H2 do plano — Seção 2.2)
# ---------------------------------------------------------------------------
#
# `classify_step` decide, POR STEP, se `build_skeleton` pode emitir o bloco
# via `emit_step_block` (deterministic), se precisa de um placeholder
# cognitivo pra LLM preencher depois (cognitive), ou se o step nunca vira
# código nenhum (omit — contrato v2 vigente pra `sup_`/`skip`).
#
# Política conservadora (Seção 2.2 do plano): TODAS as condições C1-C10
# precisam valer para 'deterministic'; qualquer dúvida cai para 'cognitive'.
# Isso nunca regride vs. hoje (hoje é 100% LLM) — só reduz o volume de
# chamadas.


class EmissionDecision(NamedTuple):
    kind: str  # "deterministic" | "cognitive" | "omit"
    reason: str  # log/manifest — por que caiu nessa rota


_SUPPORTED_TYPES = {"click", "fill", "select", "select_native"}

# C6 — heurística do Padrão N (menu suspenso): seletores que casam esses
# tokens exigem reescrita em seletor composto `>>` (julgamento, não mecânico).
_MENU_HEURISTIC_RE = re.compile(r"\.sub-menu|\.dropdown-menu|#menu-item-")

# C9 — heurística de painel de opção dinâmica/autocomplete (achado I1 da
# rodada 2 do plano: a forma real é fill -> CLICK no painel, não fill -> select).
_AUTOCOMPLETE_HEURISTIC_RE = re.compile(
    r"autocomplete|mat-option|\[role='option'\]|#mat-autocomplete-panel-|listbox",
    re.IGNORECASE,
)

# C10 — extrai o(s) literal(is) dentro de `:has-text('...')`/`:has-text("...")`
# de um seletor. Aceita aspas simples ou duplas; `\.` cobre o apóstrofo
# escapado que `_apply_has_text_anchor` produz (`\\'`).
_HAS_TEXT_LITERAL_RE = re.compile(r":has-text\(['\"]((?:[^'\"\\]|\\.)*)['\"]\)")


def _extract_has_text_literals(selector: Optional[str]) -> List[str]:
    """Extrai os literais internos de todo `:has-text(...)` presente em `selector`."""
    if not selector:
        return []
    return [m.group(1).replace("\\'", "'") for m in _HAS_TEXT_LITERAL_RE.finditer(selector)]


def _collect_observed_values(dicionario: Optional[Dict[str, Any]]) -> set:
    """Coleta o conjunto de `observed_value` de todos os fields do dicionário."""
    values = set()
    for field in (dicionario or {}).get("fields", {}).values():
        observed = field.get("observed_value")
        if isinstance(observed, str) and observed:
            values.add(observed)
    return values


def _count_field_matches(dicionario: Optional[Dict[str, Any]], selector: Optional[str]) -> int:
    """
    Conta quantos fields de `dicionario['fields']` têm `selector` == o
    `selector` informado. C4 exige EXATAMENTE 1 — 0 (binding ausente) ou 2+
    (binding ambíguo) caem para cognitive.
    """
    if not selector or not dicionario:
        return 0
    fields = dicionario.get("fields", {}) or {}
    return sum(1 for f in fields.values() if f.get("selector") == selector)


def _step_targeted_by_pending_corrections(step_id: str, pending_corrections: Optional[List[Dict[str, Any]]]) -> bool:
    """
    C8: um step é "alvo de correção pendente" se `step_id` aparece como
    `c["step_id"]` (alvo de required_wait/required_method/required_reopen,
    que sempre miram o campo 'step_id' da correção) OU como
    `c["required_reopen"]["after_step_id"]` (o step ANTERIOR ao alvo do
    re-disparo, que também precisa ficar de fora da forma canônica — ver
    Seção 5.2 do plano, achado M1).
    """
    for correction in pending_corrections or []:
        if correction.get("step_id") == step_id:
            return True
        reopen = correction.get("required_reopen") or {}
        if reopen.get("after_step_id") == step_id:
            return True
    return False


def classify_step(
    step: Dict[str, Any],
    dicionario: Optional[Dict[str, Any]] = None,
    pending_corrections: Optional[List[Dict[str, Any]]] = None,
    next_step: Optional[Dict[str, Any]] = None,
) -> EmissionDecision:
    """
    Aplica a linha de corte C1-C10 (Seção 2.2 do plano) a um único step e
    retorna a decisão de emissão.

    Parâmetros além dos dois da assinatura original do plano (`step`,
    `dicionario`) — extensões necessárias porque duas condições exigem
    contexto que não cabe dentro do próprio step:
    - `pending_corrections`: lista crua de `correcoes_acumuladas.json`
      (mesmo shape usado por `validate_required_wait_patterns` etc. em
      `step_validator.py`) — usada só pela C8.
    - `next_step`: o PRÓXIMO step "emitível" do plano (execution_hint em
      `None`/`"required"`/`"optional"` — nunca um `sup_`/`skip`), na mesma
      ordem usada por `_render_plan_for_prompt`. Usado só pela C9. `None`
      quando o step é o último emitível do plano (C9 nunca reprova nesse
      caso). É responsabilidade do CALLER (`build_skeleton`) calcular esse
      lookahead — `classify_step` nunca vê o plano inteiro.

    C7 (projeto com `skills_used` não vazio ⇒ arquivo inteiro cai pro
    fluxo full-LLM) é uma condição GLOBAL sobre o projeto, não sobre o
    step — `classify_step` não a implementa; é responsabilidade do
    CALLER da integração (Fase 4, `_generate_new_code`, tarefa H4) decidir
    ANTES de chamar `build_skeleton` se o híbrido roda ou não.

    Override operacional `AEGIS_CODEGEN_FORCE_LLM_STEPS` (CSV de step_ids
    rebaixados a cognitive) é resolvido por `build_skeleton`/pelo chamador
    da integração via `os.getenv`, não aqui — `classify_step` fica puro
    (sem I/O), o que facilita o teste unitário por condição (tabela C1-C10).

    `flaky` é pass-through puro: não é lido em lugar nenhum desta função —
    não participa da classificação.
    """
    dicionario = dicionario or {}
    step_id = step.get("step_id", "?")
    hint = step.get("execution_hint")
    step_type = step.get("type")
    parent = step.get("parent") or {}
    selector = step.get("selector") or ""
    text = step.get("text")

    # C2 (metade 'skip') — checada primeiro: sup_/skip nunca vira código,
    # independente de tipo suportado ou qualquer outra condição.
    if hint == "skip":
        return EmissionDecision(
            "omit",
            "C2: execution_hint='skip' — sup_/skip nunca emitido por default (contrato v2/D6)",
        )

    # C1
    if step_type not in _SUPPORTED_TYPES:
        return EmissionDecision(
            "cognitive",
            f"C1: tipo '{step_type}' não suportado pelo emissor determinístico "
            f"(suportados: {sorted(_SUPPORTED_TYPES)})",
        )

    # C2 (metade 'optional') — decisão de EMITIR é da LLM (contrato D6).
    if hint == "optional":
        return EmissionDecision(
            "cognitive",
            "C2: execution_hint='optional' — decisão de emitir é da LLM (convenção de bloco-vazio)",
        )

    # C3 — Padrão Q: token dinâmico no material operacional do parent.
    # `has_text_original` vive ANINHADO em `parent` (sanitizer.py:1497-1503),
    # nunca top-level do step. Notes 'padrao_q' que citam 'has_text' também
    # contam (mesmo sem has_text_original presente); notes 'padrao_q' de
    # fallback_selectors NÃO contam (campo interno que o emissor nem emite).
    padrao_q_note = any(
        isinstance(note, str) and "padrao_q" in note and "has_text" in note
        for note in (step.get("sanitization_notes") or [])
        if "fallback_selectors" not in note
    )
    if parent.get("has_text_original") is not None or padrao_q_note:
        return EmissionDecision(
            "cognitive",
            "C3: Padrão Q (parent.has_text_original presente e/ou sanitization_notes de has_text) "
            "— literal sanitizado vs. composição dinâmica com row exige julgamento",
        )

    # C4 — binding por TIPO (só se aplica a fill/select_native/select; click
    # sem valor de negócio nunca passa por C4).
    if step_type in ("fill", "select_native"):
        matches = _count_field_matches(dicionario, step.get("selector"))
        if matches == 0:
            matches = _count_field_matches(dicionario, step.get("selector_original"))
        if matches != 1:
            return EmissionDecision(
                "cognitive",
                f"C4: binding ambíguo/ausente para '{step_type}' via selector/selector_original "
                f"({matches} chave(s) casadas no dicionário, esperado exatamente 1)",
            )
    elif step_type == "select":
        matches = _count_field_matches(dicionario, step.get("trigger_selector"))
        if matches != 1:
            return EmissionDecision(
                "cognitive",
                f"C4: binding ambíguo/ausente para 'select' via trigger_selector "
                f"({matches} chave(s) casadas no dicionário, esperado exatamente 1)",
            )

    # C5 — weak_selector exige material de ancoragem mecânica.
    if step.get("weak_selector"):
        has_material = bool(parent.get("has_text")) or bool(text) or (":has-text(" in selector)
        if not has_material:
            return EmissionDecision(
                "cognitive",
                "C5: weak_selector sem material de ancoragem mecânica "
                "(parent.has_text ausente, campo text ausente, seletor sem :has-text(...))",
            )

    # C6 — Padrão N (menu suspenso).
    if _MENU_HEURISTIC_RE.search(selector):
        return EmissionDecision(
            "cognitive",
            "C6: seletor casa heurística de menu suspenso do Padrão N "
            "(.sub-menu/.dropdown-menu/#menu-item-)",
        )

    # C8 — step alvo de correção pendente.
    if _step_targeted_by_pending_corrections(step_id, pending_corrections):
        return EmissionDecision(
            "cognitive",
            "C8: step referenciado por pending_corrections (required_wait/required_method/"
            "required_reopen) — a forma canônica não implementa a correção por construção",
        )

    # C9 — fill que precede autocomplete/opção dinâmica.
    if step_type == "fill" and next_step is not None:
        next_type = next_step.get("type")
        if next_type in ("select", "select_native"):
            return EmissionDecision(
                "cognitive",
                "C9: fill precede select/select_native no plano (padrão de autocomplete)",
            )
        if next_type == "click" and _AUTOCOMPLETE_HEURISTIC_RE.search(next_step.get("selector") or ""):
            return EmissionDecision(
                "cognitive",
                "C9: fill precede click em painel de autocomplete/opção dinâmica "
                "(heurística autocomplete/mat-option/[role='option']/#mat-autocomplete-panel-/listbox)",
            )

    # C10 — valor de negócio embutido no SELETOR operacional (achado B1).
    observed_values = _collect_observed_values(dicionario)
    if observed_values:
        literals = _extract_has_text_literals(selector)
        matched_literal = next((lit for lit in literals if lit in observed_values), None)
        if matched_literal is not None:
            return EmissionDecision(
                "cognitive",
                f"C10: seletor contém :has-text('{matched_literal}') — literal casa observed_value "
                f"do dicionário (hardcode que nenhum validador estático pega)",
            )
        if isinstance(text, str) and text in observed_values:
            return EmissionDecision(
                "cognitive",
                f"C10: campo 'text' do step ('{text}') casa observed_value do dicionário",
            )

    return EmissionDecision("deterministic", "C1-C10 todas satisfeitas")


def _plan_checksum(plan: Dict[str, Any]) -> str:
    """
    sha1 do conteúdo do plano usado — carimbado no manifest para o ciclo de
    vida da Seção 2.4 (`_restore_deterministic_blocks` degrada pra no-op se
    o checksum não bater com o plano atual, ex.: re-sanitização que renumera
    step_ids).
    """
    serialized = json.dumps(plan, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(serialized).hexdigest()


def _next_emittable_step(steps: List[Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    """
    Retorna o próximo step "emitível" (execution_hint ausente/'required'/
    'optional' — nunca 'skip') após a posição `index` em `steps`, na mesma
    definição usada por `_render_plan_for_prompt` (code_generator.py). `None`
    se não houver nenhum depois de `index`.
    """
    for step in steps[index + 1:]:
        if step.get("execution_hint") != "skip":
            return step
    return None


def build_skeleton(
    plan: Dict[str, Any],
    dicionario: Optional[Dict[str, Any]] = None,
    pending_corrections: Optional[List[Dict[str, Any]]] = None,
    force_llm_step_ids: Optional[List[str]] = None,
) -> "tuple[str, Dict[str, Any]]":
    """
    Monta o corpo de `execute_scenario_default` (SEM boilerplate — header e
    bloco `if __name__` continuam sendo responsabilidade exclusiva de
    `CodeGeneratorService._normalize_boilerplate`, que roda por cima do
    resultado final) e o manifest de proveniência (Seção 2.4 do plano).

    Para cada step de `plan["steps"]`, na ordem do plano:
    - `classify_step` decide deterministic/cognitive/omit (ver docstring de
      `classify_step` para as condições C1-C10 e a nota sobre C7/global).
    - `omit` (sup_/skip): nada é emitido, nem placeholder — nem entra no
      manifest (contrato v2/D6 vigente).
    - `deterministic`: bloco completo via `emit_step_block`.
    - `cognitive`: placeholder de 3 linhas PARSEÁVEL pelo
      `_STEP_ID_IN_BLOCK_RE` existente (`code_generator.py:1127`, exige
      literalmente `step_id="..."` no texto do bloco — sem essa forma
      exata, `_build_scoped_edit_plan`/`_parse_step_blocks` nunca
      encontrariam o bloco e o modo escopado cairia silenciosamente em
      fallback full-file, achado I7 da rodada 2 do plano):
          # [PASSO N] <descrição>
          # AEGIS_COGNITIVE_SLOT step_id="st_014" motivo="<reason>"
          pass
      O `pass` mantém o arquivo sintaticamente válido entre a montagem do
      skeleton e o preenchimento cognitivo (uma chamada LLM posterior,
      responsabilidade de outra tarefa/H4 — este módulo NUNCA chama LLM).

    Numeração: `# [PASSO N]` é sequencial (1, 2, 3, ...) na ordem de
    iteração dos steps NÃO omitidos — nunca repete, e não depende do
    sufixo numérico do step_id (que `_step_number`/`emit_step_block` usa
    isoladamente por bloco; aqui a numeração final é sobrescrita pelo
    skeleton assembler para garantir sequência estritamente crescente,
    exigência da Seção 5.1 do plano: "`build_skeleton` numera `# [PASSO N]`
    sequencialmente e nunca repete step_id (assert interno)").

    Overrides: `force_llm_step_ids` (iterável de step_ids) rebaixa esses
    steps especificos para cognitive incondicionalmente, mesmo que
    `classify_step` os tivesse classificado deterministic — equivalente ao
    override operacional `AEGIS_CODEGEN_FORCE_LLM_STEPS` (resolução do
    valor de ambiente em CSV é responsabilidade do CALLER da integração;
    esta função só aceita a lista já resolvida, mantendo `build_skeleton`
    livre de I/O de ambiente).

    C7 (skills_used não vazio ⇒ fluxo full-LLM inteiro) NÃO é checado aqui
    — é uma decisão do INTEGRADOR (H4) tomada ANTES de decidir chamar
    `build_skeleton`; esta função sempre assume que já foi decidido rodar
    o híbrido para este plano.

    Retorna (skeleton_code, manifest). `skeleton_code` é só o CORPO da
    função `execute_scenario_default(page, row, runner):` (assinatura
    inclusa) — ainda precisa passar por `_normalize_boilerplate` para virar
    um arquivo completo executável.
    """
    force_llm_step_ids = set(force_llm_step_ids or [])
    steps = plan.get("steps", [])

    body_blocks: List[str] = []
    manifest_steps: Dict[str, Any] = {}
    seen_step_ids = set()
    passo_counter = 0

    for index, step in enumerate(steps):
        step_id = step["step_id"]
        next_step = _next_emittable_step(steps, index)
        decision = classify_step(step, dicionario, pending_corrections, next_step)

        if decision.kind == "omit":
            continue

        kind = decision.kind
        reason = decision.reason
        if kind == "deterministic" and step_id in force_llm_step_ids:
            kind = "cognitive"
            reason = f"forçado para cognitive via AEGIS_CODEGEN_FORCE_LLM_STEPS (motivo original: {reason})"

        if step_id in seen_step_ids:
            raise AssertionError(
                f"build_skeleton: step_id '{step_id}' duplicado no plano — "
                f"numeração de # [PASSO N] exige step_ids únicos."
            )
        seen_step_ids.add(step_id)
        passo_counter += 1

        if kind == "deterministic":
            block = emit_step_block(step, dicionario)
            # Renumera a âncora "# [PASSO N]" pra sequência estritamente
            # crescente do arquivo inteiro (emit_step_block numera pelo
            # sufixo do próprio step_id, isolado — build_skeleton é quem
            # garante a sequência global, Seção 5.1 do plano). O bloco já
            # vem indentado (4 espaços) por emit_step_block, então a âncora
            # tem espaço em branco à esquerda — o grupo \1 preserva essa
            # indentação.
            block = _STEP_ANCHOR_RENUMBER_RE.sub(rf"\1# [PASSO {passo_counter}]", block, count=1)
            body_blocks.append(block)
            block_sha1 = hashlib.sha1(block.encode("utf-8")).hexdigest()
            manifest_steps[step_id] = {
                "provenance": "deterministic",
                "reason": reason,
                "block_sha1": block_sha1,
            }
        else:  # cognitive
            description = step.get("description", "")
            placeholder = (
                f"# [PASSO {passo_counter}] {description}\n"
                f'# AEGIS_COGNITIVE_SLOT step_id={_fmt_str(step_id)} motivo={_fmt_str(reason)}\n'
                f"pass"
            )
            placeholder = _indent_block(placeholder, 4)
            body_blocks.append(placeholder)
            manifest_steps[step_id] = {
                "provenance": "cognitive",
                "reason": reason,
            }

    skeleton_body = "\n".join(body_blocks) if body_blocks else _indent_block("pass", 4)
    skeleton_code = "def execute_scenario_default(page, row, runner):\n" + skeleton_body

    manifest = {
        "generator_version": "hybrid-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_checksum": _plan_checksum(plan),
        "steps": manifest_steps,
    }
    return skeleton_code, manifest


_STEP_ANCHOR_RENUMBER_RE = re.compile(r"^(\s*)# \[PASSO [^\]]+\]", re.MULTILINE)
