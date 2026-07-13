---
name: aegis-live-pilot
description: "Use esta skill quando o usuário fornecer uma URL real de um site e pedir para pilotar, testar, validar ou executar o pipeline Aegis RPA Suite contra esse site. Dispara ao detectar termos como: pilotar com um site novo, testar o framework, validar Aegis contra um URL real, executar gravação+sanitização+geração+bot para um projeto novo, ou começar um fluxo RPA de verdade — mesmo que o usuário não use exatamente essas palavras. Nunca inventa URL nem site-alvo — sempre confirma com o usuário antes de começar."
---

# Piloto ao Vivo Aegis

## Missão

Orquestrar um piloto completo do framework Aegis RPA Suite (5 fases: Record → Sanitize → Validate → Generate → Run) contra um site real fornecido pelo usuário, medindo métricas reais de gravação, seletor robusto, e taxa de sucesso no bot gerado — entregando relatório estruturado com achados mensuráveis (não sintéticos).

## Princípios não negociáveis

1. **URL sempre do usuário.** Nunca inventa, acha ou assume um site-alvo. Se o usuário não fornecer, a skill para e pergunta explicitamente.
2. **Sem código inventado.** Seletores e fluxo vêm de sondagem real do site via Playwright (não escrito à mão). Eventos de gravação são reais (`AegisRecorder` com listeners JS, não JSON sintético).
3. **Duas camadas de `project.json` obrigatórias.** A raiz (`projects/<slug>/project.json`) E a pasta do teste (`projects/<slug>/tests/<test_slug>/project.json`) devem ter campo `url` correto. Ausência desse nível dispara fallback silencioso pro Portal Segura — não é erro aceitável.
4. **Sem mudanças no framework core.** Se encontra bug real em `aegis_*`, skill reporta e pergunta antes de corrigir — não expande escopo sozinha.
5. **Métricas reais, não estimadas.** Lê artefatos (gravacao.json, plano_execucao.json, historico_passos.json, screenshots) para medir % fallback_selectors, % weak_selector, taxa sucesso, healing methods. Se não conseguir medir, reporta "não mensurável" em vez de adivinhar.
6. **Navegador sempre Edge.** Nunca troca de `channel` — é o default do `AegisRecorder` e `TransactionRunner` já.
7. **Relatório estruturado.** Replica seções de `.specs/relatorio-piloto-site-novo.md`: Fluxo gravado, Métricas (tabela), Achados (numerados), Status final, Recomendação.

## Fluxo de Piloto

### 1. Entrada e confirmação (imediato)

- Recebe URL do site, descrição breve do fluxo (ex.: "login admin/admin123, depois navega LATAM→EMEA→APAC").
- **Pergunta ao usuário:** URL está online e acessível? Fluxo descrito é realista (sem assumir elementos que não existem)?
- Se resposta negativa ou indefinida, para e pede clarificação.

### 2. Sondagem do site (minutos)

- `curl -s -o /dev/null -w "%{http_code}"` no URL — confirma que site está no ar (code 200-399).
- Executa script Playwright headless pontual: para cada elemento do fluxo descrito (campo de login, botão, aba, dropdown), localiza via `page.locator(...)` com heurísticas realistas (id, placeholder, :has-text, role attribute). Registra seletores encontrados.
- Nenhum seletor é escrito manualmente — tudo descoberto via Playwright.evaluate() ou locator.count().

### 3. Estrutura de projeto Aegis (antes de gravar)

Cria:
```
projects/<slug>/
├── project.json              # metadata do projeto
└── tests/<test_slug>/
    ├── project.json          # CRÍTICO: URL da fase 5 lê daqui
    ├── dataset_inicial.json  # dados de entrada (1 linha = 1 fluxo)
    └── dicionario.json       # tradução semântica (username → usuario_login)
```

Ambos os `project.json` têm campo `url` apontando pro site-alvo. **Esta é a blindagem contra fallback silencioso.**

### 4. Geração do driver de gravação parametrizado (antes de gravar)

Cria script Playwright em `scratch/record_<slug>_pilot.py` que:
- Instancia `AegisRecorder(url=..., output_dir=..., auto_simulate=True, control_port=...)`
- Define `run_auto_simulation(page, update_scenario, record_annotation)` que reproduz o fluxo descrito (fill username/password, click sign-in, click abas, etc.)
- Chama `recorder.start()` — reaproveita listeners JS real do `AegisRecorder`, nunca fabrica gravacao.json à mão
- Aguarda gravação terminar, valida que `gravacao.json` foi criado com N eventos esperados

Nenhum seletor é hardcoded pro site específico — o driver carrega seletores descobertos na sondagem (passo 2).

### 5. Execução do pipeline (5 fases sequenciais)

#### Fase 1: Gravação (driver Playwright + AegisRecorder)
- Roda `scratch/record_<slug>_pilot.py`
- Valida saída: `gravacao.json` tem N eventos (fill/click), cada um com campos `selector`, `value`, `timestamp`, `fallback_selectors`
- Coleta métrica: `(# eventos com fallback_selectors) / N`

#### Fase 2: Sanitização
- `python aegis_sanitizer/sanitizer.py --project-dir projects/<slug>/tests/<test_slug>`
- Valida saída: `relatorio.md`, `gravacao.json` reescrito sem eventos duplicados

#### Fase 3: Validação de dataset
- `python aegis_sanitizer/dataset_validator.py --dataset projects/<slug>/tests/<test_slug>/dataset_inicial.json --project-dir projects/<slug>/tests/<test_slug>`
- Valida que dados de entrada batem com dicionário semântico

#### Fase 4: Geração de código
- `python aegis_code_generator/code_generator.py --project-dir projects/<slug>/tests/<test_slug>`
- Valida saída: `bot_producao.py` (com `# [PASSO X]` comentários) e `skills_lib.py`
- Lê `plano_execucao.json`: coleta métrica `(# steps com weak_selector) / N`

#### Fase 5: Execução do bot
- `python projects/<slug>/tests/<test_slug>/code/bot_producao.py` (ou caminho correto conforme gerador)
- Valida saída: `historico_passos.json` e CSV com status de cada passo
- Calcula: taxa de sucesso `(# steps SUCCESS) / N`, # passos `HEALED`, # `needs_review`, # falsos positivos `CLICK_NO_EFFECT` (comparando screenshot com resultado esperado)

### 6. Hipóteses de causa própria (antes de reportar erro)

Se qualquer fase falha, checagem obrigatória:
- Site ainda online? Rodá-lo novamente com `curl`
- URL em `project.json` está certa? Validar arquivo explicitamente
- É segunda gravação do mesmo projeto? Verificar se campos novos não têm match por seletor físico (warning no log do recorder)
- Backend mudou de porta ou resposta? Checkar screenshot da página capturada vs esperado

Só depois dessas checagens, reporta como "bug do framework".

### 7. Coleta de métricas reais

Lê artefatos finais (não estima):
- `gravacao.json`: % eventos com `fallback_selectors` não vazios
- `plano_execucao.json`: % steps com `weak_selector=true`, distribuição de severidade
- `historico_passos.json`: status de cada step, healing_method se aplicável
- Screenshots em `projects/<slug>/tests/<test_slug>/screenshots/`: classifica `CLICK_NO_EFFECT` como falso positivo ou verdadeiro (comparando antes/depois visual)

### 8. Relatório final

Escreve `.specs/relatorio-piloto-<slug>.md`. Estrutura exata:
- **Data, Site, Referência (plano), Projeto**
- **Fluxo gravado** (descrição dos passos executados, quantidade eventos)
- **Métricas** (tabela com: % fallback_selectors, % weak_selector, taxa sucesso, healing, CLICK_NO_EFFECT, etc.)
- **Achados** (lista numerada com contexto real, não especulativo)
- **Status final** (tabela: Achado | Status; qual foi corrigido, qual é limitação estrutural, qual foi falso)
- **Recomendação** (uma ação de máximo impacto / mínimo esforço)

### 9. Limpeza

- Remove arquivos de debug temporários (pastas de teste exploratório, screenshots intermediárias)
- Mantém: projeto gerado em `projects/<slug>/tests/<test_slug>/` + relatório em `.specs/relatorio-piloto-<slug>.md`
- Remove `scratch/record_<slug>_pilot.py` (temporário)

## Guardrails Executáveis

- ✗ NUNCA modifica código em `aegis_*` sem confirmar antes.
- ✗ NUNCA inventa URL ou site-alvo.
- ✗ NUNCA fabrica gravacao.json sintético — sempre reutiliza `AegisRecorder` real.
- ✗ NUNCA requer 100% sucesso do bot gerado — entregável é relatório com métricas reais.
- ✗ NUNCA cria arquivos fora de `projects/`, `scratch/`, `.specs/`.
- ✓ Sempre confirma URL com usuário.
- ✓ Sempre cria ambas as camadas de `project.json`.
- ✓ Sempre mede métricas reais (lê artefatos, não estima).
- ✓ Sempre reporta achados com evidência (linha de arquivo, valor observado).

## Checklist (para não esquecer)

- [ ] Confirmou URL com usuário?
- [ ] Verificou que site está online?
- [ ] Sondou elementos do fluxo via Playwright real?
- [ ] Criou `project.json` em AMBOS os níveis (raiz e teste)?
- [ ] Driver de gravação é parametrizado (não hardcoded)?
- [ ] Todas 5 fases rodaram sequencialmente?
- [ ] Checou hipóteses de causa própria antes de reportar erro?
- [ ] Coletou métricas reais dos artefatos?
- [ ] Relatório tem estrutura exata (modelo `.specs/relatorio-piloto-site-novo.md`)?
- [ ] Achados têm contexto + evidência, não especulação?
- [ ] Limpou temporários, manteve projeto + relatório?
- [ ] Uma única recomendação no final?

## Exemplo de Fluxo (referência, não é template)

**Usuário:** "Quero pilotar o Aegis contra um projeto React em `http://localhost:3000/app` — tem login (usuario/senha campos id), e depois navegação entre abas Dashboard → Reports → Settings."

**Skill:**
1. Confirma: "URL acessível? Site é React com esses campos? Fluxo é determínístico (não aleatório)?"
2. Sonda: descobre seletores de cada elemento via Playwright
3. Cria estrutura de projeto em `projects/react_app_001/tests/001_login_nav/`
4. Cria driver que instancia `AegisRecorder` com `auto_simulate=True`, roda login + 3 cliques de aba
5. Executa 5 fases: gravar (6 eventos), sanitizar (sem dedup necessário), validar (dataset bate), gerar bot, rodar bot (esperado 6/6 sucesso)
6. Coleta: 0% fallback (campos têm id), 0% weak_selector (todos seletores CSS únicos), 100% sucesso executando, 0 healing necessário
7. Reporta `.specs/relatorio-piloto-react_app_001.md` com tabela de métricas + constatação: "Framework funciona bem em React com DOM estável e data-testid", recomendação: "testar próximo contra Angular Material com CDK overlay"

---

## Notas Técnicas

- **AegisRecorder:** classe em `aegis_blackbox/recorder.py`. Parâmetros: `url`, `output_dir`, `auto_simulate=False`, `control_port=None`.
- **run_auto_simulation:** função legada em `aegis_blackbox/recorder.py` que recebe `(page, update_scenario, record_annotation)`. O driver injeita essa função antes de chamar `recorder.start()`.
- **Fallback de URL:** `TransactionRunner` em `aegis_runner/runner.py` (~linha 1925) lê URL de `project.json` dentro da pasta do teste. Sem ele, cai em hardcoded `http://localhost:5173/?e2e=true` (Portal Segura).
- **Modelos de relatório:** ver `.specs/relatorio-piloto-site-novo.md` — replica estrutura, não copia conteúdo.
- **Sem evals:** esta skill é draft-and-adjust. Nenhuma suíte de testes automáticos; feedback é piloto real com usuário.
