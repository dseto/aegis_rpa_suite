# Bugs e Gaps Pendentes — sessão 2026-07-09

Documento de handoff para próxima sessão. Cobre achados reais, verificados ao vivo, ainda não corrigidos ou parcialmente investigados. Não é lista de ideias — cada item tem evidência.

## 1. Ponto flaky em `mat-stepper-horizontal` intercepta clique no dropdown "Sexo" (Portal Segura)

**Onde:** fluxo de gravação Portal Segura, passo "Sexo" (dropdown Angular Material CDK overlay).

**Evidência:** revelado ao vivo após corrigir o bug de mascaramento em `recorder.py` (ver seção "Resolvido" abaixo). Erro real:
```
<div class="mat-stepper-horizontal">…</div> intercepts pointer events
```
Playwright tentou clicar no dropdown "Sexo" mas o stepper horizontal (barra de progresso Cliente→Veículo→Condutor→Coberturas→Vistoria) estava sobrepondo o elemento clicável, bloqueando o clique real.

**Status:** não investigado a fundo. Pode ser timing (overlay do stepper ainda re-renderizando) ou z-index real de layout. Não confirmado se é falha determinística ou intermitente — só uma ocorrência observada.

**Próximo passo sugerido:** reproduzir 3x seguidas com o driver `scratch/record_portal_segura_pilot.py` (ainda existe, useable) para confirmar se é determinístico. Se sim, é candidato a virar mais um "ponto flaky documentado" do site de referência, não bug do framework — mas só depois de descartar causa própria (timing insuficiente antes do clique).

## 2. Interação chaos-simulation (Portal Segura) × `AegisRecorder` no campo "Celular"

**Onde:** `projects/portal_segura_pilot/tests/001_flaky_test/`, ver `.specs/relatorio-piloto-portal_segura_pilot_unhappy.md` achado #3.

**Evidência:** `page.fill()` no campo Celular timeout (30s) com `AegisRecorder` ativo (listeners JS injetados), mas o mesmo fluxo reproduzido em Playwright puro (sem `AegisRecorder`) completou sem erro. `browser_console.log` mostra erro simulado do próprio site (`fakeFetch` / `src/simulations.js:103` — "Erro de Conexão Temporário 503") na mesma sessão.

**Status:** reproduzido uma vez, causa raiz exata (por que só falha com `AegisRecorder` ativo) não isolada. Hipótese não confirmada: overhead dos listeners JS do recorder + simulação de instabilidade de rede do site causam disputa nos "actionability checks" do Playwright.

**Próximo passo sugerido:** instrumentar `AegisRecorder` com timestamps por listener (MutationObserver, etc.) durante uma gravação que hit esse campo, comparar contra o timing do `fakeFetch` simulado — confirmar ou descartar a hipótese de disputa de concorrência.

## 3. Ausência de suíte de testes para `aegis_blackbox/recorder.py`

**Onde:** `aegis_blackbox/` não tem nenhum `test_*.py`.

**Evidência:** `ls aegis_blackbox/ | grep -i test` → vazio. Confirmado durante `/reflect` desta sessão ao verificar o fix do item "Resolvido" abaixo.

**Status:** gap pré-existente, não introduzido nesta sessão. `aegis_cockpit/cockpit.py` já tinha esse gap documentado em `CLAUDE.md`; `recorder.py` tem o mesmo problema e não está listado lá.

**Próximo passo sugerido:** ao menos um teste de regressão para o bloco `auto_simulate` (mock de `page`, força uma exceção em `run_auto_simulation`, confirma que a mensagem logada é a exceção original e que a função NÃO é chamada uma segunda vez) — cobriria diretamente o bug corrigido nesta sessão (ver "Resolvido" #1) e evitaria reintrodução futura.

## 4. Gravação Portal Segura "caminho infeliz" nunca completou até o autocomplete marca/modelo

**Onde:** `projects/portal_segura_pilot/tests/001_flaky_test/` — objetivo original do piloto.

**Status:** gravação truncada em 12 eventos (login até Email), nunca alcançou os campos de veículo (Marca/Modelo, o ponto flaky originalmente documentado em `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`). Projeto e driver mantidos (`scratch/record_portal_segura_pilot.py`) caso se queira retomar e completar o fluxo. Fases 2-5 (Sanitize/Validate/Generate/Run) nunca rodaram para este projeto.

**Próximo passo sugerido:** se ainda houver interesse em medir métricas reais do ponto flaky de marca/modelo (fallback_selectors, weak_selector, etc.), retomar a gravação a partir do driver existente, resolvendo antes os itens #1 e #2 acima (senão a gravação provavelmente trava de novo antes de chegar lá).

## Resolvido nesta sessão (para contexto, não é pendência)

1. **`recorder.py:1928-1941` mascarava a exceção real em `auto_simulate`** — bloco `except` reexecutava `run_auto_simulation` do zero via `globals()`, produzindo um erro secundário (timeout em `#username`) que escondia a causa raiz. Corrigido: agora só loga `sim_err` (a exceção original), sem retry. Verificado ao vivo — nova gravação expôs corretamente o erro real (ver item #1 acima, que só foi possível diagnosticar por causa deste fix).
