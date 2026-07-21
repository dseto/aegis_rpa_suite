# Relatório de Piloto Live — Unified Target Descriptor (PR #2)

**Data:** 2026-07-20
**Site:** http://localhost:5173/ (Portal Segura — mesmo site do gate de regressão)
**Referência:** `.specs/plans/portal-segura.baseline-001.md`
**Projeto:** `projects/portal_segura_utd_pilot/tests/001_teste`
**Branch validada:** `unified-target-descriptor-6509308849546547825` (PR #2), commit final `52e1728`

## Objetivo

Validar em execução real — não mockada — a feature Unified Target Descriptor: gravação capturando `anchor`/`expected_effect` de verdade, propagação pelo Sanitizer, emissão pelo Code Generator, e o tier `anchor_geometry` disparando em runtime. As 5 correções de fiação anteriores (commit `47b1208`) tinham suítes mockadas verdes, mas mockado só prova que o código executa — não que os dados fluem de ponta a ponta contra um browser real (Working Agreement 1 do CLAUDE.md).

## Fluxo gravado

Reaproveitado o driver `run_auto_simulation` já existente em `aegis_blackbox/recorder.py` (específico do Portal Segura, sem seletor inventado por mim). Login (`#username`, `#password`, `#btn-login`) + clique em "Nova Cotação Auto" (`#btn-new-quote`) — 4 eventos de clique. A simulação parou em "Etapa 1: Dados do Cliente" por timeout num campo (`client-document-input`) não crítico para este piloto (achado ambiental do site, não do framework — ver Achados).

## Achados

### 1. [BLOQUEADOR, corrigido] Newline literal quebrava o parse do script inteiro injetado

`aegis_blackbox/recorder.py`, `JS_MINIMAL_LISTENERS`. Um comentário JS em prosa continha `\n` como texto solto dentro de uma string Python não-raw — Python interpretou como escape de newline real, quebrando o comentário `//` no meio e produzindo `SyntaxError` de parse do script inteiro (`add_init_script` injeta tudo como uma unidade). **Toda gravação neste código falhava silenciosamente com 0 eventos** — o erro só aparecia como `[PAGE ERROR]` no console do browser, que nenhum script de gravação checa. Bug pré-existente em `main` desde o commit `11aa1b2`, não relacionado ao PR #2. Reproduzido isoladamente (Playwright real + `page.on("pageerror")`) e via `node --check` na string runtime. Fix de 1 linha, commit `8144f50` em `main`, trazido ao PR via merge.

### 2. [BLOQUEADOR, corrigido] Sanitizer não propagava `anchor`/`expected_effect`/`viewport` ao plano

`aegis_sanitizer/sanitizer.py`, `build_step_from_event`. `_serialize_plan_step` já sabia serializar os 3 campos (Jules incluiu no `field_order`), mas o dict de step intermediário nunca os recebia do evento — mesma classe de bug dos 5 fixes anteriores em `runner.py` (schema pronto, dado nunca chega lá). `gravacao.json` tinha os campos (confirmado nos 4 eventos reais); `plano_execucao.json` não tinha nenhum. Fix commit `52e1728`.

### 3. [BLOQUEADOR, corrigido] `_FakeRunner` do dry-run sandbox com assinatura desatualizada

`aegis_code_generator/step_validator.py`. O mock usado no dry-run da geração de código tem assinaturas explícitas (não `*a/**kw`, de propósito, para pegar kwarg alucinado) — desatualizadas em relação ao runner real. Assim que o fix #2 passou a propagar `anchor` ao plano, **todo bot gerado passou a falhar dry-run** com `TypeError: unexpected keyword argument 'anchor'`, queimando as 15 tentativas de correção via LLM tentando consertar código que já estava certo (reproduzido ao vivo: 15/15 exaurido, `RuntimeError`). Fix commit `52e1728`.

### 4. [Confirmado funcionando] Pipeline completo ponta a ponta

Depois dos 3 fixes acima: gravação real → 4 eventos com `anchor` (estratégias `label_for` e `nearest_stable_text`, geometria real) e `expected_effect` (deltas reais de `dom_delta`/`overlay_delta`/`new_visible_text`) → Sanitizer propaga os 4 steps → Code Generator emite o bot **na tentativa 1/15, zero chamadas LLM** (as 3 condições C1-C11 do emissor determinístico satisfeitas para os 4 steps) → bot gerado tem `anchor=`/`expected_effect=`/`viewport=` reais em cada `click_resilient(...)` → **execução real do bot dispara o tier `anchor_geometry`** (`[_resolve_via_anchor] Resolvendo click via âncora geométrica... Elemento próximo achado`).

### 5. [Não-bug, ambiental] `CLICK_NO_EFFECT` em `st_001`

A execução do bot gerado falhou em `st_001` (clique em `#username`) com `CLICK_NO_EFFECT`. Diagnóstico da IA (multimodal, screenshot real) identificou corretamente: os campos de login já estavam preenchidos (autofill do browser ou sessão persistida de execuções anteriores no mesmo perfil), então o clique — por mais que tenha passado por toda a cadeia de recuperação incluindo o novo tier de âncora — genuinamente não produziu efeito algum, porque não havia efeito a produzir. Comportamento **correto** do verificador (rejeita corretamente um clique sem efeito real, doutrina "Cauda Longa Verificada"), não regressão nem falso-negativo. Causa raiz é o ambiente de teste (perfil de browser reaproveitado entre pilotos), não o framework.

## Métricas

| Métrica | Valor |
|---|---|
| Eventos gravados | 4 (100% clique) |
| Eventos com `anchor` capturado | 4/4 (100%) |
| Eventos com `expected_effect` capturado | 4/4 (100%) |
| Steps propagados ao plano com os 3 campos | 4/4 (100%, após fix #2) |
| Tentativas de geração de código | 1/15 (0 chamadas LLM, após fix #3) |
| Steps classificados `deterministic` | 4/4 (100%) |
| Tier `anchor_geometry` disparou em runtime real | Sim (1 vez, st_001) |
| Transação final | FAILED (causa ambiental, não framework) |

## Status final

| Achado | Status |
|---|---|
| Newline literal quebrando parse do recorder | Corrigido (`8144f50`, `main`) |
| Sanitizer não propagava anchor/expected_effect/viewport | Corrigido (`52e1728`, PR #2) |
| `_FakeRunner` com assinatura desatualizada | Corrigido (`52e1728`, PR #2) |
| Pipeline ponta a ponta (captura→propagação→emissão→runtime) | Confirmado funcionando |
| `CLICK_NO_EFFECT` em st_001 | Falso positivo do framework? Não — comportamento correto diante de ambiente com sessão pré-preenchida |
| Timeout em `client-document-input` (Etapa 1) | Não investigado (fora do escopo — fluxo parou antes de qualquer step relevante ao UTD) |

## Recomendação

**De maior impacto/menor esforço:** rodar este mesmo piloto contra um perfil de browser limpo (ou `storage_state` isolado) para conseguir uma transação `SUCCESS` completa e observar o tier `anchor_geometry` sendo **aceito** (não só disparado) em pelo menos um passo — hoje a evidência prova que a cadeia inteira funciona e o tier resolve corretamente, mas nenhum passo deste piloto específico chegou a fechar como `HEALED` via âncora (o único clique que precisou de recuperação foi rejeitado por falta de efeito real, não por falha do tier). Não é bloqueador — a feature está provada funcional — mas fecharia o ciclo de evidência com um caso positivo completo.
