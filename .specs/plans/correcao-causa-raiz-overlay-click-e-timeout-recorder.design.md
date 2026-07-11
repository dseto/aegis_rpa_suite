# Correção de Causa Raiz — Overlay Intercepta Clique (Sexo) e Timeout de Fill sob Gravação (Celular) — Design Document

**Status:** proposto, não implementado
**Data:** 2026-07-09
**Origem:** `.specs/bugs-gaps-pendentes-2026-07-09.md`, itens #1, #2 e #4. Item #3 (suíte de testes do recorder) fora de escopo por pedido explícito do usuário.
**Premissa do usuário:** framework deve identificar E LIDAR com estas situações — do recorder até a execução — de forma determinística, sem depender de self-healing via LLM.

---

## Achado-chave desta investigação (muda o diagnóstico do item #1 do handoff)

O erro relatado no item #1 (`<div class="mat-stepper-horizontal"> intercepts pointer events` ao clicar no dropdown "Sexo") **não vem do framework**. Veio de `scratch/record_portal_segura_pilot.py:39`:

```python
page.click("label:has-text('Sexo') ~ div")
```

Um `page.click()` puro do Playwright (sem `force=True`), que faz a própria checagem de actionability do Playwright e lança essa exceção quando outro elemento está por cima no ponto de clique. Isso é um script de pilotagem ad hoc (fora de `aegis_*`), não o motor.

Comparando com o padrão que o próprio framework já usa em situação equivalente:
- `aegis_blackbox/recorder.py:2084` (`run_auto_simulation`, dropdown): `select_trigger.evaluate("el => el.click()")` — clique via DOM, não via hit-test de coordenada, imune a esse tipo de interceptação.
- `aegis_runner/runner.py:557` (`click_resilient`, caminho normal de produção): `loc.click(timeout=3000, force=True)` — `force=True` também ignora a checagem de "receives pointer events".

Ou seja: o padrão defensivo **já existe** e já é usado tanto no auto-simulate do recorder quanto no runner de produção. O script de pilotagem simplesmente não seguiu o padrão. Não há bug de framework a corrigir aqui — ver Feature 3.

Isso redireciona a pergunta certa: **o que acontece hoje quando um clique de produção atravessa (ou tenta atravessar) um overlay que intercepta visualmente o alvo?** Duas respostas, verificadas separadamente:

- No caminho comum de `click_resilient` (`runner.py:557`, quando `page.locator(selector).all()` encontra candidatos), o clique usa `force=True` — ignora a checagem de "receives pointer events" e o DOM recebe o evento no elemento certo. Mas se o overlay genuinamente captura o evento antes (handler no próprio elemento que sobrepõe, ou o clique caiu sobre outro elemento clicável por engano), o efeito real pode não acontecer sem nenhuma exceção. Essa é a Feature 1 abaixo.
- **Correção (verificado em `runner.py:522-530`):** `click_resilient` NÃO usa `force=True` universalmente. Quando `page.locator(selector).all()` retorna lista vazia no instante da chamada (timing/transição de DOM), o código cai no ramo `page.locator(selector).click(timeout=timeout)` — **sem `force`** — que faz a checagem normal de actionability do Playwright e É vulnerável ao mesmo `intercepts pointer events` do item #1, dentro do próprio motor de produção. Esse ramo entra no escopo de correção da Feature 1 (item 5 abaixo).

---

## Feature 1 (prioridade alta): `CLICK_NO_EFFECT` detecta mas não corrige — vira correção ativa, não só log

### Problema

`click_resilient` (`aegis_runner/runner.py:448-608`) já tem um sensor que compara snapshot da página antes/depois do clique (`_capture_click_effect_snapshot`, `:344-405`) e detecta quando um clique não teve efeito nenhum (`_detect_click_no_effect`, `:426-446`). Verificado com precisão (correção do rascunho anterior deste doc, que descrevia o timing errado): a chamada é **síncrona e bloqueante** — `_detect_click_no_effect` roda ANTES do `return True` (`:527-530`, `:597-600`), então não é verdade que "o bot já seguiu em frente" no sentido de já ter executado o próximo passo. O bug real é mais preciso e mais perigoso de detectar:

1. `_log_step(step_id=..., status="SUCCESS")` grava no audit trail (`historico_passos.json`) **antes** do sensor rodar — ou seja, o registro permanente já diz `SUCCESS` mesmo que o sensor, 1.2s depois, descubra que não houve efeito nenhum.
2. `_detect_click_no_effect` é `void` — mesmo detectando `CLICK_NO_EFFECT`, o `return True` logo em seguida (`:530`/`:600`) é hardcoded, não depende do resultado da detecção. O chamador SEMPRE recebe `True`.
3. Na melhor das hipóteses (`AEGIS_CLICK_EFFECT_REGISTER=true`), o único efeito colateral é gravar `needs_review` em `correcoes_acumuladas.json` pra revisão humana futura — a transação atual segue exatamente como se o clique tivesse funcionado.

Isso é exatamente o cenário que motivou o item #1 do handoff: um dropdown coberto por `mat-stepper-horizontal` (ou qualquer overlay real) pode ser "clicado" via `force=True`, o sensor detectar ausência de efeito, e mesmo assim o passo ser fechado como sucesso definitivo — sem chance de nenhum fallback determinístico ter sido tentado antes de decidir.

O framework já tem 3 níveis de correção reativa prontos para esse exato cenário (`_handle_click_failure`, `:687+`): Nível 2.5 Escape+retry (`:708-718`), Nível 2.75 reposiciona `.cdk-overlay-pane` via JS (`:720-767`), Nível 2.9 `fallback_selectors` gravados (`:769-789`) — mas eles só disparam a partir de uma **exceção** do Playwright, nunca a partir de um "falso sucesso" detectado pelo sensor CLICK_NO_EFFECT.

### Solução

Quando `_detect_click_no_effect` confirma ausência de efeito (fim do polling 100/300/800ms sem nenhum sinal mudar), em vez de só logar e (opcionalmente) registrar `needs_review`, acionar a mesma cadeia de correção reativa que `_handle_click_failure` já usa para falhas por exceção — antes de o passo ser considerado fechado:

1. `_detect_click_no_effect` para de ser "fire and forget" chamado depois do `_log_step(SUCCESS)`; passa a rodar **antes** do log definitivo do passo.
2. Se detectar ausência de efeito, tenta na ordem: Escape+retry → reposicionar `.cdk-overlay-pane` + clique sintético → `fallback_selectors`. Reaproveitar os métodos que `_handle_click_failure` já implementa (extrair para métodos compartilhados se necessário, não duplicar lógica).
3. Só se todas as três tentativas determinísticas também não produzirem efeito real (novo snapshot comparado), o passo é então tratado como falha genuína — segue para o fallback cognitivo (LLM) só se `strict=False`, igual ao comportamento hoje de `_handle_click_failure` para falhas por exceção.
4. `_register_healing_for_review` continua sendo chamado quando uma dessas camadas resolve, com `healing_method="click_no_effect_recovered"` — mantém o rastreamento já existente (Feature 1 do design `self-healing-tracking-e-flaky-retry`), só muda o gatilho de "log passivo" para "correção ativa registrada".
5. **Fechar o ramo sem `force` do próprio `click_resilient`** (`:522-530`, quando `page.locator(selector).all()` retorna vazio): hoje é `page.locator(selector).click(timeout=timeout)` sem `force`, vulnerável ao mesmo `intercepts pointer events` do item #1 dentro do motor de produção. Alinhar com o padrão do resto do método (`force=True`) ou redirecionar esse caso pro mesmo loop de candidatos que já usa `force=True` (linha `:557`) em vez de manter um segundo caminho de clique com comportamento diferente.

### Onde implementar

- `aegis_runner/runner.py`: mover a chamada de `_detect_click_no_effect` para antes de `_log_step(status="SUCCESS")` em `click_resilient` (linhas `:527-529` e `:597-599`); estender `_detect_click_no_effect` pra retornar um booleano de "efeito confirmado" e, se `False`, chamar a cadeia de recuperação (reaproveitando os níveis 2.5/2.75/2.9 de `_handle_click_failure`, extraídos para método(s) compartilhado(s) se a duplicação ficar grande); remover o ramo sem `force` em `:522-530`.
- **`click_chained` fica FORA do escopo desta feature, por decisão explícita, não por omissão.** Verificado (`runner.py:1320+`): `click_chained` não chama `_capture_click_effect_snapshot`/`_detect_click_no_effect` em nenhum ponto — zero cobertura do sensor hoje. Além disso, quando `identity_scoped=True`, `_handle_click_failure` pula os Níveis 1.5/2.5/2.75 (`:697`), sobrando só o Nível 2.9 (`fallback_selectors`) e os tiers 3/4 (cognitivos, bloqueados sob `strict=True`) — a cadeia de recuperação determinística disponível pra reuso é bem menor que a de `click_resilient`. Estender o sensor pra `click_chained` é a mesma classe de risco (clique `force=True` em elemento coberto), mas nenhum dos bugs #1/#2/#4 evidenciou isso na prática — registrar como item de follow-up explícito, não implementar nesta rodada, pra não expandir escopo sem evidência.

### Risco

- **Custo de performance:** cada clique que hoje já espera até 1.2s de polling (100+300+800ms) do sensor passa a, no caso de não-efeito, adicionar mais o tempo das 3 camadas de recuperação (Escape+retry ~0.5s, reposicionamento ~1s, fallback_selectors variável) antes de decidir se é falha real. Só acontece no caminho de exceção (raro), não no caminho feliz.
- **Falso positivo do sensor puxando recuperação desnecessária:** o sensor já tem tolerância (`_click_effect_signals_changed`, `:407-424`, DOM ±2 nós, fingerprint de classe dos irmãos) calibrada para casos reais documentados (troca de aba só-CSS). Extrair a cadeia de recuperação não deve mudar essa calibração — só o que acontece quando ela genuinamente não detecta efeito.
- **Regressão de teste esperada:** `_detect_click_no_effect` hoje é `void`/best-effort (nunca quebra o passo, `try/except` amplo em `:435-446`). Mudar sua assinatura para retornar um booleano e acionar retry muda contrato — testes que fazem `assert_called_once` em torno dela (ver Working Agreement #3 do CLAUDE.md) provavelmente precisam de ajuste, não reversão.

---

## Feature 2 (diagnóstico antes de fix): timeout de `fill()` no campo Celular só com `AegisRecorder` ativo

### Problema

Item #2 do handoff: `page.fill()` no campo "Celular" trava (timeout 30s) só quando os listeners do `AegisRecorder` estão injetados; sem eles, o mesmo fluxo completa. Investigação estática não achou um candidato óbvio de trabalho pesado por tecla (o listener de `input`, `recorder.py:870-873`, retorna cedo sempre; não há `MutationObserver`). O único candidato real de overhead é o monkey-patch global de `EventTarget.prototype.addEventListener` (`recorder.py:889-908`) — ele roda em **toda** chamada de `addEventListener` da página inteira durante a sessão de gravação, e sua fast-path de saída (`type === 'keydown' || type === 'keyup'`) só é barata se o campo/lib não registrar esses listeners repetidamente.

Campo "Celular" é candidato **especulativo** (não verificado — não inspecionei o HTML/JS real do Portal Segura pra esse campo) a usar uma lib de máscara de input (formatação `(XX) XXXXX-XXXX`), que tipicamente re-registra listeners de teclado a cada mudança de valor — o que, combinado com a simulação de instabilidade de rede do próprio site (`fakeFetch`/`simulations.js:103`), poderia gerar contenção de thread principal justamente na janela em que o Playwright está fazendo fill + revalidando actionability a cada char. **Esta é uma hipótese entre outras possíveis, não um diagnóstico** — o handoff original já registra a mesma incerteza. Não anexar o fix a essa hipótese específica sem dado real.

**Não dá pra propor o fix de causa raiz sem confirmar (ou descartar) uma hipótese concreta primeiro** — é exatamente o "próximo passo sugerido" que o handoff já documentou e que não foi executado.

### Solução (diagnóstico, não fix ainda)

1. Instrumentar temporariamente (atrás de uma env var, ex. `AEGIS_RECORDER_DEBUG_TIMING=true`, nunca ligada por padrão) o monkey-patch de `addEventListener` (`recorder.py:889-908`) para logar `performance.now()` + `type` + seletor **para toda chamada relevante ao campo Celular, não só a que bater no filtro `keydown`/`keyup`** — se restringir o log ao mesmo filtro que já existe no monkeypatch, qualquer causa fora dessa hipótese (mask lib usando outro tipo de evento, listener de outro campo competindo, etc.) fica invisível na instrumentação. Logar bruto, filtrar na análise depois.
2. Reproduzir ao vivo contra o Portal Segura (reusar `scratch/record_portal_segura_pilot.py` com o driver corrigido — ver Feature 3) com essa instrumentação ligada, capturando também o timestamp de início/fim do `page.fill()` do lado Playwright.
3. Comparar as duas linhas do tempo:
   - Se houver rajada de chamadas ao monkey-patch coincidindo com o timeout → hipótese confirmada. Fix subsequente (fora deste design, vira item novo): tornar o monkey-patch mais barato (`WeakSet` pra não reprocessar o mesmo elemento, ou restringir a campos que ainda não foram classificados) ou usar `getAegisSelector` de forma preguiçosa (só resolver o seletor se o campo ainda não estiver em `__aegis_keydown_fields__`).
   - Se não houver correlação → recorder não é a causa raiz; é flakiness do próprio site combinando com o fill padrão do Playwright. Documentar como comportamento conhecido do site de referência (não bug do framework) e, se necessário, tratar no nível do dataset/step do Portal Segura (ex. `fill_strategy` mais tolerante), não no core do recorder.

### Onde implementar

- `aegis_blackbox/recorder.py`, dentro do bloco IIFE do "AEGIS ANTI-BOT DETECTOR" (`:884-909`) — instrumentação condicional, removida ou mantida atrás da env var depois de confirmado o diagnóstico.
- Script de reprodução: reusar o pilot driver corrigido (Feature 3).

### Risco

- Instrumentação em produção teria custo de I/O (log por listener) — por isso fica atrás de env var default-off, nunca ligada em execução normal.
- Resultado pode ser "não é o recorder" — nesse caso não há fix de framework a fazer, só documentação. Isso é um resultado válido do diagnóstico, não uma falha do plano.

---

## Feature 3 (desbloqueia item #4): alinhar o driver de pilotagem ao padrão defensivo já existente

### Problema

`scratch/record_portal_segura_pilot.py` usa `page.click()` puro em pontos que colidem com overlays conhecidos do Portal Segura (linha 39, dropdown "Sexo"; possivelmente outros dropdowns Angular Material no mesmo arquivo, linhas 44/54). Isso trava a gravação antes de chegar ao ponto de interesse original do piloto (autocomplete Marca/Modelo, item #4).

### Solução

Ajustar os cliques em dropdowns Angular Material desse driver para seguir o mesmo padrão que `run_auto_simulation` já usa (`recorder.py:2070-2134`, `select_dropdown_local`): clique via `evaluate("el => el.click()")` no trigger, ou `force=True`, em vez de `page.click()` puro. Não é mudança de framework — é o script de pilotagem passando a usar o padrão que o próprio framework já estabeleceu.

### Onde implementar

- `scratch/record_portal_segura_pilot.py:39,44,54` (dropdowns Sexo/Estado Civil/Tipo de Isenção) e qualquer outro `page.click()` sem `force` em elemento dentro de `mat-stepper`/overlay Angular Material.

### Sequenciamento

**Correção (o rascunho anterior deste doc tinha um erro de causalidade aqui):** Feature 1 muda `aegis_runner/runner.py`, usado só pelo **bot já gerado** (Fase 5, `bot_producao.py`). A gravação (Fase 1) não chama `click_resilient` em nenhum momento — é dirigida pelo driver de pilotagem + listeners passivos do `AegisRecorder`. Ou seja, **Feature 1 não desbloqueia item #4** — só **Feature 3** desbloqueia, porque é o driver de pilotagem que trava a gravação hoje. Feature 1 só importa depois, quando o pipeline completo (Fases 2-5) rodar pra esse projeto e o bot gerado precisar clicar no mesmo dropdown "Sexo" em produção — aí sim valida se o force=True com correção ativa realmente evita o falso-sucesso.

Depois de **Feature 3** (Feature 1 e Feature 2 são independentes e podem rodar em paralelo, nenhuma bloqueia a outra nem bloqueia a gravação), retomar a gravação completa do "caminho infeliz" do Portal Segura até o autocomplete Marca/Modelo (item #4) — isso é verificação, não código novo. Só então dá pra medir métricas reais do ponto flaky de marca/modelo com o pipeline completo (Sanitize/Validate/Generate/Run) rodando pela primeira vez nesse projeto — e só aí Feature 1 é exercitada de verdade no dropdown "Sexo" gerado.

---

## Priorização

1. **Feature 3** — trivial (3 linhas), único item que de fato desbloqueia a gravação (item #4). Fazer primeiro se o objetivo imediato é retomar o piloto.
2. **Feature 1** — bug de framework confirmado, blast radius real (qualquer bot gerado que dependa do ramo sem `force` em `:522-530`, ou tenha um `force=True` que force-clique através de overlay real, tem o mesmo risco de falso-sucesso silencioso hoje). Independente de Feature 3 — pode ser feito em paralelo ou antes, mas só é validado contra o cenário real (dropdown Sexo) depois que a gravação for retomada e o pipeline completo rodar.
3. **Feature 2** — diagnóstico, não fix. Independente das outras duas; o fix real (se houver) é um item futuro, condicionado ao resultado.
4. **Item #4** — consequência direta só de Feature 3 (não de 1 nem 2): re-rodar o piloto até completar.

## Fora de escopo

- Item #3 do handoff (suíte de testes para `aegis_blackbox/recorder.py`) — excluído por pedido explícito do usuário nesta sessão.
- Qualquer extensão do sanitizer/dataset_validator para classificar seletores dentro de `.cdk-overlay-container` como `weak_selector` — não há evidência de que isso teria evitado os bugs #1/#2/#4 (o problema não foi o seletor ser fraco, foi o clique físico ser interceptado ou o fill travar). Não incluir para não fazer over-engineering sem causa comprovada.
- **Estender o sensor CLICK_NO_EFFECT/correção ativa pra `click_chained` e `fill_resilient`** — mesma classe de risco de falso-sucesso silencioso que a Feature 1 corrige em `click_resilient`, mas nenhum dos bugs #1/#2/#4 evidenciou isso na prática nesses dois métodos. Registrado como follow-up explícito (não esquecido, não incluído) — ver nota em "Onde implementar" da Feature 1.
