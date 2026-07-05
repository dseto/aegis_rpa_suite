# Self-Healing como Bug Rastreável + Retry-Antes-de-Healing para Passos Flaky — Design Document

**Status:** Backlog — não implementado, só desenhado
**Data:** 2026-07-05
**Risco:** Médio — toca `runner.py` (execução), `code_generator.py` (geração), schema de `plano_execucao.json` e `correcoes_acumuladas.json`
**Origem:** Pedido explícito do usuário após uma sessão de debugging onde self-healing por coordenada mascarou pelo menos 2 falhas reais (ver `.specs/handoff-autocomplete-select-nao-verificavel.md`) e flakiness documentada no playbook (`Padrão J — regra estendida`) continuou aparecendo de forma imprevisível.

---

## Motivação (evidência real desta sessão)

1. **Self-healing mascarando bug real, não só "salvando o dia"**: no bug de autocomplete marca/modelo (ver handoff), o clique por coordenada reportou `HEALED` (sucesso) mas não disparou o listener real do app-alvo, deixando `state.formValues.modeloVeiculo` vazio. O sintoma só apareceu 3 telas depois. Hoje, `HEALED` é só uma linha no `historico_passos.json` e um contador no resumo do Cockpit ("Healed: N") — ninguém é forçado a investigar *por que* aquele passo precisou de healing.
2. **Flakiness já catalogada, mas sem tratamento automático**: `aegis_mentor/skills/rpa-copilot-coder.md` (Padrão J, regra estendida) já documenta um bug real e nomeado ("st_034 do portal_segura — dropdown condicional não tinha renderizado a tempo em ~1 a cada N execuções"). Isso significa que a equipe **já sabe** que certos passos são inerentemente instáveis — mas hoje não existe lugar nenhum pra marcar isso de forma estruturada nem para reagir de forma diferente quando esse passo falha.

---

## Feature 1: Self-Healing vira automaticamente um item de backlog rastreável

### Problema

`_log_step(status="HEALED", ...)` em `aegis_runner/runner.py` grava o resultado no `historico_passos.json` e segue em frente. Não existe elo entre "esse passo precisou de healing" e o sistema de correções (`correcoes_acumuladas.json`) que já existe pro resto do framework. Um passo pode precisar de healing em 100% das execuções, silenciosamente, pra sempre — sem nunca virar um item de revisão.

### Solução

Sempre que qualquer caminho de self-healing tiver sucesso (`status="HEALED"` em qualquer `_log_step` — cobre `click_resilient`, `fill_resilient`, `click_chained`, `fill_chained`, `select_option_resilient`, `click_by_coordinates`), o runner grava automaticamente uma entrada em `correcoes_acumuladas.json` com um status novo: `"needs_review"`.

**Por que um status novo, e não reaproveitar `"pending"`**: `"pending"` hoje significa "correção proposta, com `proposed_fix` pronto, aguardando o Code Generator aplicar" — é isso que o filtro em `code_generator.py:347` reinjeta automaticamente na próxima geração. Uma entrada de healing NÃO tem `proposed_fix` nenhum ainda (ninguém investigou a causa) — injetar isso cegamente na próxima geração seria pedir pra IA "adivinhar" um fix sem causa raiz identificada, reproduzindo exatamente o problema que gerou o caos da Fase 4 nesta sessão (ver `.specs/handoff-*` desta mesma sessão sobre numeração de plano). `"needs_review"` fica **de fora** do filtro de reinjeção automática — só vira `"pending"` depois que um humano (ou QA) escreve o `proposed_fix` de verdade, do mesmo jeito que já acontece hoje no fluxo normal do Cockpit.

### Esquema da entrada

```json
{
    "id": "healing_<execution_id>_<step_id>",
    "timestamp": "<iso8601>",
    "execution_id": "<id da execução>",
    "step_id": "st_XXX",
    "action": "click_chained",
    "failed_selector": "<selector que precisou de healing>",
    "root_cause": null,
    "proposed_fix": null,
    "qa_insight": null,
    "healing_method": "coordinate | js_evaluate | visual_ai",
    "occurrences": 1,
    "status": "needs_review"
}
```

`healing_method` distingue qual camada de fallback resolveu (coordenada gravada, `page.evaluate` direto, ou IA visual) — ajuda a priorizar: healing por coordenada é o mais arriscado (não confirma efeito colateral real, ver Feature raiz desta sessão), healing por IA visual já reporta uma justificativa própria.

### Deduplicação

Antes de criar uma entrada nova, checa se já existe uma `needs_review` (ou `pending`/`resolved` — se já tem correção pra isso, não duplica) pro mesmo `(step_id, failed_selector)`. Se existir e for `needs_review`, só incrementa `occurrences` e atualiza `timestamp`/`execution_id` mais recente — não precisa virar uma lista crescente de N entradas idênticas por N execuções.

### Onde implementar

- `aegis_runner/runner.py`, dentro de `_log_step()` (ponto único onde todo status é gravado) — adicionar um branch: `if status == "HEALED": self._register_healing_for_review(step_id, selector, action, healing_method)`.
- Novo método `_register_healing_for_review` precisa saber o caminho do `correcoes_acumuladas.json` do teste atual — `TransactionRunner` já resolve `project_dir`/`test_dir` pra outros artefatos (`historico_passos.json`), reaproveitar o mesmo caminho.
- Cockpit (`aegis_cockpit/cockpit.py`, `/correcoes-status` e telas de correções) precisa aprender a listar/contar `needs_review` separado de `pending`/pendentes de aprovação — hoje o contador só sabe `pending/applied/failed/resolved` (ver `pending_count`/`applied_count`/etc. em `cockpit.py`).

### Risco / cuidado

- **Não pode disparar durante execução em massa sem limite**: se um teste roda 500 linhas de dataset e o MESMO passo precisa de healing em todas, a dedupe (occurrences++) evita 500 entradas, mas ainda assim escreve o arquivo 500 vezes (I/O). Considerar um throttle (só grava a cada N execuções, ou só na 1ª ocorrência de cada dia).
- Escrever em `correcoes_acumuladas.json` a partir do **runtime** (não só do fluxo design-time do Cockpit) é uma mudança de responsabilidade — hoje só o Cockpit escreve nesse arquivo (via endpoints HTTP). Precisa de lock/leitura-escrita segura se a Fase 5 puder rodar em paralelo a alguém mexendo no arquivo pelo Cockpit ao mesmo tempo (mesmo padrão de risco que já existe hoje pro `historico_passos.json`).

---

## Feature 2: Passos marcados como "flaky" tentam restart completo (até 3x) antes de acionar self-healing

### Problema

Hoje, todo passo tem a MESMA política de resiliência: tentativas normais → self-healing (coordenada/IA) → falha definitiva. Isso é ótimo pra falhas genuinamente estruturais (selector mudou, elemento não existe), mas ruim pra falhas **conhecidas como intermitentes** (Padrão J regra estendida: "dropdown condicional não tinha renderizado a tempo em ~1 a cada N execuções") — nesses casos, a ação certa não é "adivinhar via coordenada", é **tentar de novo do zero**, porque na maioria das vezes a re-execução simplesmente não bate na janela de corrida de novo.

### Solução proposta

1. **Marcação do passo como flaky** — novo campo booleano no `plano_execucao.json`:
   ```json
   { "step_id": "st_034", "type": "click", ..., "flaky": true }
   ```
   Quem marca: humano/QA via Cockpit (checkbox na tela de Passos, análogo ao fluxo de correções), OU automaticamente pelo próprio sistema quando a Feature 1 acumula `occurrences >= N` pra um mesmo passo (sinal de que healing constante = flakiness, não bug pontual).

2. **Runner respeita a marcação, com política invertida**: para um passo com `flaky=true`, o bot compilado passa `strict=True` (já existe esse parâmetro em `click_resilient`/`fill_resilient`/`click_chained`/`fill_chained` — hoje serve pra pular self-healing e falhar rápido) **nas primeiras 3 tentativas globais**, deixando a exceção propagar. Isso é capturado num nível ACIMA do passo individual — no laço de execução da transação (`TransactionRunner.run()`), não dentro do passo.

3. **Restart completo, não retry pontual**: como o app-alvo mantém estado cumulativo (wizard multi-tela — não dá pra "voltar" só um passo sem redigitar tudo de novo, confirmado nesta sessão), o restart precisa ser da **transação inteira daquela linha do dataset**: fecha a página/context atual, abre uma nova (mesmo padrão de isolamento que já existe — 1 página por linha), roda o `execute_scenario_default(page, row, runner)` completo de novo desde o passo 1.

4. **4ª tentativa libera self-healing**: se as 3 tentativas completas (com `strict=True` nos passos flaky) falharem TODAS no mesmo passo flaky, a 4ª tentativa roda com `strict=False` pra esse(s) passo(s) especificamente — aí sim self-healing entra como último recurso, do jeito que já funciona hoje.

### Arquitetura necessária

```
TransactionRunner.run()
  para cada row do dataset:
    flaky_attempt = 1
    while flaky_attempt <= 4:
        page = novo contexto isolado (fecha o anterior se existir)
        strict_para_flaky = (flaky_attempt <= 3)
        try:
            execute_scenario_default(page, row, runner, strict_flaky=strict_para_flaky)
            break  # sucesso, sai do while
        except FlakyStepFailure as e:
            if flaky_attempt == 4:
                registra falha definitiva (como hoje)
                break
            flaky_attempt += 1
            continue  # restart completo
        except Exception:
            # falha NÃO relacionada a passo flaky — comportamento atual, sem restart
            registra falha definitiva
            break
```

Pontos em aberto que essa arquitetura levanta (não resolvidos neste design, precisam de decisão antes de implementar):

- **Como o step individual sinaliza "essa falha é de um passo flaky, dispare restart" vs "essa falha é normal, só falhe"?** Proposta: nova exceção `FlakyStepFailure(Exception)`, levantada por `click_resilient`/etc. quando `strict=True` E o `step_id` da chamada está marcado `flaky=true` no plano (o runner precisaria ter acesso ao plano carregado em memória pra checar isso — hoje ele não lê `plano_execucao.json` diretamente, só recebe `step_id` como string solta vinda do bot compilado). Isso implica o `TransactionRunner` passar a carregar `plano_execucao.json` na inicialização (não parece ser feito hoje — checar antes de implementar).
- **`code_generator.py` precisa saber, ao gerar o código, quais steps são `flaky` pra decider se emite `strict=True` condicionalmente por tentativa** — isso é NOVO: hoje `strict` é fixo no código gerado (`True` ou `False`, não muda em runtime). Precisa virar algo como `strict=(runner.flaky_attempt <= 3 if step_is_flaky else False)`, ou o runner decide internamente sem o bot precisar saber (mais limpo: o runner já sabe quais step_ids são flaky, lendo do plano, e aplica a política sozinho, sem o bot gerado precisar de lógica condicional nova).
- **Custo de restart completo**: um teste de 60+ passos reiniciando do zero até 3x por causa de 1 passo flaky no meio é caro (tempo de execução × 3-4). Para datasets grandes (múltiplas linhas), isso pode multiplicar bastante o tempo total de uma Fase 5. Vale considerar um teto de tempo total, não só de tentativas.
- **Restart e efeitos colaterais no app-alvo**: reiniciar do zero pode não ser idempotente se o passo anterior já causou efeito no backend real (ex.: já criou uma proposta parcial). Precisa avaliar app a app — não é um problema do framework resolver sozinho, mas o design deveria alertar quem for configurar `flaky=true` sobre esse risco.

### Onde implementar (arquivos afetados)

- `aegis_sanitizer/sanitizer.py` — schema de `plano_execucao.json` ganha campo opcional `flaky`.
- `aegis_cockpit/` — UI pra marcar/desmarcar `flaky` por passo (tela de Passos).
- `aegis_runner/runner.py` — `TransactionRunner.run()` ganha o laço de restart; nova exceção `FlakyStepFailure`; runner passa a carregar `plano_execucao.json` (se ainda não carrega) pra saber quais `step_id` são flaky.
- `aegis_sanitizer/code_generator.py` — não precisa gerar lógica condicional se o runner decidir sozinho (opção mais limpa da lista de pontos em aberto acima); só precisa continuar passando `step_id` normalmente (já faz isso).
- `aegis_mentor/skills/rpa-copilot-coder.md` — documentar o novo comportamento como um padrão de resiliência (ex.: "Padrão R: Passos Flaky com Restart Automático"), pra manter o playbook como fonte única da lógica de resiliência do projeto.

---

## Como as duas features se conectam

Feature 1 (rastreio de healing) é o **sensor** — detecta automaticamente "esse passo é suspeito" sem precisar de um humano notar. Feature 2 (flaky retry) é a **reação automática** — mas precisa de uma marcação explícita (`flaky=true`) que, na prática, viria muitas vezes DA análise de uma entrada `needs_review` da Feature 1 depois que um humano confirma "sim, isso é intermitência, não bug estrutural" (distinção importante: nem toda falha que precisa de healing é flakiness — pode ser bug real, tipo o do autocomplete desta sessão, que healing não devia mascarar, e sim falhar rápido pra alguém investigar).

**Ordem de implementação sugerida**: Feature 1 primeiro (mais simples, self-contida em `runner.py` + schema de `correcoes_acumuladas.json`) — dá visibilidade real de quais passos SÃO flaky de fato, com dados de produção, antes de construir a máquina de restart da Feature 2 em cima de suposições.
