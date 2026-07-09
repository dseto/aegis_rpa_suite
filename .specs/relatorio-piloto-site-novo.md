# Relatório — Piloto Site Novo (Fimm Finance Corporate Backoffice)

**Data:** 2026-07-09
**Site:** `http://localhost:6174/login` (fornecido pelo usuário — React + Vite + Tailwind, sem Angular Material, sem CDK overlay)
**Referência:** plano `.specs/plans/melhorias-precisao-bots-gerados.md`, seção 8.2
**Projeto:** `projects/fimm_finance/tests/001_login_navigation`

## Fluxo gravado

Login (`admin`/`admin123`) + navegação entre abas de região no painel Cash Position (EMEA → APAC → LATAM). 6 passos: 2 `fill`, 4 `click`. Gravação dirigida programaticamente via Playwright reaproveitando a classe real `AegisRecorder` (mesmo JS injetado, mesmo `record_action`) — não um formato de gravação paralelo.

Pipeline completo executado do zero, sem nenhum ajuste manual de seletor: gravar → sanitizar → validar → gerar → executar.

## Métricas

| Métrica | Resultado |
|---|---|
| % eventos com `fallback_selectors` capturados | 2/6 (33%) — só os 2 `fill` (id + placeholder, estratégias distintas únicas) |
| % steps `weak_selector` no plano | 0/6 (0%) |
| Taxa de sucesso na execução real | 100% (6/6) na versão corrigida; 0% na primeira tentativa (erro de setup meu, não do Aegis — ver abaixo) |
| Chamadas de self-healing cognitivo (LLM vision) | 0 na execução válida |
| `needs_review`/`HEALED` gerados | 0 |
| Falsos positivos `CLICK_NO_EFFECT` | 2/6 (33%) — `st_005` (APAC), `st_006` (LATAM) |

## Achados

### 1. Cascata de seletores funciona fora do Angular — mas fallback fica pobre em botões só-texto
Login (`#username`/`#password`, HTML semântico) capturou 2 candidatos cada (id + placeholder), Padrão Q/dedup aplicados corretamente. Os 4 cliques de navegação (`Sign in`, `EMEA`, `APAC`, `LATAM`) só tinham `:has-text(...)` disponível — sem `data-testid`, sem `id`, classes Tailwind genéricas não qualificam como estratégia estável. Zero fallback candidato para esses 4 eventos: **quando a única estratégia viável é texto, não há string alternativa pra oferecer como fallback** — limitação estrutural do site, não do framework, mas reduz o valor prático de M5 em apps que não usam `data-testid`.

### 2. ~~`weak_selector` não capturava ambiguidade~~ — CORREÇÃO: era diagnóstico errado meu, não bug
Achado original (agora invalidado): "os warnings do console indicam que os seletores de clique são ambíguos, mas confidence fica 70 sem virar weak_selector". **Investigação pós-fix revelou o erro**: os 3 avisos de ambiguidade eram sobre estratégias de **fallback descartadas** durante a busca de candidatos (ex.: `idStrategy`/`tagStrategy` tentadas e abandonadas por não serem únicas), não sobre o seletor **primário** realmente usado. Confirmado com Playwright real: `button:has-text('Sign in')`, `EMEA`, `APAC`, `LATAM` são **genuinamente únicos** na página (`count() === 1` cada). `confidence=70` sem `weak_selector` estava correto o tempo todo.

Implementei o fix mesmo assim (propagar `{selector, ambiguous}` de `makeAegisSelectorUnique` até `record_action`, rebaixando `confidence` quando o primário é realmente ambíguo) — é proteção legítima para quando isso ocorrer de verdade, e não regrediu nada (suíte 34+7 verde, re-teste no site real confirma `selector_ambiguous` continua `None`/false corretamente aqui, já que não há ambiguidade real). Mas não havia bug para corrigir neste piloto especificamente — autocrítica: deveria ter verificado a QUAL seletor o console.warn se referia antes de reportar como achado.

### 3. Falso positivo novo do sensor `CLICK_NO_EFFECT`: mudança de estado só-CSS não é detectada → CORRIGIDO
Clicar em "APAC" e depois "LATAM" **funcionou de verdade** (confirmado por screenshot: aba LATAM ficou ativa, tabela trocou de conteúdo) — mas o sensor logou `CLICK_NO_EFFECT` nos dois. Causa: os 3 sinais do sensor (URL, contagem de nós DOM ±2, contagem de overlays) não capturam uma troca de estado React que só muda `className` em elementos **já existentes**. Padrão comum em SPAs modernas (tabs/toggles via classe), ausente no Portal Segura (onde mudança de estado quase sempre envolve overlay CDK ou navegação).

**Corrigido:** adicionado 4º sinal (`siblingClassFingerprint`) — fingerprint de `className`+`aria-*` do elemento clicado e seus irmãos diretos, antes/depois do clique.

**Bug na v1 do fix, achado e corrigido antes de declarar pronto:** a implementação inicial usava `document.querySelector(sel)` dentro do `page.evaluate()` — mas seletores como `button:has-text('APAC')` são sintaxe **exclusiva do Playwright**, inválida para `querySelector` nativo (lança erro, capturado pelo try/catch, fingerprint sempre `''` nos dois lados = sinal nunca dispara). Confirmado ao vivo: 1ª tentativa de fix não mudou nada (ainda 2 falsos positivos). Corrigido trocando por `page.locator(selector).evaluate(...)` — Playwright resolve a sintaxe antes de rodar o JS. **Revalidado ao vivo: 0 falsos positivos** (6/6 sucesso, zero `CLICK_NO_EFFECT`).

### 4. Erro de setup encontrado e corrigido durante o piloto (não é bug do framework)
Primeira execução falhou com bot rodando contra o site **errado** (Portal Segura, `localhost:5173`) — confirmado por screenshot. Causa: eu criei `project.json` só na raiz do projeto (`projects/fimm_finance/project.json`), não dentro da pasta do teste (`projects/fimm_finance/tests/001_login_navigation/project.json`), que é de onde `TransactionRunner.__init__`/`run()` resolve a URL. Sem esse arquivo, o runner cai no fallback hardcoded (`runner.py` ~linha 1880, `http://localhost:5173/?e2e=true`). Corrigido criando o `project.json` no nível certo; segunda execução passou 100%. **Fora de escopo do framework** — erro de operação minha, mas documentado porque o fallback silencioso pra Portal Segura (em vez de erro explícito "URL não configurada") pode confundir outros usuários também.

**Corrigido também:** `runner.py` agora loga `[WARNING]` explícito sempre que cai nesse fallback hardcoded, em vez de seguir silencioso.

### 5. ~~sanitizer não persiste tradução semântica~~ — CORREÇÃO: também não era bug do sanitizer
Achado original (agora invalidado): revalidação falhava no login com `Preencha este campo` em `#username`, e eu atribuí a causa a uma falha de persistência do sanitizer. **Investigação mais funda revelou a causa real**: reproduzi o pipeline completo (gravar → sanitizar → validar → gerar → executar) do zero, numa pasta limpa, 2 vezes — em ambas, `sanitizer.py` renomeou `dataset_inicial.json` **e** `dicionario.json` corretamente (`username`→`usuario_login`, `password`→`senha_login`), o código gerado bateu com o dado, e o bot rodou 6/6 sem nenhum ajuste manual.

A causa real do sintoma: **`aegis_blackbox/recorder.py` sobrescreve `dicionario.json`/`dataset_inicial.json` com as chaves brutas da captura toda vez que uma gravação termina** (recorder.py, salvamento final — nunca fez merge com uma tradução semântica pré-existente). Eu regravei o fluxo do Fimm uma segunda vez (pra validar o fix do sensor) sem rodar sanitizer+code_generator de novo depois — isso resetou `dicionario.json`/`dataset_inicial.json` pras chaves cruas, enquanto o bot já gerado continuava esperando as chaves traduzidas da primeira sanitização. Mismatch operacional meu, não bug de persistência.

**Corrigido na causa raiz** (a pedido do usuário, "mesmo que fora da tarefa"): `recorder.py` agora carrega o `dicionario.json` existente antes de sobrescrever e casa cada campo novo pelo **seletor físico** (identificador estável entre gravações do mesmo elemento) contra os campos antigos — quando bate, reaplica automaticamente a chave semântica já traduzida (`usuario_login`) em vez da chave crua recém-capturada (`username`), sem precisar rodar Sanitizer de novo só por causa da regravação. O `[WARNING]` virou sinal **residual**: só dispara para campos que não deu para casar por seletor (campo genuinamente novo ou seletor mudou de verdade na página) — aí sim a tradução não tem como ser recuperada automaticamente.

Validado ao vivo: regravei o fluxo do Fimm por cima do projeto já sanitizado, **sem rodar Sanitizer depois** — zero warning, `dicionario.json`/`dataset_inicial.json` mantiveram `usuario_login`/`senha_login` sozinhos, bot rodou 6/6 imediatamente.

## Status final (pós-correções, 2026-07-09)

| Achado | Status |
|---|---|
| 1. Fallback pobre em botões só-texto | Limitação estrutural do site — sem ação (não há string alternativa a oferecer) |
| 2. `weak_selector` não capturava ambiguidade | Invalidado — não havia bug; fix de proteção implementado mesmo assim, sem regressão |
| 3. Falso positivo `CLICK_NO_EFFECT` | **Corrigido e revalidado ao vivo** (0 falsos positivos, 6/6 sucesso completo) |
| 4. Fallback de URL silencioso | **Corrigido** — warning explícito agora |
| 5. Sanitizer "perdia" tradução semântica | Invalidado — não havia bug no sanitizer; causa real era recorder sobrescrever silenciosamente. **Corrigido na origem** — recorder auto-preserva tradução semântica por seletor físico ao regravar |

## Recomendação

- `AEGIS_CLICK_EFFECT_REGISTER` pode considerar mudar de `false` para piloto ativo em projetos React — o falso positivo que motivava cautela (achado 3) está corrigido e revalidado; ainda recomendo manter `false` como default global até confirmar em mais 1-2 projetos reais antes de virar `true` por padrão.
