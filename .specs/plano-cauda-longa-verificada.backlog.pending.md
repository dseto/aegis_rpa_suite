# Tarefas adiadas — fora do escopo do backlog "Cauda Longa Verificada"

> Achadas durante execução do backlog `.specs/plano-cauda-longa-verificada.backlog.md` (gates de browser real SUB03-05, projeto `TesteFimm/006-Fimm`). Registradas aqui pra tratar depois de fechar o backlog atual. Nenhuma implementada ainda.

## Tarefa A — `_attempt_deterministic_click_recovery` (Níveis 2.5/2.75/2.9) sem doutrina de verificação

**Achado:** `runner.py:1174-1178`, helper `_effect_confirmed` chama `_click_effect_signals_changed` diretamente, sem passar por `_verify_action_effect` (SUB01) nem sua ressalva de overlay. Afeta 3 tiers: escape-retry (2.5), CDK-reposition (2.75), `fallback_selectors` (2.9) — tanto no click (`runner.py` ~1242-1253) quanto no fill (`runner.py` ~2682-2698, este último sem NENHUMA verificação, nem a antiga).

**Impacto confirmado ao vivo:** `st_007` do projeto Fimm (autocomplete de banco) — `fallback_selectors` (`.grid button`, ambíguo) resolve via `.first`, reporta HEALED, mas o dropdown nunca fecha de verdade. Falso-positivo idêntico ao que o resto do plano já mata em outros tiers.

**Fix proposto:** rotear os 3 níveis por `_verify_action_effect` (igual T1/T2 no SUB05); adicionar verificação ao fill-side `fallback_selectors` (hoje zero verificação).

## Tarefa B — `recorder.py:148` constrói seletor `has-text` não-viável a partir de texto multi-linha

**Achado:** `textStrategy()` em `recorder.py:140-153` faz `el.innerText.replace(/\s+/g, ' ')` — colapsa quebra de linha real em espaço antes de montar `:has-text('...')`. Playwright `:has-text()` casa contra o texto renderizado real (que mantém a quebra de linha) — um seletor construído assim **nunca pode casar**, por construção, quando o elemento-alvo tem texto em múltiplas linhas (comum em itens de dropdown/autocomplete com título+subtítulo).

**Por que a mitigação existente não cobre:** `_viable_has_text_literal`/`_apply_has_text_anchor` (`deterministic_emitter.py`) só roda quando `step.weak_selector=true` E só quando o seletor AINDA NÃO TEM `:has-text(` embutido (adiciona âncora faltante, não revalida âncora existente). Seletor construído pelo recorder já chega com `:has-text(` e `confidence=70` fixo (nunca é marcado `weak_selector`) — a rede de segurança nunca é acionada.

**Impacto confirmado ao vivo:** `st_007` do projeto Fimm — seletor primário `button:has-text('Itaú Unibanco São Paulo ITAUBRSPXXX | Brasil')` (texto real no DOM: `"Itaú Unibanco São Paulo\nITAUBRSPXXX | Brasil"`) — 2 timeouts de 5s idênticos, garantidos, não é flakiness.

**Fix proposto:**
1. `recorder.py:148` — construir literal viável (ex.: só a primeira linha não-vazia do `innerText`) em vez de colapsar toda quebra de linha em espaço.
2. `deterministic_emitter.py` — estender a validação de viabilidade de `has-text` pra rodar mesmo quando `weak_selector` não está marcado (o gate de confiança 70-fixo esconde exatamente esse tipo de defeito).

---

**Retomar quando:** backlog atual (`.specs/plano-cauda-longa-verificada.backlog.md`) estiver fechado. Escopo é `aegis_blackbox`/`aegis_code_generator` (Tarefa B) + `aegis_runner` (Tarefa A) — não conflita com arquivos do backlog em andamento.
