# Plano — Implementação das Recomendações da Auditoria de Falso-Sucesso

**Origem:** auditoria em 3 partes (2026-07-15) da tese "os status `Success`/`Healed` do Aegis podem ser falsos-positivos". A auditoria **validou a tese em pontos nomeados** e recomendou uma ordem de prioridade. Este plano executa essas recomendações.

**Invariante central (contrato de todo o plano):** nenhum tier de resolução (identity, determinístico, geometria, coordenada, cognitivo) pode fechar um passo/transação como `SUCCESS`/`HEALED` sem uma pós-condição observável confirmando o efeito real. É a doutrina "Cauda Longa Verificada" — este plano fecha os vazamentos remanescentes dela e a estende ao payload de saída.

**Regra de verificação (não-negociável, lição M1-M5 + gate H8):** toda mudança em lógica de seletor/DOM/timing só é considerada pronta após repro **ao vivo** (browser real, mesmo headless) antes/depois — mock não revela a superfície do bug. Padrão de harness de injeção de falha (recriar/estender por rodada de repro, **não versionado**): alvo gated por `event.isTrusted` (tiers de dispatch sintético não trapaceiam) + churn ancorado no `[RETRY 2]` para isolar o seam do retry-loop do gap `_effect_confirmed`.

---

> **⚠️ Estado (2026-07-16):** F0 + F1.1 (+ o fix do carimbo, achado fora do plano) estão **implementados e aprovados no gate**
> (3/3 SUCCESS, 55/1, ver `.specs/plans/portal-segura.baseline-001.md` Seção 3). **Todo o resto — incluindo os achados
> das 3 revisões independentes e F2/F3 — está registrado, NÃO implementado, em
> [`backlog-achados-falso-sucesso.pending.md`](backlog-achados-falso-sucesso.pending.md).** Ler o backlog antes de
> executar qualquer item deste plano: vários itens abaixo (F1.2, F2) têm defeitos de desenho já mapeados lá.

## Escopo priorizado

| Fase | Item | Recomendação do auditor | Status |
|---|---|---|---|
| **F0** | Fix seam do retry-loop (`click_resilient`) + attempt-aware + baseline por tentativa | Prioridade #0 | ✅ **FEITO** — gate APROVADO |
| **F1.1** | `_effect_confirmed` por tier + roteado por `_verify_action_effect` | Prioridade #0 | ✅ **FEITO** — gate APROVADO |
| **(extra)** | Fix do carimbo (`_verify_generic_effect` recapturava sem seletor) + 4º sinal ciente de valor | achado da R4 (não estava no plano) | ✅ **FEITO** — era pré-requisito de tudo "verificado" |
| **F1 (resto)** | Caminho por exceção, select-side, lado fill | Prioridade #0 remanescente | ⬜ **→ [backlog](backlog-achados-falso-sucesso.pending.md) A1-A5** |
| **F2** | Validação de efeito de saída por JSON Schema em runtime | Proposta #2 — maior valor / menor latência | ⬜ pendente |
| **F3** | DOM semântico no `diagnose_failure` | Proposta #1 — secundária | ⬜ opcional |
| — | Re-fill agentic contínuo | Proposta #3 — **rejeitada** (baixo ROI, fere zero-IA) | ❌ não fazer |
| — | QA visual via LLM | Proposta #4 — **já implementada** (`verify_visual` já é LLM) | ❌ nada a fazer |

Ordem obrigatória: **F0 → F1 → F2 → F3**. F1 é pré-requisito moral de F2 (não faz sentido blindar o payload de saída enquanto os cliques de meio de fluxo ainda mentem). F3 é independente e pode ir a qualquer momento (path já isolado atrás de flag).

---

## F0 — Fix do seam do retry-loop  ✅ FEITO

**O quê:** os 2 call-sites de `_finalize_click_success` ([runner.py:1242](../aegis_runner/runner.py) e [:1390](../aegis_runner/runner.py)) agora embrulham a decisão terminal em `_ClickTerminalFailure` — mesmo contrato do caminho ENABLE_TIMEOUT. Uma decisão CLICK_NO_EFFECT finalizada propaga como terminal em vez de ser retentada pelo loop externo e fechar como `SUCCESS` falso via delta de DOM incidental contra baseline estagnada.

**Verificação já realizada:** repro determinística antes (B = FALSO_POSITIVO) / depois (B = RAISE honesto); A (controle) e C (auto-cura + `needs_review`) verdes; `test_runner_integration.py` 118/118 OK. Doutrina registrada no [CLAUDE.md](../CLAUDE.md).

**Pendências de fechamento:**
- [ ] Reconciliar com a task de worktree já iniciada (evitar fix duplicado) — descartar uma das duas versões.
- [ ] Rodar o gate de regressão contra `TestePortalSegura/cenario_principal` (cognitivo OFF) confirmando que F0 não regride o bot de referência.
- [ ] Commit em branch novo (estamos em `main`).

---

## F1 — Fechar os 2 furos determinísticos remanescentes

O auditor: "a prioridade #0, antes de qualquer feature nova, deveria ser rotear esses 2 tiers por `_verify_action_effect`."

### F1.1 — `_effect_confirmed` bypassa a overlay-caveat (gap documentado, Fimm st_007)

**Problema:** `_attempt_deterministic_click_recovery._effect_confirmed` ([runner.py:1494](../aegis_runner/runner.py)) chama `_click_effect_signals_changed` **direto**, pulando a overlay-caveat de `_verify_action_effect` ([:586](../aegis_runner/runner.py)). Confirmado ao vivo (Fimm `st_007`): match ambíguo de `fallback_selectors` via `.first`, painel de autocomplete nunca fechou, passo logou `HEALED`. Cobre os tiers Escape-retry / CDK-reposition / `fallback_selectors` do lado **click**.

**Abordagem (revisada pós-plan-critic — a v1 era BLOQUEANTE):** rotear `_effect_confirmed` por `_verify_action_effect`, MAS derivando `panel_closed_confirmed` da contagem de painel/overlay pós-recuperação (`_OPEN_PANEL_SELECTOR`, [runner.py:578](../aegis_runner/runner.py), ou o campo `overlays` do snapshot). **Por quê:** a overlay-caveat de `_verify_generic_effect` ([runner.py:790-799](../aegis_runner/runner.py)) é hard-gate incondicional — `if before_had_overlay: return bool(has_expected and expected.get("panel_closed_confirmed"))`. Passar `expected=None` no caso genérico (que o texto v1 admitia ser comum) faz a função **sempre** retornar `False` quando há overlay pré-clique — e overlay pré-clique é justamente o cenário-motivador dos 3 tiers (Escape-retry / CDK-reposition / fallback_selectors existem PARA cliques bloqueados por overlay, inclusive o Fimm st_007). Ou seja: a v1 não deixava o tier "mais rigoroso", **matava** o tier inteiro e cascateava tudo pra coordenada/cognitivo (mais latência, mais LLM, tensiona zero-IA). Fix: quando `before_snapshot` tinha overlay, computar `panel_closed_confirmed = (contagem de painel pós-recuperação == 0)` e passar em `expected`; sem overlay pré-clique, a caveat não se aplica e os sinais genéricos valem normalmente. Preserva a intenção (não aprovar por delta incidental) sem virar parede.

**Arquivos:** `aegis_runner/runner.py` (`_attempt_deterministic_click_recovery`, helper `_effect_confirmed`).

**DoD adicional (crítico, exposto pelo plan-critic):** o repro NÃO pode se limitar ao caso st_007 (que DEVE rejeitar) — precisa incluir ≥1 caso de **caminho feliz com overlay pré-clique que hoje se recupera corretamente** (ex.: overlay removível por Escape → clique real efetiva) e provar que ele CONTINUA `HEALED` após o fix. Senão o DoD "antes HEALED, depois VERIFY_REJECTED" passa mascarando a quebra do caminho feliz.

**Blast radius:** médio — este helper é compartilhado por `_handle_click_failure` (recuperação por exceção) e `_finalize_click_success` (CLICK_NO_EFFECT). Regressão possível: tornar a confirmação MAIS estrita pode transformar curas antes aceitas em falhas honestas (desejável, mas precisa passar no gate de regressão do bot de referência).

**DoD:**
- [ ] Repro ao vivo: caso ambíguo com painel que não fecha → antes `HEALED`, depois `VERIFY_REJECTED`/falha honesta (estender `verify_fix.py` com um cenário `fallback_selectors` + painel persistente).
- [ ] `test_runner_integration.py` verde.
- [ ] Gate de regressão contra baseline (ver nota de infra abaixo).

### F1.2 — Recuperações do lado FILL sem verificação

**Problema:** o fallback ambíguo `.first` do fill JÁ verifica ([runner.py:3028](../aegis_runner/runner.py), via `_verify_action_effect kind="fill"`). Mas o **Escape+retry do fill** ([runner.py:3040-3043](../aegis_runner/runner.py)) loga `SUCCESS` **sem verificação nenhuma**, e o tier `fallback_selectors` do fill idem (localizar o loop; CLAUDE.md o cita como sem verificação). Um fill que "resolve" após Escape mas não gravou o valor real fecha como sucesso.

**Abordagem:** após cada recuperação de fill que hoje loga `SUCCESS` direto, inserir `_verify_action_effect(page, None, expected={"kind":"fill","expected_value":text_val,"locator":<alvo real>})` — reusar exatamente o padrão já presente no branch ambíguo (3028). Só fecha `HEALED` se o valor lido do campo confirmar; senão segue a cadeia.

**Arquivos:** `aegis_runner/runner.py` (`fill_resilient` e seus tiers de recuperação).

**Blast radius:** baixo-médio — localizado em `fill_resilient`. Cuidado com campos mascarados/data (a comparação de `_verify_action_effect kind="fill"` já trata dígitos/ISO — reusar, não reinventar).

**DoD:**
- [ ] Repro ao vivo: campo coberto por overlay removível por Escape mas cujo valor NÃO persiste → antes `SUCCESS`, depois rejeição/falha honesta.
- [ ] Caso de valor que persiste → `HEALED` + `needs_review`.
- [ ] `test_runner_integration.py` verde + gate de regressão.

---

## F2 — Validação de efeito de saída por JSON Schema em runtime (Proposta #2)

**Correção de premissa (do auditor):** o enunciado dizia "a IA valide o payload". **Não precisa de IA** — validação contra `jsonschema` é determinística, latência ~zero, **não fere o princípio zero-IA-runtime nem exige flag**. É a doutrina "efeito verificado" aplicada ao **dado de saída**.

**Achado de escopo honesto (aterrado no código):** hoje os cenários são callbacks `scenario(page, row, self)` que **não retornam payload** — `extracted_val = "EMITTED-OK"` ([runner.py:3526](../aegis_runner/runner.py)) é placeholder fixo. Portanto o VALIDADOR é trivial, mas o trabalho real é a **plumbing do canal de payload**. Além disso o framework é dominantemente **emissão** (emite apólice/proposta), não extração — então o alvo primário da validação não é "dados extraídos" e sim o **artefato de confirmação da transação** (nº de proposta/apólice, tela de sucesso). O plano cobre os dois modos.

**Sub-itens:**

### F2.1 — Canal de payload (pré-requisito)
- Adicionar `self.set_transaction_output(dict)` no `TransactionRunner` (buffer por linha, limpo por transação como `steps_history`).
- Cenário passa a poder registrar o payload (nº confirmação, campos-chave lidos da tela de sucesso). Retrocompat: cenário que não registra nada → payload `None` → validação pulada (comportamento idêntico ao atual).

### F2.2 — Fonte do schema
- Arquivo opcional por teste: `projects/<slug>/tests/<test>/output_schema.json` (JSON Schema padrão). Ausente → validação pulada.

### F2.3 — Hook de validação
- No fim do cenário bem-sucedido ([runner.py:~3508](../aegis_runner/runner.py), antes do append `status:"SUCCESS"`): se schema presente E payload presente, validar. Inválido → **status NOVO** `BUSINESS_BLOCKED` (correção do plan-critic: NÃO existe hoje no vocabulário de saída do runner — que é `SUCCESS`/`SUCCESS_BLOCKED`/`SYSTEM_FAILED`/`FAILED_WRONG_BUSINESS_ERROR`/`CRITICAL_UNEXPECTED_SUCCESS`/`PENDING`; `"BUSINESS_BLOCKED"` só existe hoje como valor de `expected` vindo do dataset) com `error_message` = erro do schema, em vez de `SUCCESS`. Sem `jsonschema` instalado → log de aviso + pular (não quebrar execução). Como é status NOVO, TODO consumidor de `status` a jusante precisa reconhecê-lo (ver F2.5).

### F2.4 — Geração (code_generator)
- O `code_generator` passa a emitir, no fim do cenário, a coleta do artefato de confirmação e a chamada a `set_transaction_output(...)` quando o teste tem `output_schema.json`. Sem schema → nada muda no bot gerado.

### F2.5 — Consumidores de `status` a jusante (exposto pelo plan-critic — escopo faltante na v1)
Novo status `BUSINESS_BLOCKED` cai em allow-lists FECHADAS que hoje o classificariam errado:
- [`aegis_cockpit/project_manager.py:1198-1200`](../aegis_cockpit/project_manager.py): `any_fail` usa allow-list de falha (`SYSTEM_FAILED`/`FAILED_WRONG_BUSINESS_ERROR`/`CRITICAL_UNEXPECTED_SUCCESS`); e `passou` = `["SUCCESS","SUCCESS_BLOCKED"]`. Uma execução cujo único problema seja `BUSINESS_BLOCKED` cairia como `SUCCESS` no rollup — **reintroduz o falso-sucesso um nível acima**, ironicamente na feature que existe pra matá-lo. Fix: trocar allow-list fechada por **deny-list** (`status not in ["SUCCESS","SUCCESS_BLOCKED"]`), alinhando com o padrão já usado em [`cockpit.py:507`](../aegis_cockpit/cockpit.py).
- [`aegis_cockpit/static/index.html:4922`](../aegis_cockpit/static/index.html): mesmo padrão de allow-list fechada (`hasErrors = status === 'SYSTEM_FAILED' || ...`) — mesma correção deny-list.
- **Achado incidental (fora do escopo deste plano, registrar separado):** [`aegis_devops/junit_reporter.py:39`](../aegis_devops/junit_reporter.py) `if status in ("FAILED","ERROR")` já hoje não reconhece `SYSTEM_FAILED`/`FAILED_WRONG_BUSINESS_ERROR`/`CRITICAL_UNEXPECTED_SUCCESS` como falha no XML — bug pré-existente, não deste plano.

**Arquivos:** `aegis_runner/runner.py` (canal + hook), `aegis_code_generator/*` (emissão), `aegis_cockpit/project_manager.py` + `aegis_cockpit/static/index.html` (deny-list de status), `requirements.txt` (`jsonschema`), doc.

**Blast radius:** ALTO — cruza runner + code_generator + bots gerados + Cockpit. É a razão de F2 vir depois de F1 e de o canal (F2.1) ser item separado. Mitigação: tudo é **opt-in por presença de `output_schema.json`** — zero mudança de comportamento para projetos sem schema (mesma política de retrocompat do `weak_selector`/`fallback_selectors`).

**DoD:**
- [ ] Projeto de teste com `output_schema.json` + payload inválido → transação fecha `BUSINESS_BLOCKED`, não `SUCCESS` (repro ao vivo).
- [ ] Rollup do Cockpit para essa execução mostra falha/atenção, NÃO `SUCCESS` (prova que F2.5 fechou o consumidor).
- [ ] Payload válido → `SUCCESS` normal.
- [ ] Projeto SEM schema → comportamento byte-idêntico ao atual (gate de regressão) + Cockpit inalterado.
- [ ] `jsonschema` ausente → aviso, execução não quebra.
- [ ] Teste unitário novo do hook de validação.

---

## F3 — DOM semântico no `diagnose_failure` (Proposta #1, opcional)

**O quê:** em `CognitiveGateway.diagnose_failure` ([cognitive_fallback.py:403](../aegis_runner/cognitive_fallback.py)), anexar (ou substituir a screenshot por) um "full-scan markdown" apenas dos elementos interativos semânticos, reduzindo tokens e alucinação de causa.

**Não fere zero-IA:** `diagnose_failure` só roda sob `AEGIS_COGNITIVE_ENABLED=true` (`is_active()`, [:409](../aegis_runner/cognitive_fallback.py)). É aditivo a um path já gated; **reduz** latência/custo (texto < tokens de imagem).

**Arquivos:** `aegis_runner/cognitive_fallback.py`.

**Blast radius:** baixo — método isolado, path opcional.

**DoD:**
- [ ] Diagnóstico com DOM-markdown produz `category`/`root_cause`/`actionable_fix` ao menos tão bom quanto o baseline de screenshot em ≥1 caso real.
- [ ] `test_cognitive_fallback.py` verde.

---

## Nota de infraestrutura (gate — SEM bloqueio)

**Correção:** não há bloqueio de infra. O `projects/portal_segura` do checkout só tem `.env`, mas o bot de referência **existe e está compilado** em `C:\Projetos\TestePortalSegura\tests\cenario_principal` (fora do checkout `projects/`, análogo ao TesteFimm da baseline anterior):
- `code/bot_producao.py` (57 steps, fluxo completo: login → cliente → veículo → blindagem → residência → pix), `plano_execucao.json`, `dataset_inicial.json` presentes.
- URL `http://localhost:5173/` (no ar, HTTP 200). Credenciais reais no dataset: `admin@portalsegura.com` / `Segura@2026` (verificadas — logam; `admin/admin123` era credencial errada dos meus testes iniciais).
- Última execução (cognitivo ON) completou **SUCCESS** em 136s (53 SUCCESS / 3 HEALED / 10 PENDING), `needs_review=7`. É a linha de base de fato.

**Gate para F1/F2:** rodar `aegis-regression-gate --project-dir "C:\Projetos\TestePortalSegura\tests\cenario_principal"` **com `AEGIS_COGNITIVE_ENABLED=false`** (baseline determinístico — as 3 HEALED da última run podem ter usado IA; precisa de baseline cognitivo-OFF para isolar regressão de runtime). Estabelecer a seção de baseline cognitivo-OFF na primeira rodada; comparar cada item de F1/F2 contra ela. Fallback "repro ao vivo + suíte unitária" continua válido como camada adicional, não como substituto.

---

## 🔎 Achado aberto — verificar no fechamento: bot com tier `coordinate` NÃO é portável para headless/CI

**Descoberto em 2026-07-16** durante o gate do F0 (inicialmente confundido com "site flaky" — não é).

**Sintoma:** o bot de referência (`TestePortalSegura/cenario_principal`) fecha **100% ponta a ponta headed** (SUCCESS, 53/3/10, `verify_rejected=0/0`), mas **falha headless em pontos que MIGRAM entre rodadas** (`st_026`, `st_052`, dropdown "Nível da Blindagem"). Falha que muda de lugar a cada execução é a assinatura de divergência de geometria — não de flakiness.

**Evidência (verificada):**
- `telemetria_resolucao.json` da run boa: `identity=53 (94.6%)`, **`coordinate=3 (5.4%)`** — `st_043`/`st_045` (sliders) e `st_054` (Shadow DOM fechado, onde *só* coordenada funciona).
- `gravacao.json` (81 eventos) grava **apenas `x_percent`/`y_percent`** — **zero metadado de geometria**: `viewport`, `innerWidth`, `innerHeight`, `screen`, `devicePixelRatio` = 0 ocorrências.
- [`runner.py:3395`](../aegis_runner/runner.py): `browser.new_context(locale="pt-BR")` — **sem `viewport`** → Playwright assume default 1280x720, independente da geometria em que se gravou.

**Mecanismo:** coordenada relativa é robusta a escala pura, mas **não a reflow responsivo**. Se a geometria de execução cruza um breakpoint diferente da gravação, o elemento deixa de estar no mesmo `%` → clique por coordenada erra → o passo não cura → cascata em ponto variável. `CognitiveGateway.self_healing_click` usa o mesmo modelo (`viewport.width * x_percent`), logo herda o problema.

**Por que importa (não é só chateação de teste):** `AEGIS_BROWSER_HEADLESS` tem **default `true`**; `verify_visual.py` **força** `headless=true`; o pipeline DevOps roda headless. Ou seja: **todo bot que dependa do tier `coordinate` quebra silenciosamente em CI**, mesmo passando 100% na máquina de quem gravou. É um gap de portabilidade/fidelidade, não do plano de auditoria.

**Hipótese de fix (a validar no fechamento):**
1. Recorder passa a persistir a geometria da gravação (ex.: `gravacao.json.viewport = {width, height}`) — e o Sanitizer a propaga pro `plano_execucao.json`.
2. Runner passa `new_context(viewport=<geometria gravada>)` quando presente; ausente → comportamento atual (retrocompat).
3. Opcional: avisar quando a geometria corrente divergir da gravada (o tier `coordinate` vira suspeito).

**Verificação no fechamento:** rodar o bot de referência **headless com o viewport fixado na geometria da gravação** → deve fechar 100% igual ao headed. Se fechar, hipótese confirmada e o fix vira tarefa própria (fora deste plano de auditoria — é fidelidade de captura, não falso-sucesso).

---

## Fora de escopo (explícito)

- **Proposta #3 (re-fill agentic contínuo):** rejeitada. Loop cognitivo em runtime = maior latência, fere zero-IA (exigiria flag), e `_recover_via_recent_fills` já cobre o caso determinístico.
- **Proposta #4 (QA visual LLM):** já implementada — `verify_visual.py` já delega ao LLM multimodal (`compare_visual_similarity`); os "85%" são limiar aplicado pelo próprio LLM, não similaridade matemática. Nada a fazer além, exceto (fora de escopo) mover de design-time para runtime, o que colidiria com zero-IA.

---

## Próximos passos sugeridos

1. ~~Rodar `plan-critic`~~ ✅ **feito (Sonnet, 2026-07-15)** — veredito "aprovado com ressalvas"; 1 achado bloqueante (F1.1 overlay-caveat) + gaps de escopo F2 (Cockpit) já incorporados acima.
2. **2ª revisão cross-model recomendada pelo próprio plan-critic** (modelo diferente, sem o contexto desta revisão), sobre o plano JÁ corrigido — porque altera lógica de runtime de um motor de RPA sem supervisão humana por passo. (Alinha com a lição "cross-model pega furos não-sobrepostos".)
3. `plan-to-backlog` para gerar o backlog atômico executável.
4. `run-backlog` respeitando a ordem F0→F1→F2 (F0 já feito, só fechar).
