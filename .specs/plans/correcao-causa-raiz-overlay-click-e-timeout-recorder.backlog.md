# BACKLOG DE EXECUÇÃO - CLAUDE CODE

Origem: `.specs/plans/correcao-causa-raiz-overlay-click-e-timeout-recorder.design.md`. Este backlog cobre Features 1, 2 e 3 do design (item #3 do handoff original já está fora de escopo, não faz parte deste backlog).

---

### [SUBAGENTE 01] - Corrigir driver de pilotagem pra usar clique defensivo (Feature 3)
> ✅ CONCLUÍDO (objetivo do bloco). Verificado por mim: `grep` confirma 0 `page.click()` puro nos 3 triggers; live-run contra `localhost:5173` confirma zero `intercepts pointer events`. ⚠️ Achado colateral fora de escopo: opção "Isenção de ICMS" (3º dropdown) falha por estar fora do viewport — bug DIFERENTE, não corrigido aqui por instrução explícita de escopo. Fluxo completo até `#btn-next-step` continua bloqueado por esse novo bug — não invalida este bloco, mas item #4 (retomar gravação completa) segue pendente até isso ser tratado à parte.

- **🎯 Objetivo:** Trocar `page.click()` puro por clique que ignora interceptação de overlay (mesmo padrão que `run_auto_simulation` já usa em `recorder.py`) nos 3 dropdowns Angular Material do driver de pilotagem, pra parar de quebrar com `intercepts pointer events` durante a gravação.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_blackbox/recorder.py` (só a função `select_dropdown_local`, dentro de `run_auto_simulation`, aprox. linhas 2070-2134 — é a REFERÊNCIA do padrão a copiar, não deve ser modificada)
  - Modificar: `scratch/record_portal_segura_pilot.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é corrigir `scratch/record_portal_segura_pilot.py`. Nas linhas que fazem `page.click("label:has-text('Sexo') ~ div")`, `page.click("label:has-text('Estado Civil') ~ div")` e `page.click("label:has-text('Tipo de Isenção Aplicável') ~ div")` (dropdowns Angular Material que abrem um trigger), troque o `page.click()` puro por um clique que não faça a checagem de actionability do Playwright (ex.: `page.locator(...).evaluate("el => el.click()")` ou `page.click(..., force=True)`), seguindo exatamente o padrão que `select_dropdown_local` em `aegis_blackbox/recorder.py` já usa pro trigger do dropdown (`select_trigger.evaluate("el => el.click()")`). Não mude o clique das opções que já vêm depois (`page.click("[role='option']:has-text(...)")`) — não há evidência de que elas quebrem. Não toque em `aegis_blackbox/recorder.py`. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [ ] Revisão estática: `grep -n "page.click(\"label" scratch/record_portal_segura_pilot.py` não deve mais retornar nenhuma linha usando `page.click()` puro nesses 3 seletores.
  - [ ] Validação ao vivo (Working Agreement do CLAUDE.md: mudança de clique/DOM não está pronta até rodar contra browser real): tentar `python scratch/record_portal_segura_pilot.py` com o site de referência Portal Segura acessível em `http://localhost:5173/`. Se o site não estiver rodando localmente, reportar isso explicitamente no resultado da tarefa (não declarar "pronto" sem essa checagem) — é uma dependência externa ao agente, não um bloqueio pra marcar a tarefa como feita no código.
  - [ ] Se a execução ao vivo rodar: confirmar que o fluxo passa pelos 3 dropdowns sem lançar `intercepts pointer events` e chega pelo menos até o próximo passo do fluxo (`#btn-next-step`).

---

### [SUBAGENTE 02] - `CLICK_NO_EFFECT` vira correção ativa em `click_resilient` (Feature 1)
> ✅ CONCLUÍDO. Re-verificado por mim: `python aegis_runner/test_runner_integration.py` (34 testes, OK) e `python aegis_runner/test_cognitive_fallback.py` (7 testes, OK), rodados independentemente na thread principal. Limpeza adicional feita por mim após o gate: método `_click_effect_register_enabled` (env var `AEGIS_CLICK_EFFECT_REGISTER`) ficou órfão pela mudança (registro agora é incondicional via hook HEALED existente) — removido; `CLAUDE.md` e `README.md` (item 14) atualizados pra não descrever mais o comportamento antigo "log-only".

- **🎯 Objetivo:** Fazer `click_resilient` reagir de verdade quando o sensor `CLICK_NO_EFFECT` detecta que um clique não teve efeito real, em vez de só logar e retornar sucesso de qualquer jeito; e fechar o ramo interno que ainda faz clique sem `force=True`.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_runner/runner.py` (métodos `click_resilient` linhas ~448-608, `_handle_click_failure` linhas ~687-806, `_detect_click_no_effect`/`_capture_click_effect_snapshot`/`_click_effect_signals_changed` linhas ~326-446, `_register_healing_for_review` linha ~228)
  - Ler: `aegis_runner/test_runner_integration.py` (classe `TestClickNoEffectSensor`, linhas ~740-874 — contrato atual que vai mudar de propósito)
  - Modificar: `aegis_runner/runner.py`, `aegis_runner/test_runner_integration.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é em `aegis_runner/runner.py`, dentro de `click_resilient`:
  >
  > 1. No ramo em que `page.locator(selector).all()` retorna lista vazia (por volta da linha 522-530), o clique de fallback `page.locator(selector).click(timeout=timeout)` não usa `force=True`, ao contrário do resto do método. Ajuste esse clique para também ignorar a checagem de 'receives pointer events' do Playwright (`force=True`), alinhando com o padrão já usado no loop de candidatos (linha ~557).
  > 2. Mude `_detect_click_no_effect` pra deixar de ser 'fire and forget': hoje ela roda DEPOIS de `_log_step(status='SUCCESS')` já ter sido chamado e sempre retorna implicitamente sucesso pro chamador. Ela precisa passar a rodar ANTES do `_log_step` definitivo e retornar um booleano indicando se o clique teve efeito real confirmado.
  > 3. Quando `_detect_click_no_effect` (chamada nesse novo ponto) confirmar AUSÊNCIA de efeito, `click_resilient` deve, antes de fechar o passo como sucesso, tentar em sequência as mesmas camadas determinísticas que `_handle_click_failure` já usa pra falhas por exceção: Escape+retry, reposicionar `.cdk-overlay-pane` + clique sintético via JS, e `fallback_selectors` gravados (`self.fallback_selectors_by_step`). Reaproveite a lógica existente de `_handle_click_failure` (extraia pra um método privado compartilhado se precisar, não duplique o código JS/Python desses níveis).
  > 4. Só se nenhuma dessas tentativas produzir efeito real (novo snapshot mostrando mudança), trate como falha genuína: siga para o fallback cognitivo (LLM) apenas se `strict=False`, exatamente como `_handle_click_failure` já decide isso hoje (olhe o uso do parâmetro `strict` nesse método pra replicar o mesmo comportamento, incluindo não pular pro cognitivo quando `strict=True`).
  > 5. Quando uma dessas camadas resolver o clique após um `CLICK_NO_EFFECT` detectado, chame `_register_healing_for_review` com `healing_method='click_no_effect_recovered'` (novo valor, não reusar `'click_no_effect'` que já existe pro caso antigo log-only).
  > 6. Atualize `aegis_runner/test_runner_integration.py`, classe `TestClickNoEffectSensor`: o teste `test_overlay_covering_target_logs_click_no_effect` hoje afirma que o clique continua `SUCCESS` mesmo sem efeito nenhum (comportamento antigo, log-only) — isso não é mais verdade depois desta mudança. Ajuste esse teste (e adicione um teste novo) pra refletir o comportamento correto: quando a recuperação determinística consegue produzir efeito, o passo fecha como sucesso com `healing_method='click_no_effect_recovered'` registrado; quando NENHUMA camada produz efeito, o passo falha de verdade (ou levanta a exceção apropriada, seguindo o mesmo padrão de `_handle_click_failure` pra falha definitiva). Não é reverter a mudança pra fazer o teste antigo passar — é corrigir a asserção pro novo contrato (mesma lógica já aplicada no Working Agreement #3 do CLAUDE.md do projeto).
  > 7. NÃO toque em `click_chained` nem em `fill_resilient` — ficam fora de escopo desta tarefa, por decisão explícita do design. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [ ] Rodar a suíte de integração do runner: `python aegis_runner/test_runner_integration.py` — deve passar 100%, incluindo a classe `TestClickNoEffectSensor` atualizada e qualquer teste novo adicionado.
  - [ ] Rodar também `python aegis_runner/test_cognitive_fallback.py` (garantir que nada no fallback cognitivo quebrou por causa da mudança de fluxo em `click_resilient`).
  - [ ] Revisão manual: confirmar que sob `AEGIS_CLICK_EFFECT_REGISTER` não setado (default false), o comportamento de log-only pré-existente para 'clique com efeito real' (sem interceptação) não mudou — só o caminho de 'sem efeito' é que agora tenta recuperação.

---

### [SUBAGENTE 03] - Instrumentar recorder pra diagnosticar timeout de fill no Celular (Feature 2)
> ✅ CONCLUÍDO. Re-verificado por mim: flag `AEGIS_RECORDER_DEBUG_TIMING` default-off confirmada por grep, `import aegis_blackbox.recorder` limpo, `test_runner_integration.py` 34/34 OK, blast radius só tocou `recorder.py` + relatório novo. **Resultado do diagnóstico: hipótese do monkey-patch DESCARTADA** — reprodução ao vivo mostrou `fill()` do Celular completando sem timeout, overhead do monkeypatch sub-milissegundo. Não há fix de framework a fazer pra esse bug (consistente com o design: resultado "não é o recorder" é válido). ⚠️ Achado secundário novo, fora de escopo: valor do Celular não aparece em `events` de `gravacao.json` apesar de `fill()` bem-sucedido — possível bug de captura/flush, não investigado, ver `.specs/relatorio-timing-fill-celular-2026-07.md`.

- **🎯 Objetivo:** Adicionar instrumentação temporária e default-off no monkey-patch de `addEventListener` do recorder, reproduzir ao vivo o timeout de `fill()` no campo Celular do Portal Segura, e reportar se há correlação com o overhead do monkey-patch — sem propor fix de código além da instrumentação.
- **📂 Escopo de Arquivos:**
  - Ler: `aegis_blackbox/recorder.py` (bloco "AEGIS ANTI-BOT DETECTOR", linhas ~879-909; `getAegisSelector`/`getAegisSelectorCandidates`, linhas ~375-455, pra entender o custo do que o monkeypatch chama)
  - Modificar: `aegis_blackbox/recorder.py`
  - Depende de: [SUBAGENTE 01] concluído (a reprodução ao vivo reusa o driver de pilotagem corrigido)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é em `aegis_blackbox/recorder.py`, dentro do bloco 'AEGIS ANTI-BOT DETECTOR' (monkey-patch de `EventTarget.prototype.addEventListener`, linhas ~884-909):
  >
  > 1. Adicione instrumentação de timing condicional a uma flag nova, lida do lado Python e injetada no JS (ex.: `window.__aegis_debug_timing__`), default `false`/ausente — nunca ligada em execução normal. Quando ligada, toda chamada ao `addEventListener` interceptado (não só as que batem no filtro `keydown`/`keyup` — logue o bruto, filtragem por tipo é análise, não captura) deve registrar `performance.now()` + `type` + `this.tagName` + um identificador do elemento (id/name/seletor via `getAegisSelector`, se disponível) num array acumulado em `window.__aegis_timing_log__` (ou logue direto via `console.log` com prefixo fixo tipo `[AEGIS_TIMING]`, o que for mais simples de capturar depois pelo lado Python).
  > 2. Exponha a flag via variável de ambiente Python `AEGIS_RECORDER_DEBUG_TIMING` (default `false`), seguindo o mesmo padrão de outras flags do projeto (ex.: `AEGIS_CLICK_EFFECT_SENSOR` em `aegis_runner/runner.py`), injetando o valor no script que o recorder já injeta na página.
  > 3. Depois de implementar a instrumentação, reproduza ao vivo: rode `python scratch/record_portal_segura_pilot.py` com `AEGIS_RECORDER_DEBUG_TIMING=true` contra `http://localhost:5173/` (site precisa estar rodando localmente — se não estiver acessível, reporte isso explicitamente e pare aqui, não invente resultado) e observe o campo Celular. Capture os logs `[AEGIS_TIMING]` e o timestamp de início/fim do `fill()` desse campo do lado Playwright/console do driver.
  > 4. Escreva um resumo curto do achado (correlação confirmada ou descartada) em `.specs/relatorio-timing-fill-celular-2026-07.md` — não implemente o fix de performance do monkeypatch nesta tarefa, mesmo que a hipótese seja confirmada; isso é diagnóstico, o fix é um item futuro condicionado ao resultado.
  > 5. Não toque em `click_resilient`, `_handle_click_failure` nem em nenhum arquivo de `aegis_runner/`. Não faça refatoração, renomeação nem melhoria fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [ ] Revisão estática: confirmar que a instrumentação só roda quando `AEGIS_RECORDER_DEBUG_TIMING=true` — `grep -n "AEGIS_RECORDER_DEBUG_TIMING" aegis_blackbox/recorder.py` deve mostrar a flag controlando a instrumentação, não sempre ativa.
  - [ ] Rodar a suíte de testes existente pra confirmar que nada quebrou (recorder não tem suíte própria — rodar `python aegis_runner/test_runner_integration.py` como smoke test indireto, já que não há regressão esperada nesse módulo, e importar `aegis_blackbox/recorder.py` sem erro: `python -c "import aegis_blackbox.recorder"`).
  - [ ] Arquivo `.specs/relatorio-timing-fill-celular-2026-07.md` criado com o resultado do diagnóstico (confirmado, descartado, ou "não foi possível reproduzir — site local indisponível").

---

## 🗺️ Mapa de Dependências dos Subagentes

- 🟢 Fase 1: [SUBAGENTE 01] e [SUBAGENTE 02] — paralelo, arquivos disjuntos (`scratch/record_portal_segura_pilot.py` vs `aegis_runner/runner.py` + seu teste), sem dependência entre si.
- 🟡 Fase 2: [SUBAGENTE 03] — depende de [SUBAGENTE 01] (reusa o driver de pilotagem já corrigido pra reproduzir ao vivo). Arquivo próprio (`aegis_blackbox/recorder.py`), não conflita com [SUBAGENTE 02].
