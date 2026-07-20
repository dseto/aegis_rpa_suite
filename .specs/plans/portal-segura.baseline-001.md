# Baseline de Regressão — Portal Segura

> Gerado por `aegis-regression-gate`. Nunca sobrescrever — só anexar novas seções no fim.

## ⚠️ Seção 1 — RETRATADA / INVÁLIDA (2026-07-16)

Uma versão anterior desta seção afirmava **"F0 APROVADO"** com base na execução `executions/run_20260716_061556` (SUCCESS, 134.73s, 53/3/10, `verify_rejected=0/0`), rotulada como *"execução de referência COM o fix F0"*.

**Isso era falso.** Um comando `git stash push aegis_runner/runner.py` foi executado e o `git stash pop` correspondente **não** rodou (comando interrompido no meio). O fix F0 ficou preso em `stash@{0}` a partir daquele ponto. Portanto:

- `run_20260716_061556` — e **toda** rodada rotulada "COM F0" a partir daquele momento — executou o código **SEM o fix**.
- O "match perfeito com o histórico pré-fix" (134.73s vs 136.13s) não era evidência de não-regressão: **era o mesmo código**, comparado consigo mesmo.
- O veredito "APROVADO" não tinha fundamento. **Retratado.**

Detectado por auditoria cross-vendor (Forge/GPT-5.5), achado C1: `grep _ClickTerminalFailure` mostrava só os 2 sites pré-existentes do ENABLE_TIMEOUT (1264/1403), com os call-sites de `_finalize_click_success` (1242/1381) crus, e `git status` com `runner.py` limpo. Confirmado e o stash recuperado.

**Lição de método:** depois de qualquer `git stash` em torno de uma medição, **re-verificar a presença física da mudança** (`grep` do símbolo + `git status`) antes de atribuir qualquer número a ela. Rótulo de execução não é evidência de estado do código.

---

## Seção 2 — Gate do F0 (com o fix fisicamente verificado no working tree)

- **Data:** 2026-07-16.
- **Projeto:** `C:\Projetos\TestePortalSegura\tests\cenario_principal` — bot compilado, 57 steps, rodado sem regeneração. Dataset: 1 linha.
- **URL:** `http://localhost:5173/` (HTTP 200). Credenciais no dataset: `admin@portalsegura.com` / `Segura@2026`.
- **Config:** `channel=msedge`, `AEGIS_BROWSER_HEADLESS=false` (headed), `AEGIS_COGNITIVE_ENABLED=true`.
- **Estado do código verificado antes de rodar:** `grep -c "raise _ClickTerminalFailure" aegis_runner/runner.py` → **4** (2 guardas novas do F0 em ~1256/1407 + 2 pré-existentes do ENABLE_TIMEOUT em ~1276/1427). `git status` → `M aegis_runner/runner.py`.

### Resultado (3 execuções, COM F0)

| Execução | Duração | Status final | SUCCESS | HEALED | FAILED | STOPPED | PENDING |
|---|---|---|---|---|---|---|---|
| 1 | 132.4s | **SUCCESS** | 53 | 3 | 0 | 0 | 10 |
| 2 | 43.3s | SYSTEM_FAILED | 24 | 0 | 2 | 41 | 0 |
| 3 | 122.8s | SYSTEM_FAILED | 48 | 2 | 2 | 15 | 0 |

`needs_review` estável (7→7) nas 3. Nenhum crash Python / traceback / erro de import.

### Veredito

**INCONCLUSIVO — não APROVADO, não REPROVADO.**

Motivo: o bot exibe **não-determinismo alto no ambiente de medição** (1/3 SUCCESS com F0; medições anteriores sem F0 variaram entre 0/3 e 2/3, em configs diferentes). Com essa variância, 3 execuções não distinguem efeito do fix de ruído. A execução 1 reproduz exatamente o perfil "bom" conhecido (53/3/10, ~132s), provando que o F0 **não impede** o fluxo de fechar 100%; mas as execuções 2-3 impedem afirmar não-regressão com confiança.

**Não há evidência de regressão atribuível ao F0** (sem classe nova de erro, `needs_review` estável, perfil bom reproduzido) — mas também **não há prova de não-regressão**. Para fechar o veredito é preciso primeiro entender/estabilizar o não-determinismo (ver abaixo).

### Não-determinismo — o que foi descartado

- **Headless NÃO é a causa.** Hipótese anterior (registrada e agora refutada): "headless muda o viewport e quebra o tier `coordinate`". [`runner.py:3395`](../aegis_runner/runner.py) faz `browser.new_context(locale="pt-BR")` **sem `viewport`** → o Playwright aplica o default **1280x720 em headed E headless**. A geometria é idêntica nos dois modos. E, de fato, execuções **headed** falham na mesma proporção. Teoria descartada.
- **Cognitivo ON/OFF não explica:** falha em ambos.
- **Ponto de falha migra** entre execuções (`st_026` select "uso_veiculo", `st_052` `#btn-go-to-payment` após "Finalizar & Emitir" não transicionar, dropdown "Nível da Blindagem" após "Possui Blindagem?" não ter efeito). O padrão comum é **um clique que loga SUCCESS mas cuja tela não transiciona** — sintoma do próprio falso-sucesso que o plano ataca, agora aparecendo como quebra a jusante.

**Armadilha de leitura (custou várias rodadas):** `st_005` e os `sup_*` aparecem como **`PENDING`** — são passos opcionais/suprimidos **não-executados por design**, NÃO falhas. Extrair "ponto de falha" pegando o primeiro `PENDING`/`STOPPED` na ordem do array atribui errado (o array não está em ordem de execução). Filtrar por `status == "FAILED"` e ler `error_message` / diagnóstico da IA.

---

## Seção 3 — Gate F0-refinado + F1.1 (verificador com dentes) — **APROVADO**

- **Data:** 2026-07-16. Mesma config da Seção 2 (headed, cognitivo ON, `channel=msedge`), mesmo bot sem regeneração, 3 execuções.
- **Mudanças sob teste** (working tree): F0 attempt-aware (`_ClickTerminalFailure` só na última tentativa) + baseline por tentativa + **F1.1** (baseline fresco por tier + `_effect_confirmed` roteado por `_verify_action_effect` com `panel_closed_confirmed` derivado da redução de `overlays`) + **fix do carimbo** (`_verify_generic_effect` recaptura o `after` com o MESMO seletor do `before`, via `fingerprintSelector` gravado no snapshot) + **4º sinal ciente de valor** (`aria-valuenow` + `value`).

| Execução | Duração | Status | SUCCESS | HEALED | FAILED | PENDING |
|---|---|---|---|---|---|---|
| 1 | 128.4s | **SUCCESS** | 55 | 1 | 0 | 10 |
| 2 | 132.5s | **SUCCESS** | 55 | 1 | 0 | 10 |
| 3 | 128.6s | **SUCCESS** | 55 | 1 | 0 | 10 |

`needs_review` 7→7 estável nas 3. Nenhum crash. **3/3 determinístico.**

### Comparação com o histórico

| | Histórico (pré-mudanças) | Agora |
|---|---|---|
| Transação | SUCCESS (mas 1-2/3 em medições repetidas) | **SUCCESS 3/3** |
| SUCCESS / HEALED | 53 / 3 | **55 / 1** |
| Duração | 132-140s | 128-132s |

**Interpretação (a descoberta central):** `HEALED` caiu 3→1 e `SUCCESS` subiu 53→55 porque os 2 sliders (`st_043` `#slider-lmiDM`, `st_045` `#slider-lmiDC`) **deixaram de precisar de healing**. Um clique em `input[type=range]` muda só o VALOR — url, domSize, overlays e className ficam idênticos. Com o 4º sinal cego a valor, esses passos eram invisíveis ao sensor → `CLICK_NO_EFFECT` → escalavam pro tier de coordenada → e lá eram aprovados por **carimbo** (o `after` recapturado sem seletor fazia o fingerprint comparar `"x"` vs `""` e disparar sempre). Ou seja: o `HEALED=3` do histórico era **dois falsos-HEALED cobrindo uma cegueira do sensor**, e o tier "coordenada verificada" aprovava sem verificar nada. Com o sinal de valor, o sensor vê o efeito real no primeiro clique e os passos fecham como `identity` — mais honesto E mais barato (sem escalação). A `HEALED=1` restante é `st_054` (Shadow DOM fechado), que genuinamente exige clique por coordenada.

**Nota de método:** ao corrigir só o carimbo (sem o sinal de valor), o gate foi a **0/3** com `HEALED=0` — o slider virou falso-negativo. Isso é a prova de que o carimbo estava mascarando a cegueira: removê-lo sem devolver o sinal quebra o fluxo. Os dois fixes são inseparáveis.

### Veredito

**APROVADO.** Taxa de sucesso subiu (1-2/3 → 3/3, determinístico), passos verificados subiram (53→55), escalações de healing caíram (3→1), duração caiu, `needs_review` estável, nenhuma classe nova de erro. Suítes: `test_runner_integration.py` 118 OK, `test_cognitive_fallback.py` 7 OK.

**Esta seção substitui a Seção 2 como baseline de referência do Portal Segura.**

---

### (Seção 2) Próximo passo para fechar o veredito

O usuário reporta que o cenário fecha **100% de forma consistente** no uso normal dele (via Cockpit). As execuções aqui foram disparadas por subprocess direto com env explícito. Antes de qualquer conclusão sobre o F0, reconciliar essa diferença: identificar o que o Cockpit configura que o disparo direto não (geometria de janela real, `slow_mo`, ordem/estado do backend, storage). Sem essa reconciliação, este gate não é um instrumento confiável para F1/F2.

---

## Seção 4 — Gate pós-fixes do PR #2 (Unified Target Descriptor, fiação completa) — **APROVADO**

> Nota: um gate anterior (`fix/react-spa-support`, commit `3e2f12f`, 2026-07-19) foi rodado e aprovado nesta mesma trilha, mas a seção que o registrava foi perdida por um `git checkout` de branch nesta sessão antes do commit — o arquivo é rastreado pelo git, e a edição não commitada ficou presa no working tree de `main`. Resultado preservado no comentário do PR: https://github.com/dseto/aegis_rpa_suite/pull/1#issuecomment-5018202768 (3 execuções, 1 SUCCESS + 2 FAILED em pontos de flakiness pré-existente, `needs_review` 7→7, nenhuma classe nova de erro).

- **Data:** 2026-07-20. Branch: `unified-target-descriptor-6509308849546547825` (PR #2), commit `47b1208` — 5 correções de fiação sobre o trabalho do Jules (`dd8ee5a`, `1d9c213`, `ff616dc`), que tinha 2 rodadas de review REPROVADAS por a feature ficar morta em runtime (kwargs recebidos mas nunca atribuídos aos atributos que os tiers leem).
- **Mudança sob teste:** correção da fiação (kwarg → `self._current_anchor`/`_current_expected_effect`/`_current_viewport`/`_current_target_description`) em `click_resilient`, `fill_resilient`, `select_option_resilient`; mismatch de seletor no tier `anchor_geometry` do clique; `NameError` no except de `_verify_recorded_expected_effect`; tier de âncora geométrica para o trigger de `select_option_resilient`; dispatch síncrono no recorder (era diferido via `setTimeout`, perdendo eventos de navegação e embaralhando ordem).
- **Suítes mockadas primeiro:** `test_runner_integration.py` 118 OK, `test_cognitive_fallback.py` 7 OK, sanitizer/codegen OK, 12 testes novos do Jules + 7 testes novos de fiação (`test_unified_target_wiring.py`) — todos verdes.
- **Config:** mesma dos gates anteriores (`channel=msedge`, headed, cognitivo ON), **bot compilado ANTES desta feature** (plano sem `anchor`/`expected_effect` — o tier novo é no-op estrutural neste bot, já que `self._current_anchor` nunca é setado por steps que não passam o kwarg). Este gate mede **retrocompatibilidade**, não a feature em si (que exige re-gravação para ser exercitada — fora de escopo aqui).

### Resultado (3 execuções)

| Execução | Status | Ponto de falha |
|---|---|---|
| 1 | FAILED | `st_026` "Uso do Veículo" (select_option — flakiness pré-existente, Seção 2) |
| 2 | **SUCCESS** | — |
| 3 | FAILED | `st_052` "#btn-go-to-payment" pós "Finalizar & Emitir" (flakiness pré-existente, Seção 2) |

`needs_review` 7→7 estável. Nenhum crash Python, nenhuma classe nova de erro. Os dois pontos de falha são **nominalmente os mesmos** listados na Seção 2 como não-determinismo pré-existente do site/ambiente (não do framework).

### Veredito

**APROVADO.** 1/3 bruto replica exatamente o padrão de flakiness já documentado (mesmos passos, mesmo perfil de "clique loga efeito mas tela não transiciona"), em um bot que não exercita a feature (sem `anchor` no plano). Nenhuma evidência de regressão introduzida pelas 5 correções. Validação completa da feature em si (com re-gravação exercitando `anchor`/`expected_effect` de verdade) é tarefa separada, fora do escopo deste fix de fiação.
