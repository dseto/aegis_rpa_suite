# Backlog rastreável — Achados de falso-sucesso ainda ABERTOS

> **Status: NADA aqui foi implementado.** Documento de registro para não perder achado.
> Origem: auditoria de falso-sucesso (2026-07-15/16) + **3 revisões independentes** do plano
> `.specs/plano-recomendacoes-auditoria-falso-sucesso.md`:
> **R1** plan-critic (Sonnet) · **R2** plan-critic (Fable) · **R3** auditoria cross-vendor (Forge/GPT-5.5) · **R4** reavaliação de direção (Fable).
>
> **Já FECHADO nesta leva** (não repetir): seam do retry-loop (F0, attempt-aware), `_effect_confirmed` bypassando a
> overlay-caveat (F1.1), carimbo do `_verify_generic_effect` (recaptura sem seletor), 4º sinal cego a valor.
> Ver `CLAUDE.md` → "Self-Healing Fallback Chain" e `.specs/plans/portal-segura.baseline-001.md` Seção 3.

---

## A. Falso-sucesso ainda ABERTO no runtime (maior severidade)

### A1 — Caminho por EXCEÇÃO não tem verificação alguma  🔴
**Achado:** R2 + R3. `_handle_click_failure` chama `_attempt_deterministic_click_recovery` com `before_snapshot=None`
(`runner.py` ~2076) → o helper `_effect_confirmed` retorna `True` **incondicional** (contrato "primeiro clique sem
exceção resolve"). Pior que o gap documentado: os tiers escape_retry/cdk_reposition logam **`status="SUCCESS"` cru**
(~2085) — **nem `HEALED`**, portanto **zero registro no Sensor F1**. É a classe do Fimm `st_007`, no caminho de
recuperação **mais frequente**.
**Por que ficou de fora:** F1.1 cobriu só a metade CLICK_NO_EFFECT (que tem baseline).
**Fix candidato:** capturar baseline na entrada de `_handle_click_failure` (a página está estável pós-exceção; o
padrão já existe no `.first` ambíguo) e passar adiante; logar `HEALED` (não `SUCCESS`) quando resolver via tier.

### A2 — Tiers do `select_option_resilient` sem pós-condição  🔴
**Achado:** R2. Contradiz nominalmente o invariante do próprio plano ("nenhum tier — geometria, coordenada — fecha
sem pós-condição"):
- Tier **coordenada** (`runner.py` ~2331-2349): gate de texto via `elementFromPoint` é **pré**-clique apenas; loga
  `HEALED` (~2395) sem pós-condição. O `Escape` em ~2391 ainda contamina qualquer checagem de painel posterior.
- Tier **live-geometry** (~2318, ~2398): fecha `SUCCESS` puro — sem verificação **e sem marca de healing/Sensor F1**.

### A3 — `fill_human_like` (rota identity) sem verificação  🟠
**Achado:** R3 (M12). `runner.py` ~2981-2986: `if res: _log_step(status="SUCCESS")`. Zero verificação.
É a **rota default sempre que `AEGIS_FORCE_HUMAN_LIKE=true`**. O objetivo declarado de F1.2 ("fill que 'resolve' mas
não gravou o valor real fecha como sucesso") continua totalmente aberto nessa rota.

### A4 — F1.2 (recuperações do fill) — escopo e control-flow  🟠
**Achado:** R3 (M11) + original. Ainda aberto:
- Escape+retry do fill (`runner.py` ~3013-3019) loga `SUCCESS` sem verificar.
- `fallback_selectors` do fill (~3027-3042) loga `HEALED` sem verificar. **O `break` é o defeito**: guardar só o
  `_log_step` ainda `break`a → `return True`. A verificação precisa **gatear o `break`** e `continue`ar para o próximo
  fallback quando rejeitado (o lado click já faz certo).
- (`.first` ambíguo do fill já verifica — não mexer.)

### A5 — `_verify_fill_effect`: corrida + exceção em alvo não-`<input>`  🟠
**Achado:** R3 (M13). `locator.input_value()` é lido **imediatamente** após digitar (~854): inputs controlados
(Angular/React) reformatam/revertem no próximo tick → leitura pré-revert = **falso-positivo**. O lado click faz
polling; o fill não. Além disso `input_value()` **lança** em contenteditable/`mat-select` → `except: return False`
(~856) → fill legítimo vira falha honesta. F1.2 multiplicaria os dois por 3 novos call-sites.

---

## B. Limitação estrutural do sinal genérico

### B1 — Churn ambiente engana o identity path (cenário "D")  🔴 conceitual
**Achado:** R4, reproduzido ao vivo. Sinal genérico responde *"algo mudou?"*, nunca *"minha ação causou?"*. Um overlay
que some sozinho, carrossel ou toast de outro processo cai na janela de polling de `_detect_click_no_effect` e fecha
`SUCCESS` **identity** — sem healing, sem `needs_review`, sem rastro. Nenhum refinamento de baseline resolve.
**O que o piso genérico prova:** "não há evidência de não-efeito". **O que não prova:** "o clique causou efeito".
**⚠️ ARMADILHA (registrar):** NÃO endurecer o identity path com a overlay-caveat — rejeitaria cliques legítimos que
fecham painel (opção de autocomplete, OK de dialog) → dispararia a recovery → **re-clique de um clique que funcionou =
ação de negócio DUPLICADA**. Falso-negativo com efeito físico é pior que falso-positivo de status.
**Mitigação interina:** detectar a assinatura "delta = só `overlays` diminuiu, com `overlays>0` na baseline" e
**aceitar-mas-marcar** (`verify_result="generic_weak_overlay"` na telemetria + `needs_review` via Sensor F1), **sem
re-clicar**. Resolve auditabilidade sem risco de duplicação.
**Fix real:** Fase 2 — `expected_effect` por gesto gravado na captura (o recorder *vê* o efeito do clique humano).
**B1 é o argumento mais forte para priorizar a Fase 2.**

### B2 — Consolidar o choke point de aprovação  🟡
**Achado:** R4. `_click_effect_signals_changed` é chamado direto em 3 lugares com política própria:
`_detect_click_no_effect` (~566), `_wait_if_wizard_transition_button`, e (antes do F1.1) `_effect_confirmed`.
Toda **aprovação** deveria passar por `_verify_action_effect` como ponto único.

---

## C. Riscos do que JÁ foi implementado (revisar, não reverter)

### C1 — Multiplicação de cliques físicos no retry  🟠
**Achado:** R4. Com o attempt-aware: attempt 1 = clique + cadeia (escape_retry + clique sintético CDK + N
`fallback_selectors`) → raise retentável → attempt 2 **repete tudo**. São ~6-10 gestos num alvo que o sensor
*acredita* inerte. Se o sensor errou (efeito real com latência > ~1.2s — o caso closed-shadow documenta 3-4s), isso
**duplica ação de negócio** E fecha `FAILED` honesto num passo que funcionou.
**Fix candidato (barato):** um passe de `_poll_generic_effect_extended` **antes** de entrar na recovery / levantar o
retentável — custo só no caminho de falha.

### C2 — `_effect_confirmed` é single-shot, sem polling  🟠
**Achado:** R3 (H6). `_detect_click_no_effect` faz polling 100/300/800ms; `_effect_confirmed` faz **uma** captura.
`_poll_generic_effect_extended` existe (~699) justamente porque efeito real pode levar **~6s** para aflorar no light
DOM. Resultado: **falsos-negativos** em app latente → cascata para coordenada/cognitivo → mais latência e mais LLM.
**Fix candidato:** `_effect_confirmed` polling sobre a janela de `_detect_click_no_effect`.

### C3 — Catch largo demais na guarda terminal  🟡
**Achado:** R4. Os call-sites (~1260/1422) fazem `except Exception` e, no attempt 2, embrulham **qualquer** exceção
como terminal — inclusive um bug interno de `_finalize_click_success`, que antes iria para `_handle_click_failure`.
Estreitar o catch.

### C4 — `attempt < 2` acopla ao literal `range(1, 3)`  🟢 cosmético
**Achado:** R4. Um bool `is_last_attempt` seria à prova de extensão do loop.

---

## D. F2 (JSON Schema em runtime) — corrigir ANTES de implementar

### D1 — Renomear o status novo  🔴
**Achado:** R2 + R3 (H7). `BUSINESS_BLOCKED` **já é vocabulário de `expected_result`** do dataset ("esperamos que o
portal bloqueie") — `runner.py` ~3428/3486/3577, `sanitizer.py` ~646. E convive com `SUCCESS_BLOCKED`, que é **PASS**.
Emiti-lo como status de FALHA é armadilha semântica e é errado: payload fora do schema não é bloqueio de negócio — o
fluxo completou. **Renomear para `OUTPUT_SCHEMA_VIOLATION`.** Custo zero (o status ainda não existe).

### D2 — Hook no lugar errado pula linhas de teste negativo  🔴
**Achado:** R3 (H7). F2.3 posiciona o hook dentro do `else` de `if expected == "BUSINESS_BLOCKED"` (~3486). Uma linha
que legitimamente espera bloqueio e **tem sucesso** vai para `CRITICAL_UNEXPECTED_SUCCESS` (~3492) e **nunca é
validada contra o schema**.

### D3 — `ValidationError` seria classificada como erro de negócio  🟠
**Achado:** R3 (M10). O hook cai dentro do `try` cujo `except Exception` (~3562) roda classificação de erro de
negócio: um toast visível (~3571) flipa para `SUCCESS_BLOCKED` (~3583) ou `FAILED_WRONG_BUSINESS_ERROR`.
**Usar `Draft7Validator(...).iter_errors()` / checagem booleana — nunca o raise de `validate()` ali dentro.**

### D4 — Buffer de payload: limpar no TOPO da linha  🟠
**Achado:** R3 (M9). O handler de `FlakyStepFailure` faz `continue` no laço de restart (~3537) sem reset de payload.
Limpar no *fim* da linha (espelhando `steps_history`) faria uma tentativa de retry que **não** setou payload validar o
payload **stale da tentativa anterior** → `SUCCESS`. Falso-sucesso novo, injetado pela feature anti-falso-sucesso.
**Limpar no topo do `try` por linha (~3460).**

### D5 — Mapeamento schema→seletor é indefinido  🔴
**Achado:** R2. O recorder captura **ações**, nunca **leituras** — não existe fonte determinística dizendo *qual
seletor* contém o nº de proposta/apólice na tela de sucesso. `output_schema.json` define a **forma**, não a
**localização**. Como escrito, F2.4 só é implementável com LLM chutando seletor (alucinação) ou fica no-op silencioso
— nos dois casos o DoD passa em teste sintético e falha no mundo real.
**Fix candidato:** convenção `x-aegis-selector` por propriedade no próprio schema (autor fornece o seletor —
determinístico, zero-IA); slot cognitivo só como fallback opcional.

### D6 — Consumidores de `status` a jusante  🟠
**Achado:** R1 + R3 (H8) + R3 (M14). Um status novo cai em allow-lists **fechadas**:
- `aegis_cockpit/project_manager.py` **:1200** (`any_fail`) — **só esta linha muda** para deny-list.
  ⚠️ **:1198** (`passed_rows`) é allow-list de **PASS**, polaridade **correta** — aplicar deny-list aí **inverteria o
  contador**. R1 citou "1198-1200" sem nomear a linha; R3 pegou o erro.
- `aegis_cockpit/static/index.html` **:4922** — allow-list fechada que **também omite `CRITICAL_UNEXPECTED_SUCCESS`**
  (falso-sucesso **pré-existente**: sucesso inesperado renderiza badge verde hoje). `hasErrors` alimenta
  `loadExecutionInsights` (~4926) — deny-list dispara insights para linhas que hoje não disparam; checar custo.
- `index.html` **:4376** — consumidor por linha não listado no plano (polaridade segura; conferir o else-branch).
- `cockpit.py` :507 e `runner.py` :3693 **já usam deny-list** — nada a fazer.

---

## E. Fora do escopo deste plano (registrar e não esquecer)

### E1 — `junit_reporter.py` não reconhece os status de falha  🟠
**Achado:** R3. `aegis_devops/junit_reporter.py:39`: `if status in ("FAILED", "ERROR")` — **não** reconhece
`SYSTEM_FAILED` / `FAILED_WRONG_BUSINESS_ERROR` / `CRITICAL_UNEXPECTED_SUCCESS` como falha no XML JUnit.
**Bug pré-existente**, não introduzido por nenhum plano. Pipeline Azure reporta verde para execução que falhou.

### E2 — Portabilidade headless / tier `coordinate`  🟡
**Status:** hipótese original **REFUTADA** — `new_context(locale="pt-BR")` (`runner.py` ~3395) **não passa viewport**,
então Playwright emula **1280x720 em headed E headless**; a geometria é idêntica. Execuções headed falhavam na mesma
proporção. O delta headed/headless (se real) viria de renderização (headless oculta scrollbars → `innerWidth` difere
~15px → reflow; métricas de fonte), não de viewport.
**Fato que permanece:** `gravacao.json` (81 eventos) grava **só** `x_percent`/`y_percent`, **zero** metadado de
geometria (`viewport`/`innerWidth`/`screen`/`devicePixelRatio` = 0 ocorrências). Persistir a geometria da gravação +
`new_context(viewport=...)` continua sendo um fix barato e correto de fidelidade **captura→replay** — mas um resultado
negativo do experimento indica **segundo mecanismo** (scrollbars/fontes), não refuta a persistência.
**Nota:** após F1.1 + sinal de valor, o gate fecha **3/3 headed**. Re-medir headless antes de concluir qualquer coisa.

### E3 — Não-determinismo do bot de referência  🟡
`st_005` e os `sup_*` são **`PENDING` por design** (opcionais/suprimidos, não-executados) — **não** são falha.
Extrair "ponto de falha" pegando o primeiro `PENDING`/`STOPPED` na ordem do array **atribui errado** (o array não está
em ordem de execução). Filtrar por `status == "FAILED"` e ler `error_message`/diagnóstico da IA.

---

## Ordem sugerida quando for executar

1. **A1** (caminho por exceção) — maior superfície de falso-sucesso ainda aberta, e é o caminho mais frequente.
2. **A2** (select-side) — o invariante do plano os condena nominalmente.
3. **C1 + C2** (polling estendido antes de recovery/retentável) — mitiga duplicação de ação E falso-negativo, mesma mudança.
4. **A4 + A5 + A3** (lado fill).
5. **B1** (aceitar-mas-marcar) — auditabilidade barata enquanto a Fase 2 não vem.
6. **D1-D6** — só depois de A/B/C; renomear o status é pré-requisito.
7. **E1** — independente, pode ir a qualquer momento.

**Regra de verificação para todos:** repro **ao vivo** antes/depois (browser real) + suítes + gate contra
`TestePortalSegura/cenario_principal` (headed, cognitivo ON) comparado com `portal-segura.baseline-001.md` Seção 3.
Mock não enxerga esta classe de bug — todos os furos acima vivem na fronteira selector/DOM/timing.
