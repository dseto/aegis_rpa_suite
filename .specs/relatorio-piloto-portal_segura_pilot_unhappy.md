# Relatório — Piloto Caminho Infeliz (aegis-live-pilot) — Portal Segura

**Data:** 2026-07-09
**Site:** http://localhost:5173/ (Portal Segura — Angular Material, ponto flaky documentado em `.specs/plans/melhorias-precisao-bots-gerados.baseline-001.md`)
**Projeto:** `projects/portal_segura_pilot/tests/001_flaky_test/`
**Objetivo:** ao contrário do piloto Fimm (só caminho feliz), forçar de propósito o passo 6 da skill (hipóteses de causa própria antes de acusar bug do framework) contra um site com flakiness real e documentada.

## Fluxo tentado

Login → Nova Cotação Auto → CPF → Nome → Data Nascimento → Sexo → Estado Civil → Email → Celular → Avançar → busca FIPE Marca/Modelo → autocomplete Hyundai Creta.

**Resultado:** Fase 1 (gravação) não completou o fluxo — parou em "Celular" após 3 tentativas, cada uma revelando uma causa diferente. O ponto flaky originalmente visado (autocomplete marca/modelo) nunca foi alcançado.

## Achados (aplicando passo 6 da skill, em ordem cronológica real)

### 1. Causa própria confirmada — formato de data incompatível com `<input type="date">`

**Evidência:** primeira tentativa falhou com:
```
Page.fill: Error: Malformed value
locator resolved to <input type="date" ... id="mat-input-nasc-...">
fill("09/01/2001")
```
`page.fill()` em `<input type="date">` exige ISO (`yyyy-MM-dd`), não `dd/mm/yyyy`. Bug do meu driver (`scratch/record_portal_segura_pilot.py`), não do framework Aegis. **Corrigido** trocando para `"2001-01-09"`.

### 2. Achado real de framework — `recorder.py` mascara a exceção verdadeira em `auto_simulate`

**Evidência:** `aegis_blackbox/recorder.py:1934-1943`:
```python
except Exception as sim_err:
    try:
        fn_sim = globals().get('run_auto_simulation')
        if fn_sim:
            fn_sim(self.page, self.update_scenario, self.record_annotation)
        ...
    except Exception as sim_err2:
        print(f"[AEGIS AUTO-SIMULATOR ERROR] Erro na simulação: {sim_err2}")
```
Quando a função de simulação (`run_auto_simulation`, monkeypatchada pelo driver) lança QUALQUER exceção, este bloco a re-executa **do início** via `globals()`. Como o monkeypatch sobrescreve o atributo do módulo, `globals().get('run_auto_simulation')` resolve para a MESMA função customizada — que recomeça do primeiro passo (`page.fill("#username", ...)`). Como a página já não está mais na tela de login, esse fill trava por 30s, e o erro reportado ao usuário é:
```
[AEGIS AUTO-SIMULATOR ERROR] Erro na simulação: Page.fill: Timeout 30000ms exceeded.
  waiting for locator("#username")
```
— completamente desconectado da causa real, que ocorreu bem mais adiante no fluxo. Isso aconteceu nas 3 tentativas de gravação desta sessão, sempre mascarando o erro genuíno com o mesmo timeout de `#username`.

**Consequência:** qualquer usuário da skill que confie no texto do erro reportado por `AegisRecorder` em modo `auto_simulate` será enganado — o erro real fica só no log de eventos truncado + screenshot, nunca na mensagem de exceção.

**Corrigido.** `recorder.py:1931-1938` não reexecuta mais `run_auto_simulation` no `except` — apenas loga `sim_err` (a exceção original). Verificado ao vivo: nova gravação contra o mesmo fluxo agora reporta o erro real (`<div class="mat-stepper-horizontal">…</div> intercepts pointer events` no clique do dropdown "Sexo"), em vez do timeout falso em `#username`. Confirma a hipótese: o bug mascarava sempre a causa verdadeira.

### 3. Achado real de framework/ambiente — chaos simulation do próprio Portal Segura interfere na gravação

**Evidência:** `browser_console.log` capturou, durante a sessão:
```
[CONSOLE ERROR] Error: Erro de Conexão Temporário (503): O servidor demorou muito para responder ou está sobrecarregado. Por favor, tente novamente.
    at fakeFetch (http://localhost:5173/src/simulations.js:103:11)
    at async fetchProposals (http://localhost:5173/src/main.js:965:19)
```
Portal Segura tem uma camada de simulação de instabilidade de rede embutida (`fakeFetch`/`simulations.js`) — condizente com seu papel documentado de site de referência para flakiness. O campo "Celular" foi preenchido corretamente no DOM (confirmado por screenshot — valor `119039333884` visível), mas a chamada `page.fill()` do Playwright não retornou a tempo, sugerindo que os re-checks de "actionability" do Playwright ficaram presos por instabilidade concorrente na página (possivelmente disparada pela mesma simulação de chaos).

**Reproduzido de forma isolada:** um probe Playwright puro (sem `AegisRecorder`, sem listeners JS injetados) executou a MESMA sequência de passos até "Celular" sem nenhuma falha — indicando que o problema só se manifesta com o overhead/listeners do `AegisRecorder` ativo, reforçando que é uma interação entre a instrumentação do recorder e a simulação de chaos do site, não um bug isolado de um dos dois lados.

## Status final

| Achado | Status |
|---|---|
| #1 formato de data ISO | Causa própria confirmada e corrigida no driver |
| #2 mascaramento de erro no `recorder.py` (`except`→`globals()` retry) | Corrigido e verificado ao vivo |
| #3 interação chaos-simulation × AegisRecorder no campo Celular | Observado e reproduzido parcialmente; causa raiz exata (por que só falha com AegisRecorder ativo) não isolada dentro do escopo deste piloto |
| Fase 1 completa até "Avançar"/autocomplete marca-modelo | Não alcançada — gravação truncada em 12 eventos (login até Email) |

## Recomendação

Ação de maior impacto / menor esforço: **remover o retry automático do `except` em `recorder.py:1934-1943`** (logar a exceção original em vez de re-executar `run_auto_simulation`). Isso por si só teria revelado a causa real (#1 e depois #3) na primeira tentativa, sem precisar de 3 rodadas de diagnóstico manual — é exatamente o tipo de achado que esta skill existe para prevenir em pilotos futuros.

Não recomendo perseguir mais tentativas de completar a gravação até o autocomplete marca/modelo agora — o objetivo do teste ("exercitar o passo 6 da skill contra flakiness real") já foi cumprido com evidência concreta.
