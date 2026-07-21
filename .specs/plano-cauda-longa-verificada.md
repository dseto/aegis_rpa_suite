# Plano — "Cauda Longa Verificada" (adesão total ao padrão da indústria)

> Status: **AGUARDANDO APROVAÇÃO** — nenhum arquivo de código modificado.
> Data: 2026-07-13. Decisão de produto (Daniel): aderir totalmente ao consenso de mercado 2026 (UiPath Healing Agent, Skyvern learn-replay, Stagehand cache, Google Project Mariner) — **determinístico no caminho feliz, LLM verificado na cauda longa**. Fim do dogma "zero-LLM em runtime como proibição"; o novo contrato é "zero ação NÃO-VERIFICADA em runtime".
> Contexto: `.specs/reflexao-viabilidade-aegis.md` (Opção 3 + passo 2 da Opção 5). Este plano SUBSTITUI a semântica de `strict` do `.specs/plano-simulador-humano-fiel.md` (ver Seção 7 — reconciliação).
> **Revisado (Rodada 1, plan-critic via Fable, 2026-07-14)** — aprovado com ressalvas; 3 achados ALTOS + 5 MÉDIOS emendados neste documento. **Revisado (Rodada 2, plan-critic via Opus 4.8, 2026-07-14)** — segunda opinião independente; 1 achado ALTO + 3 MÉDIOS emendados. Ver Seção 8 (Histórico de Revisão). Recomendação pendente: verificação final focada só na migração dos 6 call sites de `self_healing_click` antes de virar backlog (Rodada 2, item 5).

## 1. A doutrina nova (uma frase)

A régua deixa de ser **"LLM sim ou não"** e vira **"verificado sim ou não"**: qualquer tier — determinístico, geometria, coordenada ou LLM — só pode reportar sucesso se uma **pós-condição observável** confirmar que a ação teve o efeito que a gravação teve. LLM vira tier de primeira classe da cauda longa; ação cega (de qualquer origem) morre.

Isso é exatamente o "intent metadata" do Skyvern e o contrato do UiPath Healing Agent: o modelo não "adivinha e reporta sucesso" — ele propõe, o motor verifica ANTES e DEPOIS de agir, e só então decide.

## 2. Evidência do problema atual (verificada no código, linhas corrigidas na Rodada 1)

| Local | Problema |
|---|---|
| `cognitive_fallback.py:311-312` | `self_healing_click`: IA aponta coordenada → `page.mouse.click(x,y)` → `return True`. Zero verificação. Falso-HEALED confirmado em produção (Padrão Q, `rpa-copilot-coder.md:264`). |
| `cognitive_fallback.py:256-263` | Com módulo cognitivo **desativado**, ainda faz clique cego de coordenada e retorna `True` — pior que o caso ativo. |
| `cognitive_fallback.py:324-331` | Exceção/timeout na chamada LLM → clique cego de coordenada → `return True`. |
| `runner.py:588-617` (T1) | Heurística multi-candidato troca de alvo silenciosamente, loga SUCCESS. |
| `runner.py:1159-1168` (T2 click) | "strict mode violation" → clica `.first`, loga SUCCESS. |
| `runner.py:2118-2123` (T2 fill, ~~era citado como 1976-1983~~ — corrigido) | "strict mode violation"/"resolved to" → preenche `.first`, loga SUCCESS. |
| `cognitive_fallback.py:279-293` (~~era citado como runner.py:279-297~~ — corrigido, arquivo errado) | O prompt recebe só `target_description` + seletor falho — não recebe **o que deve acontecer depois** (a intenção/efeito), então não tem como auto-checar. |
| `runner.py:944` | Design intencional hoje: IA responde "não encontrei" (`found=False`) → **pula** o fallback de coordenada, para não somar adivinhação a adivinhação (justificativa em `cognitive_fallback.py:314-318`). A cadeia nova (Seção 3) precisa preservar essa intenção, não revertê-la sem querer. |
| `runner.py:894-901` | Falso-positivo JÁ DOCUMENTADO no próprio código: fechar painel via clique no backdrop CDK muda `overlayCount`/`domSize` — "parecendo efeito real". Foi a causa raiz da cascata st_024→st_025 que motivou o tier de geometria. Um verificador genérico ingênuo (Seção 4.A1) herda esse falso-positivo. |

O que já existe e vira alicerce (não construir do zero):

| Primitiva existente | Local | Papel no plano |
|---|---|---|
| `_capture_click_effect_snapshot` (URL, domSize, overlayCount, className do alvo+irmãos) | `runner.py:355-417` | Base do verificador universal |
| `_click_effect_signals_changed` | `runner.py:419-431` | Comparador genérico já calibrado (±2 nós DOM) — usar com o limite da linha 894-901 em mente |
| Sensor CLICK_NO_EFFECT (snapshot antes/depois já plugado no fluxo de clique) | `runner.py:509-524`, `453-454` | Prova que o custo de snapshot por passo é aceitável |
| Hit-test por texto sob o cursor no fallback de coordenada do select | `runner.py:1489-1500` | Vira o **gate de plausibilidade pré-clique** genérico (Seção 4.A4) |
| Confirmação "painel abriu" após clique de trigger | `runner.py:1383/1409/1433` | Pós-condição específica de dropdown já em uso |
| Sensor F1 (`_register_healing_for_review`) | `runner.py` | Auditoria de todo healing — mantém |
| `classify_step` C1-C10 + manifest de proveniência | `deterministic_emitter.py` | A fatia design-time do padrão da indústria — já pronta |
| Runner já carrega `plano_execucao.json` em runtime (`flaky_step_ids` vem de lá) | `runner.py:2422` | Encanamento pronto pra Fase 2 (D2: ler `expected_effect` do plano por `step_id`) |

## 3. Arquitetura alvo — cadeia única de tiers, todos verificados

**Mudança vs. rascunho original desta seção (Rodada 1): coordenada volta a rodar ANTES do LLM (não depois), e o LLM ganha um gate de plausibilidade PRÉ-clique — "rollback via Escape" não existe como conceito, porque a doutrina agora impede o clique errado de acontecer, em vez de tentar desfazê-lo depois.**

**Correção de framing (Rodada 2)**: a caracterização original ("acidente de implementação" no click; select "invertido" sendo "corrigido") estava factualmente errada e foi removida. O estado real, verificado:
- **Click hoje** (`_handle_unrecoverable_click`): geometria-ao-vivo (Nível 3, 914) → cognitivo (Nível 3.5, 930) → coordenada (Nível 4, 943) — **por design deliberado**, não acidente. O comentário `runner.py:888-912` explica: coordenada é "Último Recurso" porque é o sinal mais obsoleto (overlays CDK reancoram na posição viva, a coordenada gravada fica obsoleta — foi exatamente essa staleness que motivou criar o tier de geometria). Mover coordenada pra ANTES do cognitivo no click **é uma mudança real de comportamento** num caminho que funciona hoje, não um no-op.
- **Select hoje** (`select_option_resilient`, 1476-1519): coordenada JÁ roda antes do cognitivo, e JÁ tem hit-test de verificação (`elementFromPoint` + match de texto, 1489-1494) antes de clicar. O select já está na ordem-alvo — não precisa de correção, só permanece como está.
- **Por que mover a coordenada do click pra antes do cognitivo é seguro** (não só "mais barato"): coordenada cega em 944 hoje é a causa-raiz confirmada da cascata st_024→st_025 (clica no backdrop obsoleto, que fecha o painel sem commitar valor — `runner.py:892-899`). Isso só deixa de ser risco porque a ressalva de overlay do item 4.A1 é **dependência dura**, não cosmética: sem ela, uma coordenada-obsoleta-que-cai-no-backdrop dispara o mesmo falso-positivo de sinal genérico (894-901) e preempta um LLM que teria acertado. A1 e este reorder do click são uma mudança só, não duas independentes.

```
1. Seletor gravado (determinístico)                     → verifica efeito
2. Tiers de identidade: fallback_selectors, geometria    → verifica efeito
   ao vivo por texto gravado, trigger gravado
3. Coordenada gravada COM verificação de efeito           → verifica efeito
   (barata, instantânea, fiel à gravação — não é
   "adivinhação", é caminho alternativo pro MESMO alvo
   gravado; select já está nesta ordem hoje; CLICK MUDA
   de comportamento — ver framing acima — e só é seguro
   com a ressalva de overlay do item 4.A1 ativa)
4. LLM verificado (cauda longa, só se 1-3 esgotaram):
   a. Proposta: visão/DOM propõe alvo COM CONTEXTO DE
      INTENÇÃO (expected_effect)
   b. Gate de plausibilidade PRÉ-clique: hit-test da
      coordenada proposta (elementFromPoint + checagem de
      tag/texto contra target_description — mesma
      primitiva do hit-test do select, generalizada; MODO
      SOFT quando o seletor original contém " >> " — ver
      ressalva de Shadow DOM no item 4.A4). Implausível →
      REJEITADA sem clicar, NENHUMA ação executada, cadeia
      segue pro próximo tier.
   c. Só proposta plausível clica; verificação PÓS-clique
      (pós-condição específica se disponível, senão sinais
      genéricos COM a ressalva da linha 894-901) decide
      HEALED / VERIFY_REJECTED.
5. FAILED limpo (nenhum tier provou efeito)
```

- **Sucesso sem verificação não existe mais em nenhum tier.** Tier 1 aprovado = SUCCESS; tiers 2-4 aprovados = HEALED + `needs_review` (Sensor F1, como hoje).
- Proposta de tier rejeitada pela verificação → log `VERIFY_REJECTED` (novo, telemetria) e a cadeia continua pro PRÓXIMO tier — nunca aborta por proposta ruim, aborta só quando esgota. Para o tier 4 (LLM), a rejeição pré-clique (4b) e a pós-clique (4c) são eventos distintos na telemetria — a pré-clique é estritamente mais barata e mais segura (nenhuma ação ocorreu).
- `AEGIS_COGNITIVE_ENABLED` continua sendo o interruptor do tier 4 (sem chave → cadeia pula do 3 pro 5/FAILED). Nada de LLM obrigatório: o caminho feliz continua 100% determinístico e de custo zero.
- **Composição com `flaky_step_ids`/`current_row_flaky_attempt`** (gap da Rodada 1, corrigido): o gate `(strict or is_flaky_step) and not flaky_healing_unlocked` continua sendo avaliado ANTES de entrar na cadeia acima, exatamente como hoje (`runner.py:878-886` e pontos equivalentes em fill/select). Ou seja: passo flaky em tentativa ≤3 continua levantando `FlakyStepFailure` e reiniciando a linha SEM tocar em tier 3/4 — comportamento hoje preservado byte a byte. Só na tentativa 4 (`flaky_healing_unlocked=True`) ou passo não-flaky é que a cadeia de tiers 3-4 roda. `VERIFY_REJECTED` dentro da cadeia (quando ela roda) nunca levanta `FlakyStepFailure` por si só — é só mais um tier esgotado, cai pro próximo/FAILED normalmente.
- **Escopo de fill nesta fase (gap da Rodada 1, corrigido)**: `fill_resilient`/`fill_chained` NÃO têm tier de coordenada hoje (sem parâmetro `original_coords`) — plumbing novo (assinatura do runner + emitter + plano) fica FORA da F1. Pra fill, a cadeia da F1 é: 1 (seletor) → 2 (retry com parent reduzido, onde aplicável) → 4 (LLM verificado, sem gate de coordenada intermediário) → 5 (FAILED). Tier de coordenada pra fill é candidato a item futuro, não deste plano.

## 4. Proposed Changes

### A. `aegis_runner/runner.py` — verificador universal + rewire da cadeia

1. **`_verify_action_effect(page, before_snapshot, expected=None) -> bool`** — novo método único que generaliza o que já existe:
   - Sinais genéricos (sempre): `_click_effect_signals_changed` (URL/domSize/overlay/className — já implementado). **Ressalva obrigatória (achado da Rodada 1)**: em contexto de overlay/painel (CDK, mat-select, autocomplete), sinais genéricos SOZINHOS não bastam — `runner.py:894-901` documenta que fechar painel via backdrop muda os mesmos sinais sem confirmar o clique certo. Quando o gesto envolve um painel (detectável: havia `.cdk-overlay-pane`/`[role='listbox']` no snapshot `before`), exigir a pós-condição específica (painel fechou E valor apareceu no trigger/opção) — nunca aceitar só genéricos nesse caso.
   - Pós-condições específicas por tipo de gesto (quando aplicável): **fill** → ler `input_value()` (ou equivalente) do **elemento que de fato recebeu a digitação** (o alvo proposto/`document.activeElement` no caminho curado — NÃO o seletor original, que por definição falhou nesse ramo) e comparar de forma **type-aware** (Rodada 2: não strip genérico) — para campos identificados como numéricos/mascarados (`input_type` já detectado pelo runner em `2094`/`2199`, ou chave semântica CPF/CNPJ/CEP conhecida pelo `_ASYNC_GUARD_KEY_RE`), comparar só dígitos; para todo o resto (texto livre — nome, endereço), comparação exata ou normalização mínima de whitespace, NUNCA strip de pontuação (evita mascarar um fill genuinamente errado em "José D'Ávila" ou "Rua X, 123"); tolerância à conversão de formato de data que o próprio runner já faz em `2100-2102` — não igualdade estrita (a implementação atual em `fill_chained`, `runner.py:2032-2034`, usa `actual != text_val` estrita; é a base a generalizar, não a copiar literalmente); select → painel fechou E valor apareceu no trigger; clique de trigger → painel abriu (já existe, 1383); navegação → URL mudou (já existe via `validate_navigation`).
   - Quando o plano trouxer `expected_effect` (Fase 2), usa o efeito gravado como critério primário; sem ele, usa os genéricos (com a ressalva de overlay acima).
2. **Rewire dos pontos de decisão — lista exaustiva (corrigida na Rodada 2)**: `_handle_unrecoverable_click`, `_handle_click_failure`, `select_option_resilient`, `select_option_native_resilient`, `fill_chained`, `fill_resilient` **e `fill_human_like`** (`runner.py:2254` — omitido na Rodada 1; é o caminho de digitação DEFAULT sob HUMAN_LIKE, não edge case) passam a seguir a ordem da Seção 3 (identidade → coordenada verificada → LLM com gate pré-clique + verificação pós-clique). Para `fill_resilient`/`fill_chained`/`fill_human_like`, sem tier de coordenada (ver escopo acima) — pulam direto de identidade pro LLM. TODO retorno positivo de tier passa por `_verify_action_effect` (ou pela pós-condição específica) antes de virar HEALED. Snapshot `before` é capturado uma vez no início do gesto (já acontece pro click via sensor M2 — estender pra fill/select).
3. **T1/T2 entram na doutrina**: multi-candidato (588-617) e `.first` (1159-1168 no click, 2118-2123 no fill) só aceitam com verificação de efeito, logam `HEALED`/`healing_method="ambiguous_candidate_verified"` + Sensor F1 (não mais SUCCESS silencioso).
4. **Gate de plausibilidade pré-clique** (substitui o conceito de "rollback via Escape" do rascunho original — Escape nunca desfez efeito colateral, só limpa overlay pra retry, `runner.py:531-534/1527/2130`): nova função (ex.: `_hit_test_plausible(page, x, y, target_description) -> bool`) que generaliza o hit-test já usado em `runner.py:1489-1494` — `elementFromPoint(x,y)` na coordenada proposta pelo LLM, checa se `tagName`/`textContent`/`role` do elemento sob o ponto é compatível com `target_description`. Roda ANTES de qualquer clique físico do tier 4. Implausível → `VERIFY_REJECTED` pré-clique (nenhuma ação ocorreu, custo zero de efeito colateral) → próximo tier.
   **Ressalva de Shadow DOM (achado novo, Rodada 2)**: `elementFromPoint` no nível do `document` retorna o shadow HOST, não o elemento interno (event retargeting) — `textContent` do host não atravessa a fronteira do Shadow DOM. Pra alvos dentro de Shadow DOM fechado (Padrão A do playbook, sancionado no CLAUDE.md — seletor gravado contém `" >> "`), o gate compararia contra o texto errado e rejeitaria sistematicamente propostas corretas, neutralizando o tier 4 inteiro nesses fluxos. Mitigação: quando o seletor original do passo contém `" >> "`, o gate roda em **modo soft** (loga a checagem mas não bloqueia com força total — deixa a verificação PÓS-clique ser a única linha de defesa nesse caso, como é hoje) em vez de tentar `shadowRoot.elementFromPoint` (mais caro e ainda incompleto pra Shadow DOM fechado real).
5. **`strict` re-semantizado** (ver Seção 7): default `strict=False` PERMANECE (não aplicar o flip do plano anterior). `strict=True` passa a significar "apenas tiers 1-2" (sem coordenada nem LLM) — modo homologação/replay-literal, não mais o default de produção.

### B. `aegis_runner/cognitive_fallback.py` — gateway proposto→verificado

1. **`self_healing_click` vira PROPOSTA, não ação final**: retorna `{x, y, reason, confidence}` (ou `None`) em vez de clicar e retornar `True`. O RUNNER faz o gate de plausibilidade (A4), clica se plausível, e verifica o efeito (A1). Remove os 3 `return True` cegos (263, 312, 331) e os cliques de coordenada embutidos no gateway (256-263, 324-331) — coordenada é tier do runner, não do gateway.
2. **Prompt ganha intenção**: além de `target_description` + seletor falho + coords hint, o prompt recebe `expected_effect` textual ("após o clique, um painel de opções deve abrir" / "a URL deve mudar" / "o campo X deve habilitar") — derivado do tipo de gesto (Fase 1) ou do efeito gravado (Fase 2). Modelo com a intenção erra menos; o gate de plausibilidade e a verificação pegam o que ainda errar.
3. **Novo método `propose_fill_target`** análogo (hoje o fill usa o mesmo `self_healing_click` + digitação por teclado). **Mapeamento explícito dos 5 callers afetados** (~~"4 callers"~~ — typo corrigido na verificação focada; a mudança de assinatura de B1 quebra silenciosamente quem não migrar): `select_option_resilient` (1514), `select_option_native_resilient` (1594), `fill_chained` (2061), `fill_resilient` (2171) e `fill_human_like` (2254) hoje fazem `clicked = self.cognitive.self_healing_click(...)` seguido de `if clicked: <digita/seleciona por teclado>` — com B1, `self_healing_click` retorna um dict (truthy) em vez de clicar, então `if clicked:` passaria a digitar em `document.activeElement` SEM o gateway ter focado nada. Todos os 5 pontos precisam migrar juntos, no mesmo commit que B1 e que o 6º call site (`_handle_unrecoverable_click:933`, coberto por A1/A4), para o fluxo `propose → gate (A4) → click/focus → verify (A1) → digitar/selecionar`. Não é consequência implícita de B1 — é trabalho de primeira classe listado aqui.
   **Severidade por caller (verificação focada, Opus, 2026-07-14)**: `933` e `1514` (click/select-visual) produzem **falso-HEALED puro** (`return True` cego, efeito de negócio nunca ocorre — reintroduz exatamente o que o plano existe pra matar). `2061`/`2171`/`2254` (os 3 fills) produzem **corrupção silenciosa de dado** — digitam em `document.activeElement` sem foco garantido; `2171`/`2254` são as rotas de fill DEFAULT (HUMAN_LIKE), maior prioridade de risco. `1594` (`select_option_native_resilient`) é o único caso que **degrada sem corromper**: o retry re-executa `page.locator(selector).first.select_option(...)`, uma chamada Playwright real e auto-verificável — se falhar, cai em FAILED limpo; migra mesmo assim (o clique visual que deveria revelar o `<select>` continua cego), mas não é a mesma classe de risco dos outros 4.
4. ~~Wrapper de compatibilidade deprecated~~ **CORTADO (Rodada 1)**: grep original contra os 186 `bot_producao.py` compilados em `projects/` — zero chamadores diretos de `self_healing_click`/`CognitiveGateway`/`.cognitive.` fora do runner. **Ressalva (verificação focada, Rodada 3)**: a contagem "186" não é reproduzível neste checkout — `projects/` é gitignored e está vazio aqui (só scaffolds/`.gitkeep`), então a evidência empírica original não pôde ser reconfirmada. O argumento arquitetural continua de pé por construção: bots gerados só chamam métodos PÚBLICOS do runner (`click_resilient`, `fill_resilient`, etc.), nunca o método interno `self_healing_click` do gateway — mas quem for implementar deve reconfirmar a contagem contra os bots reais em produção antes de assumir "zero chamadores" como fato re-verificado. Se um dia aparecer um chamador direto, o erro de assinatura é imediato e trivial de corrigir. Manter o wrapper seria reintroduzir dentro do gateway exatamente o que o item B1 está removendo (clique+coordenada sem separação proposta/execução).
5. **`cognitive_fallback.py` — sem outro método fora de escopo (verificação focada, Rodada 3)**: grep de `page.mouse`/`page.keyboard` dentro do arquivo confirma que os únicos cliques físicos diretos são os 3 `return True` cegos de `self_healing_click` (262, 311, 330) que B1 remove. `diagnose_failure`, `compare_visual_similarity`, `transcribe_audio`, `call_llm`/`parse_json_response` não executam ação física — escopo do gateway (B) está correto e completo.

### C. `aegis_blackbox/recorder.py` — captura de pós-condição (Fase 2)

1. Snapshot leve antes/depois de cada ação gravada (mesmos sinais do runner: URL, domSize, overlayCount, painel aberto/fechado, valor comitado) → campo aditivo `observed_effect` por evento no `gravacao.json`. **Redimensionado (Rodada 1)**: isto NÃO é "só anexar uma medição" para todo caso — os listeners são síncronos ao evento (`recorder.py:806-875`), e quando o clique causa NAVEGAÇÃO, o contexto de página morre antes do snapshot "depois" poder rodar (flush por `beforeunload` em `875`, re-injeção via `add_init_script` em `1907`). Correlacionar efeito pós-navegação com o evento causador é infraestrutura nova de verdade, não uma linha a mais. Mitigação de escopo: para cliques que causam navegação, `observed_effect: {navigation: true}` inferido diretamente do próprio evento de unload já é suficiente e barato — não tentar capturar o snapshot "depois" completo através de uma navegação.
2. Schema aditivo (eventos sem o campo continuam válidos — retrocompat total; mesma política do `confidence`/`weak_selector`).

### D. `aegis_sanitizer/sanitizer.py` + `deterministic_emitter.py` (Fase 2)

1. Sanitizer propaga `observed_effect` → `expected_effect` no step do `plano_execucao.json` (schema v2 é aditivo por contrato).
2. Emitter NÃO precisa inventar encanamento novo pra isso: o runner já carrega `plano_execucao.json` em runtime e já indexa por `step_id` (`flaky_step_ids`, `runner.py:2422`, é o precedente direto) — ler `expected_effect` do plano pelo `step_id` em runtime, sem passar como kwarg emitido (coerente com "emissão limpa").

### E. Telemetria/observabilidade

1. `historico_passos.json` ganha por passo: tier resolvedor, `verify_result` (sinais que passaram), contagem de `VERIFY_REJECTED` separada por pré-clique (4b) e pós-clique (4c).
2. Métrica agregada por execução: taxa de resolução por tier (P0 do produto: medir quanto da cauda longa o tier 4 realmente resolve, taxa de rejeição pré vs. pós-clique — é o número que valida a adesão à tendência e informa a F3).

### F. Testes

- Unit: `_verify_action_effect` (genéricos + específicos por gesto + ressalva de overlay); `_hit_test_plausible`; gateway retorna proposta (não clica); proposta implausível rejeitada SEM clique físico (mock de `page.mouse.click` não chamado); proposta plausível mas pós-condição rejeitada → cadeia segue; T1/T2 logam HEALED verificado; comportamento flaky (tentativa ≤3 não entra na cadeia de tiers 3-4).
- Integração mockada: cadeia completa click/select com tiers 3-4 aceitos e rejeitados (pré e pós); fill limitado a tiers 1-2-4 (sem coordenada).
- **Browser real (Working Agreement #1)**: piloto com seletor sabotado → confirmar tier 4 resolve COM verificação; sabotagem de efeito (elemento clicável mas inerte) → confirmar `VERIFY_REJECTED` pós-clique → FAILED limpo, zero falso-HEALED; sabotagem de posição (coordenada aponta pra elemento errado plausível-parecendo) → confirmar gate pré-clique rejeita quando o hit-test não bate com `target_description`.
- **Migração de testes existentes (achado da verificação focada, Rodada 3 — ausente das rodadas anteriores)**: B1 muda o contrato de `self_healing_click` de `bool` (clica) para `dict|None` (propõe, não clica) — isso quebra testes que já existem e mockam esse método, mesmo commit, trabalho de primeira classe, não descoberta pós-hoc:
  - `aegis_runner/test_cognitive_fallback.py`: `test_self_healing_click_success` (57-85) quebra duro — assere `mouse.click.assert_called_once_with(...)`, que deixa de ser verdade; reescrever pra assertar o dict de proposta. `test_self_healing_click_not_found` (90-113) sobrevive por acidente (`assertFalse(None)` ainda passa) — reescrever para assertar `None` explicitamente, não deixar passando por coincidência.
  - `aegis_runner/test_runner_integration.py`: 7 métodos com `@patch(...self_healing_click, return_value=True)` que ALCANÇAM o call site pós-migração quebram duro (`TypeError`, dict tratado como valor de proposta em vez de bool) — `test_click_resilient_fallback_success` (71, também tem assert de assinatura na linha 77 que quebra se a assinatura mudar), `test_click_chained_non_strict_falls_back_to_self_healing` (123), `test_click_resilient_flaky_attempt_4_unlocks_self_healing` (472), `test_select_option_resilient_flaky_attempt_4_unlocks_self_healing` (530), `test_click_resilient_flaky_strict_false_attempt_4_unlocks_self_healing` (570), `test_click_resilient_non_flaky_strict_false_self_healing_untouched` (653), `test_fill_chained_falls_back_to_cognitive_when_no_unique_reduction` (1945). Mais 2 métodos com `return_value=False` que sobrevivem por serem falsy mas devem virar `None` pra ter sentido semântico: `test_select_option_resilient_coordinate_fallback_logs_healed` (346), `test_click_no_effect_genuine_failure_raises_after_all_recovery_layers_fail` (894).
  - Sem essa lista no backlog, `python aegis_runner/test_runner_integration.py` vira vermelho no commit de B1/B3 e passa a impressão de regressão em vez de migração esperada.

## 5. Fases

| Fase | Conteúdo | Depende de | Valor |
|---|---|---|---|
| **F1** | Verificador universal + gate de plausibilidade (A1-A5) + gateway proposto→verificado (B, sem B4) + telemetria (E) + testes (F) — usando só sinais GENÉRICOS já existentes (com ressalva de overlay) | nada | Mata o falso-HEALED hoje; LLM vira tier confiável imediatamente; fill escopado a tiers 1-2-4 |
| **F2** | Pós-condição gravada (C, redimensionado) + propagação no plano (D) + prompt com efeito gravado (B2 pleno) | F1 | Verificação deixa de ser genérica e vira "o efeito que a gravação teve" — precisão da cauda longa sobe |
| **F3** | Calibração: analisar telemetria E2 de pilotos reais, ajustar thresholds/prompts; decidir se tier de coordenada pra fill vale a pena; avaliar spike com harness open-source (Skyvern/browser-use) como motor de localização alternativo ao prompt próprio (Opção 4a da reflexão) | F1+F2 rodando em piloto | Decisão informada por dados, não por opinião |

## 6. Riscos declarados

1. **Custo/latência no tier 4**: 1 chamada de visão por passo-em-falha, mais o hit-test pré-clique (barato, JS local). Mitigação: tier 4 só roda depois dos tiers determinísticos/coordenada (cauda longa real, não caminho feliz), e a telemetria E2 mede o custo real por execução.
2. **Dado de tela vai pro modelo nos passos de exceção**: mudança de postura de compliance vs. dogma zero-LLM. Mitigação já suportada: `AEGIS_COGNITIVE_BASE_URL` aceita endpoint OpenAI-compatível — cliente sensível aponta pra modelo local/VPC. Documentar como decisão por projeto.
3. **Pós-condição de identidade em tabela** ("clicou a linha CERTA?") continua difícil — efeito genérico não distingue linha certa de errada. Fase 2 melhora (efeito gravado inclui className/contexto do alvo), mas o caso residual permanece — é o mesmo caso residual que o Padrão Q já trata com `strict` hoje, e continua tratável com tier 2 (identidade por texto).
4. **Falso-positivo de sinal genérico em contexto de overlay** (achado da Rodada 1, `runner.py:894-901`): mitigado por design na Seção 4.A1 (exigir pós-condição específica quando há painel envolvido), mas é risco residual até a F2 trazer `expected_effect` gravado — documentar explicitamente em vez de assumir que os sinais genéricos bastam.
5. **Snapshot antes/depois em todo gesto** (não só click): custo de ~2 avaliações JS por passo. Sensor M2 já paga isso pro click sem problema medido; estender e medir.
6. **Efeito pós-navegação é infraestrutura nova, não trivial** (Seção 4.C, redimensionado) — escopar como `observed_effect: {navigation: true}` inferido do unload, não como snapshot completo pós-navegação.

## 7. Reconciliação com os planos anteriores

- **`.specs/plano-simulador-humano-fiel.md`**: itens de fidelidade física PERMANECEM válidos e compatíveis (HUMAN_LIKE default, headless=False, hover físico, emissão limpa, allowlist `time.sleep`, auditoria live_geometry, Cockpit). **CAI**: o flip `strict=True` como default global bloqueando os tiers 3-4 — substituído pela doutrina da verificação (Seção 1). `strict=True` vira modo opt-in de homologação (tiers 1-2 apenas). **Correção da Rodada 1**: o item "gate de coordenada no select" NÃO é mais absorvido "depois do cognitivo" — a ordem correta (Seção 3) é coordenada verificada ANTES do LLM, preservando (e estendendo ao select) a ordem que o click já tinha.
- **`.specs/plano-fidelidade-comportamental-total.md`**: continua sendo o roteiro da fidelidade de CAPTURA (gesto, input_trace, busca≠seleção). Ortogonal e complementar — a Fase 2 daquele plano e a Fase 2 deste tocam o recorder juntas e devem ser implementadas coordenadas (mesmo release de schema v3). **Nota de consistência (Rodada 1)**: esse documento inclui o plano-simulador-humano-fiel como sua "Fase 1" (linhas 103/145 do arquivo), herdando o flip `strict=True` — ambos os documentos foram emendados nesta rodada com uma nota apontando pra este plano como a semântica vigente de `strict`. Ver nota no topo de cada arquivo.
- **`.specs/reflexao-viabilidade-aegis.md`**: este plano é a execução da Opção 3 (+ semente da 4a na F3). A Opção 2 (nicho Angular/PT-BR) segue como decisão de posicionamento independente — não bloqueia nem é bloqueada por este plano.

## 8. Histórico de Revisão

**Rodada 1 — plan-critic via Fable (2026-07-14).** Verificou toda citação arquivo:linha contra o código real (a maioria correta; 3 citações derivadas corrigidas — ver Seção 2). Veredito: "Aprovado com ressalvas". Achados aplicados neste documento:
- `[ALTO]` "Rollback via Escape" era premissa falsa pra ação irreversível — Escape nunca desfez efeito colateral no código, só limpa overlay pra retry. → Substituído por gate de plausibilidade PRÉ-clique (Seção 3, item 4b; Seção 4.A4) — o clique errado deixa de acontecer, em vez de precisar ser desfeito.
- `[ALTO]` Pós-condição de fill genérica (`input_value()` do seletor original) é inverificável no cenário-alvo (seletor já falhou) e quebra com máscara/formato. → Corrigido: ler do elemento proposto/ativo, comparação normalizada (Seção 4.A1).
- `[ALTO]` Contradição pendente entre os 3 documentos `.specs` sobre default de `strict`. → Nota de reconciliação adicionada nos 3 documentos (Seção 7 + topo de cada arquivo anterior).
- `[MÉDIO]` Mecânica flaky ausente da cadeia nova. → Subseção explícita adicionada (Seção 3).
- `[MÉDIO]` Cadeia prometia tier de coordenada pra fill que não existe hoje. → Escopo explícito: fill fica em tiers 1-2-4 na F1; coordenada pra fill vira candidato de F3 (Seção 3, Seção 5).
- `[MÉDIO-ALTO]` Ordem "cognitivo antes da coordenada" regredia custo no select (coordenada com hit-test é mais barata e já verificada) e revertia sem aviso o design "IA disse não achei → pula coordenada" (`runner.py:944`). → Ordem revertida: coordenada verificada roda ANTES do LLM em toda a cadeia (Seção 3); a interação com `runner.py:944` fica moot porque coordenada já não vem mais depois do LLM.
- `[MÉDIO]` Sinal genérico herda falso-positivo documentado (`runner.py:894-901`, backdrop CDK). → Ressalva explícita: exigir pós-condição específica em contexto de overlay (Seção 4.A1; Risco 4).
- `[MÉDIO]` Fase 2 do recorder subestimada (efeito pós-navegação morre com o contexto da página). → Redimensionado (Seção 4.C; Risco 6).
- `[BAIXO]` Wrapper de compatibilidade deprecated (B4) era dead code on arrival — zero chamadores em 186 bots compilados. → Cortado.
- `[BAIXO]` 3 citações de linha derivadas incorretas. → Corrigidas (Seção 2).

**Rodada 2 — plan-critic via Opus 4.8 (2026-07-14), segunda opinião independente.** Verificou toda citação arquivo:linha (Seção 2 e alicerces confirmados corretos) e escrutinou especificamente as emendas da Rodada 1 em busca de problema novo introduzido ao resolver o antigo. Veredito: "Aprovado com ressalvas" — Rodada 1 não convergiu totalmente. Achados aplicados neste documento:
- `[ALTO]` Lista de "pontos de decisão" do rewire (A2, Rodada 1) omitia `fill_human_like` (`runner.py:2254`) — caminho de digitação DEFAULT sob HUMAN_LIKE. A mudança de assinatura de B1 (`self_healing_click` retorna dict em vez de clicar) faria `if clicked:` digitar sem foco correto — corrupção silenciosa na rota quente. → Adicionado explicitamente a A2; B3 agora mapeia os 5 callers afetados (1514, 1594, 2061, 2171, 2254) que precisam migrar juntos no mesmo commit que B1.
- `[MÉDIO]` A justificativa da Rodada 1 pra reordenar coordenada-antes-do-LLM ("acidente de implementação" no click; select "invertido" sendo "corrigido") estava factualmente errada — verificado: no click a ordem atual é deliberada (coordenada é "Último Recurso" por staleness documentada, `runner.py:888-912`), e o select JÁ está na ordem-alvo (coordenada com hit-test antes do cognitivo, 1489-1519). A ação (mover coordenada pro tier 3 no click) continua correta, mas é mudança REAL de comportamento, não no-op. → Seção 3 reescrita: framing correto, e a ressalva de overlay (A1) declarada como dependência dura desse reorder, não ressalva cosmética.
- `[MÉDIO]` Achado novo: gate de plausibilidade pré-clique via `elementFromPoint` não atravessa Shadow DOM fechado (Padrão A sancionado, seletores com `" >> "`) — rejeitaria sistematicamente propostas corretas, neutralizando o tier 4 nesses fluxos. → Mitigado: modo soft do gate quando o seletor original contém `" >> "` (Seção 4.A4).
- `[BAIXO-MÉDIO]` Normalização de fill "strip de pontuação/máscara" genérica demais — mascararia fill errado em texto livre (nome com hífen, endereço com vírgula). → Normalização type-aware: dígitos-only só pra campos numéricos/mascarados conhecidos, exata para texto livre (Seção 4.A1).
- Não-achados confirmados (a tarefa pediu escrutínio, resultado negativo — registrado por transparência): telemetria `VERIFY_REJECTED` pré/pós tem consumidor definido (F3); latência do tier 4 já está tratada como "medir em piloto, não assumir" (Risco 1 + F3) — nenhuma emenda necessária nesses dois pontos.

Recomendação pendente da Rodada 2: verificação final focada especificamente na migração dos 6 call sites de `self_healing_click` (não o diff, o código real pós-implementação) antes de considerar a F1 pronta — é onde mora o risco residual de corrupção silenciosa em runtime não supervisionado.

**Rodada 3 — verificação focada via Opus 4.8 (2026-07-14), item pendente da Rodada 2.** Não é plan-critic geral — redescobriu do zero (sem confiar no mapeamento anterior) todo call site de `self_healing_click` no repo inteiro, checou testes que mockam o método diretamente, e verificou se `cognitive_fallback.py` tem outro método de ação fora de escopo. Resultado:
- **Lista dos 6 call sites de produção: confirmada correta e completa** — redescoberta bateu byte a byte com o mapeamento das Rodadas 1-2. Nenhum call site novo encontrado em `code_generator`/`cockpit`/`recorder`/`sanitizer` (esses instanciam `CognitiveGateway` só pra outros métodos: `diagnose_failure`, `compare_visual_similarity`, `transcribe_audio`).
- **Severidade diferenciada por caller, não mencionada antes**: `933`/`1514` (click/select) = falso-HEALED puro; `2061`/`2171`/`2254` (fills) = corrupção silenciosa de dado via `document.activeElement` sem foco, sendo `2171`/`2254` a rota DEFAULT (maior prioridade); `1594` (select nativo) = único caso que degrada sem corromper (retry re-verifica via `select_option` real). → Adicionado a B3.
- **Escopo do gateway (item 3 da tarefa) confirmado completo**: nenhum outro método de `cognitive_fallback.py` faz ação física fora de `self_healing_click`. → Registrado como não-achado em B5 (novo item).
- `[typo]` "4 callers" no texto da Rodada 2 deveria ser "5" (a lista sempre teve 5 nomes). → Corrigido em B3.
- `[GAP REAL]` Item F do plano nunca enumerava os testes EXISTENTES que quebram com a mudança de contrato `bool→dict` de B1 — 8 métodos quebram duro (`test_cognitive_fallback.py` + `test_runner_integration.py`), 3 sobrevivem por acidente e devem ser saneados. Sem isso, o commit de B1/B3 passaria a impressão de regressão. → Lista nominal adicionada a F.
- **Ressalva sobre a evidência de B4**: a contagem "186 bots compilados, zero chamadores diretos" da Rodada 1 não é reproduzível neste checkout (`projects/` é gitignored, vazio aqui) — o argumento arquitetural continua válido por construção (bots só chamam API pública do runner), mas quem implementar deve reconfirmar contra bots reais antes de tratar "zero chamadores" como fato re-verificado, não só herdado. → Ressalva adicionada a B4.

Nenhum achado novo de severidade ALTA nesta rodada — os gaps encontrados (testes existentes, typo, ressalva de evidência) são MÉDIO/BAIXO e já foram incorporados ao documento. **Plano pronto para virar backlog de execução**, sujeito à reconfirmação da contagem de B4 no ambiente real de implementação.
