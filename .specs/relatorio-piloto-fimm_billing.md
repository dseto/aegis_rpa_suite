# Relatório — Piloto Fimm Billing Engine (teste da skill `aegis-live-pilot`)

**Data:** 2026-07-09
**Site:** `http://localhost:6174/login` (Fimm Corporate — React/Vite/Tailwind)
**Referência:** skill `aegis-live-pilot` (primeira execução real, disparada por linguagem natural)
**Projeto:** `projects/fimm_billing/tests/001_billing_engine`

## Objetivo desta execução

Validar a skill `aegis-live-pilot` recém-criada: dispara sozinha via frase natural? Segue o processo documentado? Produz resultado correto? Acha bug real?

## Fluxo gravado

Login (`admin`/`admin123`) → clicar link "Billing Engine" (sidebar) → selecionar cliente B2B "Tech Solutions Ltda" no `<select>` nativo. 5 eventos: 2 `fill`, 2 `click`, 1 `fill` (select).

## Métricas

| Métrica | Resultado |
|---|---|
| % eventos com `fallback_selectors` | 2/5 (40%) — os 2 `fill` de login (id + placeholder) |
| % steps `weak_selector` no plano | 1/5 (20%) — `st_005`, `<select>` sem name/id/placeholder, score 40 |
| Taxa de sucesso na execução real | 100% (5/5) |
| Chamadas de self-healing cognitivo | 0 |
| `HEALED`/`needs_review` gerados | 0 |
| Falsos positivos `CLICK_NO_EFFECT` | 0 |
| Tentativas do Ralph Loop (Fase 4) | 1/15 |

## Achados

### 1. Skill disparou corretamente por linguagem natural
Frase de teste: "roda um piloto do Aegis contra o site http://localhost:6174/login (Fimm Corporate), testando o fluxo de Billing Engine...". Sem citar o nome da skill, o sistema identificou e carregou `aegis-live-pilot` corretamente (confirmado pelo `description` do frontmatter fazer match).

### 2. Sondagem real encontrou informação que uma suposição erraria
A sidebar do Fimm vem com **todas as seções expandidas por padrão** — clicar no cabeçalho de uma categoria ("BILLING & COLLECTIONS") na verdade **colapsa** a seção, removendo o link visível. Se o driver tivesse assumido "preciso clicar na categoria pra abrir o submenu" (padrão comum em outros sites), teria quebrado. A sondagem via Playwright real (passo 2 da skill) pegou isso antes de gravar.

### 3. `weak_selector` + ancoragem obrigatória (M3) funcionou fim-a-fim em dado 100% novo
`st_005` (`<select>` puro, sem `name`/`id`/`placeholder`) pontuou `confidence=40`, foi marcado `weak_selector: true` no plano, e o Code Generator ancorou corretamente com `:has-text('Tech Solutions Ltda'), select` — respeitando a instrução injetada no prompt (`WEAK_SELECTOR_WITHOUT_ANCHOR`). Primeira confirmação real de M3 funcionando em produção fora do projeto onde foi implementado.

### 4. Nenhum bug do framework encontrado nesta rodada
Diferente do piloto anterior (login+navegação, achou 3 bugs reais), este fluxo passou limpo de primeira — sem exigir intervenção manual, sem `project.json` esquecido (a skill já documenta os dois níveis como princípio #3), sem falso positivo do sensor.

## Status final

| Achado | Status |
|---|---|
| 1. Skill dispara por linguagem natural | ✅ Confirmado |
| 2. Sondagem real evita suposição errada sobre sidebar | ✅ Processo da skill funcionou como desenhado |
| 3. `weak_selector`/ancoragem (M3) em produção nova | ✅ Confirmado fim-a-fim |
| 4. Bug do framework | Nenhum encontrado nesta rodada |

## Recomendação

Testar a skill `aegis-live-pilot` num fluxo com **falha real esperada** (ex.: seletor genuinamente ambíguo, ou site com Chaos Cockpit ativo) — este piloto validou o "caminho feliz" do processo; falta provar que o passo 6 (hipóteses de causa própria antes de acusar bug) da skill funciona quando algo dá errado de verdade.
