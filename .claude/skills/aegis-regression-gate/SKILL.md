---
name: aegis-regression-gate
description: "Use esta skill quando o usuário pedir para 'rodar o gate de regressão', 'comparar com o baseline', 'validar que não quebrou nada', 'confirmar retrocompatibilidade do bot compilado', ou verificar regressão após mudanças no código do framework core (aegis_*). Dispara ao detectar termos: gate, baseline, regressão, retrocompatibilidade de bot, teste de referência, comparar métricas de execução — mesmo que o usuário não use exatamente essas palavras, se o contexto é validação pós-mudança no framework."
---

# Gate de Regressão — Aegis RPA Suite

## Missão

Verificar que mudanças no código do framework Aegis (módulos `aegis_*`) **não regrediram** o desempenho ou comportamento de um bot já compilado (sem regeneração). O gate roda um projeto/teste de referência N vezes, coleta métricas de execução, compara contra um baseline salvo em disco, e emite veredito **APROVADO** ou **REPROVADO**.

**Invariante crítico:** O bot roda **tal como compilado**, sem chamar `code_generator.py`. Isso prova retrocompatibilidade do runner com planos gerados em versões anteriores do framework.

## Princípios não negociáveis

1. **Nunca regenera o bot.** O gate testa especificamente o artefato compilado (`bot_producao.py`, `plano_execucao.json`) — se ambos fossem regenerados, não haveria como isolar regressão do framework de mudanças na geração de código.

2. **Nunca corrige nada sozinho.** A skill só mede, coleta e compara. Se reprovar, para e reporta. Não tenta consertar o bot, não inicia workflows de correção, não chama `code_generator.py`.

3. **Não modifica o projeto de referência, apenas o baseline.** Coleta de métricas e execução deixam o projeto intacto (os dados de execução vão para `reports/` e `screenshots/`, não sobrescrevem fontes). Apenas o arquivo de baseline recebe atualizações (novas seções anexadas, nunca sobrescrita).

4. **Navegador sempre MS Edge.** Usa `channel="msedge"` (padrão do `TransactionRunner`), nunca força outro browser. Variação de browser é fator de confusão para regressão.

5. **Confirma site no ar antes de começar.** Via `curl` (HTTP 200) para a URL configurada no projeto. Se site estiver offline, falha antes de desperdiçar tempo/recursos.

## Entradas esperadas

- **Caminho do projeto/teste de referência:** Default: `projects/portal_segura/tests/001_teste` (projeto de referência histórico deste repositório). Usuário pode customizar passando um path alternativo.
- **Nº de execuções:** Default: 3. Usuário pode pedir "5 vezes", "1 vez só", etc.
- **Arquivo de baseline:** Convenção: `.specs/plans/<nome-do-baseline>.md`. Procura por arquivos nesse diretório com padrão `*.baseline-*.md` ou exato `<nome-do-baseline>` se informado. Se não existir, cria um novo (primeira execução).

## Passos de Execução

### 1. Validação de Pré-Condições

- [ ] Confirma que o projeto-teste existe e contém `bot_producao.py`.
- [ ] Confirma que `plano_execucao.json` existe (plano de execução do bot).
- [ ] Confirma que `dataset_inicial.json` (ou `.csv` alternativo) existe.
- [ ] Confirma que a URL alvo (de `project.json`) está no ar (`curl -I`, HTTP 200 ou 3xx redirect, não 5xx/timeout).
- [ ] Se alguma condição falhar, reporta ao usuário e para.

### 2. Coleta de Métricas (N execuções)

Para cada execução (de 1 a N):

1. Cria um novo contexto de execução: novo diretório em `reports/` com timestamp (ex.: `reports/exec_20260709_143055_1/`).
2. Configura variáveis de ambiente necessárias (`AEGIS_EXECUTION_DIR`, `AEGIS_EXECUTION_ID`).
3. **Executa o bot:** `python <caminho>/code/bot_producao.py` — sem nenhuma regeneração.
4. Aguarda conclusão (não aborta por timeout — deixa o runner decidir seus próprios timeouts).
5. **Extrai métricas** do arquivo de relatório de execução:
   - `historico_passos.json`: taxa de sucesso de transações (nº de linhas com status final SUCCESS / total linhas dataset), contagem de passos com status `HEALED`, agrupados por `healing_method`.
   - `correcoes_acumuladas.json`: contagem de entradas ANTES e DEPOIS, filtradas por `status="needs_review"` (novas correções detectadas durante execução).
   - Logs de execução: detecção de `FlakyStepFailure` (padrão "Padrão R" — restarts de linha), contagem de restarts por linha, quantidade total de restarts.
   - Tempo total da execução (timestamp início/fim).
   - **Ponto de falha:** `failed_field` ou mensagem de erro final (útil para diagnosticar variação).

6. Registra as métricas em estrutura interna (não escreve em arquivo do projeto ainda).

### 3. Comparação com Baseline (se existir)

Se um arquivo de baseline já existe:

- Carrega a seção de "Baseline de Regressão" ou a última seção de gate anterior.
- **Critérios de aprovação:**
  - **Taxa de sucesso não pode CAIR.** Se baseline era 50%, novo gate pode ser 50% ou 60%, mas não 40%. Se baseline era 0%, novo gate pode ser 0% (não piorou).
  - **Nenhum novo TIPO de falha sistêmica.** Tipos conhecidos (ex.: "timeout no `.mat-row`", "self-healing cognitivo falhou em dropdown") podem reaparecer — isso é variância normal. Mas uma **nova classe de erro** (ex.: crash do runner, exceção Python não capturada, erro de import) que não aparecia no baseline = regressão (REPROVADO).
  - **Contagem de entradas `needs_review` em `correcoes_acumuladas.json` não pode CRESCER significativamente.** Tolerância: +1 entrada nova é normal (framework detectou algo novo); +3 ou mais = possível regressão (REPROVADO).
  - **Tempo total não pode DOBRAR.** Se média do baseline era 100s, novo gate pode ser até 150s (50% variação aceitável) — mas não 200s+.

- **Emite veredito:** `APROVADO` ou `REPROVADO` com motivo específico.

### 4. Anexa Resultado ao Baseline

Abre o arquivo de baseline existente (ou cria novo se não houver):

- **Se for primeira execução (criando baseline novo):** escreve cabeçalho com data/commit, tabela de métricas das N execuções, resumo médio. Termina com "Baseline capturado; próximas execuções serão comparadas contra este."
- **Se já houver baseline:** adiciona nova seção no fim do arquivo (ex.: "# Gate pós-<data-mudança>") com data/commit atual, tabela de N execuções, comparação ponto-a-ponto com seção anterior, e veredito (APROVADO/REPROVADO com justificativa).

**Nunca sobrescreve o histórico anterior** — o arquivo cresce apenas por append.

## Saídas

### Arquivo de Baseline
Caminho: `.specs/plans/<nome-do-baseline>.md`

Estrutura esperada (ver arquivo `melhorias-precisao-bots-gerados.baseline-001.md` como referência):
- Seção de cabeçalho com data, commit hash, ambiente
- Tabela de métricas por execução (taxa sucesso, restarts flaky, healed steps, correcoes_acumuladas, tempo, ponto de falha)
- Resumo de médias
- Observações
- Seção de veredito (APROVADO/REPROVADO)

### Saída para o Usuário
- Relatório conciso no console/chat, resumindo: nº de execuções, taxa média de sucesso, principais diferenças vs baseline (se houver), e **veredito final em MAIÚSCULAS: APROVADO ou REPROVADO**.
- Se REPROVADO, lista os critérios específicos que falharam (ex.: "taxa de sucesso caiu de 50% para 30%", "nova classe de erro detectada: ImportError em aegis_runner").

## Exemplos de Trigger

Usuário digita qualquer um dos seguintes (ou variações que o Claude entenda como equivalentes):
- "roda o gate de regressão"
- "compara com o baseline"
- "testa se quebrou o bot de referência"
- "valida retrocompatibilidade após mudança no runner"
- "confirma que as melhorias não regressaram nada"
- "gate — 3 vezes"
- "novo gate contra `projects/outro_projeto/tests/001`"

## Configuração de Exemplo

```bash
# Forma 1: usar projeto de referência padrão (portal_segura/001_teste), 3 execuções
/aegis-regression-gate

# Forma 2: especificar projeto customizado
/aegis-regression-gate --project-dir "projects/meu_projeto/tests/001_teste" --runs 5

# Forma 3: especificar baseline customizado
/aegis-regression-gate --baseline "meu-baseline-customizado"
```

## Ressalvas

- **M3, M5 e outras melhorias futuras:** Se o `plano_execucao.json` do projeto de referência foi gerado antes da implementação de uma melhoria (ex.: M3 = fallback_selectors, M5 = weak_selector), essa melhoria não será exercitada neste gate. Requer re-gravação (Fase 1) e regeneração (Fase 4) para produzir um plano com os novos campos. O gate notificará se campos esperados estão ausentes.
- **Flakiness pré-existente:** A baseline documenta variância natural do site/ambiente já presente antes de qualquer mudança do framework. Futuras variações "no mesmo ponto" (ex.: dropdown que falha em execução 1, sucesso em 2, falha em 3) não são atribuídas a regressão — são esperadas. O critério é **novo tipo de falha**, não repetição de falha conhecida.
- **Sem regeneração = sem teste de M1/M4:** O gate roda o bot compilado. Se o bot foi gerado antes de M1 (error_message_selector) ou M4 (surgical correction), essas melhorias não serão ativas. O gate notificará isso na seção de ressalvas.

---

## Checklist (para você não esquecer)

- [ ] Confirmou que projeto-teste existe (bot_producao.py, plano_execucao.json, dataset)?
- [ ] Confirmou que site alvo está no ar (curl)?
- [ ] Rodou N execuções **sem regenerar o bot**?
- [ ] Extraiu métricas de cada execução (sucesso, restarts flaky, healed, correcoes, tempo)?
- [ ] Comparou com baseline (taxa sucesso, novo tipo falha, estabilidade correcoes_acumuladas, tempo)?
- [ ] Emitiu veredito claro (APROVADO/REPROVADO com motivo)?
- [ ] Anexou resultado ao arquivo de baseline (nunca sobrescreve histórico)?
- [ ] **Não regenerou o bot e não tentou consertar nada sozinho?**
