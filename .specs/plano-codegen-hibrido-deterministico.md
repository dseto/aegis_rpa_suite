# Plano de Refatoração — Code Generator Híbrido (Fase 4: de "LLM escreve tudo" para "motor determinístico + slots cognitivos")

**Data:** 2026-07-12
**Módulos alvo:** `aegis_sanitizer/code_generator.py`, `aegis_sanitizer/step_validator.py`
**Módulo novo:** `aegis_sanitizer/deterministic_emitter.py`
**Módulos impactados (leves):** `aegis_mentor/skills/rpa-copilot-coder.md`, `docs/`
**Módulos que NÃO mudam:** `aegis_runner/runner.py`, `aegis_blackbox/recorder.py`, `aegis_sanitizer/sanitizer.py`, `aegis_cockpit/` (backend e frontend)
**Status:** revisado (rodadas 1, 2 + re-checagem focada); backlog executado até [SUBAGENTE 09]; [SUBAGENTE 10]/H8 REPROVADO ⇒ **emenda rodada 3 na Seção 3.3 (Padrão Q) — pendente de implementação antes de nova tentativa de H8**
**Emenda 2026-07-13 (rodada 4, `plan-critic` — SEGUNDA OPINIÃO INDEPENDENTE sobre a emenda da rodada 3, agente frio sem contexto da rodada 3, re-verificação linha-a-linha + simulação empírica contra os goldens):** núcleo técnico da rodada 3 CONFIRMADO — todas as citações arquivo:linha conferiram; a estrutura de retry (slot single-shot `code_generator.py:1330-1339`; reflection via `_surgical_correct_with_reflection` `code_generator.py:599` só re-renderiza o JSON do erro `code_generator.py:2663-2666`, NÃO re-renderiza `_render_hybrid_slots_context`/Q-a — verificado: `_surgical_correct` só usa `reflection_section`) justifica o `detail` prescritivo; os fatos verificados ao vivo (st_062 ⇒ `nome_cliente`+`cpf_cliente`; C10 por igualdade exata NÃO pega st_062, logo Q-b é genuinamente necessário; st_005 da matriz não dispara). **3 correções aplicadas nesta rodada:** (1) **IMPORTANTE — blast radius do round-trip subestimado:** "1 ajuste de fixture" é INSUFICIENTE. `_force_classify_where_possible` (`test_deterministic_emitter.py:631-676`) força `st_062` a `deterministic` (só desvia p/ cognitive em C1/C4/C5/C10, NÃO tem ramo de Padrão Q), emitindo um bloco real com `has_text` literal; como `st_062` fica então em `code_ids`, o guard optional-skip de `step_validator.py:892` (`... and step["step_id"] not in code_ids`) NÃO o pula e `HARDCODED_PARENT_HAS_TEXT` dispara ⇒ `test_round_trip_zero_errors_against_all_validators` REPROVA no golden v2 (simulado empiricamente). Correção real = 2 edições coordenadas no teste + 1 comentário (ver Seção 3.3 corrigida), não só o `_KNOWN_COGNITIVE_ONLY_STEP_IDS`. (2) **MENOR — "mesma mecânica da C10" é impreciso:** C10 casa por PERTINÊNCIA EXATA (`literal ∈ observed_values`, `deterministic_emitter.py:643,650`); Q-b precisa de SUBSTRING (`observed_value ⊂ has_text`, pois `parent.has_text` é composto) — direção invertida, código de casamento NOVO (só `_collect_observed_values` é reusável) e com risco de falso-positivo por valores curtos (`'Sim'`/`'2026'`/`'50000'`) que a pertinência exata não tem. (3) **MENOR — gatilho mais estreito que o perigo nomeado:** o golden v1 `real_portal_segura_001` st_062 carrega o MESMO literal perigoso `parent.has_text: "daniel setttt 22401666818 FIPE"` SEM `has_text_original` — nem C10 (só seletor) nem Q-b (exige `has_text_original`) o pegam; "Q-b fecha a brecha para as duas rotas" (Seção 3.3) superestima: fecha só o subconjunto Padrão Q. Veredito rodada 4: **aprovar com ajustes** (as 3 correções acima aplicadas; gatilho por `has_text_original` mantido — trade-off de blast radius legítimo, mas com scope-note explícito).
**Emenda 2026-07-13 (rodada 3, `plan-critic` pós-reprovação do gate H8/[SUBAGENTE 10], verificação direta contra código + goldens + projeto de referência):** o "Nada a mudar" da Seção 3.3 era premissa FALSA — o validador `MISSING_PARENT_HAS_TEXT` aceita o LITERAL gravado como prova equivalente à composição dinâmica (`step_validator.py:983-987`), o prompt do slot cognitivo AUTORIZA explicitamente o literal ("julgamento seu", `code_generator.py:1393-1398`, contradizendo a proibição de hardcode do mesmo prompt em 1404-1405), e o texto do erro sugere o literal como correção válida (`step_validator.py:992-1000`). Resultado real no gate H8: `st_062` (Padrão Q) saiu com `has_text` literal em 2/2 regenerações — hardcode de nome/CPF que nenhum validador pega e só quebra com dataset de 2+ linhas. Decisão desta rodada: aplicar **(a) prompt prescritivo E (b) validador endurecido** — (b) sozinho oscilaria (a chamada de slots é single-shot, `code_generator.py:1330-1339`; o retry via reflection só vê o JSON do erro, `code_generator.py:2663-2666`, e o prompt de slots não é re-renderizado) e (a) sozinho não é verificável (repetiria a classe de bug "regra só em prosa" da Seção 1). Endurecimento REFINADO: gatilho = `parent.has_text_original` presente + residual contendo `observed_value` do dicionário (mesma mecânica da C10) — Padrão Q com residual 100% estático continua aceitando literal (é a escolha correta lá). Novo erro `HARDCODED_PARENT_HAS_TEXT` com `step_id` (working agreement nº 5 ok) e `detail` prescritivo nomeando as chaves derivadas mecanicamente (verificado ao vivo: st_062 ⇒ `nome_cliente` + `cpf_cliente`). Blast radius verificado: 1 ajuste de fixture no round-trip (`st_062` ⇒ `_KNOWN_COGNITIVE_ONLY_STEP_IDS` do golden v2; `st_005` da matriz NÃO dispara sob o gatilho refinado — verificado); `test_step_validator_hints.py`/`test_sanitizer_execution_plan.py`/`test_hybrid_generation.py` sem dependência (grep). A correção beneficia TAMBÉM a rota full-LLM (`validate_resilience_patterns` é compartilhada, chamada única em `code_generator.py:765`). Detalhes completos na Seção 3.3 emendada.
**Re-checagem focada 2026-07-12 (mesmo agente da rodada 2, restrita às seções emendadas):** todas as incorporações da rodada 2 confirmadas tecnicamente corretas (C10 verificada contra o golden real — `st_023`/`st_024`/`st_025` presentes; I7 conferida contra o regex real; I3/I6/M1/M3 com citações conferidas). 1 achado IMPORTANTE corrigido: **R1 — a C4 emendada bindava `select_native` por `trigger_selector`, mas `select_native` nasce de `fill` em `<select>` (`sanitizer.py:1469-1471`) e carrega `selector` normal SEM `trigger_selector` (verificado em `katalon_demo_form/002`: ambos com `trigger_selector: None`)** — corrigido: `select_native` binda como `fill` (por `selector`); só `select` customizado usa `trigger_selector`. Menores corrigidos: R2 (casamento por `dropdown_label` era inimplementável — fields do dicionário não têm a chave; removido), R3 (erros de dry-run não carregam `lineno`, `step_validator.py:1750-1758` — excluídos explicitamente do fail-fast nesta v1), R4 (enumeração do prompt no H4 alinhada com a Seção 2.3 — incluía tudo menos `pending_corrections`), R5 (bullet "manifest ausente" da 5.2 alinhado ao ciclo de vida da 2.4). Veredito do revisor: convergência atingida, sem necessidade de nova rodada.
**Revisão 2026-07-12 (rodada 2, segunda opinião independente, agente Fable frio sem contexto da rodada 1, testada contra planos de execução REAIS de `projects/portal_segura/`):** veredito "aprovar com ajustes" — 1 BLOQUEANTE, 7 importantes, 3 menores, todos incorporados nesta versão. As correções da rodada 1 foram confirmadas consistentes e as ~22 citações de linha conferiram. **BLOQUEANTE (B1):** a linha de corte não cobria valor de negócio embutido no SELETOR do próprio step — o step real `st_023` do projeto de referência (`#mat-autocomplete-panel-marca div:has-text('Hyundai')`, click de opção de autocomplete) passava por C1-C9 inteira como deterministic, e o emissor geraria `'Hyundai'` hardcoded onde o bot LLM atual parametriza com `f"div:has-text('{row.get('marca_veiculo', '')}')"` (`bot_producao.py:106-107` do 001_teste) — nenhum validador pega (`HARDCODED_TEXT_VAL` só olha kwarg `text_val`, `step_validator.py:336-344`), regressão só em execução real com dataset variado → nova C10. Importantes: (I1) C9 estava calibrada contra forma que não existe — autocomplete real é fill→CLICK em painel (st_022→st_023), nunca fill→select → recalibrada + cenário do H8.2 corrigido; (I2) os 15 steps `select` reais têm `selector: ""` (binding em `trigger_selector`/`dropdown_label`) — C4 nunca casava e todo select viraria cognitive → C4 desdobrada por tipo; (I3) prompt dos slots cognitivos não incluía `pending_corrections`, contradizendo a razão de existir da C8 → incluído; (I4) contrato `optional` × "slot faltando ⇒ fallback full-LLM" era contraditório → convenção de bloco-vazio; (I5) manifest stale após regeneração full-LLM armaria o restore contra bot não-híbrido → ciclo de vida definido (toda rota sobrescreve/invalida + checksum do plano); (I6) fail-fast da 5.2 ainda tinha falso-positivo com erros de ORDEM apontando bloco restaurado → restrito a erros de conteúdo; (I7) placeholder de slot era ilegível pelo `_STEP_ID_IN_BLOCK_RE` (`code_generator.py:1127` exige `step_id="..."`) — todo slot cairia silenciosamente em full-LLM e o DoD do H4 não pegaria → resolução de slot especificada + fixture com slot no DoD. Menores: `target_scope` ganha `after_step_id` de `required_reopen` (M1); nota sobre `gateway.is_active()` continuar exigido mesmo com zero slots (M2); H5 corrigido para UM ponto de chamada (M3). Claims decisivas (B1, I1, I2, I7) re-verificadas pelo orquestrador direto no repo antes da incorporação.
**Revisão 2026-07-12 (rodada 1, `plan-critic` via agente Fable, verificação linha-a-linha contra HEAD `b5cc4e7`):** veredito "aprovar com ajustes" — 0 bloqueantes, 3 importantes, 6 menores, todos incorporados nesta versão. Importantes: (1) a linha de corte C1-C7 ignorava `pending_corrections` — um step alvo de `required_wait`/`required_method`/`required_reopen` emitido deterministicamente violaria a correção por construção e a regra fail-fast original da Seção 5.2 abortaria a geração com diagnóstico falso ("bug do emissor") já na tentativa 1 → adicionada C8 + fail-fast restrito a adulteração efetivamente revertida; (2) o golden v2 existente (`synthetic_r1_merge_case`) tem só 2 steps (1 `st_` + 1 `sup_ skip`) e o golden real é v1 puro (63 steps, zero hints — verificado por inspeção direta dos JSONs) — o round-trip "gate central" passaria vazio na metade v2 → H0 ganhou a captura de um golden v2 rico; (3) a regra 4 do prompt atual (Padrão M, `code_generator.py:1022`) obriga HUMAN_LIKE também para input que precede autocomplete, independente de `fill_strategy` no dicionário — julgamento contextual que o emissor por `fill_strategy` perderia silenciosamente (nenhum validador cobra; regressão só em runtime) → nova condição de autocomplete na linha de corte. Menores incorporados: decisão explícita sobre `flaky` (pass-through), caso "bloco deterministic AUSENTE" definido no restore, `block_sha1` rebaixado a telemetria (restore incondicional, mais simples), citação `cockpit.py:1597/1654` corrigida para `1630/1664-1665`, C3 precisado (`has_text_original` vive em `parent`, `sanitizer.py:1500`, e notes `padrao_q` de `fallback_selectors` não contam), snapshot de prompt do H4 marcado como gate descartável pós-flip. Das 22 citações arquivo:linha do plano, 21 conferiram exatas; as premissas centrais (subsequência hint-aware, `Try` transparente ao AST-walk, forma do modo escopado, schema v2 no sanitizer) foram todas confirmadas no código real.

---

## 0. Correção de premissa do enunciado (importante para quem executar)

O enunciado desta demanda descreve a "Mudança A" com campos hipotéticos (`"step_type": "exploratory"`, `"ignore_in_strict_generation": true`). **Esses campos não existem.** O schema real, já implementado e testado (plano v2 de `.specs/plano-sanitizer-alta-fidelidade.md`, backlog concluído), é:

- `execution_hint`: ausente/`"required"` | `"optional"` | `"skip"`;
- ids em dois espaços: `st_NNN` (emitíveis) e `sup_NNN` (suprimidos, sempre `skip`), com invariante `sup_ ⟺ skip`;
- `step_role` (`overlay_noise`, `phantom_click`, `superseded_correction`, `redundant_refill`, `stale_panel_click`, `raw_duplicate_click`, `composite_select`), `suppression_reason`, `merged_from`, `source_events`, `original_index`, `sanitization_notes`, `has_text_original`, `selector_original`.

Todo este plano usa o schema real. O "passo exploratório" do enunciado = step `sup_NNN`/`skip` (ou, quando emitível mas discricionário, `optional`).

**Estado real do código (verificado por leitura direta, 2026-07-12):** a integração da Mudança A na Fase 4 **já está feita**:

- `validate_bot_against_plan` (`step_validator.py:349`) já valida por subsequência monotônica hint-aware, com `EXTRA_STEPS` calculado antes da ordem e tolerância `required_reopen` incluindo ids `skip`.
- `validate_resilience_patterns` (`step_validator.py:774`) já pula step `optional`/`skip` não emitido (guard na linha 892).
- `code_generator.py` já tem `_render_plan_for_prompt` (linha 205, seção "PASSOS SUPRIMIDOS" compacta), `_strip_internal_step_fields` estendido (linha 173) e o contrato de `execution_hint` nos três pontos de prompt.

Logo, **este plano é só a Mudança B** (geração híbrida). A Mudança A entra como *insumo consolidado*, não como trabalho a fazer.

---

## 1. Diagnóstico: por que a LLM ainda é gargalo na geração nova

Hoje `_generate_new_code` (`code_generator.py:807`) manda um prompt de ~15k+ tokens (playbook inteiro + dicionário + relatório + plano completo + 13 blocos de regras) e pede o arquivo inteiro. O Ralph Loop (`generate()`, linhas 517-805) existe porque a LLM erra exatamente as coisas que o prompt proíbe em caixa alta:

| Classe de erro observada | Evidência no código atual | Natureza |
|---|---|---|
| Ordem de step_ids embaralhada | `reorder_steps_to_match_plan` existe porque "30+ tentativas sem convergir" (`step_validator.py:1440-1443`) | 100% mecânica |
| Método alucinado (`select_native_resilient`) | autocorreção `difflib` em `code_generator.py:584-607` | 100% mecânica |
| `TransactionRunner` espúrio em corpo de função | `_strip_stray_transaction_runner_calls` (`code_generator.py:116`) | 100% mecânica |
| Boilerplate `__main__`/imports errado | `_normalize_boilerplate` (`code_generator.py:32`) reconstrói tudo | 100% mecânica |
| `value=` em vez de `text_val=`, falta `page` | `_validate_runner_call_contract` (`step_validator.py:260`) | 100% mecânica |
| coords/parent/HUMAN_LIKE/select ignorados | `validate_resilience_patterns` inteiro (`step_validator.py:774-1085`) | 100% mecânica |
| campo de dataset inventado | `validate_dataset_field_names` (`step_validator.py:717`) | 100% mecânica |
| `def` vazado em splice escopado | guard coluna-0 em `_surgical_correct_scoped` (`code_generator.py:1333`) | mecânica |
| `has_text` dinâmico (Padrão Q), decidir emitir `optional`, waits semânticos, Padrão N (menu `>>`), posicionamento de skills | regras 2/4/8 do prompt + contrato de fidelidade | **cognitiva** |

**Insight central do plano:** metade do `step_validator.py` é a especificação executável de como cada step do plano DEVE virar código. Se um validador consegue cobrar mecanicamente "step com `parent` ⇒ `click_chained(parent={...}, child={...})`", um emissor consegue GERAR isso mecanicamente. O emissor determinístico é a **inversão dos validadores**: mesma tabela de regras, sentido contrário. Por construção, o que ele emite passa nos validadores — e cada linha da tabela acima marcada "100% mecânica" deixa de existir como classe de falha na geração nova.

---

## 2. Arquitetura alvo do `_generate_new_code` (a linha de corte)

### 2.1 Novo módulo: `aegis_sanitizer/deterministic_emitter.py`

Python puro (f-strings/builders, zero dependência nova, compatível `>=3.8`). Sem Jinja: os blocos são curtos, e função Python testável unitariamente vale mais que template engine. API:

```python
class EmissionDecision(NamedTuple):
    kind: str      # "deterministic" | "cognitive" | "omit"
    reason: str    # log/manifest — por que caiu nessa rota

def classify_step(step: dict, dicionario: dict) -> EmissionDecision
def emit_step_block(step: dict, dicionario: dict) -> str      # bloco completo: "# [PASSO N] ..." + chamada(s) runner
def build_skeleton(plan: dict, dicionario: dict) -> tuple[str, dict]
    # retorna (código do execute_scenario_default com placeholders cognitivos, manifest)
```

Emissores por tipo (cada um espelha o check correspondente de `validate_resilience_patterns`):

| Emissor | Regras que aplica deterministicamente |
|---|---|
| `_emit_click(step)` | `click_resilient` ou `click_chained` (se `parent`), `parent`/`child` como dicts, `has_text` do plano, `original_coords` se `coords`, `step_id=`, `target_description=step["description"]` |
| `_emit_fill(step, field)` | `fill_resilient`/`fill_chained`; `text_val=row.get("<chave>", "")` resolvida por selector→chave via `dicionario.json`; `strategy="HUMAN_LIKE"` se `fill_strategy` do dicionário mandar, senão `"DIRECT"`; datas passam valor de `row` direto (regra 6 do prompt: NÃO converter é o default correto — o emissor implementa o default seguro por construção) |
| `_emit_select(step)` | `select_option_resilient` com `option_text=row.get(...)` (chave via dicionário quando houver; literal do plano NUNCA — mesma proibição de hardcode de hoje: se não há chave, o step é cognitivo, ver 2.2), `original_coords_trigger`/`original_coords_option` |
| `_emit_select_native(step)` | `select_option_native_resilient` idem |
| `_emit_async_guard(step, field)` | pós-fill: `time.sleep(2.0)` quando a chave semântica casa `r"cpf|cnpj|cep"` (mesma heurística da regra 8 do prompt, agora determinística) |
| `_emit_optional_wrapper(inner, step)` | envelopa bloco em `try/except` não-fatal (ver Seção 3) |

Boilerplate (header + `__main__`) NÃO é responsabilidade do emitter: `_normalize_boilerplate` já é o dono canônico disso e continua rodando sobre o resultado final — zero duplicação.

### 2.2 A linha de corte exata (`classify_step`)

Um step é **deterministic** somente se TODAS as condições valem; qualquer dúvida ⇒ **cognitive** (política conservadora — errar pro lado da LLM nunca regride vs. hoje):

| # | Condição para deterministic | Se falhar ⇒ |
|---|---|---|
| C1 | `type` ∈ {`click`, `fill`, `select`, `select_native`} | cognitive (`filechooser` e qualquer tipo futuro ⇒ cognitive) |
| C2 | `execution_hint` ausente ou `"required"` | `optional` ⇒ cognitive (decisão de emitir é da LLM, contrato D6); `skip` ⇒ **omit** (não gera slot nenhum) |
| C3 | Sem token dinâmico do Padrão Q no material OPERACIONAL do step: `parent.has_text_original` ausente (é lá que o campo vive — aninhado no `parent`, `sanitizer.py:1497-1503`, NÃO top-level do step) E nenhuma entrada de `sanitization_notes` com `padrao_q` referente a `parent.has_text`. **Notes `padrao_q` geradas para `fallback_selectors` NÃO contam** (achado 3.3 do plan-critic, 2026-07-12: `fallback_selectors` é campo interno que o emissor nem emite e que `_strip_internal_step_fields` já esconde da LLM — rebaixar o step por causa delas custaria chamadas LLM à toa). **Emenda 2026-07-13:** a classificação C3 em si NÃO muda, mas o gate H8 provou que "cair no slot cognitivo" não garantia a escolha certa — a Seção 3.3 emendada fecha o loop com prompt prescritivo (Q-a) + novo check `HARDCODED_PARENT_HAS_TEXT` (Q-b), gatilhado por `has_text_original` presente + `observed_value` no residual (mesma mecânica da C10) | cognitive (decidir entre literal sanitizado vs f-string com `row` exige julgamento — e, desde a emenda, a escolha é VERIFICADA, não só delegada) |
| C4 | Para step com valor de negócio, o binding resolve para exatamente UMA chave em `dicionario.json`, **por tipo** (achado I2 da rodada 2; precisão de `select_native` corrigida na re-checagem focada, achado R1): `fill` E `select_native` ⇒ `fields[*].selector == step.selector` (fallback `selector_original`) — `select_native` nasce de um evento `fill` em `<select>` (`sanitizer.py:1469-1471`) e carrega `selector` normal SEM `trigger_selector` (verificado: os 2 `select_native` reais de `katalon_demo_form/002` têm `trigger_selector: None` e o dicionário casa pelo `selector` `#role`); `select` (customizado/composite) ⇒ `fields[*].selector == step.trigger_selector` — os 15 steps `select` reais do projeto de referência têm `selector: ""` e o binding vive em `trigger_selector` (`trigger_selector` é campo interno escondido da LLM, mas o EMISSOR pode e deve usá-lo — o strip é para o prompt, não para o motor). Nota: NÃO existe casamento por `dropdown_label` — os fields do `dicionario.json` não têm essa chave (achado R2); a via `trigger_selector` resolve os casos reais. Sem essa regra por tipo, C4 casaria 18/18 fills mas 0/14 selects e os emissores `_emit_select`/`_emit_select_native` seriam inalcançáveis com dados reais | cognitive (binding ambíguo/ausente ⇒ inferência) |
| C5 | Se `weak_selector: true`: existe material de ancoragem mecânica (`parent.has_text` OU campo `text` do step para `:has-text(...)`) | cognitive (sem material, a ancoragem exige julgamento — e a LLM também não pode inventar seletor, então provavelmente vai cair no mesmo `WEAK_SELECTOR_WITHOUT_ANCHOR`; aceitável: é o comportamento de hoje) |
| C6 | Selector não casa heurística de menu suspenso do Padrão N (`.sub-menu`, `.dropdown-menu`, `#menu-item-`) | cognitive (reescrita em seletor composto `>>` exige escolha do ponto de corte) |
| C7 | Projeto sem skills (`skills_used` vazio) — condição GLOBAL, não por step | skills presentes ⇒ **arquivo inteiro cai no fluxo full-LLM atual** nesta v1 (o posicionamento de `run_skill_*` não tem step no plano para ancorar; ver Fora de escopo) |
| C8 | Step NÃO é referenciado por nenhuma correção pendente (achado 1.1 do plan-critic, 2026-07-12 — o mais importante da rodada): checar `c["step_id"]`, `c["required_reopen"]["after_step_id"]` e o alvo de `required_wait`/`required_method` de toda correção em `pending_corrections`. Sem isso, um step alvo de `required_wait` emitido na forma canônica do plano **viola a correção por construção** (`validate_required_wait_patterns`, `step_validator.py:1088`, exige loop de espera antes da chamada — que o emissor nunca gera) e falha a validação na tentativa 1 com culpa falsamente atribuída ao emissor pela política da Seção 5.2 | cognitive (a correção é justamente o caso onde a forma canônica não basta) |
| C9 | `fill` que NÃO precede autocomplete/opção dinâmica: o step emitível imediatamente seguinte no plano não é (a) `select`/`select_native`, NEM (b) `click` cujo seletor casa heurística de painel de opções (`autocomplete`, `mat-option`, `[role='option']`, `#mat-autocomplete-panel-*`, `listbox`). **Recalibrada na rodada 2 (achado I1):** a forma original ("seguinte é `select`") NUNCA dispararia para o padrão real — em todas as ocorrências reais verificadas (001_teste st_022→st_023; 005_teste005 st_017→st_018, st_020→st_021, st_023→st_024) o passo seguinte ao fill de autocomplete é um `click` no painel, não um `select`. Motivação original (achado 3.2 da rodada 1): regra 4/Padrão M do prompt atual (`code_generator.py:1022`) obriga HUMAN_LIKE para input que precede autocomplete **independente** de `fill_strategy` — julgamento hoje da LLM, que nenhum validador cobra. Nota factual da rodada 2: os bots de referência atuais usam `strategy="DIRECT"` nesses fills e são o baseline aprovado — a decisão HUMAN_LIKE vs DIRECT aqui é dependente do site | cognitive — ou, alternativa a decidir na implementação de H2: o emissor emite `strategy="HUMAN_LIKE"` por construção nesse padrão (validar com o cenário de autocomplete obrigatório do H8.2) |
| C10 | **(BLOQUEANTE B1 da rodada 2)** Nenhum valor de negócio embutido no SELETOR operacional do step: o seletor (e o `child` derivado dele) não contém `:has-text(<literal>)` cujo literal case algum `observed_value` de `dicionario.json`, E o campo `text` do step também não casa nenhum `observed_value`. Caso real que escapava de C1-C9: `st_023` do 001_teste, `selector: "#mat-autocomplete-panel-marca div:has-text('Hyundai')"` com `parent.has_text: null` — 'Hyundai' é `observed_value` de `marca_veiculo`, e o bot LLM atual parametriza (`child={"selector": f"div:has-text('{row.get('marca_veiculo', '')}')"}`). Emitir o literal seria hardcode que NENHUM validador pega (`HARDCODED_TEXT_VAL` só inspeciona kwarg `text_val`, `step_validator.py:336-344`; `MISSING_PARENT_HAS_TEXT` não dispara com `has_text` nulo; dry run usa runner fake) e só falha em execução real com dataset variado. Checagem mecânica e barata: os `observed_value` já estão no dicionário | cognitive (parametrizar seletor com `row` é exatamente o tipo de composição que fica com a LLM) |

**`flaky` (decisão explícita — achado 1.3):** campo QA-facing gravado pelo endpoint da Cockpit no plano e herdado entre re-sanitizações; hoje não existe NENHUM contrato de geração para ele (zero ocorrências em `code_generator.py`/`step_validator.py` — a LLM o vê no JSON mas nada o cobra). No híbrido, `flaky` é **pass-through**: não participa da classificação nem altera o bloco emitido — comportamento efetivamente idêntico ao atual. Se um dia ganhar contrato (ex.: timeout maior), entra como regra nova no emissor E no validador juntos (invariante do round-trip 4.1).

Overrides operacionais: `AEGIS_CODEGEN_HYBRID` (`true`/`false`, master switch) e `AEGIS_CODEGEN_FORCE_LLM_STEPS="st_004,st_017"` (rebaixa steps específicos para cognitive sem tocar código — vital para depurar piloto real).

### 2.3 Fluxo novo dentro de `_generate_new_code`

```
1. plan + dicionario carregados (como hoje)
2. Se AEGIS_CODEGEN_HYBRID=false OU skills_used OU plano ausente → fluxo full-LLM ATUAL, byte-idêntico (rota preservada, não deletada)
3. decisions = {step_id: classify_step(s)}   →  log 1 linha/step + manifest
4. skeleton, manifest = build_skeleton(plan, dicionario)
   - blocos deterministic: código final, com "# [PASSO N] descrição" + step_id
   - blocos cognitive: placeholder ancorado E PARSEÁVEL pela maquinaria
     existente (achado I7 da rodada 2 — _STEP_ID_IN_BLOCK_RE,
     code_generator.py:1127, exige literalmente `step_id="..."` no texto do
     bloco, e _build_scoped_edit_plan ignora blocos com step_id None,
     code_generator.py:1178-1183; um placeholder sem essa forma faria TODO
     slot cair silenciosamente em fallback full-LLM):
         # [PASSO N] <descrição>
         # AEGIS_COGNITIVE_SLOT step_id="st_014" motivo="<reason da classificação>"
         pass
     (o `step_id="st_014"` dentro do comentário satisfaz o regex existente —
     nenhuma mudança em _parse_step_blocks necessária; o `pass` mantém o
     arquivo sintaticamente válido entre os passos 4 e 5)
   - steps skip/sup_: nada (contrato v2 vigente: não emitir por default)
5. Se houver slots cognitivos: UMA chamada LLM pedindo SOMENTE esses blocos,
   no formato BEGIN_STEP/END_STEP — generalização de _surgical_correct_scoped
   (nova função _generate_scoped_blocks, extraída/parametrizada da atual):
   prompt = playbook (seções relevantes) + fatia do plano dos slots
   (_render_plan_for_prompt, já existente) + blocos vizinhos já emitidos como
   contexto SOMENTE-LEITURA + dicionário + regras cognitivas (Padrão Q/N,
   contrato optional) + **as entradas de `pending_corrections` cujo `step_id`
   (ou `required_reopen.after_step_id`) esteja entre os slots, na mesma
   renderização de `_surgical_correct` (`code_generator.py:1360-1418` —
   qa_insight, tentativas fracassadas, correção requisitada)**. Achado I3 da
   rodada 2: sem isso a C8 é autossabotada — o step vai para a LLM POR CAUSA
   da correção (`required_wait` exige loop de espera que a forma canônica não
   tem), mas a LLM não veria a correção e falharia a validação na tentativa 1
   do mesmo jeito. Splice por substituição de linhas; guard coluna-0
   def/class reutilizado verbatim.
   **Convenção de omissão para `optional` (achado I4):** a LLM que decidir
   NÃO emitir um step optional retorna o par delimitador com bloco-vazio
   explícito:
         # BEGIN_STEP st_014
         # [PASSO N] <descrição>
         # AEGIS_COGNITIVE_SLOT step_id="st_014" motivo="optional não emitido: <justificativa curta>"
         # END_STEP st_014
   O splice aceita (não é "slot faltando"), registra
   `provenance: "cognitive", reason: "optional_omitted"` no manifest, e o
   validador já tolera a ausência (guard optional/skip). Sem essa convenção,
   todo plano com `optional` dispararia fallback full-LLM sistemático,
   anulando o híbrido exatamente onde ele mais interessa. O comentário-slot
   remanescente mantém `step_id="..."` parseável caso uma correção futura
   precise ancorar o bloco.
6. Resposta faltando algum slot (sem par BEGIN/END nem bloco-vazio) OU splice
   inválido → fallback full-LLM na MESMA tentativa (mesma semântica do
   fallback escopado→full de hoje, code_generator.py:1501-1505).
7. Arquivo completo entra no pipeline EXISTENTE sem mudança:
   _validate_syntax → _normalize_boilerplate → validadores → dry_run → Ralph.
```

Zero slots cognitivos ⇒ **zero chamadas LLM** na geração nova (fora compilação de skills). Prompt da chamada única (quando existe) cai de "arquivo inteiro + plano inteiro" para "N blocos + fatia". **Ressalva operacional (achado M2 da rodada 2):** o gate `gateway.is_active()` no início de `generate()` (`code_generator.py:272-279`) continua exigindo `AEGIS_COGNITIVE_ENABLED=true` + API key mesmo num projeto 100% determinístico — a Fase 4 nem inicia sem gateway. Nesta v1, documentar (o custo é zero chamadas, não zero configuração); relaxar o gate quando híbrido-sem-slots fica como melhoria futura consciente, não omissão.

### 2.4 Manifest de proveniência: `code/generation_manifest.json`

Gravado ao lado de `bot_producao.py` (mesmo padrão de `index_arquivos.json` — artefato de projeto, nunca no core):

```json
{
  "generator_version": "hybrid-1",
  "generated_at": "...",
  "steps": {
    "st_001": {"provenance": "deterministic", "reason": "click simples", "block_sha1": "..."},
    "st_014": {"provenance": "cognitive", "reason": "padrao_q token dinâmico"},
    "st_020": {"provenance": "cognitive_patched", "reason": "corrigido por QA em 2026-07-12"}
  }
}
```

`block_sha1` = hash do texto do bloco (delimitação por `_parse_step_blocks`, que já existe) no momento da escrita. Usos (revisado 2026-07-12, achado 2.1): **telemetria e forense apenas** — quanto do bot é determinístico, e `aegis-pipeline-forensics` ganha um elo novo na cadeia. A política anti-drift da Seção 5.2 usa só `provenance` (o restore é incondicional e regenera o bloco via `emit_step_block`, sem comparar hash). Manifest ausente/corrompido ⇒ todas as políticas que dependem dele degradam para o comportamento atual (nunca é pré-requisito).

**Ciclo de vida do manifest (achado I5 da rodada 2 — sem isto, manifest STALE arma o restore contra um bot que nunca foi híbrido):** TODA rota de geração bem-sucedida termina escrevendo o manifest — a rota híbrida escreve o manifest real; a rota full-LLM (flag off, skills, plano ausente, fallback) escreve `{"generator_version": "full-llm", "steps": {}}` por cima do que existir. `steps` vazio ⇒ `_restore_deterministic_blocks` é no-op por construção. Cenário que isso previne: geração híbrida (manifest gravado) → skill adicionada ao projeto → regeneração full-LLM (sem esta regra, manifest antigo fica em disco) → ciclo cirúrgico posterior re-spliceando blocos canônicos por cima de código 100% LLM. Guarda adicional: o manifest carimba `plan_checksum` (sha1 do `plano_execucao.json` usado na geração); `_restore_deterministic_blocks` degrada para no-op se o checksum não bater com o plano atual — cobre re-sanitização que renumera step_ids (fluxo corriqueiro, working agreement nº 4) sem regeneração intermediária.

---

## 3. Tradução da telemetria rica em código

### 3.1 Steps `skip` (`sup_NNN`) — NÃO viram código na geração nova

Decisão já tomada e implementada na Mudança A (D6) e este plano a mantém: o motor determinístico **omite** `sup_` (nem placeholder). Eles chegam à LLM só como a seção compacta "PASSOS SUPRIMIDOS" quando há slots cognitivos (via `_render_plan_for_prompt`, inalterada). Reintrodução acontece exclusivamente pelo ciclo de correção:

- **Rota LLM (existente):** correção pendente/QA justifica ⇒ LLM emite o `sup_NNN` com o id do plano; validadores já aceitam (subsequência + `planned_set_for_reopen`).
- **Rota determinística (NOVA, barata e cobre o caso nº 1 real — fechar overlay):** uma entrada de `correcoes_acumuladas.json` pode carregar `"reintroduce_step_id": "sup_003"`. O gerador, ao ver isso, insere deterministicamente o bloco do `sup_003` (emitido por `emit_step_block` + `_emit_optional_wrapper`) na posição relativa correta do plano — sem LLM. QA marca isso na Cockpit hoje já conseguindo apontar `sup_` (mark-failed começa em `cockpit.py:1630` e casa por string em `cockpit.py:1664-1665` — `str(step.get("step_id")) == str(step_id)`; no endpoint `/flaky`, em `cockpit.py:1614`. Citação corrigida na revisão de 2026-07-12 — a versão anterior apontava 1597/1654, linhas erradas do mesmo arquivo); adicionar o campo é mudança de dado, não de UI.

### 3.2 Steps `optional` — LLM decide; se emitido, bloco não-fatal padronizado

Um step que o próprio Sanitizer classificou como discricionário não pode derrubar a transação quando o elemento não existe naquela execução. Template canônico (usado tanto pela LLM — exigido via prompt — quanto pela rota determinística de reintrodução):

```python
# [PASSO 7] Fechar overlay residual (optional/sup_003 — não-fatal)
try:
    runner.click_resilient(page, selector=".cdk-overlay-backdrop",
                           target_description="Fechar overlay residual",
                           step_id="sup_003")
except Exception as _opt_err:
    print(f"[BOT] Passo opcional sup_003 pulado (não-fatal): {_opt_err}")
```

Por que `try/except` no código gerado e **não** um kwarg `optional=True` no runner nem `strict=` condicional:

- `aegis_runner/runner.py` fica com **zero bytes de mudança** (invariante herdado do plano do Sanitizer; mexer no runner puxa gate de regressão + risco em bots já compilados).
- `strict` controla healing cognitivo, não fatalidade — semanticamente errado para "pode não existir".
- **Compatibilidade provada com a máquina existente (verificado no código):** `extract_step_ids_from_code` usa `ast.walk` + ordenação por `(lineno, col)` (`step_validator.py:46-67`) — acha a chamada dentro do `Try`; `reorder_steps_to_match_plan` agrupa por statement de nível de função e `_extract_step_id_from_stmt` também usa `ast.walk` (`step_validator.py:1427`) — o `Try` inteiro se move como um bloco; `_parse_step_blocks` delimita por comentário-âncora — o `try` fica dentro do bloco; dry run chama a função com runner fake — o `except` nunca mascara erro de alucinação porque `MagicMock` não levanta (e um NameError DENTRO do try seria engolido — por isso o template do except imprime o erro E o teste de round-trip da Seção 4 valida o template, não confia nele).
- Risco residual "except engole falha genuína": aceitável por definição — o step é *opcional*; o runner já logou a falha interna dele; e o `print` do template deixa rastro no stdout que a Cockpit captura.

Um step `required` NUNCA recebe o wrapper — fatalidade de required é contrato do runner e não muda.

### 3.3 Padrão Q (`has_text_original` ≠ `has_text`) — sempre cognitivo, agora com loop de verificação fechado (EMENDADA 2026-07-13)

O emissor nunca decide sozinho entre o literal sanitizado e uma composição dinâmica com `row`. O slot cognitivo recebe, na fatia do plano, os dois valores + `sanitization_notes` (já expostos pós-strip — `_strip_internal_step_fields` mantém `has_text_original`/`sanitization_notes` visíveis de propósito, `code_generator.py:190-193`).

**EMENDA 2026-07-13 (rodada 3, pós-reprovação do gate H8/[SUBAGENTE 10]) — a premissa "Nada a mudar" da versão anterior desta seção estava ERRADA.** Ela fechava com: "o validador `MISSING_PARENT_HAS_TEXT` já aceita `has_text` dinâmico via `dict_dynamic_keys` (`step_validator.py:979-987`). Nada a mudar". Aceitar o dinâmico não basta: o validador aceita o LITERAL como igualmente válido, e o prompt do slot autoriza explicitamente a escolha do literal — a combinação produz exatamente o hardcode que a C10 elimina no seletor, só que no `has_text` do parent.

**Achado (gate H8, 2/2 regenerações independentes, evidência preservada em `scratchpad/evidence_subagente10/`):** `st_062` do projeto de referência (`projects/portal_segura/tests/001_teste/plano_execucao.json` — `parent.has_text: "daniel setttt 22401666818 FIPE"`, `parent.has_text_original: "PRO-80935 daniel setttt 22401666818 FIPE"`, note `"padrao_q: removido token 'PRO-80935'"`) é corretamente classificado cognitive via C3, mas o slot gerado saiu `parent={"selector": ".mat-row", "has_text": "daniel setttt 22401666818 FIPE"}` (literal gravado) em vez da composição dinâmica do baseline (`f"{row.get('nome_cliente', '')} {row.get('cpf_cliente', '')} FIPE"`). O bot passa em TODOS os validadores e no dry run; com dataset de 2+ linhas mira sempre o cliente gravado — mesma classe de bug da C10/B1, na variante `parent.has_text`.

**Por que aconteceu (três brechas que se reforçam, verificadas no código):**

1. `MISSING_PARENT_HAS_TEXT` (`step_validator.py:983-987`) aceita `code_has_text == plan_has_text` (literal) E `plan_has_text in code_selector` (literal embutido no seletor do parent) como equivalentes a `"has_text" in code_parent_dynamic_keys` (dinâmico) — não distingue "a LLM copiou o literal" de "a LLM reconstruiu dinamicamente e por acaso bate".
2. O prompt do slot cognitivo (`_render_hybrid_slots_context`, `code_generator.py:1393-1398`) instrui literalmente "decida entre usar o literal sanitizado OU compor `has_text` dinamicamente com `row.get(...)` — julgamento seu", AUTORIZANDO o caminho mais barato — e contradizendo a "Proibição absoluta de hardcode" três parágrafos abaixo no MESMO prompt (`code_generator.py:1404-1405`). A LLM resolveu a contradição pela regra permissiva.
3. O próprio texto do erro `MISSING_PARENT_HAS_TEXT` (`step_validator.py:992-1000`) sugere o literal como correção válida ("...nem via `parent={'selector': ..., 'has_text': '<literal>'}`..."). Endurecer o check sem trocar a mensagem entregaria ao retry uma instrução que manda fazer exatamente o que o check passou a rejeitar.

**Estrutura de retry relevante (por que endurecer SÓ o validador oscilaria):** a chamada de slots cognitivos é single-shot — `_generate_new_code_hybrid` → `_generate_scoped_blocks(mode="write")` uma única vez, sem retry interno (`code_generator.py:1330-1339`; resposta malformada ⇒ fallback full-LLM na mesma tentativa, não re-tentativa do slot). Reprovação nos validadores manda a tentativa ≥2 do Ralph para `_surgical_correct_with_reflection` (`code_generator.py:599`), cujo ÚNICO sinal novo para a LLM é o JSON dos erros da tentativa anterior (`code_generator.py:2663-2666`) — o prompt de slots com as regras cognitivas NÃO é re-renderizado no retry. Conclusão: **o `detail` do erro É a instrução de correção**; um endurecimento mudo (rejeitar sem prescrever) repetiria o padrão de oscilação do working agreement nº 5.

**Correção (as DUAS frentes, com o endurecimento refinado):**

- **Q-a — prompt prescritivo (`_render_hybrid_slots_context`, `code_generator.py:1393-1398`):** substituir a regra permissiva do Padrão Q por regra prescritiva: quando o step tem `parent.has_text_original` (≠ `has_text`) E o literal residual de `has_text` contém um ou mais `observed_value` do `dicionario.json`, a composição DEVE ser dinâmica — f-string com `row.get("<chave>", "")` das chaves cujos `observed_value` aparecem no literal, preservando o texto estático residual (ex.: `"FIPE"`) como literal dentro da f-string. O literal puro só é aceitável quando NENHUM `observed_value` casa (residual 100% estático). De quebra, elimina a contradição interna com a "Proibição absoluta de hardcode" do mesmo prompt.
- **Q-b — novo check em `validate_resilience_patterns` (`step_validator.py`), erro novo `HARDCODED_PARENT_HAS_TEXT`** (tipo NOVO, não reutilizar `MISSING_PARENT_HAS_TEXT` — modo de falha diferente e mensagem OPOSTA à atual). **Gatilho:** step com `parent.has_text_original` presente E `plan_has_text` contendo ≥1 `observed_value` do dicionário (mesma mecânica da C10; o dicionário já está carregado dentro da função — `step_validator.py:797-803` — zero mudança de assinatura). Sob o gatilho, `code_has_text == plan_has_text` E `plan_has_text in code_selector` deixam de ser prova válida — exige `"has_text" in code_parent_dynamic_keys`. Fora do gatilho, o comportamento atual fica intacto (steps sem Padrão Q, e Padrão Q com residual estático, continuam aceitando literal — que é correto para eles). **O `detail` DEVE nomear as chaves candidatas derivadas mecanicamente** (substring de `observed_value` no literal — verificado ao vivo contra o projeto de referência E o golden: para `st_062` deriva exatamente `nome_cliente` + `cpf_cliente`) **e prescrever a forma f-string com `row.get(...)`** — pela estrutura de retry acima, esse texto é a única instrução nova que a LLM verá na tentativa seguinte. O erro carrega `step_id` naturalmente (mesmo loop por step dos demais checks — `step_validator.py:888-889`, padrão idêntico ao `step_id` de `MISSING_PARENT_HAS_TEXT` em `step_validator.py:991`) — working agreement nº 5 satisfeito.

**Por que o gatilho é refinado (`has_text_original` + observed_value, e não "qualquer note padrao_q"):**

1. Existe caso legítimo de literal pós-Padrão Q: residual 100% estático (a note só registra que um token dinâmico foi removido; nada garante que o restante seja dado de negócio). Exigir dinâmico aí empurraria a LLM a inventar composição sem matéria-prima — oscilação no sentido oposto.
2. A note real de `st_062` é `"padrao_q: removido token 'PRO-80935'"` — NÃO contém a substring `has_text`; gatilho por texto da note seria frágil. O sinal confiável é `parent.has_text_original` presente — o mesmo sinal primário que a C3 já usa (`deterministic_emitter.py:570`).
3. Reduz o blast radius nos testes (abaixo): a fixture `st_005` da matriz sintética não dispara sob o gatilho refinado, mas dispararia sob "qualquer padrao_q".

**Derivação das chaves é mecânica; a COMPOSIÇÃO continua interpretativa:** o casamento `observed_value` ⊂ literal residual deriva QUAIS chaves participam (mecânico) — mas a montagem (ordem dos tokens, separadores, residual estático embutido) continua trabalho da LLM. Por isso o Padrão Q PERMANECE cognitivo (C3 inalterada): a emenda não move a decisão para o emissor, ela fecha o loop de instrução (Q-a) e verificação (Q-b) em volta do slot.

**CORREÇÃO rodada 4 — "mesma mecânica da C10" é impreciso (a direção do casamento é INVERTIDA):** a C10 do emissor casa por PERTINÊNCIA EXATA — extrai o literal de `:has-text('...')` do SELETOR e testa `literal ∈ observed_values` (`deterministic_emitter.py:643`), idem para o campo `text` (`:650`). Q-b precisa de SUBSTRING (`∃ observed_value : observed_value ⊂ plan_has_text`), porque `parent.has_text` é COMPOSTO (`"daniel setttt 22401666818 FIPE"` — nome+cpf+estático), nunca um `observed_value` inteiro (por isso `has_text ∈ observed_values` = False para st_062, confirmado ao vivo — e é exatamente por isso que a C10 atual não pega este caso e Q-b é necessário). Consequências que a redação "mesma mecânica" obscurece: (a) só `_collect_observed_values` (`deterministic_emitter.py:452`) é reusável para COLETAR os valores; o casamento por substring + a derivação de chaves é código NOVO em `step_validator.py`, não reuso mecânico (e importar do emissor inverteria a dependência conceitual validador→emissor — reimplementar o coletor de 6 linhas é aceitável); (b) substring tem risco de falso-positivo que pertinência exata não tem — `observed_value` curtos do próprio dicionário de referência (`'Sim'`=condutores_jovens, `'2026'`=ano_modelo E ano_fabricacao, `'50000'`=limite_danos_*) podem casar por acaso um residual Padrão Q futuro e derivar chaves erradas/ambíguas (`'2026'` mapeia DUAS chaves — a promessa "deriva exatamente as chaves" só vale por sorte no st_062). Nenhum falso-positivo nos goldens atuais (verificado), mas o `detail` prescritivo deve tolerar match vazio/ambíguo (degradar para a proibição genérica de hardcode em vez de nomear chave errada), e vale considerar exigir limite mínimo de comprimento/limite de palavra no substring.

**Blast radius verificado (suítes, por inspeção + grep):**

- `test_deterministic_emitter.py`: o round-trip força C3 a deterministic e DOCUMENTA a dependência do comportamento antigo (comentário nas linhas ~598-603: o Padrão Q forçado "emite o has_text JÁ SANITIZADO — que é literalmente o que MISSING_PARENT_HAS_TEXT compara — mesmo sendo a escolha 'errada'"). Sob o gatilho refinado, `st_062` do golden v2 DISPARA (o golden v2 empresta o `dicionario.json` do diretório v1 via `GOLDEN_CASES` `test_deterministic_emitter.py:687-692`, que tem `nome_cliente`/`cpf_cliente` casando o literal por substring — verificado ao vivo). **CORREÇÃO rodada 4 — o conserto NÃO é "1 ajuste de fixture"; são 2 edições coordenadas + 1 comentário, senão o round-trip fica VERMELHO:** (i) adicionar a `st_062` a `_KNOWN_COGNITIVE_ONLY_STEP_IDS["real_portal_segura_001_v2"]` (linha ~620) SOZINHO é INSUFICIENTE — esse set só rebaixa o `execution_hint` da CÓPIA do plano para `optional`, mas `_force_classify_where_possible` (`test_deterministic_emitter.py:631-676`) continua forçando `st_062` a `deterministic` (ele só desvia p/ cognitive em C1/C4/C5/C10; NÃO tem ramo de Padrão Q), então um bloco REAL `click_chained(parent={..., "has_text": "daniel setttt 22401666818 FIPE"}, ..., step_id="st_062")` é emitido no skeleton, `st_062` entra em `code_ids`, e o guard optional-skip de `step_validator.py:892` (`execution_hint in (optional,skip) AND step_id not in code_ids`) NÃO o pula (está em `code_ids`) ⇒ `HARDCODED_PARENT_HAS_TEXT` dispara e `test_round_trip_zero_errors_against_all_validators` REPROVA (confirmado por simulação empírica contra o golden v2). (ii) O conserto correto exige TAMBÉM adicionar um ramo de Padrão-Q-com-valor-de-negócio a `_force_classify_where_possible` (retorna `cognitive` — mesma detecção `has_text_original` + `observed_value` substring da nova regra Q-b), para que `st_062` vire PLACEHOLDER cognitivo (fora de `code_ids`, como já ocorre com `st_023`/`st_011` de C10); só aí o par (i)+(ii) funciona (categoria "genuinamente impossível de forçar", working agreement nº 3). (iii) Atualizar o comentário longo `test_deterministic_emitter.py:605-614` que enumera as impossibilidades genuínas (hoje "3 clicks de autocomplete... (C10)") para incluir a 4ª categoria (valor de negócio em `parent.has_text` sob Padrão Q). `st_005` da matriz NÃO dispara (`has_text` residual `'cliente exemplo 12345678900 categoria'` não contém nenhum `observed_value` da fixture — `'Casado(a)'`/`'Pleno'`/`'Curitiba'`; verificado ao vivo) ⇒ intacto, e vira de graça o teste do caso "residual sem valor de negócio continua aceitando literal".
- `test_step_validator_hints.py`, `test_sanitizer_execution_plan.py`, `test_hybrid_generation.py`: zero ocorrências de `MISSING_PARENT_HAS_TEXT`/`padrao_q`/`has_text` (grep) — não afetados.
- **Célula nova obrigatória na matriz do round-trip (Seção 4.1):** fixture "Padrão Q com valor de negócio no residual" (forma do `st_062`) forçada a deterministic DEVE reprovar com `HARDCODED_PARENT_HAS_TEXT`, e a asserção DEVE cobrar que o `detail` contém as chaves derivadas — trava o contrato da mensagem prescritiva (sem isso, um refactor futuro que emudecesse o `detail` re-armaria a oscilação silenciosamente).

**A correção vale para o pipeline TODO, não só o híbrido:** `validate_resilience_patterns` é chamada uma única vez no loop compartilhado do `generate()` (`code_generator.py:765`) — a rota full-LLM sempre teve a mesma brecha (o baseline não a exibiu porque a LLM acertou por conta própria, não porque algo a impedia). Q-b fecha a brecha para as duas rotas; Q-a cobre a rota híbrida (a full-LLM tem a proibição de hardcode no prompt de arquivo inteiro e agora passa a ter o check mecânico por trás).

**Scope-note rodada 4 — Q-b NÃO fecha o hazard inteiro, só o subconjunto Padrão Q:** o gatilho exige `parent.has_text_original` presente. O golden v1 `real_portal_segura_001/plano_execucao.json` st_062 carrega o MESMO literal perigoso `parent.has_text: "daniel setttt 22401666818 FIPE"` (nome+cpf de negócio) SEM `has_text_original` (nenhum token foi removido, então o sanitizer não gravou transformação Padrão Q) — verificado ao vivo. Nesse caso NEM a C3 (não classifica cognitive: sem `has_text_original` e sem note `padrao_q`), NEM a C10 (só inspeciona `:has-text()` no seletor e o campo `text`, não `parent.has_text`), NEM a Q-b (exige `has_text_original`) o pegam ⇒ seria emitido deterministicamente como hardcode, intacto. Portanto a afirmação acima "Q-b fecha a brecha para as duas rotas" vale APENAS para o subconjunto com `has_text_original`; o hazard geral "valor de negócio composto em `parent.has_text`" continua aberto quando o sanitizer não registrou Padrão Q. Manter o gatilho por `has_text_original` é um trade-off legítimo (chavear puramente por `observed_value ⊂ parent.has_text` pegaria o v1 mas alargaria o blast radius do round-trip — v1-st_062 passaria a reprovar também), mas o plano deve declarar o resíduo em vez de alegar fechamento total. Fechar o hazard geral (irmão da C10/B1 para `parent.has_text`) fica como item consciente fora de escopo desta rodada.

**O que NÃO muda:** a classificação C3 (Padrão Q ⇒ sempre cognitive) está correta e fica como está — o slot continua sendo da LLM. Continua valendo documentar no playbook que este é um dos poucos pontos onde a LLM ainda escreve código — agora com a regra prescritiva de Q-a, não com "julgamento seu".

**Ordem de implementação e re-gate:** Q-a + Q-b + ajustes de teste entram como tarefa única (blast radius pequeno e interdependente: o novo `detail` e o novo texto de prompt devem contar a MESMA história); depois, re-execução INTEGRAL de [SUBAGENTE 10]/H8 desde o passo 1 — a reprovação foi no passo 1, e os passos 2-5 nunca rodaram.

---

## 4. Adaptação do `step_validator.py`

A boa notícia estrutural: **os validadores quase não mudam** — a Mudança A já os deixou hint-aware, e blocos `try/except` já são transparentes para eles (Seção 3.2). O que este plano adiciona:

### 4.1 Teste de round-trip (o gate novo mais importante)

Novo `aegis_sanitizer/test_deterministic_emitter.py`:

1. Para cada plano golden (`.specs/golden/`): `build_skeleton` com TODOS os steps forçados a deterministic (fixtures onde isso é possível) ⇒ o arquivo resultante (pós `_normalize_boilerplate`) deve passar com **zero erros** em `validate_bot_structure`, `validate_bot_against_plan`, `validate_resilience_patterns`, `validate_dataset_field_names` E em `dry_run_bot`. **Atenção ao inventário real dos goldens (achado 1.2 do plan-critic, verificado por inspeção direta em 2026-07-12):** `real_portal_segura_001/plano_execucao.json` é v1 PURO (63 steps, zero `execution_hint`, zero `sup_`) e `synthetic_r1_merge_case/plano_execucao_esperado.json` é v2 com apenas 2 steps (1 `st_` + 1 `sup_ skip`) — sem `optional`, sem `parent`, sem `select`, sem `coords`, sem `weak_selector`, sem `padrao_q`. Rodar o round-trip só contra esses dois faria o "gate central" passar VAZIO em toda a matriz v2. Pré-requisito obrigatório (executado em H0): capturar um golden v2 rico.
2. Fixture com step `optional` emitido via `_emit_optional_wrapper` ⇒ mesmos validadores PASS + `reorder_steps_to_match_plan` aplicado a uma versão embaralhada reordena o `Try` como unidade sem quebrar sintaxe.
3. Fixture `sup_` reintroduzido via `reintroduce_step_id` ⇒ `validate_bot_against_plan` PASS (subsequência) — prova mecânica do contrato D6.
4. **Célula obrigatória da matriz (achado B1 da rodada 2):** fixture "click de opção de autocomplete com valor de negócio no seletor" (forma do `st_023` real: `div:has-text('<observed_value>')`, `parent.has_text` nulo) ⇒ `classify_step` DEVE retornar cognitive via C10. Teste negativo do emissor: nenhum bloco emitido deterministicamente pode conter `:has-text(<literal>)` cujo literal case um `observed_value` do dicionário (varredura pós-emissão sobre a saída do round-trip inteiro — pega qualquer regressão futura de C10 por qualquer rota).

Qualquer divergência emissor×validador é, por definição, bug de um dos dois — e este teste transforma a "spec espelhada" (Seção 1) em invariante executável permanente: quem mudar um check de `validate_resilience_patterns` no futuro quebra o round-trip na hora se esquecer o emissor (e vice-versa).

### 4.2 Regra de `lineno` (working agreement nº 5 — vale para tudo que este plano criar)

Nenhum check novo entra sem `step_id` ou `lineno`/`linenos` no dict de erro, senão fica invisível para o escopo cirúrgico (`live_error_step_ids`, `code_generator.py:1468-1487`). Vale inclusive para os erros internos do próprio emitter quando reportados no Ralph (Seção 5.2).

### 4.3 O que deliberadamente NÃO muda

`validate_bot_against_plan` (subsequência pronta), `validate_resilience_patterns` (guard pronto), `extract_step_ids_from_code`, `reorder_steps_to_match_plan`, `dry_run_bot`, todos os `validate_required_*`. **Nenhum falso-positivo novo é esperado porque o único formato novo de código (bloco `try/except` opcional) já é transparente ao AST-walk desses validadores** — e o teste 4.1(2) prova isso em vez de assumir.

---

## 5. Blindagem da correção cirúrgica (`_surgical_correct`)

### 5.1 O híbrido MELHORA as âncoras, não as ameaça

`_build_scoped_edit_plan` cai no fallback de arquivo inteiro quando: sem anchors, target ausente, ou step_id duplicado (`code_generator.py:1163-1205`). Hoje esses três casos dependem da disciplina da LLM. Com o emissor determinístico, `# [PASSO N]` + `step_id=` únicos são **garantidos por construção** para todo bloco deterministic — o modo escopado passa a estar sempre disponível em bots híbridos. Exigência de implementação: `build_skeleton` numera `# [PASSO N]` sequencialmente e nunca repete step_id (assert interno).

### 5.2 Política anti-drift no Ralph Loop (manifest + hash)

Problema a prevenir: na tentativa ≥2, `_surgical_correct_with_reflection` deixa a LLM tocar no arquivo; ela pode "melhorar" um bloco determinístico correto (classe de drift já catalogada em PROBLEMA_ST055). Nova etapa determinística no `generate()`, logo após `_normalize_boilerplate` de cada tentativa (**simplificada na revisão de 2026-07-12, achado 2.1: restore INCONDICIONAL, sem comparação de hash** — `emit_step_block` é determinístico, então re-splicear o bloco canônico é idempotente; comparar sha1 antes era otimização prematura que dobrava os modos de falha da política):

```
_restore_deterministic_blocks(bot_code, manifest, target_scope):
  restored = []
  para cada step com provenance == "deterministic" e step_id ∉ target_scope
  (target_scope = target_step_ids da correção corrente + live_error_step_ids
   + after_step_id de todo required_reopen pendente — achado M1 da rodada 2:
   a chamada de re-disparo exigida por validate_required_reopen_patterns
   precisa ficar entre after_lineno e target_lineno, região que textualmente
   pertence ao bloco do after_step_id; num fallback full-file a LLM
   legitimamente insere o re-disparo no fim desse bloco, e um restore que não
   o poupasse removeria a inserção ⇒ MISSING_REOPEN_PATTERN ⇒ oscilação):
     bloco_atual = _parse_step_blocks(...) lookup por step_id
     se bloco_atual é None:            # bloco AUSENTE (âncora removida em rewrite full-file)
         continue                       # NÃO é caso de restore — ver regra abaixo
     canonico = emit_step_block(step, dicionario)   # regenerado, não armazenado
     se bloco_atual.text != canonico:
         re-splice de `canonico` no lugar; restored.append(step_id)
  retorna (novo_codigo, restored)
```

`block_sha1` continua existindo no manifest **apenas como telemetria/forense** — nenhuma decisão de lógica depende dele.

Regras da política (reescritas na revisão de 2026-07-12 — achados 1.1 e 1.4):

- **Fail-fast restrito à adulteração efetivamente revertida E a erros de CONTEÚDO:** `RuntimeError` ("bug no deterministic_emitter para st_XXX — não gaste tentativas de LLM") dispara SOMENTE quando (a) o erro de validação aponta para um step_id que está em `restored` **nesta mesma tentativa** — o bloco estava na forma canônica recém-restaurada e mesmo assim falhou — E (b) o tipo do erro é de conteúdo do bloco: padrões de resiliência (`MISSING_*`, `INVALID_CHAINED_LOCATOR_SHAPE`, `WEAK_SELECTOR_WITHOUT_ANCHOR`...) ou contrato de chamada. Erros de dry-run NÃO participam do fail-fast nesta v1 (achado R3 da re-checagem: os erros de `dry_run_bot` não carregam `lineno` — `step_validator.py:1750-1758`, só `type`/`exception_type`/`detail` — então não há como atribuí-los a um bloco; comportamento resultante é conservador, sem falso-positivo; se um dia o dry-run ganhar `lineno`, a regra 4.2 deste plano já cobra o campo e a inclusão aqui é natural). **Erros de ORDEM/CONTAGEM (`STEP_ID_MISMATCH`, `COUNT_MISMATCH`, `MISSING_STEPS`, `EXTRA_STEPS`) NUNCA disparam o fail-fast** (achado I6 da rodada 2): num rewrite full-file de reflection a LLM pode mover um bloco deterministic — o restore o reverte NO LUGAR MOVIDO, e o erro de ordem causado pelo layout que a LLM deu aos OUTROS blocos aponta `found_id`/`expected_id` para o bloco restaurado, que não tem culpa nenhuma; além disso a reordenação automática (`code_generator.py:667-669`) só roda quando `error_types ⊆ {STEP_ID_MISMATCH}`, então com erros mistos a ordem não é limpa antes do julgamento. A versão original desta regra ("qualquer erro em bloco deterministic após o restore ⇒ bug do emissor") era um falso-positivo armado: na tentativa 1, todo bloco deterministic acabou de ser emitido (equivale a "restaurado por definição") e um step alvo de correção `required_wait`/`required_method` falharia a validação DE PROPÓSITO — a C8 remove esse caso da rota deterministic, e as duas restrições (a)+(b) garantem que qualquer combinação futura parecida degrade para o fluxo de erro normal (escopo cirúrgico) em vez de abortar a geração com diagnóstico falso.
- **Bloco deterministic AUSENTE não é caso de restore nem de `RuntimeError`:** se a LLM removeu a âncora `# [PASSO N]` inteira num rewrite full-file, `_parse_step_blocks` não retorna o bloco e não existe posição onde re-splicear. O caso segue o fluxo de erro normal — vira `MISSING_STEPS`, cujo `step_ids` o escopo cirúrgico já resolve (`code_generator.py:1476-1477`).
- Correção legítima (QA/pendência) mirando um bloco deterministic: permitida — o step entra em `target_scope`, o restore o ignora, e ao final da tentativa vencedora o manifest atualiza `provenance: "cognitive_patched"`. Regenerações futuras do zero voltam a emiti-lo deterministicamente (correções acumuladas re-aplicam por cima, fluxo atual). Nota: com a C8, um step com correção pendente já nasce cognitive na geração nova — este caso cobre correções que surgem DEPOIS, no ciclo de execução do bot híbrido.
- Manifest ausente (bot pré-híbrido, gerado antes desta feature) ⇒ etapa inteira é no-op. Nota (achado R5): com o ciclo de vida da Seção 2.4, a rota full-LLM NOVA não deixa manifest ausente — ela escreve `{"generator_version": "full-llm", "steps": {}}`, cujo efeito é o mesmo no-op por `steps` vazio; "ausente" só ocorre em bots pré-híbrido. Comportamento atual intacto nos dois casos.

### 5.3 O que não muda no fluxo cirúrgico

`_surgical_correct`, `_surgical_correct_scoped`, `_build_scoped_edit_plan`, escopo por `lineno`, guard coluna-0, fallback escopado→full — tudo intacto. A única extração é generalizar o miolo de prompt/parse de `_surgical_correct_scoped` para a nova `_generate_scoped_blocks` compartilhada (mesmo formato BEGIN_STEP/END_STEP, mesma regex, mesmo guard), parametrizando o texto-moldura ("corrija este bloco" vs "escreva este bloco novo"). Refatoração mecânica com os testes de T4 protegendo.

---

## 6. Passo a passo de implementação

> Convenção: cada tarefa fecha com comando de validação executável. Mudança em `aegis_*` core ⇒ `aegis-regression-gate` obrigatório antes de considerar done (working agreement). Ordem projetada para a suíte existente ficar verde em TODO commit intermediário.

**H0 — Baseline + golden v2 rico (quase sem código).**
1. Congelar como referência: bot atual do projeto de referência (`portal_segura/tests/001_teste/code/bot_producao.py`, compilado, NÃO regenerar) + golden plans já versionados em `.specs/golden/`. Registrar `git rev-parse HEAD`.
2. **Capturar golden v2 rico (achado 1.2):** re-sanitizar a `gravacao.json` do golden real (`.specs/golden/real_portal_segura_001/gravacao.json`, existe no diretório) com o sanitizer v2 recém-commitado (`b5cc4e7`) em pasta descartável e versionar o `plano_execucao.json` v2 resultante como `.specs/golden/real_portal_segura_001_v2/`. Se o plano resultante não exercitar a matriz toda (`optional`, `parent`+`has_text`, `select` com coords, `weak_selector`, `padrao_q`, **click de opção de autocomplete com valor de negócio no seletor — caso C10/B1, presente no golden real como `st_023`**), complementar com fixtures sintéticas mínimas por caso — a matriz do round-trip 4.1 não pode ter célula vazia.
*DoD:* anotação em `.specs/` com commit e inventário dos artefatos de referência + golden v2 rico versionado cobrindo a matriz (checklist explícito por caso da matriz na anotação).

**H1 — `deterministic_emitter.py`: emissores puros.**
`_emit_click`, `_emit_fill`, `_emit_select`, `_emit_select_native`, `_emit_async_guard`, `_emit_optional_wrapper`, `emit_step_block`. Nenhuma integração ainda.
*Arquivos:* novo `aegis_sanitizer/deterministic_emitter.py`, novo `aegis_sanitizer/test_deterministic_emitter.py` (casos unitários por emissor: parent⇒chained com dicts, coords⇒original_coords, HUMAN_LIKE, weak+text⇒`:has-text`, select coords_trigger/option).
*DoD:* `python aegis_sanitizer/test_deterministic_emitter.py` verde; suíte existente intocada.

**H2 — `classify_step` + `build_skeleton` + manifest.**
Tabela C1-C10 da Seção 2.2 (incluindo C8 correções-pendentes, C9 autocomplete recalibrada, C10 valor-de-negócio-no-seletor, e a decisão pass-through de `flaky`), placeholders `# AEGIS_COGNITIVE_SLOT step_id="..."` parseáveis, manifest com `plan_checksum` (hashes só telemetria). Incluir os testes de round-trip da Seção 4.1 (itens 1, 2 e 4) — este é o gate central — rodando contra o golden v2 rico capturado em H0.
*DoD:* round-trip verde contra os golden plans v1 E v2; `python aegis_sanitizer/test_sanitizer_execution_plan.py` e `test_step_validator_hints.py` verdes (sem edição — se precisarem de edição, é regressão real).

**H3 — `_generate_scoped_blocks` (extração compartilhada).**
Generalizar miolo de `_surgical_correct_scoped` (prompt-moldura parametrizada + parse BEGIN_STEP/END_STEP + guard coluna-0 + splice). `_surgical_correct_scoped` vira caller da função extraída.
*Arquivos:* `code_generator.py`.
*DoD:* `test_error_selector_config.py`, `test_dryrun_multirow.py` verdes; teste novo cobrindo a extração (resposta malformada ⇒ None; def coluna-0 ⇒ None).

**H4 — Integração em `_generate_new_code` atrás de `AEGIS_CODEGEN_HYBRID` (default `false`).**
Fluxo da Seção 2.3, incluindo curto-circuito full-LLM para skills/flag/plano ausente e fallback full-LLM por slot faltante. Prompt dos slots cognitivos (enumeração completa — achado R4 alinhou com a Seção 2.3 passo 5, que é a fonte canônica): fatia via `_render_plan_for_prompt` + contrato optional com convenção de bloco-vazio (template da Seção 3.2 embutido no prompt) + blocos vizinhos read-only + **entradas de `pending_corrections` cujo `step_id`/`required_reopen.after_step_id` esteja entre os slots, na renderização de `_surgical_correct` (`code_generator.py:1360-1418`)**.
*DoD:* com flag `false`, geração byte-equivalente ao fluxo atual (teste: prompt montado idêntico via snapshot — **gate deliberadamente overspecificado e DESCARTÁVEL: remover após o flip do default em H8.5**, achado 2.2/working agreement nº 3: ele codifica detalhe de implementação, não contrato, e qualquer mudança legítima de prompt futura o quebraria "corretamente mas inutilmente"); com flag `true` sobre fixture sem slot cognitivo, bot gerado passa todos os validadores + dry run **sem nenhuma chamada LLM** (mock do gateway assertando zero calls); **com flag `true` sobre fixture COM slot cognitivo (achado I7 da rodada 2): mock do gateway retornando BEGIN_STEP/END_STEP ⇒ asserção de que a resposta foi SPLICEADA no skeleton (bloco presente no arquivo final) e de que NÃO houve fallback full-LLM (uma única chamada ao gateway, com o prompt de slots, não o prompt de arquivo inteiro) — sem este caso, um bug que degrade silenciosamente todo slot para full-LLM passaria o H4 inteiro e só apareceria (talvez) no H8**; e fixture com step `optional` onde o mock responde com o bloco-vazio da convenção da Seção 2.3 ⇒ splice aceita, manifest registra `optional_omitted`, validadores PASS.

**H5 — Política anti-drift no Ralph (`_restore_deterministic_blocks`).**
Seção 5.2: restore + fail-fast de bug de emissor + atualização de manifest pós-correção (`cognitive_patched`) + ciclo de vida do manifest da Seção 2.4 (toda rota de geração sobrescreve; `plan_checksum`).
*Arquivos:* `code_generator.py` — função nova + **UM ponto de chamada no `generate()`** (logo após `_normalize_boilerplate`, `code_generator.py:564`, dentro do loop de tentativas — um ponto único cobre todas as tentativas; achado M3 da rodada 2 corrigiu a menção anterior a "2 pontos"), testes com manifest fixture (bloco adulterado fora do escopo ⇒ restaurado; dentro do escopo ⇒ preservado; bloco AUSENTE ⇒ ignorado sem erro; `after_step_id` de `required_reopen` pendente ⇒ poupado; manifest stale com `plan_checksum` divergente ⇒ no-op; sem manifest ⇒ no-op; erro de ORDEM apontando bloco restaurado ⇒ NÃO dispara fail-fast).
*DoD:* testes novos verdes + suíte `code_generator`-adjacente verde.

**H6 — Rota determinística de reintrodução de `sup_` (`reintroduce_step_id`).**
Seção 3.1. Leitura do campo em `pending_corrections`, inserção posicional via ordem do plano, wrapper optional, marcação `applied` pelo fluxo existente.
*DoD:* teste: correção com `reintroduce_step_id: "sup_003"` ⇒ bot final contém o bloco na posição relativa correta, `validate_bot_against_plan` PASS (é o teste 4.1(3)).

**H7 — Playbook + contrato de prompt.**
`rpa-copilot-coder.md`: seção nova "Geração híbrida — o que a LLM escreve e o que ela nunca escreve" (slots cognitivos, template optional canônico, proibição de tocar blocos deterministic no modo reflection). Ajustar o texto do reflection prompt (`_surgical_correct_with_reflection`) para citar a política de restore ("blocos fora do seu escopo serão restaurados — não gaste tokens neles").
*DoD:* snapshot do prompt renderizado com fixture híbrida; leitura humana.

**H8 — Validação de ponta a ponta real (working agreement nº 1) + flip do default.**
1. `AEGIS_CODEGEN_HYBRID=true` em CÓPIA do projeto de referência: regenerar Fase 4 e comparar com H0 (mesmos step_ids, mesmos métodos por step, diffs só onde classificação mudou a forma).
2. Executar o bot híbrido contra o site real (`aegis-live-pilot` se for site novo; senão execução direta) — taxa de sucesso ≥ baseline H0. **Obrigatório incluir um cenário com autocomplete real na forma REAL do padrão** (fill que precede CLICK em opção de painel dinâmico — ex. `st_022→st_023` do 001_teste; descrição corrigida na rodada 2, achado I1: a forma anterior "fill que precede select" não é como o padrão aparece em nenhum plano real): valida de uma vez a C9 recalibrada (decisão HUMAN_LIKE vs DIRECT — dependente do site, nenhum validador estático cobre) E a C10 (o click da opção deve sair parametrizado com `row`, nunca com o literal gravado) contra o site de verdade (working agreement nº 1).
3. `aegis-regression-gate` (mudou core `aegis_sanitizer/`).
4. Ciclo cirúrgico real: introduzir uma correção QA num bloco deterministic e num cognitivo; confirmar modo escopado ativo (não caiu em full rewrite) e manifest atualizado.
5. Passando tudo: flip `AEGIS_CODEGEN_HYBRID` default `true` (um commit isolado, revert trivial).
*DoD:* veredito APROVADO do gate + execução real ≥ baseline + escopado confirmado nos dois casos.

**H9 — Documentação.**
`docs/aegis_architecture_manual.md`, `docs/aegis_bot_generation_flow.md`, CLAUDE.md (fluxo Fase 4 + flag nova + manifest), skill `aegis-pipeline-forensics` (manifest entra na cadeia forense).
*DoD:* docs coerentes; commit. Atenção: docs têm modificações locais não commitadas — coordenar.

Dependências: H0 → H1 → H2 → {H3, H5 em paralelo} → H4 → {H6, H7} → H8 → H9. H3 é pré-requisito de H4 (slots usam a extração); H5 pode ser desenvolvido em paralelo a H3/H4 mas só é exercitado de verdade a partir de H4.

---

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Bug do emissor replica silenciosamente em TODOS os bots novos (antes, o erro da LLM era estocástico; agora seria sistemático) | Round-trip 4.1 como invariante permanente; H8 contra site real antes do flip; flag master + `FORCE_LLM_STEPS` para contornar em produção sem release |
| Linha de corte agressiva demais (step "mecânico" que na verdade precisava de julgamento) | Política conservadora (dúvida ⇒ cognitive); manifest registra `reason` por step ⇒ auditável; downgrade por env sem código |
| `except` do bloco optional engolindo NameError/TypeError de código cognitivo mau-gerado dentro do try | Dry run roda ANTES em arquivo completo com runner fake que não levanta — alucinações de nome/assinatura estouram fora do except no dry run? **Não necessariamente (estão dentro do try).** Mitigação real: round-trip valida o template; e slots cognitivos emitidos com wrapper passam por um `ast`-lint específico no splice (except deve re-imprimir o erro; corpo do try só chamadas runner + page) — checagem barata na `_generate_scoped_blocks` |
| Restore de bloco (5.2) entra em guerra com uma correção legítima cujo erro apareceu SEM step_id/lineno mapeável | `target_scope` inclui `live_error_step_ids` (que já resolve lineno→bloco); erro não mapeável nem a correção escopada de hoje alcança — fallback full-file continua existindo e o restore respeita `provenance: cognitive_patched` |
| Prompt dos slots perde contexto global e a LLM gera bloco incoerente com o fluxo | Blocos vizinhos read-only no prompt (mesma técnica do escopado atual, que já funciona em produção); fallback full-LLM por tentativa |
| Dois caminhos de geração para manter (híbrido + full-LLM) | Deliberado: full-LLM é o fallback e a rota de skills; o custo de manutenção é pago pela redução de tentativas Ralph (cada tentativa = 1 chamada de modelo de código, a parte mais cara da Fase 4) |

## 8. Fora de escopo (anti-overengineering deliberado)

- **Skills no híbrido** — posicionamento de `run_skill_*` sem step no plano exige o Sanitizer emitir steps `call_skill` no plano (mudança de schema v2.1). Fica para depois de o híbrido estabilizar; até lá, projeto com skill usa full-LLM.
- **`filechooser` determinístico** — padrão `with page.expect_file_chooser()` envolve composição de contexto; cognitivo por ora.
- **Geração via ast.unparse/CST em vez de f-strings** — só se os templates começarem a acumular casos de escaping; hoje seria custo sem caso real.
- **Mudanças no runner** (kwarg `optional=`) — zero bytes, pelas razões da Seção 3.2.
- **UI da Cockpit para `reintroduce_step_id`** — o campo funciona via JSON; botão dedicado é conveniência futura.
- **Reaproveitar o emissor no fluxo cirúrgico para reescrever blocos deterministic quebrados por causa externa** (site mudou) — aí o seletor novo vem de correção QA, que já entra pelo fluxo normal.

**Gap de fidelidade do SANITIZER, achado durante H8 (2026-07-13) — explicitamente FORA de escopo deste backlog, registrado aqui só para referência futura.** Cadeia de autocomplete dependente (Marca→Modelo→Versão, `st_020/023, st_021/024, st_022/025` do projeto de referência): o site (`main.js:1852-1856`) só popula o dropdown de "Versão" quando Marca E Modelo já estão selecionados, mas o Sanitizer emite os fills (`020/021/022`) e os cliques (`023/024/025`) em blocos separados na ordem gravada, não intercalados por dependência — e, independentemente disso, `fill_human_like` (`aegis_runner/runner.py:1962`) dispara `element.dispatch_event("blur")` incondicional ao final da digitação, o que fecha o painel de autocomplete do Angular Material sempre que a estratégia HUMAN_LIKE é usada no campo que precede o clique da opção. Resultado observado ao vivo: com `st_022` classificado cognitive pela C9 e a LLM escolhendo HUMAN_LIKE nessa regeneração, `st_025` falhava 100% (`Locator.wait_for: Timeout 8000ms exceeded` — o painel nunca reabre sozinho, `required_wait` não serve, é preciso uma AÇÃO de reabertura). Workaround validado (fora do sanitizer, só como correção pontual via `correcoes_acumuladas.json`): `required_reopen` re-disparando o campo com `strategy="DIRECT"` (nunca HUMAN_LIKE — reintroduziria o mesmo blur) entre a seleção do campo anterior e o clique da opção — confirmado por execução real repetida (`st_025` HEALED em 6/6, nunca mais FAILED, sob DIRECT e HUMAN_LIKE em `st_022`). Correção estrutural real (não implementada aqui, é do Sanitizer): (1) emitir a ordem fiel intercalada fill→seleção→próximo campo para autocompletes dependentes, em vez de agrupar todos os fills e depois todos os cliques; (2) emitir automaticamente um `required_reopen`/re-disparo DIRECT antes do clique de opção sempre que o fill anterior ao clique puder ter usado HUMAN_LIKE. Evidência completa em `scratchpad/evidence_s13_autocomplete_fix/` (investigação ad-hoc, fora deste backlog).

**Gap de ciclo-de-vida do `required_reopen` — `EXTRA_STEPS` hard-fail quando a correção já está `applied` (achado no H8 retry8, 2026-07-13), explicitamente FORA de escopo deste backlog.** O `required_reopen` acima (`st_025_reopen`) é tolerado por `step_validator.py:402-416` **só enquanto a correção que o originou está em `pending_corrections`**. Assim que o gerador marca essa correção `applied` (após a regeneração que a aplicou), o bloco `st_025_reopen` sai da lista de exceções e passa a contar como `EXTRA_STEPS` puro — qualquer ciclo cirúrgico QA rodado DEPOIS disso, mirando outros steps (deterministic ou cognitive, sem relação com o reopen), falha imediatamente (15/15 tentativas → `RuntimeError`) porque o validador vê um passo "extra" que não devia estar lá. Reproduzido de propósito no H8 retry8 (`scratchpad/evidence_h8_retry8/step5a_FAILED_appliedreopen_*`): rodar o Passo 5 (ciclo cirúrgico) com o reopen do Passo 3 já `applied` falha; rodar sobre um bot limpo (sem reopen `applied` pendente) passa normalmente. Não é bug do gerador híbrido — é o ciclo de vida de correção (`correcoes_acumuladas.json`) e o validador de `EXTRA_STEPS` que não têm memória de "isto já foi um reopen legítimo, mesmo resolvido". Correção estrutural real (não implementada aqui): manter a tolerância de `st_*_reopen` no validador independente do status da correção que o originou (por padrão de nome/`step_id`, não por lookup em `pending_corrections`), ou re-derivar os reopens esperados a partir dos blocos de fato presentes no bot em vez de a partir do status da correção. Evidência completa em `scratchpad/evidence_h8_retry8/`.

---

## Apêndice — resumo do porquê desta forma

O Ralph Loop foi construído para compensar uma LLM que escreve 100% do arquivo; cada autocorreção determinística já adicionada (`_normalize_boilerplate`, rename por `difflib`, strip de runner espúrio, `reorder_steps_to_match_plan`) foi um passo tácito na direção deste plano: **tirar da LLM o que é mecânico**. Este plano completa o movimento invertendo os validadores em emissores — o código que hoje só *cobra* o padrão passa a *produzi-lo* — e confina a LLM aos slots onde há julgamento real (Padrão Q dinâmico, decisão de `optional`, Padrão N, correção cirúrgica). O resultado esperado não é só menos token: é que a classe inteira de falha "alucinação sintática em passo óbvio" deixe de existir por construção, e o Ralph Loop vire o que deveria ser — um verificador que quase nunca precisa iterar.
