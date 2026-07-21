# Plano Revisado — "Fidelidade Comportamental Total"

> Status: **PROPOSTA — AGUARDANDO DECISÃO** (nenhum arquivo modificado). Substitui o escopo do `.specs/plano-simulador-humano-fiel.md` — aquele plano vira a **Fase 1** deste documento, não é descartado. Auditoria feita por subagente Fable (2026-07-13), a pedido do usuário, sobre pipeline completo (recorder → sanitizer → dataset → code_generator → runner), motivada por: plano anterior (2 rodadas de revisão) só ataca cadência/timing de clique/digitação, não fidelidade comportamental real ao voo gravado.
> **SUPERSEDIDO (2026-07-14):** o default `strict=True` herdado da Fase 1 (item A/1-8 acima) foi revertido por `.specs/plano-cauda-longa-verificada.md` (Seção 7) — `strict=True` vira modo opt-in de homologação, não default de produção. Os demais itens da Fase 1 permanecem válidos.

## 0. Resposta direta à pergunta que motivou a revisão

*"Se num campo texto for digitado errado, apagado e corrigido, o bot reproduz isso?"* — **Não, e a informação é destruída em DOIS pontos independentes antes mesmo do Sanitizer:**

1. **`aegis_blackbox/recorder.py:868-873`** — listener de `input` é no-op deliberado ("Não gravamos no evento 'input' imediatamente para evitar gravar valores parciais"). Só `change` (856) e `blur` (862) disparam `recordFill` (724), que lê `target.value` — o **estado final**. Keystrokes, Backspace, cadência real **nunca existem** em nenhum artefato.
2. **`recorder.py:1253-1285` (`save_telemetry_files_disk`)** — mesmo o rastro parcial que sobreviveria é **apagado fisicamente** antes de gravar `gravacao.json`: loop 1259-1276 remove o fill anterior do mesmo seletor (salvo barreira de navegação); 1278-1280 remove cliques/fills consecutivos no próprio seletor. Roda **antes** do contrato "classifica, nunca deleta" do Sanitizer v2 — o contrato é violado rio acima, na captura.

Mesmo que o dado existisse, o replay não o usaria: `fill_human_like` (runner.py:2098-2100) e `fill_chained` HUMAN_LIKE (1869-1871) digitam caractere a caractere **o valor do dataset** (`row.get(chave, "")` — emitter 236-237), 60ms fixo. É digitação lenta de um valor correto, não replay de comportamento.

## 1. Diagnóstico — inventário completo de simplificação/dedução/descarte

### 1.1 Captura (`aegis_blackbox/recorder.py`)

| # | Componente | Gravado | Perdido/inferido | Evidência |
|---|---|---|---|---|
| R1 | Texto/input | Valor final (change/blur) | Keystream: erros, correções, Backspace, colar vs. digitar, cadência | 856-873, 724-768 |
| R2 | Re-digitação do mesmo valor | Nada | Dedup por valor (721, 739-743) — conferência do usuário não gera evento | 739-743 |
| R3 | Correção entre campos | Só valor final | Cleanup destrutivo no save remove fill anterior | 1253-1285 |
| R4 | Timestamps | ISO no callback IPC (não `e.timeStamp` DOM) | Latência JS→Python embutida; fill carimbado no commit, não na digitação; `flushAllInputs` num clique reposiciona no tempo do clique | 1470; 770-800 |
| R5 | Cliques duplicados | 1 clique | Dedup 250ms no JS — duplo clique físico intencional descartado na fonte; sem listener `dblclick` | 802-821 |
| R6 | Teclado | Nada | Enter/Tab/Escape/atalhos nunca capturados — submit via Enter perde o evento | ausência total |
| R7 | Hover | Nada | Inferido no replay a partir de `" >> "` no seletor — trilha real não existe | runner.py 480-495 |
| R8 | Scroll | Nada | Replay decide via `scroll_into_view_if_needed` | ausência |
| R9 | Drag-and-drop / clique direito / Ctrl+click | Nada | Sem listeners | ausência |
| R10 | Checkbox/radio | Só clique genérico | `EXCLUDED_INPUT_TYPES` exclui de recordFill; estado só via scan_field, sem binding — dataset por linha não muda replay | 722, 1141-1189 |
| R11 | Upload de arquivo | Só ocorrência do diálogo | Nome/caminho/conteúdo nunca gravados; generator reconstrói por convenção (slot cognitivo) | 1712-1721 |
| R12 | `<select>` nativo | Valor final (change, multi-select via selectedOptions) | OK — sem gap relevante | 724-768 |
| R13 | Dropdown custom (mat-select) | 2 cliques (trigger+opção) + coords | Vira par re-inferido pelo Sanitizer | — |
| R14 | Data | Valor **transformado** ISO→DD/MM/YYYY já na captura | Literal digitado é reescrito antes de persistir | 1484-1487, 1515-1518 |
| R15 | Multi-aba | Stream único, sem id de página | Runner replaya numa página só | 1879-1895 |
| R16 | Navegação intermediária | Só `initial_url` | Mudanças de URL durante fluxo não são eventos | 1391-1399 |

### 1.2 Sanitizer (`aegis_sanitizer/sanitizer.py`)

| # | Mecanismo | Natureza | Evidência |
|---|---|---|---|
| S1 | Padrão P — inversão física click-opção↔fill | Reordena sequência temporal gravada | 145-160 |
| S2 | R1-R4 (`_classify_raw_events`) — duplicate_click/overlay_noise/stale_panel_click/redundant_refill | Classifica mas suprime; 2º clique real (UI lenta) também é suprimido — runner compensa com retries próprios, comportamento do framework não do usuário | 708-818 |
| S3 | `_merge_consecutive_clicks` | Vencedor pode ser seletor de clique ANTERIOR (mais específico), não último gesto físico | 1151-1271 |
| S4 | `_reorder_dropdown_pairs` | Colapsa abridor+opção em step sintético, move steps intercalados | 943-1037 |
| S5 | `_mark_superseded_selects` | Correção do usuário num dropdown (escolheu A, corrigiu p/ B) é suprimida — **equivalente de dropdown da pergunta original**; política já decide "não reproduzir correção" | 1040-1103 |
| S6 | `_mark_phantom_pretrigger_clicks` | Descarta clique a <5% do trigger | 1106-1149 |
| S7 | Padrão Q | Reescreve `has_text` removendo tokens dinâmicos — necessário mas é edição do registro | 1359-1392 |
| S8 | `fix_encoding` + normalização de datas | Reescreve valores gravados | 69-130 |
| S10 | Timestamps descartados do plano | `_serialize_plan_step` sem campo temporal — cadência entre AÇÕES morre aqui; replay usa sleeps fixos + `slow_mo=50` | 1273-1300; runner.py 2257 |

### 1.3 Geração (`code_generator.py` + `deterministic_emitter.py`)

| # | Achado | Evidência |
|---|---|---|
| E1 | Não existe fluxo de replay literal — `text_val`/`option_text` SEMPRE `row.get()`; literais são proibição absoluta (validador `HARDCODED_*`) | emitter 236-237, 277, 306 |
| E2 | Replay de select é RECONSTRUÍDO, não replayado: plano carrega `trigger_selector`/`option_selector` gravados, mas `_emit_select` não os passa — `select_option_resilient` sintetiza seletores a partir de label/texto. Alvo físico real gravado é descartado no replay | emitter 265-293; runner 1338-1346 |
| E3 | Timing sintético — único wait é `time.sleep(2.0)` heurístico CPF/CNPJ/CEP | emitter 320-336 |
| E4 | `filechooser` fora de `_SUPPORTED_TYPES` → slot cognitivo → LLM inventa upload | emitter 426 |
| E5 | Clique de checkbox emitido sem binding de dataset — estado por linha inatingível deterministicamente | emitter 579-596 |

### 1.4 Runner — tensão "resiliência vs. fidelidade"

| # | Tier | Inventa alvo? | Gate strict? | Auditado (HEALED/Sensor F1)? |
|---|---|---|---|---|
| T1 | Heurística multi-candidato (primeiro visível, evita âncora) na tentativa primária | **Sim** | **NÃO — roda sob strict** | **NÃO — loga SUCCESS** |
| T2 | Nível 1.5 "strict violation → `.first`" | **Sim** | **NÃO** | **NÃO — SUCCESS** |
| T3 | Escape p/ limpar overlay (keystroke sintético) | Não (gesto extra) | Não | Não |
| T4 | CDK reposition + clique sintético JS | Parcial | Não (determinístico) | Só via CLICK_NO_EFFECT |
| T5 | `fallback_selectors` gravados | Não (mesmo alvo) | Sobrevive por design | Sim |
| T6 | Geometria ao vivo por texto | Não (mesmo alvo gravado) | Sobrevive (pós-plano atual) | Sim (fix já no plano atual) |
| T7 | IA visual | **Sim** | Sim (gated) | Sim |
| T8 | Coordenada gravada | **Sim** | Sim no click; select antes do gate (fix já no plano atual) | Sim |
| T9 | `_recover_via_recent_fills` | Gesto inventado | Não | Sim |
| T10 | Inferência de coluna do grid pelo FORMATO do texto ("10%"→desconto) | **Sim** heurística pura | Não | Não |
| T11 | `fill_human_like` — click force + Ctrl+A + Backspace + 60ms/tecla + blur incondicional | Gesto sintetizado (usuário pode ter usado Tab) | fallback cognitivo próprio sem gate (fix já no plano atual) | Parcial |

**Achado novo mais importante — não coberto pelo plano nem pelas 2 revisões anteriores: T1 e T2.** Plano atual gasta esforço gateando tiers 3.5/4 (IA/coordenada), mas os dois pontos onde o framework troca de alvo **silenciosamente, sob strict, logando SUCCESS puro** são a heurística multi-candidato (runner.py:588-617) e `.first` do Nível 1.5 (1159-1168 / 1976-1983). São exatamente "deduções do que é certo" invisíveis à auditoria anterior.

### 1.5 Resiliência vs. fidelidade — resposta arquitetural

Não conciliáveis num modo único — conciliáveis como **dois modos + régua de classificação de tier**. Régua: tier compatível com fidelidade = **re-localiza o MESMO alvo gravado por evidência determinística** (fallback_selectors, geometria por texto do próprio seletor gravado, trigger_selector gravado); incompatível = **escolhe alvo por heurística/visão/posição** (T1, T2, T7, T8, T10). Hoje a régua só é aplicada a T7/T8. Escolha de produto: (a) **modo produção** — tiers de identidade sempre; tiers de adivinhação só com `strict=False` explícito e sempre `HEALED`+Sensor F1; (b) **modo replay-literal** (homologação, dataset = linha gravada) — só seletor primário + tiers de identidade, resto falha rápido.

## 2. Distinção necessária: fidelidade estrutural × fidelidade de dado

**Fidelidade ESTRUTURAL** (alcançável para 100% das linhas do dataset):
- Qual elemento (trigger real do dropdown — hoje descartado, E2).
- Ordem (reordenações só quando fisicamente necessárias, sempre carimbadas como divergência auditável).
- Tipo de gesto: digitou vs. colou; Enter vs. clique; simples vs. duplo — hoje incapturável.
- Timing entre ações: cadência gravada com teto, em vez de sleeps fixos.
- Nenhuma troca de alvo não auditada (T1/T2).

**Fidelidade de DADO** (alcançável só como PADRÃO):
- Valor digitado vem do dataset por definição do produto (500 linhas ≠ 1 gravação). Reproduzível: padrão comportamental de entrada (cadência realista derivada da gravação, colar se colou, blur/Tab se gravado).
- Erro de digitação específico do analista **não deve** ser replayado com dado de produção (digitaria dado errado no sistema-alvo); só faz sentido em modo replay-literal com a linha gravada.
- Correções intra-gravação: default continua "intenção final" — mas vira decisão explícita e configurável sobre dado que existe, não impossibilidade silenciosa por dado destruído na captura.

## 3. Plano em fases

### Fase 0 — Decisão de produto + contrato de fidelidade (documento, ~1 dia)
Registrar em `.specs/` o contrato acima (estrutural × dado; régua identidade × adivinhação; dois modos de execução). Validar com dono do produto que "fiel" para correções = intenção final por default + rastro bruto preservado + replay literal opt-in — leitura literal da diretriz ("sem deduzir certo/errado") implicaria digitar dado errado em produção.

### Fase 1 — Cirúrgica, entra já (plano atual + 4 novos itens, risco baixo)
1. **Todos os itens de `.specs/plano-simulador-humano-fiel.md` permanecem válidos** (defaults strict/HUMAN_LIKE/headless, gate reposicionado Nível 3, gate coordenada select, strict em fill_human_like, allowlist time.sleep, emissão limpa, hover, auditoria live_geometry, Cockpit, testes) — resolvem a metade "parar de adivinhar". Ressalva: `MISSING_HUMAN_LIKE_STRATEGY` ajustar já prevendo nome da estratégia comportamental da Fase 3.
2. **NOVO — remover cleanup destrutivo do recorder** (`recorder.py:1253-1285`): mover decisão pro Sanitizer como classificação R5 (`recorder_refill_superseded`, keep=False) — restaura contrato "classifica, nunca deleta" na origem.
3. **NOVO — gatear/auditar T1 e T2**: sob `strict=True`, seletor ambíguo = falha (ou no mínimo `HEALED`/`healing_method="ambiguous_first_match"` + Sensor F1 em vez de SUCCESS silencioso) em runner.py:588-617, 1159-1168, 1976-1983.
4. **NOVO — replay do trigger gravado no select**: `_emit_select` passa `trigger_selector`/`option_selector` do plano; `select_option_resilient` tenta seletor GRAVADO antes da cascata sintetizada por label; heurísticas viram fallback auditado. Dado já está no plano — ganho barato.
5. **NOVO — timestamp de origem DOM**: JS envia `e.timeStamp`/`performance.now()` em vez de carimbar no Python (~5 linhas, pré-requisito da Fase 3).

### Fase 2 — Schema de captura comportamental (`gravacao.json` v3) — mudança estrutural, projeto próprio
- `input_trace` por campo: listener `input` deixa de ser no-op, acumula `{inputType, data, timeStamp}` por elemento, anexado ao evento fill no commit. Captura correções, colar vs. digitar, cadência real — campo aditivo, sem mudar shape existente.
- Eventos de teclado de primeira classe: keydown global Enter/Tab/Escape (`keypress`), `dblclick`, nome/tamanho de arquivo em inputs file.
- Compat: versão de schema no arquivo; Sanitizer ignora campos novos desconhecidos.
- Riscos: volume de eventos (mitigar: trace só por campo, flush no commit); overhead em apps Zone.js (medir com `AEGIS_RECORDER_DEBUG_TIMING` antes de ligar por default); privacidade (trace expõe valor tecla a tecla — mesmo dado já em `observed_value`, documentar).

### Fase 3 — Replay comportamental (emitter/runner) — depende da Fase 2
- `fill_behavioral` substitui `fill_human_like` como default: replaya *padrão* com valor de produção — cadência amostrada dos delays gravados (não 60ms fixo), `.fill()`/paste se analista colou, gesto de foco gravado, blur só se gravado (resolve gap H8 na causa).
- Pacing entre passos: plano ganha `recorded_delay_ms` por step; `AEGIS_REPLAY_TIMING=recorded|fast` substitui sleeps fixos.
- `press_key` fim-a-fim: recorder → sanitizer → emitter (`_emit_press`) → `runner.press_resilient`.
- Binding de checkbox (E5/R10): step ganha binding opcional → `set_checked_resilient(target_state=row.get(...))`.

### Fase 4 — Modo replay-literal (opt-in, validação/homologação)
`AEGIS_REPLAY_MODE=literal`: dataset = linha gravada (recorder.py:1370); tiers restritos a identidade (T5/T6 + trigger gravado); correções intra-gravação replayadas do `input_trace`/steps `superseded_correction`; timing gravado. Responde literalmente "reproduzir exatamente o que o analista fez" — também vira gate de regressão perfeito pro `aegis-regression-gate`. Esforço alto, valor indireto — última fase.

## 4. O que NÃO dá para resolver (não deve ser prometido)

1. **Erro de digitação do analista pras linhas 2..N** — não existe nos dados de produção. Só o padrão é transferível, o conteúdo do erro não. Replay literal só na Fase 4 com a linha gravada.
2. **"100% fiel ao voo" E "rodar em massa"** são mutuamente exclusivos pra campos de dado — por isso dois modos, não um default único.
3. **Token dinâmico (Padrão Q)** — texto gravado contém identificadores que nunca mais existirão; reescrita do registro é irredutível, máximo é auditar (já feito via `has_text_original`).
4. **Shadow DOM fechado** — coordenada é único caminho; fidelidade de alvo inverificável por construção da plataforma.
5. **Timing humano literal em lote** — replayar think-time real em 500 linhas multiplica custo por ordem de grandeza; teto/escala inevitável (decisão Fase 0).
6. **Mudança real de DOM do site-alvo** — se elemento gravado deixou de existir, "fiel" e "funciona" divergem por definição; modo produção cura auditado, modo literal falha rápido; não há terceira opção honesta.

## Arquivos críticos por fase

- `aegis_blackbox/recorder.py` — Fases 1.2/1.5/2 (no-op `input` 868-873, cleanup destrutivo 1253-1285, timestamps 1470)
- `aegis_runner/runner.py` — Fases 1/3 (T1/T2 588-617/1159-1168/1976-1983, select sintetizado 1338-1346, `fill_human_like` 2044-2123)
- `aegis_sanitizer/sanitizer.py` — Fases 1.2/3 (R1-R4 708-818, supressões 1040-1149, plano sem timestamps 1273-1300)
- `aegis_code_generator/deterministic_emitter.py` — Fases 1.4/3 (`_emit_select` 265-293, `_emit_fill` 219-262, `_SUPPORTED_TYPES` 426)
- `aegis_code_generator/step_validator.py` — Fase 1 (allowlist sleep, ajuste `MISSING_HUMAN_LIKE_STRATEGY`)

---

## Histórico

- **Rodada 1** (Opus 4.8, plan-critic) e **Rodada 2** (Fable, fidelidade de intenção) revisaram `.specs/plano-simulador-humano-fiel.md` — achados aplicados lá, preservados como Fase 1 aqui.
- **Rodada 3** (Fable, auditoria arquitetural completa, este documento): usuário apontou que "fiel ao que o usuário fez" vale pra todo componente, não só digitação, e que o plano anterior era raso demais. Auditoria releu recorder/sanitizer/emitter/runner por completo e mapeou toda simplificação/dedução — resultado acima.
