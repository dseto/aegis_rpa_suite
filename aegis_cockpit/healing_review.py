"""
Núcleo testável do loop Sensor F1 -> correção cirúrgica (E2,
.specs/backlog-evolucao-agentica-design-time.md). Puramente leitura +
enriquecimento de `correcoes_acumuladas.json` -- nunca aplica a correção
sozinho. `enrich_needs_review` produz propostas prontas para revisão
humana; `approve_proposal` é o único ponto que converte uma proposta
aprovada em correção `status="pending"`, no formato que o fluxo surgical
existente (`aegis_code_generator.code_generator._surgical_correct`,
consumido via `pending_corrections`) já espera -- reaproveita o schema
(`root_cause`/`proposed_fix`), nunca reescreve o mecanismo de aplicação.

Mantido fora do handler HTTP do `cockpit.py` (gap conhecido: `cockpit.py`
não tem suite de testes e já causou regressão real quando editado sem
re-check live) para que esta lógica seja testável em isolamento.
"""
import json
import os

# Healing methods resolvidos por um tier DETERMINÍSTICO (sem LLM) que já
# grava, na própria captura (`plano_execucao.json`), o dado necessário para
# sugerir a promoção do seletor -- `anchor` (Unified Target Descriptor) ou
# `fallback_selectors` (M5). `parent_has_text_reduced` não tem seletor
# alternativo gravado (é reduzido em runtime, ver CLAUDE.md), mas ainda é
# determinístico: a proposta aponta pro mecanismo, não inventa seletor.
DETERMINISTIC_HEALING_METHODS = {"anchor_geometry", "fallback_selector", "parent_has_text_reduced"}


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def scan_needs_review(test_dir):
    """Lê `correcoes_acumuladas.json` do cenário e devolve as entradas com
    `status == "needs_review"`, agrupadas por `(action, failed_selector)`
    -- o mesmo par que o Sensor F1 (`_register_healing_for_review` em
    `runner.py`) já usa como chave de dedup na escrita; o agrupamento aqui
    é garantia defensiva contra estado legado/editado a mão, nunca a
    fonte da dedup em si."""
    corr_path = os.path.join(test_dir, "correcoes_acumuladas.json")
    all_corrs = _load_json(corr_path, [])
    if not isinstance(all_corrs, list):
        return {}
    groups = {}
    for entry in all_corrs:
        if not isinstance(entry, dict) or entry.get("status") != "needs_review":
            continue
        key = ((entry.get("action") or "").strip().lower(), (entry.get("failed_selector") or "").strip())
        groups.setdefault(key, []).append(entry)
    return groups


def resolve_step_id(entry):
    """Regra 5 dos Working Agreements (CLAUDE.md): uma correção sem
    `step_id` resolvido é estruturalmente invisível ao scoped-edit do
    `code_generator`. `"auto_N"` é o marcador sintético de
    fim-de-transação do runner (`_log_step`, fallback quando o `step_id`
    não bate com nenhum bloco do plano) -- nunca existe como âncora
    `# [PASSO X]` em nenhum bot gerado, então é tratado como não-resolvido
    (mesma convenção que `cockpit.py` já aplica no pipeline de insights)."""
    step_id = entry.get("step_id")
    if not step_id or not isinstance(step_id, str):
        return None
    if step_id.startswith("auto_"):
        return None
    return step_id


def _find_plan_step(plan_steps, step_id):
    for step in plan_steps or []:
        if isinstance(step, dict) and step.get("step_id") == step_id:
            return step
    return None


def _occurrences_note(entry):
    occ = entry.get("occurrences", 1)
    return f"{occ}x nesta execução" if occ and occ > 1 else "nesta execução"


def build_deterministic_proposal(entry, plan_step):
    """Sem chamada de LLM: promove o seletor/âncora que resolveu (já
    gravado no plano na captura) a seletor primário sugerido do passo.
    Cobre a classe de `needs_review` mais barata e mais comum -- só os
    `healing_method` estruturais em `DETERMINISTIC_HEALING_METHODS`."""
    healing_method = entry.get("healing_method")
    failed_selector = entry.get("failed_selector", "")
    step_id = entry.get("step_id")

    promoted_selector = None
    detail = ""
    if healing_method == "anchor_geometry" and plan_step:
        anchor = plan_step.get("anchor") or {}
        promoted_selector = anchor.get("selector")
        detail = f"âncora gravada (label/texto: '{anchor.get('text', '')}')"
    elif healing_method == "fallback_selector" and plan_step:
        fallbacks = plan_step.get("fallback_selectors") or []
        promoted_selector = fallbacks[0] if fallbacks else None
        detail = "primeiro fallback_selector gravado na captura"
    elif healing_method == "parent_has_text_reduced":
        detail = "seletor reduzido via _reduce_parent_has_text em runtime (ver CLAUDE.md)"

    root_cause = (
        f"Seletor original '{failed_selector}' parou de resolver diretamente; "
        f"tier determinístico '{healing_method}' recuperou o passo {_occurrences_note(entry)}."
    )
    if promoted_selector:
        proposed_fix = (
            f"Promover '{promoted_selector}' ({detail}) a seletor primário do passo {step_id}, "
            f"mantendo '{failed_selector}' como fallback_selector."
        )
    else:
        proposed_fix = (
            f"Revisar o passo {step_id}: {detail or 'sem seletor alternativo gravado explicitamente'}; "
            f"seletor original '{failed_selector}' segue instável."
        )

    return {
        "kind": "deterministic",
        "step_id": step_id,
        "healing_method": healing_method,
        "promoted_selector": promoted_selector,
        "root_cause": root_cause,
        "proposed_fix": proposed_fix,
    }


def build_cognitive_proposal(entry, gateway, screenshot_path=None):
    """Rota cognitiva: casos sem resolução estrutural (`healing_method`
    fora de `DETERMINISTIC_HEALING_METHODS`). Usa `gateway._call_llm_api`
    diretamente -- não `gateway.diagnose_failure`, que exige uma página
    Playwright AO VIVO para tirar screenshot (`page.screenshot(...)`),
    indisponível numa revisão pós-hoc no Cockpit (execução já terminou,
    sem browser aberto). `screenshot_path` aponta pro arquivo JÁ salvo
    pela execução (campo `screenshot` do passo em `historico_passos.json`),
    quando existir."""
    step_id = entry.get("step_id")
    healing_method = entry.get("healing_method") or "unknown"
    failed_selector = entry.get("failed_selector", "")
    action = entry.get("action", "")

    if gateway is None or not gateway.is_active():
        return {
            "kind": "cognitive",
            "step_id": step_id,
            "healing_method": healing_method,
            "root_cause": (
                f"Passo {step_id} ({action} em '{failed_selector}') precisou de healing "
                f"'{healing_method}' sem resolução estrutural conhecida."
            ),
            "proposed_fix": "Gateway cognitivo inativo -- revisão manual necessária.",
        }

    prompt = f"""
Você é um especialista sênior em QA/RPA revisando uma correção JÁ APLICADA em runtime (self-healing).
Passo: {step_id} | Ação: {action} | Seletor original que falhou: '{failed_selector}'
Método de recuperação usado em runtime: '{healing_method}'

Com base na screenshot (se fornecida) e no contexto acima, retorne um JSON com:
- "root_cause_summary": causa provável de o seletor original ter parado de funcionar
- "actionable_fix": sugestão concreta de correção no código do bot (ex.: novo seletor, ajuste de espera)

Retorne EXCLUSIVAMENTE o JSON, sem texto antes/depois.
"""
    try:
        raw = gateway._call_llm_api(prompt, image_path=screenshot_path, force_json=True)
        diag = gateway._clean_json_response(raw)
    except Exception as e:
        diag = {
            "root_cause_summary": f"Falha ao diagnosticar via IA: {e}",
            "actionable_fix": "Revisão manual necessária.",
        }

    return {
        "kind": "cognitive",
        "step_id": step_id,
        "healing_method": healing_method,
        "root_cause": diag.get("root_cause_summary", ""),
        "proposed_fix": diag.get("actionable_fix", ""),
    }


def build_proposal(entry, plan_steps, gateway=None, screenshot_path=None):
    """Roteador: `healing_method` estrutural -> proposta determinística
    (zero LLM); resto -> rota cognitiva."""
    healing_method = entry.get("healing_method")
    if healing_method in DETERMINISTIC_HEALING_METHODS:
        plan_step = _find_plan_step(plan_steps, entry.get("step_id"))
        return build_deterministic_proposal(entry, plan_step)
    return build_cognitive_proposal(entry, gateway, screenshot_path)


def enrich_needs_review(test_dir, gateway=None):
    """Orquestrador: varre `needs_review`, resolve `step_id` (Regra 5),
    monta proposta (determinística ou cognitiva) para cada entrada
    resolvida, e devolve as propostas prontas para aprovação humana --
    NÃO altera `correcoes_acumuladas.json` (isso é `approve_proposal`,
    chamado só depois da aprovação explícita via endpoint do cockpit)."""
    plan_path = os.path.join(test_dir, "plano_execucao.json")
    plan = _load_json(plan_path, {})
    plan_steps = plan.get("steps", []) if isinstance(plan, dict) else []

    groups = scan_needs_review(test_dir)
    proposals = []
    skipped_unresolved = []
    for entries in groups.values():
        entry = entries[0]
        step_id = resolve_step_id(entry)
        if step_id is None:
            skipped_unresolved.append(entry)
            continue
        proposal = build_proposal(entry, plan_steps, gateway=gateway)
        proposal["correction_id"] = entry.get("id")
        proposals.append(proposal)

    return {"proposals": proposals, "skipped_unresolved": skipped_unresolved}


def approve_proposal(test_dir, correction_id, proposal):
    """Converte uma proposta aprovada pelo humano em correção
    `status="pending"`, no formato que o fluxo surgical existente já
    consome. Gate humano: só deve ser chamado pelo endpoint do cockpit
    após aprovação explícita -- nunca automaticamente a partir de
    `enrich_needs_review`."""
    corr_path = os.path.join(test_dir, "correcoes_acumuladas.json")
    all_corrs = _load_json(corr_path, [])
    if not isinstance(all_corrs, list):
        return False
    for entry in all_corrs:
        if entry.get("id") == correction_id:
            entry["root_cause"] = proposal.get("root_cause")
            entry["proposed_fix"] = proposal.get("proposed_fix")
            entry["qa_insight"] = f"healing_review: {proposal.get('kind')} ({proposal.get('healing_method')})"
            entry["status"] = "pending"
            _save_json(corr_path, all_corrs)
            return True
    return False
