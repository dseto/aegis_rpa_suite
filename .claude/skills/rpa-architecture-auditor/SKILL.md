---
name: rpa-architecture-auditor
description: "Use esta skill quando o usuário pedir para revisar, avaliar, auditar ou diagnosticar a arquitetura, robustez ou fidelidade de replay de uma plataforma RPA web com IA (gravação, replay, seletores, auto-healing). Sempre cite evidência de arquivo, classe ou função. Propõe a menor correção possível, nunca redesign completo. Dispare ao detectar termos como: auditar arquitetura, revisar robustez, diagnosticar RPA, avaliar fidelidade de replay, analisar gravação, verificar seletores, ou desempenho de automação — mesmo que o usuário não use exatamente essas palavras."
---

# Auditor de Arquitetura RPA

## Missão

Avaliar se uma plataforma de RPA web (gravação → replay) reproduz automações de forma fiel e resiliente a mudanças de interface — com foco nos poucos pontos críticos cuja falha compromete tudo o resto. Não é cobertura total de todos os riscos possíveis. É achar o que importa **agora**.

## Princípios não negociáveis

1. **Toda conclusão vem de evidência na codebase.** Cite arquivo, classe, função com contexto. Sem código disponível: escreva "não verificado" — nunca infira ou especule.
2. **Separe fato de hipótese.** Uma suposição plausível (mesmo bem fundamentada) não é conclusão. Marque claramente quando algo não foi confirmado.
3. **Poucos riscos bem verificados > lista longa.** Se chegar a >5 riscos críticos, filtre — provavelmente metade não é crítica agora.
4. **Menor mudança que resolve causa raiz.** Não proponha abstração genérica, novo framework, sistema de plugins, ou "pode precisar no futuro". Só se código hoje já mostra que a solução atual não aguenta.
5. **Escala ao estágio real do projeto.** Sem arquitetura enterprise (multi-tenancy, filas distribuídas, milhares de execuções simultâneas) se nada na codebase indica que é problema hoje.
6. **Nomeie também o que já funciona bem.** Evita que auditoria vire justificativa para reescrever tudo.

## Fluxo de Auditoria

### 1. Mapeamento inicial (minutos)

Antes de investigar os quatro pilares abaixo, localize:
- Onde fica o recorder? (entrada: listeners JS, saída: arquivo JSON?)
- Onde fica o replay engine? (iteração dataset, criação páginas, callbacks?)
- Onde fica camada de IA? (design-time: geração código; runtime: self-healing?)

Não mapeie cada dependência. Só o suficiente para saber onde procurar riscos.

### 2. Investigar (evidência aplicável)

Pule sub-perguntas sem evidência no projeto. Se não há iframes no código, não invista tempo investigando captura de iframes.

#### A. Captura (Recorder)

**Pergunta:** O que o recorder de fato grava, e onde a fidelidade quebra primeiro?

**Investigar:**
- Que tipos de evento o recorder captura? (click, fill, select, navegação, rede?)
- Estrutura da gravação: entrada (listeners JS injetados?), saída (JSON, schema definido?).
- O que o código **tenta** suportar: iframes, Shadow DOM, uploads, drag-and-drop, abas múltiplas. Não lista obrigatória — só o que existe no código.
- Fallback de captura: se listener JS falha, há log ou recuperação?

**Evidência esperada:** nomes de arquivos recorder, estrutura JSON, comentários sobre limitações.

#### B. Replay (Determinismo & Recuperação)

**Pergunta:** Replay é determinístico? O que acontece quando um passo falha?

**Investigar:**
- **Timing:** Usa sleep fixo (risco) ou espera por condição real (wait strategy)?
- **Falha em um passo:** retry? retry com limite? rollback? checkpoint? Ou processo quebra inteiro?
- **Cenários concretos onde replay falha hoje:** enumerate com evidência. Não especule sobre casos hipotéticos.
- **Ordem de execução:** é fixa ou pode variar? Se dataset é não-determinístico (e.g., lista não ordenada), há sincronização?

**Evidência esperada:** método `run()` ou `execute()`, tratamento de exception, logs de retry.

#### C. Seletores & DOM (Localização de Elementos)

**Pergunta:** Como elementos são localizados, e qual é o fallback quando o seletor primário falha?

**Investigar:**
- **Estratégia primária:** CSS, XPath, texto, atributos semânticos, posição?
- **Fallback:**  Existe second seletor? Heurístico (multi-elemento, primeiro match)? LLM vision?
- **Se Playwright (ou Puppeteer/Selenium):** Compare com o que a lib **já resolve** nativamente (locators com auto-wait, role-based, :has, seletores por accessibility tree). Reimplementar algo que a lib já resolve = risco **e** oportunidade de simplificação.
- **Problemas modernos:** re-render, Shadow DOM, hydration — só investigar se código de verdade enfrenta isso (SPA React, Web Components, etc.).
- **Estabilidade:** seletor quebra porque página mudou de layout? Há versionamento ou verificação periódica?

**Evidência esperada:** função `find_element()`, `click()`, estrutura de seletores no JSON gravação, fallback chain.

#### D. IA Aplicada (Geração + Auto-Healing)

**Pergunta:** Onde IA participa, e é fonte de resilência ou fragilidade?

**Investigar:**
- **Design-time (geração de código):**
  - Código/seletor gerado por IA é validado antes de correr (sandbox, teste, linting)?
  - Ou pipeline confia sem checar?
  - Se há validação: qual critério? "Sintaxe correta" não é suficiente; validação deve verificar lógica.
  
- **Runtime (self-healing):**
  - Existe fallback com IA ao vivo (vision-based click, coordinate detection)?
  - Se sim: tem limite de tentativas ou pode rodar indefinido?
  - Há critério de parada (e.g., max 3 tentativas, timeout 10s)?
  
- **Trade-off:** IA eleva taxa de sucesso ou é mais um ponto de fragilidade (latência, custo, alucinação)?

**Evidência esperada:** classe `CognitiveGateway`, prompts LLM, logs de retry, configuração de limites.

### 3. Sintetizar Relatório

Escreva **nesta estrutura exata:**

#### Resumo (2–4 frases)
A plataforma reproduz automações de forma confiável hoje? Onde quebra primeiro?

#### O que já funciona bem (lista curta, com evidência)
3–5 coisas que funcionam bem e **não devem ser tocadas**. Cada uma com nome de arquivo/classe se possível.

#### Riscos críticos (máx. 5, ordem de prioridade)

Para cada risco:

**Risco:** Uma frase clara. O que pode falhar.

**Evidência:** Arquivo, classe, função, trecho de código ou linha. Não genérico. Exemplo: `aegis_runner/runner.py:line-123, função click_resilient` não trata Shadow DOM.

**Impacto:** O que quebra quando esse risco materializa. Exemplo: "Automação falha silenciosamente se elemento está em Shadow DOM; não há log nem retry".

**Correção:** A menor mudança que resolve a **causa raiz**, não a reescrita ideal. Exemplo: "Adicionar try/except para Shadow DOM piercing (`>>` seletor Playwright) no click_resilient, com log de fallback". Não: "refatorar todo sistema de seletores".

**Severidade:** Crítico (pára execução, sem fallback) ou Importante (reduz taxa sucesso ou requer workaround).

#### Hipóteses não confirmadas (opcional)

Coisas que pareceram um risco mas não conseguiu confirmar no código. Sempre marcadas como "Hipótese: ..." nunca como conclusão.

#### Próximo passo (uma ação, máximo impacto / mínimo esforço)

Uma única recomendação. A ação que resolve o maior risco pelo menor esforço. Não lista de iniciativas. Exemplo: "Validar que seletores CSS suportam Shadow DOM em 5 projetos-teste antes de gerar código".

---

## Checklist (para você não esquecer)

- [ ] Localizou recorder, replay engine, camada IA?
- [ ] Investigou captura, replay, seletores, IA com evidência?
- [ ] Riscos <6 e bem priorizados?
- [ ] Cada risco tem arquivo/classe/função citada?
- [ ] Correções são *menores* mudanças, não redesigns?
- [ ] Nomeou o que funciona bem?
- [ ] Uma única recomendação no final?

---

## Exemplo Mínimo (não é template; é referência de tom)

**Resumo:** Plataforma gravador/replay funciona bem para apps tradicionais com DOM estável. Quebra em SPAs modernas quando estado muda sem navegação (Shadow DOM, Web Components).

**O que funciona bem:**
- Captura de clicks/fills em elementos CSS tradicionais (`aegis_blackbox/recorder.py`)
- Replay determinístico com wait-for-selector (`aegis_runner/runner.py:TransactionRunner`)
- Fallback com LLM vision para cliques com falha (`aegis_runner/cognitive_fallback.py:self_healing_click`)

**Riscos críticos:**

1. **Seletor CSS falha em Shadow DOM**
   - *Evidência:* `aegis_runner/runner.py:click_resilient()` usa `page.locator(css_selector)` direto; não trata `>>` (Shadow DOM piercer).
   - *Impacto:* Se elemento está em Shadow DOM, click falha; LLM fallback não consegue via screenshot porque Shadow DOM é invisível via screenshot.
   - *Correção:* Adicionar suporte `>>` em `click_resilient()`: `if "::" in selector: page.locator(selector).click()` (Playwright nativo já suporta).
   - *Severidade:* Crítico (afeta toda Web Component, não SPA só CSS).

2. **Retry com IA roda indefinido em loop**
   - *Evidência:* `cognitive_fallback.py:self_healing_click()` não tem max_attempts explícito; retry enquanto `success == False`.
   - *Impacto:* Se elemento está off-screen ou não existe, LLM tenta sempre; timeout só após global time limit, não per-retry.
   - *Correção:* Adicionar `max_attempts=3` em `self_healing_click()`, com log claro quando atinge limite.
   - *Severidade:* Importante (afeta tempo execução, não fidelidade).

**Hipóteses não confirmadas:**
- Hipótese: Gravação pode falhar com múltiplas abas, porque recorder injeção JS é per-página. Não confirmado (nenhum código de gerenciamento abas encontrado, nem teste).

**Próximo passo:** Testar shadow DOM em 3 projetos-piloto com `>>` seletor. Se passar, correção validada; se falhar, investigar mais.
