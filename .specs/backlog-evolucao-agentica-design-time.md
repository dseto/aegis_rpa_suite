# Backlog — Evolução agêntica em design-time (resposta à proposta APA)

> **Status: revisado 2026-07-20 pós-merge do Unified Target Descriptor (PR #2, main `8476360` + docs
> `4cfcf39`).** O UTD entregou o núcleo do que este backlog chamava de E1 (captura de
> `anchor`+`expected_effect` na gravação, propagação Sanitizer→Emitter→Runner, verificador
> `_verify_recorded_expected_effect`, validado live no Portal Segura com bot 1/15 zero-LLM).
> E1 foi reescopado para o **residual** que o UTD deliberadamente não fechou.
> Origem: análise (2026-07-20) da proposta "Cognitive Gateway → Agentic Process Automation (APA) +
> Self-Healing Avançado". Veredito da análise: **rejeitar APA em runtime** (colide com o decoupling
> design-time/run-time e com a doutrina Cauda Longa Verificada), **aproveitar direções em design-time**.
> Anti-goals registrados na Seção D para a discussão não reabrir do zero.
>
> Relação com `.specs/backlog-achados-falso-sucesso.pending.md`: B1 de lá apontava `expected_effect`
> gravado como "fix real" — o UTD entregou a **infraestrutura** disso, mas **não fechou B1** (ver E1
> abaixo: o verificador nunca rejeita, só confirma-ou-cai-no-genérico). Este backlog detalha o caminho
> construtivo; aquele registra os buracos abertos.

---

## E. Itens com retorno real (ordem de prioridade)

### E1 — Residual do `expected_effect`: fechar B1 de fato  🔴 reescopado pós-UTD

**O que o UTD já entregou (não refazer):** captura na gravação (`computeGeometricAnchor`,
`captureSnapshot`/`computeSnapshotDelta` em `JS_MINIMAL_LISTENERS`), propagação aditiva pelo plano
(`build_step_from_event` → `_serialize_plan_step`), emissão como kwargs opcionais
(`anchor=`/`expected_effect=`/`viewport=`), tier 2.95 `anchor_geometry` (resolve, nunca clica; HEALED
só com efeito verificado; mesmo seletor no baseline/confirmação), e o verificador
`_verify_recorded_expected_effect` (OR-match: `url_changed`, `dom_delta`/`overlay_delta` mesmo sinal,
`new_visible_text`). Retrocompat total confirmada.

**O que continua aberto — o residual É este item:**

1. **B1 não fechou.** Por contrato, `_verify_recorded_expected_effect` **nunca rejeita** — sem match,
   cai nos sinais genéricos (decisão correta para não reabrir o falso-negativo com re-clique). Mas
   isso significa que o cenário B1 (churn ambiente na janela de polling, ação real bloqueada) **ainda
   fecha `SUCCESS` identity**: o piso continua sendo o sinal genérico. Residual proposto, na linha da
   mitigação interina do B1 — **aceitar-mas-marcar, nunca re-clicar**:
   - Quando o passo TEM `expected_effect` gravado e o efeito específico NÃO disparou (aprovação veio
     só do genérico), estampar `verify_result="generic_only_expected_missing"` na telemetria e
     registrar `needs_review` via Sensor F1. Zero mudança de control-flow — só auditabilidade.
   - Idem no caminho identity (`_detect_click_no_effect`): hoje o `expected_effect` participa da
     verificação dos tiers de healing; avaliar estampar a mesma marca quando o identity aprova sem o
     efeito esperado gravado. **Armadilha B1 vale integralmente**: marcar, jamais rejeitar/re-clicar.
2. **Gap conhecido do UTD** (documentado no CLAUDE.md): o trigger tier de `select_option_resilient`
   não foi validado positivamente contra um `mat-select` Angular Material real — a gravação do piloto
   parou antes da tela de dados do veículo. Exatamente a classe `st_023`/`st_026` que motivou o tier.
   Fechar com gravação nova do Portal Segura cobrindo a tela + run live com seletor primário quebrado.
3. **Cobertura de eleição de âncora em campo.** Piloto exercitou `label_for`/`nearest_stable_text`.
   Estratégias restantes (`aria-labelledby`, label ancestral) só têm teste unitário — validar num
   piloto de site não-Angular (política da skill `aegis-live-pilot`: URL sempre fornecida pelo usuário).

**Critério de aceitação (revisado):** (1) cenário B1 reproduzido via fault-injection deixa **rastro
auditável** (`generic_only_expected_missing` + `needs_review`) mesmo fechando SUCCESS; (2) run live
com `mat-select` real resolvido pelo trigger tier com `HEALED`/`anchor_geometry` verificado; (3) gate
de regressão (Portal Segura 3×) segue 3/3.

---

### E2 — Fechar o loop Sensor F1 → correção cirúrgica automática (Cockpit)  🟠 agora o maior item aberto

**O que é:** hoje a cadeia para no meio: healing em runtime registra `needs_review` em
`correcoes_acumuladas.json` (Sensor F1), e um humano precisa acionar a correção cirúrgica na mão.
Evolução: o Cockpit, ao acumular entradas `needs_review` de uma execução, dispara automaticamente
(a) `diagnose_failure` multimodal do `CognitiveGateway` sobre o screenshot/contexto da entrada,
(b) o fluxo de correção cirúrgica existente (âncoras `# [PASSO X]`, Ralph Loop, `step_validator`,
restore anti-drift do manifest) com o diagnóstico como insumo, e (c) apresenta o **diff pronto** para
aprovação humana — humano aprova/rejeita, nunca escreve.

**Por que tem retorno:** é 80% do benefício que o pitch APA chama de "self-healing sem intervenção do
suporte", com zero do risco — a IA reescreve o **código-fonte versionado do bot** (validado, gated,
auditável), não a execução ao vivo. Reduz o tempo entre "healing caro escalou em produção" e "bot
corrigido rodando determinístico de novo", que é exatamente a métrica que o `telemetria_resolucao.json`
já mede (taxa de resolução por tier — quanto mais `identity`, melhor).

**O UTD deixou este item mais rico e mais barato:**
- Entrada `needs_review` com `healing_method="anchor_geometry"` já carrega o **fix quase pronto**: o
  seletor primário quebrou, mas a âncora resolveu — a correção cirúrgica óbvia é promover o seletor
  resolvido pela âncora (ou a própria âncora) a seletor primário do passo. Classe de correção
  **determinística** (sem LLM) para o caso mais comum, com `diagnose_failure` reservado aos casos sem
  âncora. Baixa o custo médio do loop.
- Se o residual E1.1 for feito antes, entradas `generic_only_expected_missing` também alimentam o
  loop — o Cockpit passa a enxergar passos suspeitos de falso-sucesso, não só falhas curadas.

**Escopo mínimo viável:**
1. Endpoint/rotina no Cockpit: varrer `needs_review` pós-execução, agrupar por `(action, failed_selector)`.
2. Rota determinística primeiro: `healing_method` com resolução estrutural (`anchor_geometry`,
   `fallback_selectors`, `parent_has_text_reduced`) → proposta de promoção de seletor sem LLM.
3. Demais casos: montar contexto (screenshot, `healing_method`, seletor que falhou, o que resolveu)
   → `diagnose_failure` → proposta de correção estruturada.
4. Reusar o fluxo surgical existente do `code_generator.py` sem fork — a novidade é o gatilho e o
   insumo, não o mecanismo.
5. Gate humano obrigatório no diff (aprovação vira `pending` → pipeline atual segue igual).

**Dependências/riscos:**
- `aegis_cockpit/cockpit.py` **não tem suite de testes** (gap conhecido, causou regressão real) —
  extrair a rotina para módulo testável fora do handler HTTP.
- Regra 5 do Working Agreements: erro/correção sem `step_id` concreto é invisível ao scoped-edit —
  o diagnóstico automático precisa sempre resolver a entrada `needs_review` para um `step_id` antes
  de disparar a correção, ou vira Ralph Loop queimando tentativas.
- Custo LLM em design-time é aceitável; cap de tentativas do Ralph Loop continua valendo.

**Critério de aceitação:** entrada `needs_review` real com `healing_method="anchor_geometry"` gera
diff de promoção de seletor aprovável no Cockpit sem LLM e sem intervenção manual além do aprovar;
passo corrigido volta a resolver como `identity` na execução seguinte.

---

### E3 — Handler determinístico de overlay não mapeado  🟡 menor esforço

**O que é:** o caso concreto que o pitch APA usa como motivação ("injeção de múltiplos pop-ups não
mapeados") não precisa de agente. Antes de a cadeia de recovery escalar para tier caro
(coordenada/cognitivo), um passo determinístico: detectar overlay presente que **não existia no
baseline do passo** (o snapshot já conta `overlays`), tentar a sequência padrão de dismiss —
`Escape` (já existe no tier 1), botão de fechar canônico (`[aria-label*=close]`, `.close`, `×`) —
logar o dismiss na telemetria e re-tentar o gesto original **uma vez**.

**Ganho pós-UTD:** o `expected_effect` gravado dá um discriminador que não existia — se o passo
gravado NÃO produziu `overlay_delta` positivo na gravação, um overlay novo no momento da falha é
**comprovadamente não mapeado** (não faz parte do efeito esperado do fluxo), o que torna o dismiss
seguro por construção em vez de heurístico. Passos cujo efeito gravado É abrir overlay ficam imunes
ao handler automaticamente.

**Dependências/riscos:**
- **Armadilha B1 vale aqui**: nunca disparar o dismiss no caminho identity (clique que funcionou e
  legitimamente abriu um painel seria "corrigido" fechando o painel). Handler só roda **dentro** da
  cadeia de recovery, quando o passo já falhou/`CLICK_NO_EFFECT`, e só sobre overlay **ausente no
  baseline daquele attempt** (per-attempt baseline já existe pós-fix do retry-loop).
- Dismiss é gesto físico → mesma disciplina de `_tier_baseline` (snapshot fresco pós-dismiss,
  pré-retry) para não fabricar o delta que aprova o próprio tier — lição do `_effect_confirmed` já paga.
- Variante "clique fora do overlay" descartada: risco de acertar elemento de negócio.

**Critério de aceitação:** harness de fault-injection (padrão do retry-loop) com overlay sintético
injetado pós-gravação: passo resolve com `healing_method="unmapped_overlay_dismissed"` + `needs_review`
via Sensor F1, sem escalar para tier cognitivo; overlay legítimo aberto pelo próprio clique (ou
previsto no `expected_effect` gravado) **não** é fechado.

---

## D. Anti-goals — rejeitados com fundamento (não reabrir sem fato novo)

### D1 — Agente que "reavalia o objetivo e adapta o fluxo" em runtime  ❌
Sem pós-condição possível: se o fluxo mudou, nada verifica que o objetivo de negócio foi atingido —
é o falso-sucesso elevado de "passo" para "processo". Destrói custo-zero-por-execução, latência
previsível, auditabilidade (`historico_passos.json`) e reprodutibilidade. Contexto de uso é sistema
de negócio em produção: rota improvisada em portal de billing é passivo, não resiliência. E o
histórico do projeto (saga do falso-`HEALED`: rubber-stamp, `_effect_confirmed`, retry-laundering)
prova ao vivo o que recovery não-verificado produz — a proposta pede remover o guarda-corpo que
custou semanas construir. **O UTD reforça o argumento:** a resposta certa para "layout mudou" se
provou ser MAIS dado gravado + verificação determinística (âncora + efeito esperado), não menos.

### D2 — Multi-agente com memória compartilhada em runtime  ❌
Aegis já é multi-agente onde erro é barato: geração (emitter determinístico + slots cognitivos +
Ralph Loop + plan-critics cross-model). Em runtime: custo e não-determinismo sem caso de uso
identificado. Se um caso de uso concreto aparecer, entra como item novo com pós-condição definida —
não como princípio.

### D3 — "Aprender continuamente" ajustando comportamento do bot em produção  ❌
Todo aprendizado passa pelo ciclo versionado: telemetria → `needs_review` → correção em código →
validação → gate de regressão → deploy. Bot que muda o próprio comportamento entre execuções sem
diff aprovado quebra o contrato de auditoria. E2 é a forma sancionada disso.

---

## Sequência sugerida (revisada pós-UTD)

1. **E1.2** primeiro — fechar o gap live do `select_option` trigger tier (gravação nova do Portal
   Segura até a tela do veículo + run com seletor quebrado). Pequeno, e valida o pedaço do UTD que
   motivou a feature.
2. **E1.1** em seguida — marca de auditoria `generic_only_expected_missing` (aditiva, sem control-flow;
   pré-requisito para o E2 enxergar suspeitas de falso-sucesso, não só healings).
3. **E3** em paralelo — isolado na cadeia de recovery, harness de teste já tem padrão, e agora com o
   discriminador `overlay_delta` do `expected_effect` gravado.
4. **E2** por último — maior superfície (Cockpit sem testes), e fica mais barato depois do UTD (rota
   determinística de promoção de seletor via `anchor_geometry`) e mais completo depois de E1.1.

Cada item, ao ser iniciado, vira plano próprio (`plan-critic` → backlog cirúrgico → execução), padrão
do pipeline de skills já em uso.
