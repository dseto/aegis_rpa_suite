# Reflexão estratégica: o Aegis generaliza, ou é um catálogo infinito de exceções?

> Análise crítica via Fable (subagente, 2026-07-13), com pesquisa de mercado ao vivo + leitura de código. Motivada por dúvida legítima do dono do produto sobre viabilidade de escala do framework pra centenas/milhares de sites.

## 1. O que o código realmente mostra sobre generalização

### 1.1 Acoplamento a Angular Material — quantificado

Grep `mat-|cdk-` no core: **146 ocorrências em 18 arquivos**. Não é a contagem que importa — é o tipo:

- **Acoplamento tolerante (~40%)**: seletores Angular em lista OR com equivalentes ARIA genéricos (`runner.py:815,1266,1383/1409/1433`) — degrada graciosamente pra React com ARIA correto.
- **Acoplamento estrutural (~45%)**: só existe em Angular — reposicionamento de `.cdk-overlay-pane` (`runner.py:798`), trigger `mat-form-field .mat-select-trigger` como estratégia primária (`runner.py:1344`), heurística de grid `.mat-select-grid-trigger` — classe de UM portal específico, nem Angular padrão (`runner.py:1357-1367`).
- **Acoplamento a IDIOMA (~15%, pior que Angular)**: detecção de dropdown testa `/selecione/i` ou `/escolha/i` no texto (`recorder.py:158`; Padrão O). Portal Angular Material idêntico em inglês ("Select...") já quebra. **O framework hoje não é genérico pra web nem genérico pra Angular Material — é calibrado pra portais Angular Material em português brasileiro.**

### 1.2 Catálogo A-R (17 padrões) cresce por categoria ou por site?

11/17 genéricos de web, 3/17 Angular/CDK-específicos na essência, 3/17 conceito genérico mas detecção acoplada (idioma/portal). Mas o dado revelador é a **taxa de nascimento**: ~2-3 sites reais produziram 17 padrões + 11 tiers de fallback + ciclo M1-M5 inteiro + 1 gap ainda aberto. Cada padrão é uma cicatriz de UM incidente documentado ("bug real confirmado: st_034 do portal_segura", "falso positivo confirmado em produção" — citações literais do playbook). **~5-6 padrões novos por site, sem sinal de assíntota.**

**Contraponto justo**: piloto Fimm (React/Vite/Tailwind, stack diferente) passou 100%, zero self-healing, Ralph Loop 1/15 — mas fluxo trivial (2 fills, 2 clicks, 1 `<select>` nativo, zero widget customizado). **Conclusão honesta: Aegis generaliza bem onde a web ainda é HTML puro; onde é framework de componentes (custom select, autocomplete, grid, modal, date picker), cada família de UI exige seu próprio mini-catálogo — hoje só existe o de Angular Material + PT-BR.**

### 1.3 A trajetória desta conversa — dois problemas, não um

Os 4 buracos encontrados (correção de texto destruída → auditoria geral → autocomplete parcial → dataset mal modelado) são **o mesmo buraco por 4 ângulos**: o modelo de dados captura *estado final*, não *gesto*. Isso é **fechável** — decisão de modelagem única, corrigível trocando o modelo de captura.

O problema do catálogo (1.2) é de natureza diferente — **estruturalmente aberto**: replay por seletor exige adivinhar semântica de widget a partir do DOM, e o espaço de widgets customizados é aberto e adversarial. Nenhuma heurística fecha espaço aberto.

**São dois problemas, estratégias diferentes pra cada um.**

## 2. Mercado (pesquisa ao vivo 2026-07 + treinamento)

**RPA enterprise (UiPath etc.)**: mesmo problema nunca resolvido deterministicamente — UiPath, ~20 anos e milhares de engenheiros, lançou "Healing Agent" em 2025-26: seletor falha → IA analisa UI → substitui. **É a mesma arquitetura que o Aegis chama de cognitive fallback.** UiPath com smart selectors multi-âncora + computer vision nativa AINDA precisou disso — evidência forte de que o teto do puramente-determinístico é conhecido pela indústria inteira, e é mais baixo que "qualquer site".

**Codegen cru (Playwright codegen, Selenium IDE)**: mesma limitação de fidelidade do Aegis (valor final, não gesto) — não é defeito exclusivo do Aegis, é formulação padrão da categoria.

**Automação agêntica (achado mais importante da pesquisa)**: mercado NÃO ficou no extremo "LLM decide cada passo" — convergiu pra híbrido quase idêntico ao desenho do Aegis. Skyvern opera "learn-replay": LLM na exploração, compila em Playwright determinístico, cai pra LLM só na cauda longa, **grava a intenção por trás de cada ação como metadado pra recuperação não ser adivinhação cega**. Field guide 2026 cita Stagehand, Anchor, browser-use, Google Project Mariner como "4 implementações do mesmo insight: LLM em build-time, esqueleto determinístico cacheado, vision-LLM só na cauda longa". **A macro-arquitetura do Aegis (LLM design-time, determinístico runtime, fallback cognitivo opcional) não é aposta excêntrica — é o consenso emergente de mercado em 2026.** A diferença: Skyvern usa LLM na cauda longa COM verificação de intenção; Aegis proíbe isso por default e tenta cobrir a cauda longa manualmente — exatamente a parte que não fecha por catálogo.

**RPA low-code (Robocorp, PAD)**: mesma limitação de fidelidade, manutenção por site é queixa #1 histórica da categoria inteira (30-50% do TCO de um programa RPA).

## 3. A tensão central

3 objetivos: (a) zero-LLM runtime, (b) fidelidade comportamental total, (c) generalização pra qualquer site.

- **(a)+(b)**: compatíveis — fidelidade total é mais determinística, não menos.
- **(a)+(c)**: **par estruturalmente conflitante**. Generalizar sem modelo em runtime exige entendimento de widget todo pré-compilado — catálogo (aberto, evidência 1.2) ou ARIA (só sites bem-comportados). UiPath gastou 2 décadas e terminou com Healing Agent.
- **(b)+(c)**: compatíveis abrindo mão de (a) — é o computer-use puro.

**Veredito: 2 de 3 é o teto absoluto — mas o mercado achou a fronteira de Pareto real: não escolher 2, fatiar por PASSO.** (a) estrito nos passos onde determinístico é correto por construção (emitter híbrido já faz essa classificação em design-time — `classify_step` C1-C10), exceção controlada e verificada de (a) só na cauda longa. **O Aegis já tem ~80% dessa arquitetura construída** (gateway cognitivo, manifest de proveniência, Sensor F1). O que falta não é reescrita — é mudar o status do fallback cognitivo de "adivinhação envergonhada bloqueável por strict" pra "tier de primeira classe com verificação de pós-condição" (hoje self-healing visual clica e reporta HEALED sem confirmar — o falso-positivo do Padrão Q, `rpa-copilot-coder.md:264`, é exatamente essa falha).

## 4. Caminhos — nenhum descartado, preço na etiqueta

**Opção 1 — Continuar como está (catálogo aberto, zero-LLM estrito).** Ganha determinismo total. Custa: manutenção cresce com diversidade de UI (ilimitada), não com nº de sites. Só racional se sites-alvo forem sempre da mesma família — o que é a Opção 2 disfarçada.

**Opção 2 — Restringir escopo declarado: "portais corporativos Angular Material Brasil", fundo em vez de largo.** Ganha: honestidade produto-mercado, acoplamento atual vira feature, espaço de widgets Angular Material é FECHADO (biblioteca finita), nicho seguros/governo/bancos BR não é pequeno, heurística em português deixa de ser bug. Custa: abandona tese "qualquer site", risco de migração de stack do nicho. **Código já votou nela — 146 ocorrências `mat-|cdk-` são o produto dizendo o que já é.** Melhor razão evidência/esforço hoje.

**Opção 3 — Híbrido com verificação de pós-condição.** Runtime determinístico por default; quando falha, LLM propõe alvo e proposta só é aceita se pós-condição verificável passar (painel abriu? URL mudou? campo habilitou?) — capturável na própria gravação. Falhou pós-condição → FAILED limpo, nunca HEALED falso. Ganha: ataca a cauda longa que catálogo nunca fecha, alinhado ao consenso de mercado 2026, reaproveita ~80% do que já existe. Custa: quebra dogma zero-LLM (vira "zero-LLM no caminho feliz"), dado vai pro modelo nos passos de exceção, engenharia de pós-condição não é trivial. **Única opção que escala em diversidade de UI sem catálogo manual.**

**Opção 4 — Adotar ferramenta madura pra parte do problema.** (4a) harness agêntico open-source (browser-use/Skyvern) como motor de localização da Opção 3 — spike de 1 semana, compatível com Opção 3. (4b) migrar runtime pra UiPath/PAD, manter só captura/geração do Aegis — joga fora o runner, que é a parte mais testada e valiosa (isolamento por linha, sensores, auditoria — não existe pronto nos incumbentes nesse formato). (4c) virar consultoria — mata o produto.

**Opção 5 — Combinação recomendada pela evidência (sequencial):**
1. Agora: Opção 2 como posicionamento — declarar nicho, corrigir dentro dele os problemas *fecháveis* (modelo de captura gesto-based, dataset busca≠seleção — dívida de modelagem, não catálogo infinito).
2. Em paralelo, barato: instrumentar pós-condição na gravação (recorder já vê efeito de cada ação; grava sem mudar runtime). Deixa porta da Opção 3 aberta sem comprometer nada agora.
3. Quando/se demanda multi-stack for real: Opção 3, possivelmente via 4a, usando pós-condições já gravadas. Dogma vira: determinístico no caminho feliz, modelo verificado na exceção, FAILED limpo quando nem o modelo prova que acertou.

**O que a evidência NÃO sustenta**: continuar adicionando padrões com tese "qualquer site" — taxa de 5-6 padrões/site sem assíntota, precedente UiPath, convergência unânime do mercado agêntico pra "LLM na cauda longa" apontam na mesma direção. Cauda longa de widgets não fecha por enumeração manual — fecha por nicho (Opção 2) ou por modelo verificado (Opção 3). **Aegis está bem posicionado pra qualquer uma das duas — mal posicionado só pra tentar as duas negadas ao mesmo tempo (determinístico E genérico E sem catálogo que fecha).**

## Fontes (pesquisa web ao vivo, 2026-07-13)

- [UiPath Healing Agent — how it solves UI automation challenges](https://www.uipath.com/blog/product-and-updates/technical-tuesday-how-healing-agent-solves-ui-automation-challenges)
- [UiPath Healing Agent docs](https://docs.uipath.com/agents/automation-cloud/latest/user-guide-ha/what-is-healing-agent)
- [UiPath UI Automation platform](https://www.uipath.com/platform/agentic-automation/rpa/ui-automation)
- [The Complete Field Guide to Browser Harnesses in 2026](https://theairuntime.com/p/the-complete-field-guide-to-browser)
- [Skyvern Products — AI Agents & Workflow Builder](https://www.skyvern.com/products)
- [Browser Use vs Skyvern comparison 2026](https://findaichat.com/compare/browser-use-vs-skyvern)
- [Accelirate — UiPath agentic trends 2026](https://www.accelirate.com/uipath-ai-agentic-automation-trends-2026/)
