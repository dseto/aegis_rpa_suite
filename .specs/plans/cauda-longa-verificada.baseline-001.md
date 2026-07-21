# Baseline de Regressão — Cauda Longa Verificada

> Gerado por `aegis-regression-gate`. Nunca sobrescrever — só anexar novas seções no fim.

## Seção 1 — Baseline inicial (pré-implementação)

- **Data:** 2026-07-14
- **Commit:** `7af1586` (`7af158670f3680e680a0ff0759697368aece94ff`) — antes de qualquer mudança do backlog `.specs/plano-cauda-longa-verificada.backlog.md`.
- **Projeto de referência:** `C:\Projetos\TesteFimm\tests\cenario_principal` (fora do checkout padrão `projects/` — projeto criado pelo usuário especificamente para servir de baseline desta implementação, já que `projects/portal_segura` está vazio neste ambiente/gitignored).
- **URL alvo:** `http://localhost:6174/login` (dev server local, confirmado HTTP 200 antes de cada rodada).
- **Browser:** MS Edge (`channel="msedge"`, padrão do `TransactionRunner`) — não regenerado, bot rodado tal como compilado.
- **Bot:** `code/bot_producao.py`, plano `plano_execucao.json` (47 steps, `fidelity_summary`: raw_events=48, steps_required=43, steps_optional=0, steps_suppressed=4, merges=1). Dataset: 1 linha.

### Tabela de métricas (3 execuções)

| Execução | Duração | Status final | Passos SUCCESS | Passos HEALED | Passos STOPPED | Passos FAILED | Total passos logados | Ponto de falha |
|---|---|---|---|---|---|---|---|---|
| 1 (`exec_20260714_172849_1`) | 211.6s | FAILED | 19 | 6 | 21 | 2 | 48 | `st_026` (fill_chained — campo "Taxa Strike Garantida" não encontrado; tela não avançou após seleção do par de moedas) |
| 2 (`exec_20260714_173351_2`) | 211.9s | FAILED | 19 | 6 | 21 | 2 | 48 | `st_026` — mesmo ponto |
| 3 (`exec_20260714_173811_3`) | 211.9s | FAILED | 19 | 6 | 21 | 2 | 48 | `st_026` — mesmo ponto |

### Resumo de médias

- **Taxa de sucesso da transação:** 0% (0/1 linha do dataset) — determinístico, mesma falha nas 3 execuções (não é flakiness).
- **Duração média:** 211.8s.
- **Passos SUCCESS médio:** 19/48 (~40%). **HEALED médio:** 6/48. `healing_method` não populado nos passos HEALED deste bot (campo `None` — bot foi compilado antes de alguma instrumentação de método; não é regressão, é característica do artefato pré-existente).
- **`correcoes_acumuladas.json`:** 9 entradas totais, todas `needs_review`, estável nas 3 execuções (nenhuma entrada nova surgiu entre runs — 9 antes e depois de cada execução).

### Observações

- Falha é **sistêmica e determinística**: o bot para sempre no mesmo passo (`st_026`), mesma causa raiz nas 3 execuções — indica gap real no plano de execução (o fluxo depende de uma tela subsequente que não foi alcançada, conforme diagnóstico IA), não flakiness de rede/timing. Bom para baseline: qualquer regressão real deve mudar ESTE padrão (novo tipo de falha, novo ponto de parada, ou queda de sucesso abaixo do que já é 0%).
- Este bot foi compilado num checkout anterior — não exercita necessariamente M3/M5/fallback_selectors mais recentes (ressalva padrão da skill). Não é impeditivo para o propósito deste baseline (medir regressão do runtime do plano "Cauda Longa Verificada", que altera `runner.py`/`cognitive_fallback.py` independente de quando o plano foi gerado).
- **Uso deste baseline:** cada tarefa do backlog `.specs/plano-cauda-longa-verificada.backlog.md` que altera `aegis_runner/runner.py` ou `aegis_runner/cognitive_fallback.py` deve rodar este gate novamente (mesmo projeto, mesma URL) e comparar contra esta seção. Critérios de aprovação: taxa de sucesso não pode cair abaixo de 0% (não pode, é o piso), nenhuma NOVA classe de erro sistêmico (crash Python, exceção não capturada, erro de import — falha em `st_026` pela mesma causa continua sendo variância aceitável), `needs_review` não pode crescer +3 ou mais, duração não pode dobrar (teto ~424s).

**Baseline capturado; próximas execuções serão comparadas contra esta seção.**

## Seção 2 — Gate pós-SUB03 (contrato proposto→verificado + migração dos 6 call sites)

- **Data:** 2026-07-14
- **Estado:** working tree em cima do commit `7af1586`, sem commit (backlog `.specs/plano-cauda-longa-verificada.backlog.md`, SUB01+SUB02+SUB03 aplicados). Arquivos alterados: `aegis_runner/cognitive_fallback.py`, `aegis_runner/runner.py`.
- **Mesmo projeto/URL da Seção 1**, 3 execuções.

### Tabela de métricas

| Execução | Duração | Status final | SUCCESS | HEALED | STOPPED | FAILED | Total passos | Ponto de falha |
|---|---|---|---|---|---|---|---|---|
| 1 (`gate_sub03_..._1`) | ~136s | FAILED | 17 | 4 | 25 | 2 | 48 | `st_022` |
| 2 (`gate_sub03_..._2`) | ~136s | FAILED | 17 | 4 | 25 | 2 | 48 | `st_022` |
| 3 (`gate_sub03_..._3`) | 133.8s | FAILED | 17 | 4 | 25 | 2 | 48 | `st_022` |

`correcoes_acumuladas.json`: 9 entradas, 9 `needs_review` — **inalterado** vs. Seção 1 (nenhuma entrada nova).

### Divergência vs. baseline (Seção 1) e diagnóstico

Ponto de falha migrou de `st_026`→`st_022` (mais cedo); SUCCESS caiu 19→17; HEALED caiu 6→4. **Por leitura mecânica dos critérios padrão da skill ("taxa de sucesso não pode cair"), isso pareceria REPROVADO.** Investigação do log completo (`stdout.log` das 3 execuções, idêntico) mostra que não é regressão:

1. `st_022` (`fill_chained` em `input[type='range']`, "Piso de Alerta") falha no fill primário porque o elemento está **`disabled` no DOM** (`<input disabled ... type="range" value="5.75">`) — problema pré-existente do plano/site, não do runner.
2. O self-healing cognitivo é acionado; a IA de visão propõe coordenada `(1095, 580)`, que na verdade aponta pra um painel de "Configuração de Alarme Cambial" **completamente diferente** (contém a substring "5.45" por coincidência, mas é outro componente da tela).
3. **`_hit_test_plausible` rejeita a proposta ANTES do clique** — texto do elemento sob o ponto não bate com `target_description` — log `[VERIFY_REJECTED]` pré-clique, **nenhuma ação física executada**.

Na Seção 1 (código antigo), esse EXATO cenário — mesma falha de fill primário, mesmo erro de alvo da IA — clicava cego na coordenada errada, digitava em qualquer coisa que ganhasse foco, e reportava incondicionalmente `HEALED=True`/`healing_method=None` (confirmado: `st_022` era `HEALED` na Seção 1). Ou seja: **a queda de SUCCESS/HEALED não é perda de capacidade — é a remoção de um falso-positivo que a Seção 1 carregava sem detectar.** É exatamente a doutrina do plano (Seção 1 do plano: "ação cega... morre") funcionando em produção, contra um site real, no primeiro caso não-trivial encontrado.

**Working Agreement #3 do CLAUDE.md** (regressão de métrica não é automaticamente bug — investigar antes de reverter) se aplica: métrica caiu, causa raiz investigada, é comportamento correto e desejado, não regressão real.

### Veredito

**APROVADO, com exceção anotada.** Nenhuma classe NOVA de erro sistêmico (mesmo padrão de timeout/disabled-element já visto na categoria da Seção 1); `needs_review` estável; duração menor (menos trabalho feito antes do stop, consistente com falha mais cedo). A queda de SUCCESS/HEALED é explicada e é o efeito pretendido do plano, não regressão de framework. **Ressalva para o backlog**: o `input[type='range']` `disabled` em `st_022` é um gap real do PLANO deste projeto Fimm (falta um passo anterior pra habilitar o campo, ou o campo nunca deveria ter sido mapeado como fill) — fora de escopo desta implementação (é problema de geração/gravação, não de runtime), mas vale reportar ao usuário como achado incidental.

## Seção 3 — Gate pós-SUB04 (coordenada gravada verificada antes do LLM no click)

- **Data:** 2026-07-14. Working tree em cima do commit `7af1586`, sem commit (SUB01+02+03+04 aplicados).
- **3 execuções, mesmo projeto/URL.**

| Execução | Status final | SUCCESS | HEALED | STOPPED | FAILED | Ponto de falha |
|---|---|---|---|---|---|---|
| 1 | FAILED | 17 | 4 | 25 | 2 | `st_022` |
| 2 | FAILED | 17 | 4 | 25 | 2 | `st_022` |
| 3 | FAILED | 17 | 4 | 25 | 2 | `st_022` |

`needs_review`: 9, estável (idêntico à Seção 2).

**Veredito: APROVADO, sem exceção.** Métricas idênticas à Seção 2 (pós-SUB03) — o reorder da coordenada-antes-do-cognitivo no click não alterou nenhum resultado observável neste cenário (o click de `st_022` que falha é um fill, não um click; os clicks deste fluxo não passaram pelo tier de coordenada gravada nesta execução). Nenhuma divergência a investigar.

**Achado incidental confirmado pelo usuário** (fora do escopo de SUB04, aguardando SUB05): `st_007` (click em `.grid button`, seletor ambíguo casando múltiplos botões no dropdown de autocomplete "Banco Destinatário") continua `HEALED`/`usedHealing=true` sem nenhuma verificação de efeito — vai pelo tier T1 (heurística multi-candidato, `runner.py` bloco "Heurística Estática"), que usa o sensor CLICK_NO_EFFECT antigo (sem a ressalva de overlay do `_verify_action_effect` novo), não o contrato proposto→verificado. Usuário observou ao vivo (screenshot) o dropdown permanecendo aberto na tela mesmo com o passo marcado HEALED. Este é exatamente o escopo do SUB05 — usar como caso de teste explícito no gate de browser real daquela tarefa.

## Seção 4 — Gate pós-SUB05 (T1/T2 verificados) + achado incidental novo

- **Data:** 2026-07-14. Working tree em cima do commit `7af1586`, sem commit (SUB01-05 aplicados).
- **3 execuções, mesmo projeto/URL.** Todas: `SUCCESS=17, HEALED=4, STOPPED=25, FAILED=2`, falha em `st_022`, `needs_review=9`. Idêntico à Seção 3 (pós-SUB04) — **APROVADO, sem exceção**.

### Correção de diagnóstico sobre `st_007`

A Seção 2/3 supôs que `st_007` (autocomplete de banco, `.grid button`) iria pelo tier T1 (heurística multi-candidato) e seria corrigido pelo SUB05. **Investigação do log completo mostrou que isso estava errado.** `st_007` na verdade resolve via `[FALLBACK SELECTOR]` — o tier de `fallback_selectors` (Nível 2.9, dentro de `_attempt_deterministic_click_recovery`, código M5 pré-existente ao plano inteiro), depois de 2 tentativas do seletor primário (`button:has-text(...)`) darem timeout.

**Causa raiz real:** `_attempt_deterministic_click_recovery` (Níveis 2.5 escape-retry, 2.75 CDK-reposition, 2.9 fallback_selectors) tem um helper local `_effect_confirmed` (`runner.py:1174-1178`) que chama `_click_effect_signals_changed` **diretamente**, sem passar pelo `_verify_action_effect` (SUB01) e sua ressalva de overlay. É a mesma classe de falso-positivo documentada em `runner.py:894-901` (fechar painel via backdrop CDK muda os sinais genéricos "parecendo efeito real"), ressurgindo num código que nenhuma tarefa do backlog (SUB01-08) tem escopo pra tocar.

**Status: bug real, confirmado, fora do escopo do backlog atual.** `st_007` continua `HEALED` sem verificação de overlay em todas as 3 execuções pós-SUB05 — comportamento inalterado desde a Seção 2. Decisão pendente com o usuário: adicionar tarefa nova (candidata: "SUB05b — rotear Níveis 2.5/2.75/2.9 de `_attempt_deterministic_click_recovery` por `_verify_action_effect`") antes de prosseguir pro SUB06, ou registrar e prosseguir com o backlog original primeiro.

## Seção 5 — Reimplementação completa pós-perda + gate final (2026-07-15)

- **Contexto:** SUB01-07 (código) perdidos por colisão com sessão concorrente (working tree nunca commitada — ver relato do `close-backlog` run). Reimplementados do zero usando a suíte de testes gitignored sobrevivente (`test_runner_integration.py`/`test_cognitive_fallback.py`) como especificação exata. **Desta vez, cada tarefa foi commitada imediatamente após o gate fechar** — 7 commits locais (`f8a82c2`..`c5d6909`), suíte 118+7 testes 100% verde.
- **3 execuções, mesmo projeto/URL, código atual (pós-reimplementação completa).**

| Execução | Status final | SUCCESS | HEALED | STOPPED | FAILED | Ponto de falha |
|---|---|---|---|---|---|---|
| 1 (`gate_reimpl_..._1`) | FAILED | 18 | 3 | 25 | 2 | `st_022` |
| 2 (`gate_reimpl_..._2`) | FAILED | 18 | 3 | 25 | 2 | `st_022` |
| 3 (`gate_reimpl_..._3`) | FAILED | 18 | 3 | 25 | 2 | `st_022` |

`correcoes_acumuladas.json`: 12 entradas totais, 6 `needs_review` (cresceu de 9→12 total desde a Seção 4, mas inclui acúmulo das sessões de sabotagem do SUB08 e da outra sessão concorrente — não é regressão desta reimplementação).

### Divergência vs. Seção 4 (pós-SUB05, antes da perda) — explicada, não é regressão

`SUCCESS` subiu 17→18, `HEALED` caiu 4→3. Causa: **o bot foi regenerado por fora** (`generation_manifest.json.generated_at = 2026-07-14T23:36`, plan_checksum novo) pela sessão concorrente que corrigiu a Tarefa B pendente (`recorder.py` — colapso de `\n` em espaço no `has-text`). `st_007` mudou de seletor estático quebrado (`button:has-text('Itaú Unibanco São Paulo ITAUBRSPXXX | Brasil')`) para seletor dinâmico viável (`f"button:has-text('{row.get('nome_banco_swift', '')}')"`) — resolve agora via `resolver_tier="identity"` direto, sem healing nenhum. **As duas tarefas adiadas (`plano-cauda-longa-verificada.backlog.pending.md`) convergiram**: Tarefa B já foi resolvida por outra sessão; Tarefa A (`fallback_selectors`/`_effect_confirmed` sem doutrina de verificação) continua pendente, mas deixou de ser exercitada por `st_007` especificamente (o bug de origem que a expunha sumiu).

`st_022` (range slider `disabled`, bug de dado do site) permanece idêntico nas 3 execuções — confirma que a reimplementação não introduziu nenhuma regressão nova; o único ponto de falha é o mesmo de sempre, de origem não relacionada ao framework.

**Telemetria** (`telemetria_resolucao.json`, idêntica nas 3 execuções): `identity=18 (85.7%), parent_has_text_reduced=2 (9.5%), coordinate=1 (4.8%)`, `verify_rejected: pre_click=1, post_click=0`.

**Veredito: APROVADO.** Reimplementação ponta a ponta reconfirmada contra site real — comportamento estável, sem falso-HEALED, sem regressão. Fase F1 do plano "Cauda Longa Verificada" está implementada, testada e commitada localmente.
