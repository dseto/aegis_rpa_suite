"""
golden_diff.py — compara a subsequência de steps EMITÍVEIS (step_id
começando em "st_") de um plano_execucao.json v2 recém-gerado contra um
golden v1 (.specs/golden/<nome>/plano_execucao.json), campo a campo,
POSIÇÃO A POSIÇÃO — a ordem relativa dos steps faz parte do invariante que
está sendo verificado, não só o conteúdo de cada um isoladamente (ver
.specs/plano-sanitizer-alta-fidelidade.md, Seção 4, "invariante de
migração": "para qualquer gravação, a sequência de steps emitíveis (st_) do
plano v2 deve ser byte-idêntica ... exceto pelos campos novos aditivos").

Uso:
    python aegis_sanitizer/golden_diff.py <golden_dir> <output_plano.json>

- <golden_dir>: diretório contendo um plano_execucao.json v1 golden (ex.:
  .specs/golden/real_portal_segura_001).
- <output_plano.json>: caminho para um plano_execucao.json v2 recém-gerado
  a ser comparado.

Comportamento:
- Filtra o plano v2 para conter só os steps cujo step_id começa com "st_"
  (descarta "sup_"), preservando a ORDEM em que aparecem no array `steps`
  do JSON de saída — nunca reordena/agrupa antes de comparar.
- Para cada posição i, compara TODOS os campos presentes no step golden[i]
  contra o step v2[i] correspondente: cada chave do step golden precisa
  existir no step v2 com o MESMO valor. Campos aditivos do v2 que não
  existem no golden (merged_from, source_events, step_role, scenario,
  text, original_index, sanitization_notes, selector_original,
  has_text_original, execution_hint, etc.) são ignorados de propósito —
  não fazem parte do invariante v1.
- Se a contagem de steps "st_" divergir do golden, ou qualquer campo
  golden divergir do correspondente v2, imprime o diff completo e sai com
  código 1. Caso contrário, imprime uma confirmação e sai com código 0.

Campos deliberadamente NÃO comparados (fora do array `steps`): "test_dir"
e "generated_at" no nível raiz do plano são não-determinísticos por
natureza (ver .specs/golden/real_portal_segura_001/META.md) — este script
nunca olha para o nível raiz além de `steps`, então esses campos nunca
entram na comparação.
"""
import json
import os
import sys


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_MISSING = object()


def _golden_subset_matches(g_val, o_val):
    """
    Compara um valor do golden contra o correspondente do v2, permitindo
    campos aditivos novos DENTRO de valores dict aninhados (ex.: "parent"
    ganha "has_text_original"/"sanitization_notes" pelo Padrão Q — D4 do
    plano — sem que o "has_text"/"selector" operacional mude). Uma
    comparação `==` direta do dict inteiro reprovaria isso incorretamente,
    já que dict.__eq__ exige o MESMO conjunto de chaves nos dois lados.

    Regra: se g_val é um dict, cada chave DE g_val precisa existir em o_val
    com um valor que também bata recursivamente (chaves extras em o_val são
    ignoradas — são aditivas). Para qualquer outro tipo (lista, escalar),
    exige igualdade exata — coords/step_id/selector/etc. não têm essa
    flexibilidade nem deveriam precisar dela.
    """
    if o_val is _MISSING:
        return False
    if isinstance(g_val, dict):
        if not isinstance(o_val, dict):
            return False
        return all(_golden_subset_matches(v, o_val.get(k, _MISSING)) for k, v in g_val.items())
    return g_val == o_val


def compare(golden_path: str, output_path: str) -> list:
    """Retorna uma lista de strings de diff (vazia == sem divergências)."""
    golden = _load(golden_path)
    output = _load(output_path)

    golden_steps = golden.get("steps", [])
    output_st_steps = [
        s for s in output.get("steps", [])
        if str(s.get("step_id", "")).startswith("st_")
    ]

    diffs = []

    if len(golden_steps) != len(output_st_steps):
        diffs.append(
            f"Contagem de steps 'st_' diverge: golden={len(golden_steps)} "
            f"vs v2={len(output_st_steps)}"
        )

    for i, (g_step, o_step) in enumerate(zip(golden_steps, output_st_steps)):
        g_id = g_step.get("step_id")
        o_id = o_step.get("step_id")
        if g_id != o_id:
            diffs.append(f"[posição {i}] step_id diverge: golden={g_id!r} vs v2={o_id!r}")
        for key, g_val in g_step.items():
            if key == "step_id":
                continue
            o_val = o_step.get(key, _MISSING)
            if not _golden_subset_matches(g_val, o_val):
                shown = "<AUSENTE>" if o_val is _MISSING else o_val
                diffs.append(
                    f"[posição {i}] step_id={g_id!r} — campo {key!r}: "
                    f"golden={g_val!r} vs v2={shown!r}"
                )

    return diffs


def main(argv):
    if len(argv) != 3:
        print("Uso: python aegis_sanitizer/golden_diff.py <golden_dir> <output_plano.json>")
        return 2

    golden_dir, output_path = argv[1], argv[2]
    golden_path = os.path.join(golden_dir, "plano_execucao.json")

    if not os.path.isfile(golden_path):
        print(f"[GOLDEN_DIFF] ERRO: golden não encontrado em {golden_path}")
        return 2
    if not os.path.isfile(output_path):
        print(f"[GOLDEN_DIFF] ERRO: plano de saída não encontrado em {output_path}")
        return 2

    diffs = compare(golden_path, output_path)

    if diffs:
        print(f"[GOLDEN_DIFF] FALHOU — {len(diffs)} divergência(s) encontrada(s) contra {golden_path}:")
        for d in diffs:
            print(f"  - {d}")
        return 1

    print(
        f"[GOLDEN_DIFF] OK — subsequência de steps 'st_' de {output_path} "
        f"idêntica ao golden {golden_path} (campos presentes no golden batem "
        f"posição a posição)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
