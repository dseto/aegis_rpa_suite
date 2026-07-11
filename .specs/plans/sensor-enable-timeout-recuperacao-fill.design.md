# Sensor `ENABLE_TIMEOUT` + Recuperação de Fills da Tela Atual — Design Document

**Status:** proposto, não implementado
**Data:** 2026-07-09
**Origem:** corrida real observada ao vivo no Portal Segura (campo "Nome" preenchido pelo bot ANTES da busca assíncrona por CPF terminar — o app só considera o campo válido se ele for preenchido, manual ou automaticamente, DEPOIS da resposta da busca chegar; preencher cedo deixa o valor visualmente certo no DOM mas o flag interno de validação do app nunca vira `true`, travando `#btn-next-step` indefinidamente). Revisado por um segundo agente (modelo Fable) cético, que descartou a proposta original (F: retry gatilhado por correlação de timing de rede; G: propagar delta de tempo humano gravado) e propôs a alternativa deste documento. Ver `.specs/plans/correcao-causa-raiz-overlay-click-e-timeout-recorder.design.md` para o contexto da sessão que revelou o bug.

**Premissa do usuário:** o framework deve identificar e lidar com esse tipo de corrida de forma genérica (não um workaround específico pro campo CPF/Nome deste site), preferencialmente sem depender de LLM.

**Revisão:** este design passou por `plan-critic` e por um `/reflect` em cima do achado de overengineering (item B) — as duas rodadas mudaram partes do documento. Onde algo foi corrigido em relação a uma versão anterior, o texto diz explicitamente o quê e por quê, para não se perder a rastreabilidade da decisão.

---

## Achado-chave: dois gaps distintos no mesmo botão, não um só

Dois gaps confirmados no código, ambos preexistentes a esta sessão — **são mecanismos diferentes, não a mesma causa em dois lugares** (correção de imprecisão apontada pelo `plan-critic`):

1. **`#btn-next-step` está explicitamente excluído do sensor `CLICK_NO_EFFECT`** (`aegis_runner/runner.py:331`, `_CLICK_EFFECT_EXCLUDED_SELECTORS = {"#btn-confirm-payment-progress", "#btn-next-step"}`). O único sensor hoje capaz de perceber "cliquei e nada mudou" é deliberadamente cego pro botão do caso real.
2. **Gap pré-clique (o que realmente causa o sintoma observado ao vivo):** `_wait_for_known_disabled_button` (`runner.py:823-844`, espera ANTES do clique) só cobre `#btn-confirm-payment-progress` — `#btn-next-step` **não está no set**, então hoje ele não recebe NENHUMA espera pré-clique. Não é "espera existe e o resultado é descartado" — é "a espera nem se aplica a este selector". No bug real (botão nasce `disabled` por formulário inválido, nunca chega a ser clicado), este é o gap que importa.
3. **Gap pós-clique (real, mas de um cenário diferente):** `_wait_if_wizard_transition_button` (`runner.py:846-870`, espera DEPOIS do clique — cenário de botão que se autodesabilita durante um submit e reabilita quando a resposta chega) engole o timeout em silêncio: o loop (`runner.py:859-870`) sai sem levantar nada quando os 15s esgotam, e nos dois pontos de chamada (`runner.py:526`, `runner.py:595`) o retorno é ignorado — `_finalize_click_success` roda incondicionalmente logo depois. Esse é um falso-sucesso real, só que não é o mecanismo do bug do CPF/Nome especificamente.

Ou seja: **a correção (generalizar as duas esperas, item 1 da Feature 1) resolve os dois gaps de uma vez — mas o diagnóstico do bug real aponta pro gap #2 (pré-clique ausente), não pro #3.**

Causa raiz adicional: `click_resilient` usa `force=True` de forma generalizada (`runner.py:525`, `:556`), o que desliga a checagem nativa do Playwright de "elemento habilitado antes de clicar". O framework então recriou essa espera à mão, mas só para 2 seletores literais (`_wait_for_known_disabled_button`, `runner.py:823-844`; `_wait_if_wizard_transition_button`, `runner.py:846-870`) em vez de generalizá-la.

---

## Feature 1: Generalizar a espera de habilitação + sensor `ENABLE_TIMEOUT` com recuperação por re-fill

### Problema

Hoje, quando um clique depende de um botão que só habilita após uma validação assíncrona do app (qualquer causa: busca de CPF, cálculo de valores, submissão de formulário), o framework só cobre isso para 2 seletores hardcoded, e mesmo nesses 2 casos, o timeout da espera não vira nenhuma ação corretiva — só é silenciosamente ignorado.

### Solução

**B (complementar, timeout curto e calibrado) — antes de recorrer a `force=True`, tentar o clique nativo do Playwright (sem force) com timeout BAIXO (300-800ms, não 1-2s).**

Revisão (`/reflect` pós-`plan-critic`): a primeira versão deste item foi descartada por engano como "redundante com A" — correção: **não é redundante**. `force=True` não clica "por dentro" ignorando o que está por cima; ele pula a checagem de actionability mas ainda dispara o clique na coordenada do centro do elemento via input real do browser — se outro elemento estiver visualmente por cima naquele ponto, o clique acerta o elemento ERRADO, não o alvo (é exatamente por isso que o sensor `CLICK_NO_EFFECT` existe, e o próprio `CLAUDE.md` já documenta esse comportamento). A espera de habilitação (item A abaixo) só checa o atributo `disabled` — não sabe dizer "tem algo por cima agora". B cobre um eixo diferente (cobertura visual TRANSIENTE, ex.: toast/spinner passando por 200ms), que sem B só seria pego DEPOIS do fato, reativamente, via `CLICK_NO_EFFECT`/`ENABLE_TIMEOUT` — mais lento, mais maquinário acionado.

O risco real de B não é redundância nem re-crash (dentro de `click_resilient` qualquer exceção do clique nativo já cai no try/except existente e segue pro `force=True` normalmente — o crash observado ao vivo só aconteceu no driver de pilotagem ad hoc, sem try/except, timeout default de 30s, não dentro do runner). O risco real é **custo de latência em escala**: em selector coberto por overlay PERSISTENTE (não transiente — o caso do bug #1, stepper sobre dropdown), B falha sempre, em todo clique, antes de cair pro force. Por isso o timeout precisa ser baixo (300-800ms) — barato o suficiente pra não pesar em dataset de centenas de linhas, mas ainda útil pro caso transiente que motiva o item.

**A (o essencial) — sensor `ENABLE_TIMEOUT`, irmão do `CLICK_NO_EFFECT` já existente:**

1. Generalizar `_wait_for_known_disabled_button`/`_wait_if_wizard_transition_button` de "2 seletores literais" para "qualquer clique cujo alvo, no momento do clique, está desabilitado" — remove o hardcode, mantém o mesmo padrão de polling (300ms) e o mesmo teto (15s, configurável).
2. Quando essa espera estoura (o botão nunca habilita), NÃO seguir para `_finalize_click_success` incondicionalmente como hoje. Em vez disso, acionar uma recuperação determinística: **re-executar, em ordem, os fills do buffer `self._recent_fills`** (ver abaixo — NÃO é "desde o último clique"), cada um com um pequeno settle (poll de rede/DOM, ~300-800ms, mesmo padrão de tolerância do `CLICK_NO_EFFECT`) entre um e outro — e reusando a estratégia original de cada fill (`DIRECT`/`HUMAN_LIKE`), nunca um `.fill()` genérico. Depois de re-preencher todos, tenta a espera de habilitação de novo, uma única vez.
3. Se, mesmo após a recuperação, o botão continuar desabilitado: falha genuína — mesmo tratamento de `strict`/flaky que o resto da cadeia de resiliência já usa (bloqueia cognitivo sob `strict=True`, senão cai no fallback existente).
4. Remover `#btn-next-step` de `_CLICK_EFFECT_EXCLUDED_SELECTORS` (`runner.py:331`) SÓ se, após esta mudança, o novo sensor `ENABLE_TIMEOUT` cobrir o caso — não faz sentido esse selector continuar excluído de todo sensor de efeito quando agora existe um sensor específico pra ele.

**Buffer `self._recent_fills` — peça de implementação nova, não reusar `steps_history`, NÃO limpa a cada clique.**

Correção crítica (`plan-critic`, achado bloqueante): a versão original deste item mandava limpar o buffer "a cada clique bem-sucedido", usando "desde o último clique" como proxy de "campos desta tela". Isso quebra no próprio caso que motivou o plano: no fluxo real (`bot_producao.py:73-83`) há `fill(CPF)` → `fill(Nome)` → `click(Sexo)` → `click(opção)` → `click(Estado Civil)` → `click(opção)` → `fill(Email)` → `fill(Celular)` → `click(PCD)` → `click(Isenção)` → `click(opção)` → `click(#btn-next-step)` [ENABLE_TIMEOUT] — com a regra antiga, o buffer no momento do timeout conteria só os fills desde o clique da opção "Isenção", e CPF/Nome (os campos que precisam ser re-preenchidos) já teriam sido descartados 7 cliques antes. **Correção: o buffer nunca limpa proativamente — só é limitado por tamanho** (cap fixo, ex. últimos 20-30 fills). Re-fill é idempotente (sempre limpa o campo antes de digitar de novo), então reencher um campo de telas anteriores não corrompe nada, só custa um pouco de tempo num cenário raro — mais simples e mais correto que tentar adivinhar a fronteira exata de "tela atual".

Verificado: `steps_history` (`runner.py:97`) guarda `step_id`, `type`, `selector`, `desc`, `status` — mas **não guarda `text_val` nem `strategy`** (confirmado lendo `_log_step`, `runner.py:153-164`), então não dá pra "re-tocar" um fill a partir dele sem esses dados. Em vez de estender o schema persistido (risco: `historico_passos.json` passaria a guardar valores de campo, potencialmente PII, em todo audit trail, não só quando precisa), o buffer é novo, **em memória, não persistido, com tamanho fixo (deque)**: `self._recent_fills = collections.deque(maxlen=30)`, guardando `(selector, text_val, strategy, step_id, target_description)`.

**Ponto de append — só em `fill_resilient`, nunca em `fill_human_like` nem `fill_chained`.**

Correção 1 (`plan-critic`, gap de double-entry): `fill_resilient` (`:1585+`), quando `strategy=="HUMAN_LIKE"`, CHAMA `fill_human_like` (`:1698+`) internamente e ainda faz seu próprio `_log_step` (confirmado em `runner.py:1618-1622`). Se o append acontecesse também dentro de `fill_human_like`, todo fill `HUMAN_LIKE` (exatamente a estratégia do Nome/Celular no bot de referência — verificado em `bot_producao.py:55-56`, `strategy="HUMAN_LIKE"`) entraria duplicado no buffer.

Correção 2 (`/reflect`, achado bloqueante — uma versão intermediária deste doc tinha incluído `fill_chained` como ponto de append pra "resolver" a correção 1 de forma mais simétrica, contradizendo a própria seção "Fora de escopo" abaixo, que já excluía `fill_chained` desde a primeira versão do plano). `fill_chained` (`:1494+`) NÃO tem um `selector` plano — resolve via `parent` (dict `{selector, has_text}`) + `child` (dict `{selector}`), e o `selector_full` que ele monta pra log/exibição contém colchetes de `has_text` que **não são sintaxe CSS válida** (mesmo motivo documentado em `click_chained`, `runner.py:1334-1338`, pra não reusar essa string em nível determinístico). Se uma entrada de `fill_chained` entrasse no buffer e a recuperação chamasse `fill_resilient(selector=entry['selector'], ...)` uniformemente, quebraria — `fill_resilient` não sabe resolver um seletor parent/child composto. Verificado que isso não custa nada ao caso real: CPF e Nome usam `fill_resilient` (`bot_producao.py:55-56`), não `fill_chained` — campos de topo de formulário não usam locator hierárquico, só grids (ex. tabela de coberturas) usam.

**Append só em `fill_resilient`.** Nunca em `fill_human_like` (double-entry) nem em `fill_chained` (seletor incompatível com a recuperação via `fill_resilient` — mantido fora de escopo, ver seção "Fora de escopo").

### Onde implementar

- `aegis_runner/runner.py`:
  - `click_resilient` (`:444-607`): tentativa B (clique sem force, timeout 300-800ms, dentro do try/except já existente) antes do force-click principal (`:525`, `:556`).
  - Generalizar `_wait_for_known_disabled_button`/`_wait_if_wizard_transition_button` (`:823-870`) — remover a restrição a selectors literais, manter os dois pontos de chamada (pré-clique e pós-clique).
  - Novo método de recuperação (ex. `_recover_via_recent_fills`), chamado quando a espera pós-clique generalizada estoura, ANTES de `_finalize_click_success` (`:526-528`, `:595-597`) — itera `self._recent_fills`, sem limpar o buffer.
  - Novo buffer `self._recent_fills = collections.deque(maxlen=30)`, populado só em `fill_resilient` (`:1585+`) — nunca em `fill_human_like` (`:1698+`, evita double-entry) nem em `fill_chained` (`:1494+`, seletor parent/child incompatível com a recuperação, ver correção 2 acima) — e nunca limpo por clique (evita o gap crítico corrigido acima).
  - Reavaliar `_CLICK_EFFECT_EXCLUDED_SELECTORS` (`:331`) após o sensor novo cobrir `#btn-next-step`.

### Risco

- **Falso positivo é barato**: re-fill é idempotente no valor final (sempre limpa antes de digitar de novo), custo é tempo (1 rodada extra de fills + settle), não corretude.
- **Falso negativo (form genuinamente quebrado)**: falha corretamente depois da tentativa de recuperação — comportamento correto, não pior que hoje.
- **Regressão de teste esperada**: `_wait_for_known_disabled_button`/`_wait_if_wizard_transition_button` mudam de "no-op pra maioria dos selectors" para "ativo sempre" — qualquer teste que hoje depende do comportamento antigo (retorno mudo, sem generalização) precisa de ajuste, não reversão (mesmo princípio já aplicado nesta sessão pro `CLICK_NO_EFFECT`).
- **Custo de performance em selector com overlay persistente**: a tentativa B falha sempre (não é caso raro, é o padrão documentado do bug #1 — stepper sobre dropdown) antes de cair pro force, em TODO clique afetado. Timeout calibrado baixo (300-800ms, não 1-2s) mantém isso barato mesmo em dataset de centenas de linhas — não desprezível, mas limitado e conhecido.
- **Recuperação re-preenchendo campos de telas anteriores**: como o buffer não limpa por clique, um `ENABLE_TIMEOUT` tardio pode re-tentar até 30 fills, alguns de telas já passadas. Custo é tempo (idempotente), não corretude — aceito conscientemente em troca de não quebrar o caso real (ver correção do buffer acima).

---

## Feature 2 (diagnóstico apenas): logar rede recente quando `ENABLE_TIMEOUT` disparar

### Problema

A proposta original (F) tentava usar timing de resposta de rede como GATILHO de decisão — descartado (Fable): "alguma resposta chegou depois do fill" é quase sempre verdade em qualquer app real (polling, telemetria, keepalive), não discrimina nada, e a API do Playwright não expõe timestamp de resposta tão diretamente quanto a proposta original assumia.

### Solução

Manter o valor informativo sem usar como gate: quando o sensor `ENABLE_TIMEOUT` (Feature 1) disparar, logar (não decidir com base nisso) as últimas entradas de `captured_network`/requisições recentes na telemetria do passo — útil para o Mentor/forense (`aegis-pipeline-forensics`) diagnosticar retrospectivamente se uma corrida de rede foi a causa provável, sem o runner precisar "adivinhar" isso em tempo real.

### Onde implementar

- `aegis_runner/runner.py`: no ponto onde `ENABLE_TIMEOUT` é logado (dentro do novo método de recuperação da Feature 1), incluir no log/registro de correção (`_register_healing_for_review` ou equivalente) uma nota com as últimas respostas de rede observadas, se disponíveis via `page` no momento — sem bloquear nem condicionar a recuperação a isso.

### Risco

- Nenhum risco de correção — é só log adicional. Único cuidado: não deixar esse log virar, sem querer, gate de decisão no futuro (é exatamente o erro que a proposta F cometeu).

---

## Rejeitado: propagar delta de tempo humano gravado (G)

Descartado por avaliação do Fable e mantido aqui só como registro de decisão, para não ser reproposto sem essa análise: delta de tempo entre eventos de uma gravação humana mede hesitação/leitura, não latência de rede real do app — sinal ruidoso para esta inferência especificamente. Ou não muda nenhuma decisão que a Feature 1 já toma sozinha (peso morto atravessando recorder → sanitizer → schema do plano → runner), ou pode enfraquecer a decisão certa em casos onde o humano digitou rápido por outro motivo (ex.: auto-fill fez a maior parte do trabalho na gravação original). Custo de implementação (mudança de schema do `plano_execucao.json`, retrocompatibilidade de bots já compilados) não se paga pelo valor.

Se a intuição de aproveitar dados da gravação for retomada no futuro, a versão correta é outra, não esta: recorder passar a timestampar cada resposta de rede (hoje `captured_network` só guarda a ÚLTIMA resposta por URL, sem timestamp — `recorder.py:1690-1710` — perde histórico e timing) e o Sanitizer, ao detectar uma resposta de API entre dois fills NA GRAVAÇÃO REAL, compilar um passo explícito e auditável de espera no `plano_execucao.json`. Isso prevendo a corrida em design-time em vez de curá-la em runtime — mas é uma feature de escopo bem maior, complementar à Feature 1 (não substitui), e fica fora deste plano.

---

## Priorização

1. **Feature 1 (A+B)** — resolve o caso real, fecha os gaps já existentes no código (exclusão do sensor em `:331`, ausência de espera pré-clique pro caso real e timeout pós-clique engolido em `:846-870`, ver "Achado-chave"), sem depender de correlação de rede.
2. **Feature 2 (F como diagnóstico)** — baixo custo, acompanha a Feature 1, não é pré-requisito nem bloqueante.
3. **G — não implementar.**

## Fora de escopo

- Versão design-time da intuição de G (recorder timestampar rede + sanitizer compilar espera explícita) — feature maior, considerar como evolução futura separada, não faz parte deste plano.
- **Estender o buffer/recuperação por re-fill para `fill_chained`/campos fora do fluxo linear de `# [PASSO X]`** — `fill_chained` resolve via `parent`+`child` (locator hierárquico), não um seletor plano; o buffer e a recuperação deste design são construídos em cima de `fill_resilient` especificamente (ver correção 2 na Feature 1). Grids com múltiplas linhas (uso típico de `fill_chained`) não são cobertos por este design e não têm evidência de precisar — campos de topo de formulário (o caso real, CPF/Nome/Celular) sempre usam `fill_resilient`.
