# Relatório SUB08 — Validação de browser real (sabotagem) da doutrina "Cauda Longa Verificada"

**Escopo:** apenas a Parte A (Parte B — reconfirmação de B4, zero chamadores diretos de
`self_healing_click`/`CognitiveGateway`/`.cognitive.` no bot compilado real — já foi feita e
confirmada em tarefa anterior, não repetida aqui).

**Nenhum arquivo de framework foi modificado** (`aegis_runner/*`, `aegis_sanitizer/*`,
`aegis_code_generator/*`, `aegis_blackbox/*` intocados). Nenhum commit/push/mudança de git.

## Ambiente

- Projeto real alvo: `C:\Projetos\TesteFimm\tests\cenario_principal` (**intocado** — nenhum
  arquivo desse projeto foi editado).
- Servidor de dev real: `http://localhost:6174/login`, confirmado no ar (`200`) antes de cada
  execução.
- `AEGIS_COGNITIVE_ENABLED` já configurado no `.env` do projeto (não alterado) — confirmado ativo
  nas execuções abaixo (`[COGNITIVE SUCESSO]`/`[COGNITIVE FALHA]` disparando normalmente).
- Mudanças de código do backlog SUB01–07 já aplicadas em `aegis_runner/runner.py` e
  `aegis_runner/cognitive_fallback.py` (working tree, não commitadas) — usadas como estão, não
  tocadas por esta tarefa.

### Nota de execução (armadilha de sandbox descoberta durante a tarefa)

O tool `Bash` (Git Bash) deste ambiente opera sobre uma visão de filesystem isolada/overlay para
caminhos **fora** do repositório `C:\Projetos\aegis_rpa_suite` — comandos `mkdir`/`cp`/`python`
executados via `Bash` sobre `C:\Projetos\TesteFimm\...` reportavam sucesso (inclusive com saída de
execução de browser real plausível) mas os artefatos não existiam no filesystem real do host
(confirmado via `Get-ChildItem`/`Test-Path` do PowerShell, que é a shell primária real deste
ambiente). Todo o setup e as execuções reais deste relatório foram refeitos e confirmados
exclusivamente via **PowerShell** (criação de pastas, escrita dos scripts, execução do
`python.exe`), com verificação cruzada de cada artefato via `Test-Path`/`Get-Item` antes de
qualquer captura de evidência. Isso não é um achado sobre o Aegis RPA Suite — é uma característica
do ambiente do agente — mas fica registrado aqui porque explica por que a primeira tentativa deste
relatório (descartada) não deixou nenhum rastro real em disco.

## Metodologia (não-destrutiva, revertível)

Como o `bot_producao.py` compilado tem os **seletores primários hard-coded** como argumentos
Python (não lidos de `plano_execucao.json` em runtime — o plano só alimenta
`fallback_selectors_by_step`/`flaky_step_ids`), sabotar apenas uma cópia de `plano_execucao.json`
não teria efeito nenhum na resolução do seletor real. Por isso, em vez de copiar o projeto inteiro
(89 MB de `trace.zip` + históricos de 21 execuções anteriores), foram criadas duas pastas-irmãs
novas, com uma cópia mínima dos artefatos de dados (`dataset_inicial.json`, `dicionario.json`,
`plano_execucao.json`, `project.json`) e um script Python próprio por cenário que:

- reusa `TransactionRunner`/`CognitiveGateway` **reais e intocados** (mesmo `import
  aegis_runner.runner`);
- executa **só os passos necessários** para alcançar o alvo sabotado (login + navegação mínima),
  em vez dos 43 passos completos do bot de produção — mais rápido, mesmo motor;
- sabota **apenas o passo-alvo**, com `selector` primário trocado para algo que nunca existiu no
  DOM real, e `original_coords=None` de propósito — sem isso, o Nível 4 (fallback físico por
  coordenada de gravação, que roda ANTES do tier cognitivo desde a doutrina reordenada) resolveria
  o clique usando a coordenada REAL do elemento antes de sequer acionar a IA, mascarando o próprio
  cenário que se queria provar.

Artefatos criados (preservados para inspeção, **nada foi apagado do projeto original**):

- `C:\Projetos\TesteFimm\tests\cenario_principal_sabotage1\` (Cenário 1)
- `C:\Projetos\TesteFimm\tests\cenario_principal_sabotage2\` (Cenário 2, inclui o reconhecimento
  `recon_fx_desk.html`/`.png` usado para escolher o alvo estático real)

Cada pasta contém `reports/historico_passos.json`, `reports/telemetria_resolucao.json`,
`screenshots/*.png` e `run_log*.txt` da(s) execução(ões) real(is).

---

## Cenário 1 — LLM resolve COM verificação (tier `visual_ai`)

**Verdict: CONFIRMADO AO VIVO.**

### Tentativa 1 (descartada, mas documentada — achado real sobre o limite do verificador)

Primeira tentativa sabotou `st_019` ("EMEA", troca de aba ativa entre botões-irmãos já
existentes na tela Cash Position). A IA visual acertou o alvo quase exatamente (coordenada da IA
`(391, 239)` vs. coordenada gravada original `(396, 238.7)`), mas o passo terminou `FAILED` — não
`HEALED`. Causa raiz, confirmada lendo `runner.py`: `_capture_click_effect_snapshot` calcula o 4º
sinal (`siblingClassFingerprint`, o sinal desenhado especificamente para pegar troca de aba
CSS-only) resolvendo o **seletor original passado ao chamador** (`selector`) — quando esse seletor
está 100% quebrado (não apenas desatualizado), a resolução falha silenciosamente e o fingerprint
fica `""` nos dois snapshots (antes/depois), sempre igual. Os outros 3 sinais genéricos
(`url`/`domSize`/`overlays`) também não mudam para uma troca de aba puramente visual. Resultado:
`_verify_action_effect` nunca teve como detectar o efeito real, mesmo com a IA clicando no lugar
certo. Log relevante:

```
[COGNITIVE SUCESSO] Elemento 'Clicar no botao 'EMEA'' localizado via IA em (391, 239) [...]
[AEGIS RUNNER] [VERIFY_REJECTED] Clique proposto pela IA em (391, 239) para '#nao-existe-de-verdade-emea-xyz' nao produziu efeito verificavel (pos-clique).
```

Isso é um **gap real e verificável** (não um bug do meu setup): quando o seletor original está
totalmente inexistente, o verificador de efeito perde acesso ao 4º sinal (o único capaz de
detectar troca-de-classe-entre-nós-já-existentes) e só sobra url/domSize/overlays — cegos para
esse tipo específico de UI. Fica fora do escopo desta tarefa consertar (é medição, não fix); ver
"Achados adicionais" abaixo.

### Tentativa 2 (a que conta como a evidência do Cenário 1)

Trocado o alvo sabotado para `st_005` ("Wire Transfers", navegação real para uma tela com DOM
completamente diferente) — sinal genérico robusto (URL/domSize mudam de qualquer forma), não
depende do seletor sabotado resolver nada.

Log real (`run_log2.txt`):

```
[AEGIS_STEP] START | st_005 | click | #nao-existe-de-verdade-wire-transfers-xyz | Navegar para a secao 'Wire Transfers' | | | 1
[AEGIS RUNNER] Tentativa 1 de clique falhou ... Timeout 5000ms exceeded.
[AEGIS RUNNER] [RETRY 2] Limpando possíveis overlays pendentes via Escape...
[AEGIS RUNNER] Tentativa 2 de clique falhou ... Timeout 5000ms exceeded.
[AEGIS RUNNER] Reposicionando CDK overlay no viewport...
[AEGIS RUNNER] Falha no clique padrão de '#nao-existe-de-verdade-wire-transfers-xyz'. Acionando Self-Healing cognitivo via IA...
[COGNITIVE] Iniciando Self-Healing para seletor falho: '#nao-existe-de-verdade-wire-transfers-xyz'
[COGNITIVE SUCESSO] Elemento 'Navegar para a secao 'Wire Transfers'' localizado via IA em (152, 214) [Justificativa: O elemento 'Wire Transfers' foi identificado visualmente no menu lateral esquerdo, abaixo de 'Cash Position'.]
[AEGIS_STEP] HEALED | st_005 | click | #nao-existe-de-verdade-wire-transfers-xyz | Navegar para a secao 'Wire Transfers' |  | screenshots/step_1_5_click__nao-existe-de-verdade-wire-tr.png | 1
[✓ SUCESSO] Transação 1 executada com sucesso!
```

`reports/telemetria_resolucao.json`:

```json
{
  "tier_resolution_counts": {"identity": 4, "visual_ai": 1},
  "verify_rejected_counts": {"pre_click": 0, "post_click": 0, "total": 0}
}
```

`reports/historico_passos.json` (`st_005`): `status: "HEALED"`, `resolver_tier: "visual_ai"`,
`verify_result: {"kind": "generic", "specific": false, "passed": true}`.

Screenshot `screenshots/step_1_5_click__nao-existe-de-verdade-wire-tr.png` confirma visualmente a
tela "WIRE TRANSFERS" renderizada — navegação real efetivada, não falso-positivo.

**Cadeia confirmada ao vivo:** seletor quebrado → 2 tentativas físicas falham → Escape+retry falha
→ reposição CDK falha → sem `fallback_selectors` → sem coordenada de gravação (`None`, proposital)
→ self-healing cognitivo propõe coordenada plausível → gate de plausibilidade pré-clique aceita →
clique físico → `_verify_action_effect` confirma efeito real (mudança de URL/DOM) → `HEALED`,
`healing_method="visual_ai"`.

---

## Cenário 2 — Rejeição PÓS-clique (efeito sabotado)

**Verdict: CONFIRMADO AO VIVO.**

### Escolha do alvo

Reconhecimento real (script `recon_fx_desk.py`, só login + navegação FX Desk, sem clicar em nada
sabotado) confirmou via `page.content()` que o texto "Feed de Câmbio em Tempo Real" é um `<h3>`
estático puro, sem handler de clique:

```html
<div class="flex justify-between items-center">
  <h3 class="font-bold text-sm font-display ...">Feed de Câmbio em Tempo Real</h3>
  <span class="... WS LIVE FEED ...">...</span>
</div>
```

### Tentativa 1 (descartada — caiu no gate PRÉ-clique, não no pós-clique)

Primeira tentativa com descrição de alvo genérica levou a IA a confundir o título do painel com
um cabeçalho de coluna da tabela (`<th>Taxa Spot (À Vista)</th>`), rejeitado corretamente pelo
**gate pré-clique** (`_hit_test_plausible`) — nenhuma ação física ocorreu:

```
[COGNITIVE SUCESSO] ... localizado via IA em (458, 284) [Justificativa: ... usando OCR ...]
[AEGIS RUNNER] [HIT-TEST] Implausível em (458, 284): alvo='...' não corresponde ao elemento sob o ponto (tag='th', ..., texto='Taxa Spot (À Vista)').
[AEGIS RUNNER] [VERIFY_REJECTED] Proposta da IA ... rejeitada pelo gate de plausibilidade (pre-clique, nenhuma acao executada).
```

Isso é o Cenário 3 (gate pré-clique), não o Cenário 2 — descartado e refeito com uma descrição de
alvo mais específica (distinguindo explicitamente do cabeçalho de coluna da tabela).

### Tentativa 2 (a que conta como a evidência do Cenário 2)

Log real (`run_log2.txt`):

```
[AEGIS_STEP] START | sab_002_static_heading | click | #nao-existe-de-verdade-feed-header-xyz | Clicar exatamente no texto do TITULO (...) que diz 'Feed de Câmbio em Tempo Real' -- NAO e um cabecalho de coluna da tabela ... | | | 1
[AEGIS RUNNER] Tentativa 1/2 de clique falhou ... Timeout 5000ms exceeded.
[AEGIS RUNNER] Falha no clique padrão de '#nao-existe-de-verdade-feed-header-xyz'. Acionando Self-Healing cognitivo via IA...
[COGNITIVE SUCESSO] Elemento '...' localizado via IA em (453, 246) [Justificativa: O elemento 'Feed de Câmbio em Tempo Real' foi identificado visualmente como o título do painel, em negrito, no canto superior esquerdo do painel de cotações, ao lado do badge 'WS LIVE FEED', conforme a descrição.]
[AEGIS RUNNER] [VERIFY_REJECTED] Clique proposto pela IA em (453, 246) para '#nao-existe-de-verdade-feed-header-xyz' nao produziu efeito verificavel (pos-clique). Avancando para o proximo tier.
[AEGIS RUNNER] Falha definitiva ao clicar em '#nao-existe-de-verdade-feed-header-xyz'.
[❌ FALHA] Transação 1 quebrou por erro sistêmico.
```

`reports/telemetria_resolucao.json`:

```json
{
  "verify_rejected_counts": {"pre_click": 0, "post_click": 1, "total": 1}
}
```

Confirma exatamente o contrato: coordenada plausível (passou no gate pré-clique — nenhum log
`[HIT-TEST] Implausível` desta vez), clique físico realmente ocorreu, `_verify_action_effect` não
confirmou nenhuma mudança real (heading estático, sem side effect), `[VERIFY_REJECTED]` **pós**-
clique disparou, e a cadeia terminou em `FAILED` limpo — **nunca** reportou `HEALED`. Nenhum outro
tier disponível depois do cognitivo (é o último antes de `FAILED`), então o resultado final da
transação foi falha reportada corretamente, sem falso-positivo.

---

## Cenário 3 — Rejeição PRÉ-clique (gate de plausibilidade)

**Verdict: CONFIRMADO — evidência orgânica já existente, não re-executado por instrução da
tarefa** (também apareceu de raspão, fora do alvo, na tentativa 1 descartada do Cenário 2 acima).

Citação de execução real anterior desta mesma sessão (`gate_sub07_20260714_222259_3/stdout.log`,
step `st_022`, range slider `disabled` no DOM real — bug de dado do site, não do framework):

```
[AEGIS RUNNER] [HIT-TEST] Implausível em (1098, 507): alvo='Ajustar um valor genérico de range para '5.45'' não corresponde ao elemento sob o ponto (tag='input', role='', texto='').
[AEGIS RUNNER] [VERIFY_REJECTED] Proposta de preenchimento da IA para 'input[type='range']' rejeitada pelo gate de plausibilidade (pre-clique, nenhuma acao executada).
[AEGIS_STEP] FAILED | st_022 | fill_chained | ...
```

Esse padrão se repetiu de forma consistente nas 21 execuções anteriores citadas no contexto da
tarefa (`SUCCESS=17, HEALED=4, FAILED=2, STOPPED=25`, falha sempre em `st_022`), e reapareceu ao
vivo (fora do alvo pretendido) na tentativa 1 do Cenário 2 nesta própria tarefa.

---

## Achados adicionais (fora do escopo de correção desta tarefa, só registro)

1. **Gap no 4º sinal de verificação quando o seletor original está 100% inexistente** (não apenas
   desatualizado): `_capture_click_effect_snapshot(page, selector)` (`aegis_runner/runner.py`,
   chamado a partir da linha ~1485 dentro de `_handle_unrecoverable_click`) sempre recalcula o
   `siblingClassFingerprint` resolvendo o `selector` **original** (sabotado), não a coordenada que
   a IA efetivamente clicou. Quando esse seletor nunca existiu, a resolução falha silenciosamente
   dos dois lados (antes/depois) e o sinal vira `"" == ""` sempre — cego especificamente para o
   caso de troca de classe ativa entre nós-irmãos já existentes (abas LATAM/EMEA/APAC), que é a
   motivação original documentada desse mesmo sinal. Reproduzido ao vivo na Tentativa 1 do
   Cenário 1 (log acima). Não é um bug de regressão desta sessão — é um limite estrutural do
   verificador nesse caso específico (seletor 100% morto + efeito é troca de classe CSS pura).
   Deixado como observação para avaliação futura, não corrigido aqui (fora do escopo: esta tarefa
   só mede/valida, não modifica `aegis_runner/*`).
2. A IA de self-healing (Gemini via OpenRouter, a julgar pelas mensagens `[COGNITIVE SUCESSO]`)
   não é determinística na localização visual — a primeira tentativa de cada cenário produziu uma
   proposta de coordenada diferente da segunda tentativa (mesmo prompt, mesma tela), incluindo uma
   confusão real entre o título de um painel e o cabeçalho de uma coluna de tabela com texto
   parecido. Isso é comportamento esperado de um modelo de visão, não um bug — mas reforça por que
   o gate de plausibilidade pré-clique existe.

## Artefatos gerados (preservados, nada apagado do projeto original)

- `C:\Projetos\TesteFimm\tests\cenario_principal_sabotage1\` — Cenário 1 (script, 2 execuções,
  screenshots, `reports/historico_passos.json`, `reports/telemetria_resolucao.json`,
  `run_log.txt`/`run_log2.txt`)
- `C:\Projetos\TesteFimm\tests\cenario_principal_sabotage2\` — Cenário 2 (script de reconhecimento
  + script de sabotagem, 2 execuções, `recon_fx_desk.html`/`.png`, screenshots,
  `reports/historico_passos.json`, `reports/telemetria_resolucao.json`, `run_log.txt`/`run_log2.txt`)
- `C:\Projetos\TesteFimm\tests\cenario_principal\` — **projeto original, intocado** (nenhum
  arquivo lido nele foi modificado; usado só como referência de seletores/estrutura para escrever
  os scripts de sabotagem acima).

## Veredito final

| Cenário | Descrição | Veredito |
|---|---|---|
| 1 | LLM resolve COM verificação pós-clique (`HEALED`, `healing_method="visual_ai"`) | **Confirmado ao vivo** (`st_005`, 2ª tentativa) |
| 2 | Rejeição PÓS-clique (`_verify_action_effect` reprova depois do clique físico já ter ocorrido) | **Confirmado ao vivo** (`sab_002_static_heading`, 2ª tentativa) |
| 3 | Rejeição PRÉ-clique (gate de plausibilidade, nenhuma ação física) | **Confirmado** — evidência orgânica já existente (`st_022`, 21 execuções anteriores) + reaparição ao vivo na tentativa 1 descartada do Cenário 2 |
