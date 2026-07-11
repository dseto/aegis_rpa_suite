# Plan Critic — Self-Healing Tracking + Flaky Retry
**Data:** 2026-07-05  
**Revisor:** Arquiteto Sênior + QA Principal  
**Status:** Aprovado com Ressalvas (bloqueante: Achado 1)

---

## ⚖️ Veredito Geral

Arquitetura da F2 (state-based, `FlakyStepFailure`, restart por linha) é sólida e as premissas revisadas batem com o código real — o trabalho de revisão anterior foi bem feito. Porém o design **erra o alvo no método de dropdown custom**: mapeia a linha 806 como `select_option_resilient`, quando 806 é `select_option_native_resilient` — e o dropdown custom (o caso st_034 que motivou a feature inteira) fica **fora** da cobertura de flaky-retry e parcialmente invisível ao sensor da F1.

**Veredito:** **Aprovado com Ressalvas** — ressalva 1 é bloqueante: exige ajuste no backlog antes de despachar os Subagentes 01 e 05.

---

## 🔍 Análise Crítica de Benefício vs. Raio de Impacto

* **Análise de Benefício:** Sim. F1 é sensor barato sobre ponto único (`_log_step`); F2 resolve flakiness real documentada (Padrão J). ROI bom — *desde que* cubra o método onde a flakiness de fato acontece (ver Achado 1).
* **Abordagem Cirúrgica:** Plano é focado — bot compilado e `code_generator.py` intocados, decisão correta e verificada (gate AST em `aegis_sanitizer/step_validator.py:548` confirma que parâmetro extra quebraria mesmo). Blast radius honesto.

---

## ⚠️ Pontos Críticos Encontrados

### 1. Inconsistências & Gaps

#### Achado 1 (BLOQUEANTE) — F2 não cobre o dropdown custom, o caso-título da feature

**Localização:** Design (linha 127) e backlog (Subagente 05) apontam "`select_option_resilient` em :806". Falso: `aegis_runner/runner.py:806` está dentro de `select_option_native_resilient` (def na :767, `<select>` nativo). O `select_option_resilient` real (def na `runner.py:551` — dropdown custom Angular/Material) tem shape diferente: o strict na :738 só pula o cognitive, e a falha termina num `RuntimeError` incondicional em `runner.py:765`. O comentário em :624-633 confirma: a causa raiz do st_034 (o exemplo flaky do Padrão J) vive **dentro deste método**.

**Impacto:**
- Passo flaky de dropdown custom levanta `RuntimeError`, não `FlakyStepFailure` → `run()` trata como falha definitiva → zero restart. A feature não funciona para o cenário que a justificou.
- Subagente 05 manda localizar por texto `'[STRICT] Falha definitiva'` esperando 4 pontos — o grep real retorna **5** matches (475, 739, 806, 1115, 1195). Subagente frio pode editar :739 com o padrão errado (lá não existe `raise e` para substituir).

**Sugestão:** Adicionar 5º ponto de instrumentação: antes do `raise RuntimeError` em :761-765, aplicar a mesma decisão flaky (levantar `FlakyStepFailure` se flaky e tentativa ≤3; deixar o cognitive rodar se tentativa ≥4 — aqui exige também condicionar o `strict` da :738/:740). Corrigir nomes/linhas no design e no bloco do Subagente 05.

---

#### Achado 2 — Sensor F1 é cego para healing no dropdown custom

**Localização:** Em `select_option_resilient`, o healing cognitivo (:740-751) e o fallback de coordenada (:715-728) marcam `option_clicked=True` e caem no log de **`SUCCESS`** na `runner.py:759` — nunca `HEALED`. O design afirma que os 6 pontos grep-confirmados são "os pontos reais que emitem HEALED" — literalmente verdade, mas o grep achou quem *emite* HEALED, não todos os caminhos de healing. Este método cura sem emitir.

**Impacto:** Exatamente os passos mais instáveis (dropdowns custom com overlay) nunca geram `needs_review`. O sensor perde sua fonte mais valiosa.

**Sugestão:** Flag local no método (ex.: `healed_via_fallback`) e logar `HEALED` em vez de `SUCCESS` na :759 quando o clique veio de cognitive/coordenada. É correção de logging pré-existente — cabe como item novo no backlog (pode ser junto do Subagente 01).

---

#### Achado 3 — Caminho do `correcoes_acumuladas.json` ambíguo no backlog

**Localização:** Runner grava `historico_passos.json` em **dois** lugares: `output_dir/reports/` (`runner.py:150`) e raiz do `project_dir` (`runner.py:1707`). Cockpit lê `correcoes_acumuladas.json` na **raiz** do test_dir (`cockpit.py:641`). Backlog diz só "mesmo diretório de teste onde resolve historico_passos.json".

**Impacto:** Subagente frio pode gravar em `reports/` → Cockpit nunca enxerga as entradas.

**Sugestão:** Especificar no bloco 01: raiz de `self.project_dir`, padrão da linha 1707.

---

#### Achado 4 — Restart precisa englobar o reset de `steps_history`

**Localização:** Ordem atual em `run()`: cria página (:1477) → inicializa `steps_history` com PENDING (:1493-1508) → chama cenário (:1550). O while do Subagente 06 deve começar **antes** da :1493, senão entradas FAILED da tentativa anterior sobrevivem no histórico (mitigado parcialmente porque `_log_step` atualiza por step_id, mas passos não re-alcançados ficariam sujos).

**Sugestão:** Explicitar no bloco 06 que o corpo do while é :1477→:1555 (página + reset de histórico + cenário).

---

### 2. Overengineering & Complexidade

Sem sinais relevantes. Lock via `msvcrt` é aceitável para o ambiente Windows declarado; só exigir que `_register_healing_for_review` seja **não-fatal** (try/except total — sensor jamais pode derrubar uma transação por I/O; o backlog não diz isso explicitamente).

---

### 3. Riscos, Alucinações & Inviabilidade

#### Achado — `step_id` não é identidade estável, é índice posicional

**Localização:** `st_{i+1:03d}` é gerado por enumeração pós-dedup (`aegis_sanitizer/sanitizer.py:1032`). Re-sanitizar a **mesma** gravação é determinístico (merge do Subagente 04 funciona para o gap descrito). Mas uma **re-gravação** desloca índices: a marca `flaky` gruda silenciosamente no passo errado.

**Mitigação Proposta:** No merge, validar chave secundária (`type` + `selector` do step antigo vs novo); se divergirem, descartar a marca com warning no log do Sanitizer. Ou, no mínimo, documentar a limitação no design e no Padrão R.

**Nota menor:** Whitelist final do plano (:1030-1044) descarta campos não listados — `flaky` precisa entrar nela, não só no dict intermediário. O fallback do prompt do Subagente 04 cobre, e o teste (a) pegaria a regressão; só conferir no gate.

---

## 🛠️ Recomendações de Ajuste (Plano de Ação)

### Ação 1 (BLOQUEANTE) — Corrigir design + backlog (Subagente 05)
- Trocar rótulo ":806 = select_option_resilient" por `select_option_native_resilient` (essa é nativa)
- Adicionar 5º ponto de instrumentação no `select_option_resilient` real (:738/:761-765, shape adaptado)
- Avisar que o grep por `'[STRICT] Falha definitiva'` retorna 5 matches, não 4

### Ação 2 — Adicionar ao Subagente 01 (ou bloco novo)
- Logar `HEALED` na `:759` quando healing/coordenada resolveu o dropdown custom
- Senão F1 nasce cega para o pior caso

### Ação 3 — Precisar caminho no Subagente 01
- `correcoes_acumuladas.json` na raiz de `self.project_dir` (padrão `:1707`)
- Exigência de sensor não-fatal (try/except total em `_register_healing_for_review`)

### Ação 4 — Precisar escopo do while no Subagente 06
- Englobar `:1477-1555` (página + reset `steps_history` + cenário)
- Deixar claro que restart é COMPLETO da linha, não só do cenário

### Ação 5 — Subagente 04
- Merge com chave secundária `type+selector` (ou documentar limitação de re-gravação)
- Garantir `flaky` na whitelist final (:1030-1044)

---

## Próximas Etapas

Itens 1-2 mudam conteúdo de blocos → caminho certo é passar pelo `plan-to-backlog` para emendar o backlog antes de retomar o `run-backlog` (que está parado na Fase 1, sem nada executado — subagentes morreram no limite de sessão).

**Status do backlog:** Não iniciar novos subagentes até correções serem aplicadas.
