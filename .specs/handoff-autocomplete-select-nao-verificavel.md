# Handoff: Seleção de Autocomplete (mat-autocomplete) Não Verificável Após Clique

**Data**: 2026-07-05
**Status**: ✅ RESOLVIDO (2026-07-05) para o caso concreto do 001_teste, via processo de correção manual + LLM (não via fix genérico no runner — ver seção 8)
**Prioridade**: Média (mitigado por correção manual existente no 001_teste; não é bloqueador)
**Projeto de origem**: `portal_segura`, teste `001_teste`, campos Marca/Modelo/Versão (FIPE) do formulário de veículo

---

## 1. Sintoma

Ao rodar `bot_producao.py` do 001_teste **sem** `correcoes_acumuladas.json` (teste isolado, ver contexto na seção 6), a cadeia de seleção Marca → Modelo → Versão do veículo falha silenciosamente:

1. Bot preenche `input[placeholder='Pesquisar Marca...']` = "Hyundai" — OK.
2. Bot preenche `input[placeholder='Pesquisar Modelo...']` = "Creta" — OK.
3. Bot clica na sugestão "Hyundai" no painel `#mat-autocomplete-panel-marca` — `click_chained` falhou nas 2 tentativas normais, escalou pra self-healing cognitivo (IA por screenshot), que reportou `SUCESSO` e clicou por coordenada.
4. Bot clica na sugestão "Creta" no painel `#mat-autocomplete-panel-modelo` — mesmo padrão: falhou normal, `HEALED` via IA por coordenada.
5. Bot preenche `input[placeholder='Versões Disponíveis...']` = "Creta Limited 1.0 Turbo Flex" (valor completo, não termo de busca parcial).
6. Bot tenta clicar na sugestão da versão — **falha definitiva**, painel nunca mostra a opção (ou mostra "Nenhum resultado").
7. Aproximadamente 9 passos depois (`#btn-next-step`, ida pro Passo 3), o botão "Avançar" está desabilitado. Diagnóstico automático (IA) aponta erroneamente pra "CEP de Pernoite"/timing de transição — **essa pista é falsa**, veio de investigação anterior deste handoff que foi corrigida pelo usuário após inspeção visual direta.

**Causa raiz real** (confirmada pelo usuário via inspeção visual do browser, não pela IA de diagnóstico): nenhuma versão válida foi de fato selecionada no dropdown de veículo — é isso que mantém "Avançar" desabilitado, não um problema de timing de transição de tela.

---

## 2. Causa Raiz Técnica (confirmada lendo o código-fonte do app-alvo)

Arquivo: `C:\Projetos\portalSegura\app\src\main.js`

### 2.1. Autocomplete de Versão depende de estado, não de texto

```js
// main.js:1852-1856
setupMatAutocomplete('versao', 'versaoVeiculo', async (val) => {
  if (!state.formValues.marcaVeiculo || !state.formValues.modeloVeiculo) return [];
  const res = await fakeFetch('getFipeVersions', { brand: state.formValues.marcaVeiculo, model: state.formValues.modeloVeiculo });
  return res.versions.filter(v => v.toLowerCase().includes(val.toLowerCase())).map(v => ({ label: v, value: v }));
});
```

Se `state.formValues.marcaVeiculo` OU `.modeloVeiculo` estiverem vazios no momento em que o campo Versão dispara a busca, a função retorna `[]` — painel mostra "Nenhum resultado" **independentemente do texto digitado no campo de busca**. Não adianta digitar a versão certa se marca/modelo não foram genuinamente comitados antes.

### 2.2. Comitar o valor só acontece dentro do próprio listener de clique da opção

```js
// main.js:395-465, setupMatAutocomplete()
optionElem.addEventListener('click', () => {
  input.value = res.value;
  state.formValues[fieldName] = res.value;   // <- só aqui o estado reativo é setado
  clearOverlays();
  const event = new Event('input', { bubbles: true });
  input.dispatchEvent(event);
  updateFormValidity();
});
```

`input.value` e `state.formValues[fieldName]` são setados **juntos, na mesma função síncrona**, disparada exclusivamente pelo evento `click` do elemento da opção. Não existe nenhum outro caminho (ex.: `blur`, `change` no input de busca) que comite o valor.

### 2.3. Por que isso quebra o self-healing por coordenada

Quando `click_chained` falha nas tentativas normais (locator não visível a tempo) e escala pro self-healing cognitivo (`runner.py`, `cognitive.self_healing_click`), o clique final é feito por **coordenada de tela** (`click_by_coordinates`/mouse click simulado), não por locator resolvido no DOM. Se o painel foi re-renderizado/reposicionado entre o momento gravado originalmente e a execução atual (o app cria/recria o painel dinamicamente, `main.js:404-425`), o clique por coordenada pode:
- Cair fora do elemento da opção (miss silencioso — o clique "acontece" em algum lugar, mas não no `optionElem`).
- Cair em cima de um elemento diferente que não tem o listener.

Nos dois casos, **o clique é reportado como sucesso pelo runner** (`HEALED`), mas o listener de `main.js:443` nunca dispara, `state.formValues[fieldName]` fica vazio, e isso só se manifesta várias telas depois (Versão sem opções → Avançar desabilitado), longe o suficiente do ponto real da falha pra confundir tanto o diagnóstico automático quanto uma investigação inicial (foi o que aconteceu nesta sessão — ver seção 5).

---

## 3. Por que não tem fix genérico limpo (o que foi tentado e descartado)

### 3.1. Tentativa 1: heurística "painel fechou sozinho, valor já commitado" — DESCARTADA

Implementada em `click_chained` (`aegis_runner/runner.py`), depois **revertida** nesta mesma sessão:

```python
# REVERTIDO — não usar esta abordagem
if "autocomplete-panel" in parent.get("selector", ""):
    match = re.search(r"has-text\((['\"])(.*?)\1\)", child.get("selector", ""))
    if match:
        target_text = match.group(2)
        already_set = page.evaluate(
            """(text) => Array.from(document.querySelectorAll('input, textarea'))
                .some(el => (el.value || '').trim() === text.trim())""",
            target_text
        )
        if already_set:
            return True  # <- FALSO POSITIVO GARANTIDO
```

**Por que é ruim**: o campo de busca (`input[placeholder='Pesquisar Marca...']` etc.) **já contém o texto digitado pelo próprio robô antes da tentativa de clique** (o `fill()` do passo anterior). Checar "algum input tem esse valor" dá `True` sempre, tenha o clique funcionado ou não — não distingue entre "seleção genuína" e "só digitei o texto e nada mais aconteceu". Essa foi a causa do diagnóstico errado que o usuário corrigiu nesta sessão (ver conversa: "vi no visual que o problema é que não foi clicado/selecionado uma versão existente").

### 3.2. Por que não dá pra verificar `state.formValues` diretamente

```bash
grep -n "window\.state\|window\.__\|export.*state\|globalThis" main.js
# (sem resultados)
```

`state` é uma variável de módulo ES (Vite), **não exposta em `window`**. Não existe hook externo acessível via `page.evaluate()` pra confirmar que o clique realmente comitou o campo no app-alvo. Qualquer verificação via Playwright só enxerga efeitos colaterais no DOM (`input.value`, presença/ausência do painel) que são ambíguos, pelos motivos da seção 3.1.

### 3.3. Hipótese descartada: Escape do click_chained fechando o painel

`click_chained` tem um fallback que aperta Escape entre tentativas (`aegis_runner/runner.py`, "Nível 2.5"). Hipótese inicial: isso fecharia o painel do autocomplete prematuramente. **Descartada** — conferido no código-fonte que o app-alvo não tem NENHUM listener de `keydown`/Escape chamando `clearOverlays()`:

```bash
grep -n "clearOverlays()\|Escape" main.js
# clearOverlays() é chamada só a partir de cliques em opções/botões, nunca de keydown
```

### 3.4. Hipótese não descartada, não confirmada: latência de `fakeFetch` variável

`click_chained` já tem um piso de espera de 8s especificamente para paineis de autocomplete (comentário no código: "latência observada de até ~4s"). Não foi possível confirmar nesta sessão se a falha inicial (que dispara a cascata pro self-healing) é por essa latência variar acima do esperado em algumas execuções, ou por outro motivo. Precisaria de instrumentação/log de timing real (`fakeFetch` em `simulations.js`) pra confirmar.

---

## 4. Estado atual / mitigação existente

O bot **funcional** do 001_teste (fora desta sessão de teste isolado) já tem uma correção manual pra esse ponto, registrada em `correcoes_acumuladas.json` (`corr_20260703_101840_1`) e baked diretamente no código gerado como workaround:

```python
# Correção para o problema de autocomplete de modelo
page.fill("input[placeholder='Pesquisar Modelo...']", row.get("modelo_veiculo", ""))
page.wait_for_timeout(300)
```

Esse workaround (re-preencher o campo antes de tentar selecionar) **na prática evita** o cenário de painel obsoleto/reposicionado que dispara o self-healing por coordenada, contornando o problema sem resolvê-lo na raiz. Enquanto `correcoes_acumuladas.json` não for removido/dessincronizado (ver `.specs/handoff-*` desta mesma sessão sobre numeração de `plano_execucao.json`), essa fragilidade fica mascarada.

---

## 5. Contexto da sessão (por que isso apareceu agora)

Esta investigação começou como parte de uma sessão maior corrigindo 3 bugs reais e confirmados no pipeline Aegis:

1. Cockpit mostrando "passos fantasma" (usava `gravacao.json` cru em vez de `plano_execucao.json`) — **corrigido e testado**.
2. `sanitizer.py` com 2 regras de dedup mortas (nunca executavam por bug de dead code) que, ao serem reativadas, tinham bugs próprios (regra do CDK-overlay derrubava cliques de seleção reais; regra do autocomplete tinha checagem de idioma inglês contra seletores em português) — **corrigido e testado**.
3. `fill_human_like()` usando `click(force=True)`, que ignora a checagem `enabled` do Playwright, causando digitação em campo bloqueado por busca assíncrona (CPF → Nome Completo) — **corrigido e testado**.

Ao testar o fix #2 (sanitizer) de forma isolada, sem `correcoes_acumuladas.json`, o bug de autocomplete marca/modelo/versão descrito neste handoff apareceu como efeito colateral — ele **sempre existiu**, só ficava mascarado pela correção manual já aplicada no bot de produção. Diferente dos 3 bugs acima, este não teve uma causa mecânica única, clara e corrigível de forma genérica e segura dentro do escopo desta sessão.

---

## 6. Caminhos possíveis para investigação futura

- **Instrumentar `fakeFetch`** (`simulations.js`) temporariamente com logging de latência real por chamada, rodar o bot repetidas vezes, e confirmar/descartar a hipótese da seção 3.4.
- **Runner**: considerar se `click_chained`, ao escalar pro self-healing por coordenada especificamente para seletores `mat-autocomplete-panel-*`, deveria re-tentar o locator normal MAIS uma vez logo antes do fallback por coordenada (o painel pode ter simplesmente terminado de renderizar entre a tentativa 2 e a chamada de self-healing) em vez de ir direto pra coordenada.
- **Runner**: para painéis de autocomplete especificamente, considerar aumentar o número de tentativas normais (hoje são só 2) antes de escalar, já que o custo de uma tentativa extra é baixo comparado ao risco de coordenada errada.
- **Não recomendado**: qualquer heurística de "verificar se já foi selecionado" baseada em conteúdo visível do DOM — provado nesta sessão que produz falso positivo (seção 3.1).

---

## 7. Arquivos relevantes

- `C:\Projetos\portalSegura\app\src\main.js` — linhas 395-465 (`setupMatAutocomplete`), 1852-1856 (busca de versão dependente de estado), 303-305 (`clearOverlays`).
- `aegis_runner/runner.py` — `click_chained` (clique encadeado + fallback de self-healing), `_handle_click_failure`.
- `projects/portal_segura/tests/001_teste/correcoes_acumuladas.json` — entrada `corr_20260703_101840_1` (mitigação manual existente).
- `projects/portal_segura/tests/001_teste/code/bot_producao.py` — workaround `page.fill()` duplicado antes da seleção de modelo (busca por "Correção para o problema de autocomplete de modelo").

---

## 8. Resolução aplicada (2026-07-05)

Resolvido via processo normal de correção manual (`correcoes_acumuladas.json` + Fase 4 cirúrgica), não via mudança genérica no framework. Investigação ao vivo revelou 2 causas distintas dentro do mesmo sintoma:

### 8.1. Marca (`st_022`) e Versão (`st_025`): latência de fetch, não estado

Fix: `page.locator(seletor_da_opcao).wait_for(state="visible", timeout=15000)` imediatamente antes do `click_chained`, dando tempo pro `fakeFetch` (`getFipeModels`/`getFipeVersions`) terminar antes da 1ª tentativa de clique — evita cair no self-healing por coordenada por completo. Confirmado em execução real: `st_022` resolveu via locator normal (sem `usedHealing`).

### 8.2. Modelo (`st_023`): causa DIFERENTE — dependência de campo, não latência

O fix de `wait_for` sozinho **não resolveu** — estourava timeout de 15s porque a opção nunca aparecia. Causa raiz real, confirmada lendo `main.js`: a busca de Modelo (`fakeFetch('getFipeModels', {brand: state.formValues.marcaVeiculo})`) roda no momento do `fill` do campo Modelo (`st_021`), que na ordem gravada acontece **antes** da Marca ser efetivamente selecionada (`st_022`). Nesse momento `marcaVeiculo` ainda está vazio — o painel de sugestões do Modelo é montado com resultado errado e não se atualiza sozinho depois.

Fix definitivo: re-preencher o campo Modelo (re-disparando o evento `input` que remonta o painel) **depois** que a Marca já foi selecionada, só então esperar a opção certa aparecer:
```python
page.fill("input[placeholder='Pesquisar Modelo...']", row.get('modelo_veiculo', ''))
page.wait_for_timeout(300)
page.locator(f"#mat-autocomplete-panel-modelo div:has-text('{row.get('modelo_veiculo', '')}')").first.wait_for(state="visible", timeout=15000)
```

Confirmado em execução real: bot passou por `st_022`, `st_023`, `st_024`, `st_025` (todos `SUCCESS`, nenhum via self-healing) e avançou muito além de qualquer tentativa anterior nesta sessão (chegou em `st_053`/tela seguinte, travando num bug diferente e já catalogado de transição pós-Avançar).

**Lição geral pra qualquer autocomplete encadeado** (documentada em `qa_insight` das correções): campos que dependem uns dos outros (Modelo depende de Marca, Versão depende de Marca+Modelo) precisam ser **re-preenchidos** depois que a dependência foi satisfeita — não basta esperar mais tempo se a causa é ordem/dependência, não latência. As duas causas produzem o MESMO sintoma externo (painel nunca mostra a opção), mas pedem fixes diferentes — vale sempre confirmar qual é qual antes de aplicar `wait_for` cegamente.

**Correções aplicadas**: `corr_20260705_manual_st022`, `corr_20260705_manual_st023`, `corr_20260705_manual_st025` em `correcoes_acumuladas.json`.
