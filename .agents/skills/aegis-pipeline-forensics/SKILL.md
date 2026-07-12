---
name: aegis-pipeline-forensics
description: "Use esta skill quando o usuário suspeitar de dessincronia entre os artefatos das fases do pipeline Aegis RPA — dado capturado vs código gerado vs dataset real. Diagnóstico puramente forense (nunca corrige, só aponta onde a cadeia quebrou). Dispare ao detectar termos como: por que o bot lê o campo errado, o dado não bate com o gerado, isso funcionava antes o que mudou, o bot espera uma chave que não existe no dataset, verificar se o pipeline está sincronizado, diagnosticar por que a geração falha — mesmo que o usuário não use exatamente essas palavras."
---

# Diagnóstico Forense de Dessincronia — Aegis Pipeline

## Missão

Diagnosticar onde a cadeia de artefatos do pipeline Aegis (Record → Sanitize → Validate → Generate → Run) quebrou. Puramente read-only: aponta a dessincronia com evidência concreta, nunca corrige nem executa fases.

Quando um teste/projeto apresenta sintomas de dessincronia — "o bot tá lendo campo errado", "o dado não bate", "isso funcionava antes", "o bot espera uma chave que não existe no dataset" — sua tarefa é determinar EXATAMENTE onde a cadeia se partiu e por quê.

## Princípios não negociáveis

1. **Puramente diagnóstico.** Nunca edita, cria, ou sobrescreve nenhum arquivo. Só LÊ os artefatos existentes.
2. **Nunca executa fases do pipeline.** Sem rodar `recorder.py`, `sanitizer.py`, `code_generator.py`, etc. Só inspeciona outputs já existentes.
3. **Evidência concreta sempre.** Toda conclusão cita arquivo, linha, e trecho exato — nunca "provavelmente" ou "deve ser".
4. **Considera ações recentes do usuário primeiro.** Antes de acusar "bug no framework", verifica se o mismatch pode ter sido causado por uma re-gravação, reexecução, ou mudança manual posterior do usuário — consulta `.specs/licoes-aprendidas-melhorias-precisao.md` se existir.
5. **Reporta incompletude.** Se algum arquivo esperado não existe, reporta isso como parte do diagnóstico ("dataset_inicial.json não existe — pipeline não passou da Fase 1"), não trata como erro fatal.

## Fluxo de Diagnóstico

### 1. Levantamento (minutos)

Antes de investigar a cadeia de dessincronia, confirme com o usuário:
- Qual é o caminho da pasta do teste suspeita? (ex.: `projects/portal_segura/tests/001_teste`)
- Qual é o sintoma concreto? (ex.: "bot tá lendo campo chamado 'username' mas dataset tem 'usuario_login'")

Não mapeie cada dependência. Só localize os arquivos-chave que você vai ler:
- `gravacao.json` (saída do Recorder)
- `dicionario.json` (saída do Recorder/Sanitizer)
- `dataset_inicial.json` (dados de entrada)
- `plano_execucao.json` (saída do Sanitizer)
- `code/bot_producao.py` (saída do Code Generator)

### 2. Investigar — Cadeia de Artefatos

Siga esta ordem **exata** — ela reproduz a cadeia real do pipeline:

#### A. Gravação Bruta (`gravacao.json` — Saída do Recorder, Fase 1)

**O que verificar:**
- Quais **seletores** foram capturados nos eventos de `click`, `fill`, `select`?
- Quais **chaves de campo** aparecem nos eventos de `fill` (ex.: `fill|#username|admin123`)?
- Se houver eventos duplicados ou seletor danificado?

**Buscar:**
```json
"events": [
  {
    "type": "fill",
    "selector": "...",
    "value": "...",
    "field_name": "..."  // chave semântica capturada
  }
]
```

**Questão:** A gravação capturou o seletor certo? A chave semântica foi registrada?

#### B. Dicionário Estruturado (`dicionario.json` — Saída do Recorder, Fase 1/2)

**O que verificar:**
- Quais **chaves de campo** aparecem em `fields` (inputs) e `outputs` (outputs)?
- Qual é o **seletor associado** a cada chave? (campo `selector`)
- Todos os campos capturados em `gravacao.json` aparecem aqui?

**Buscar:**
```json
{
  "fields": {
    "usuario_login": {
      "selector": "[data-testid='username-field']",
      "type": "text",
      "observed_value": "..."
    }
  }
}
```

**Questão:** O dicionário tem as mesmas chaves e seletores que a gravação? Alguma chave foi renomeada ou perdida?

#### C. Dataset de Entrada (`dataset_inicial.json` — Dados usados na execução)

**O que verificar:**
- Quais **chaves** (column names) aparecem em cada linha do dataset?
- Cada chave que o bot vai ler existe aqui?

**Buscar:**
```json
[
  {
    "id": 1,
    "usuario_login": "admin",
    "email": "admin@test.com"
  }
]
```

**Questão:** O dataset tem as mesmas chaves que o dicionário? Se não, quais chaves faltam ou sobram?

#### D. Plano de Execução (`plano_execucao.json` — Saída do Sanitizer, Fase 2)

**O que verificar:**
- Quais **step_id** (IDs de passo) foram gerados?
- Cada step_id referencia um seletor válido?

**Buscar:**
```json
{
  "steps": [
    {
      "step_id": "step_001",
      "selector": "[data-testid='username-field']",
      "action": "fill",
      ...
    }
  ]
}
```

**Questão:** O plano contém o step_id que o bot vai referenciar depois?

**Nota — schema v2 (`plano_execucao.json` de alta fidelidade):** planos gerados pelo Sanitizer atual usam dois espaços de id disjuntos — `st_NNN` (steps emitíveis, `execution_hint` ausente/`"required"`/`"optional"`) e `sup_NNN` (steps suprimidos, `execution_hint: "skip"`, sempre com `step_role` + `suppression_reason`). Um `bot_producao.py` que referencia só `st_` é normal e esperado, não um sintoma de dessincronia — `sup_` ausente do código é o caso comum. Campos úteis para forense: `original_index` (posição no `gravacao.json` bruto, antes de qualquer merge/reordenação — rastreia um step até o(s) evento(s) físico(s) de origem), `merged_from`/`source_events` (lista de `original_index` absorvidos quando o step é resultado de um merge, ex.: cliques duplicados ou par abridor+opção de dropdown), e `sanitizer_class` (também presente nos eventos de `gravacao.json` em si — `role`/`keep`/`reason` — mostra por que um evento bruto foi classificado como ruído mesmo que nunca tenha sido fisicamente removido). Se o bot referencia um `step_id` que não existe no plano (nem como `st_` nem como `sup_`), isso é sempre um id alucinado pela LLM — não confundir com um `sup_` legitimamente suprimido.

#### E. Código Gerado (`code/bot_producao.py` — Saída do Code Generator, Fase 4)

**O que verificar:**

**5.1. Todas as chamadas `row.get("<chave>", ...)`:**
- Grep por padrão `row\.get\(["']([^"']+)["']` — extrai todas as chaves que o bot tenta ler
- Essas chaves existem em `dataset_inicial.json`?

**5.2. Todos os comentários âncora `# [PASSO N]`:**
- Grep por padrão `# \[PASSO \d+\]` — lista todos os passos comentados no código
- Grep por padrão `step_id=["']([^"']+)["']` — extrai todos os step_id referenciados em `click_resilient`, `fill_resilient`, etc.

**Buscar:**
```python
# [PASSO 1] Clica em campo de usuário
runner.click_resilient(
  selector="[data-testid='username-field']",
  step_id="step_001"
)

# [PASSO 2] Preenche com usuário
usuario_login = row.get("usuario_login", "")
runner.fill_resilient(
  selector="[data-testid='username-field']",
  value=usuario_login,
  step_id="step_002"
)
```

**Questão:** Todo `row.get("<chave>")` tem correspondência em `dataset_inicial.json`? Todo `step_id` existe em `plano_execucao.json`?

### 3. Comparações Cruzadas (a Cadeia)

Agora que leu os 5 artefatos, faça estas comparações **na ordem**:

1. **gravacao.json vs dicionario.json:**
   - Todos os seletores de `gravacao.json` estão em `dicionario.json`?
   - Todas as chaves de campo em `gravacao.json` estão em `dicionario.json` com o mesmo seletor?
   - Se não: dicionário foi gerado de uma gravação anterior ou foi truncado/corrupto.

2. **dicionario.json vs dataset_inicial.json:**
   - Todas as chaves em `dicionario.json.fields` existem como coluna em `dataset_inicial.json`?
   - Se não: dataset foi editado manualmente ou sanitizer não sincronizou corretamente.

3. **plano_execucao.json vs bot_producao.py:**
   - Todo `step_id` em `bot_producao.py` existe em `plano_execucao.json`?
   - Se não: plano é de uma geração anterior ou o bot foi editado manualmente.

4. **dataset_inicial.json vs bot_producao.py:**
   - Todo `row.get("<chave>")` em `bot_producao.py` existe em `dataset_inicial.json`?
   - Se não: bot foi gerado para um dataset diferente do que está em uso, ou dataset foi regravado sem rodar sanitizer/gerador.

5. **dicionario.json vs bot_producao.py:**
   - Todo `row.get("<chave>")` tem o mesmo seletor em `dicionario.json`?
   - Todos os seletores em `bot_producao.py` não estão "hardcoded" (exceto por fallback explícito)?
   - Se não: bot pode ter sido gerado de um dicionário diferente ou modificado manualmente.

### 4. Hipótese de Ação Recente do Usuário

**Antes de concluir "bug no framework"**, leia `.specs/licoes-aprendidas-melhorias-precisao.md` (se existir) procurando por:
- **Lição 1.2** ("Causa raiz exige comparar dado real"): verificar se o usuário rodou uma re-gravação sem rodar Sanitizer depois. A gravação nova pode ter seletores atualizados, mas o dicionário permanece no antigo.
- **Achado #6**: se o seletor mudou de verdade na página (app foi atualizado estruturalmente), a auto-preservação de chave semântica (do Recorder) falha silenciosamente — reaparece uma chave "crua" (ex.: `username` em vez de `usuario_login`) no dicionário novo.

**Se isso parecer o caso, reporte a hipótese junto com a evidência:**
- Ex.: "Re-gravação sem Sanitizer: `gravacao.json` novo tem seletor `[data-testid='user-field']` mas `dicionario.json` ainda referencia `[data-testid='username-field']` (antigo). Auto-preservação não casou porque seletor mudou. Próximo passo: rodar Sanitizer + Code Generator."

### 5. Reportar Dessincronia

Estruture o relatório **exata nesta forma**:

#### Resumo (2–3 frases)
A cadeia está sincronizada? Onde quebrou?

#### Artefatos disponíveis (lista de presença)
- [ ] gravacao.json
- [ ] dicionario.json
- [ ] dataset_inicial.json
- [ ] plano_execucao.json
- [ ] bot_producao.py

Se algum está faltando, reporta agora qual fase não foi completada ainda.

#### Dessincronia Detectada (máx. 5, ordem de onde está a "falha")

Para cada mismatch:

**Mismatch:** Uma frase clara. O que está fora de sincronismo.

**Evidência:** Nome do arquivo, trecho exato do JSON/Python. Exemplos:
- `dicionario.json: chave 'usuario_login' references seletor '[data-testid='username-field']'` (linha X)
- `dataset_inicial.json: coluna 'username' existe, mas 'usuario_login' não` (primeira linha de dados)
- `bot_producao.py: line 45, `row.get("usuario_login")` mas dataset não tem essa chave`

**Consequência:** O que falha em runtime se isso não for corrigido.

**Hipótese:** Qual artefato "virou para trás"? Gravação nova sem Sanitizer? Bot gerado de dataset antigo? Seletor mudou? Edição manual não documentada?

#### Ação Recomendada (uma única recomendação)

A menor ação que resolve o mismatch sem refazer a cadeia inteira. Exemplos:
- "Rodar Sanitizer sobre `gravacao.json` novo — vai resincronizar `dicionario.json` com seletores atuais"
- "Rodar Code Generator novamente — vai re-gerar `bot_producao.py` com as chaves corretas do `dataset_inicial.json` atual"
- "Comparar `dataset_inicial.json` com versão anterior (ou com .git) — detectar se foi editado manualmente fora da pipeline"
- "Se o seletor mudou na página de verdade, há warning em `gravacao.json` (fim do arquivo), procurar por 'auto-preservação não pôde'"

---

## Checklist (para você não esquecer)

- [ ] Usuário confirmou qual é o caminho do teste?
- [ ] Usuário descreveu o sintoma concreto?
- [ ] Leu os 5 artefatos (gravacao, dicionario, dataset, plano, bot)?
- [ ] Fez as 5 comparações cruzadas em ordem?
- [ ] Considerou hipótese de ação recente (releu `.specs/licoes-aprendidas-melhorias-precisao.md`)?
- [ ] Reportou com arquivo + linha + trecho concreto, não genérico?
- [ ] Máx. 5 dessincronia reportadas, bem priorizadas?
- [ ] Uma única ação recomendada no final?

---

## Exemplo Mínimo (referência de tom)

**Cenário:** Usuário: "Bot tá tentando ler 'usuario_login', mas não existe no dataset. Isso funcionava semana passada."

**Diagnóstico:**

**Resumo:** Dessincronia entre `bot_producao.py` (gerado para chave `usuario_login`) e `dataset_inicial.json` (que tem coluna `username`). Síndrome típica de re-gravação sem Sanitizer posterior.

**Artefatos:** Todos os 5 presentes.

**Dessincronia:**

1. **Mismatch:** `bot_producao.py` tenta ler `usuario_login` mas `dataset_inicial.json` não tem coluna `usuario_login`
   - **Evidência:**
     - `bot_producao.py:45: usuario_login = row.get("usuario_login", "")`
     - `dataset_inicial.json: ["id": 1, "aegis_scenario": "default", "username": "admin", ...]` (coluna é `username`, não `usuario_login`)
   - **Consequência:** Em runtime, `usuario_login` sempre é `""` (fallback); fill envia string vazia ao campo, erro de login.
   - **Hipótese:** Uma das:
     - Re-gravação feita desde a última geração → `gravacao.json` pode ter novo seletor → auto-preservação não casou se seletor mudou → `dicionario.json` perdeu tradução para `usuario_login`.
     - Dataset foi editado manualmente antes de re-executar (coluna renomeada de `usuario_login` para `username`).

2. **Mismatch:** `dicionario.json` tem chave `usuario_login` (do `bot_producao.py` antigo) mas `gravacao.json` novo registra chave bruta `username` (capturada agora)
   - **Evidência:**
     - `dicionario.json: "usuario_login": { "selector": "[data-testid='user-input']", ... }`
     - `gravacao.json: { "type": "fill", "selector": "[data-testid='user-input']", "field_name": "username", ... }` (chave crua, não semântica)
   - **Consequência:** Sanitizer vê discrepância entre nome capturado (`username`) e nome mapeado (`usuario_login`).
   - **Hipótese:** Seletor permaneceu o mesmo (`[data-testid='user-input']`), mas app foi regravado sem rodare Sanitizer depois — Sanitizer faria a auto-preservação pelo seletor e recuperaria `usuario_login`.

**Ação Recomendada:** Rodar Sanitizer (`python aegis_sanitizer/sanitizer.py --project-dir projects/portal_segura --test-slug 001_teste`) — vai resincronizar `dicionario.json` com `gravacao.json` novo, re-aplicando auto-preservação de chave semântica por seletor físico.

---

## Notas para Contexto de Lições Aprendidas

Se o projeto tem `.specs/licoes-aprendidas-melhorias-precisao.md`:

- **Lição 1.2** ("Causa raiz exige comparar dado real"): Não confie só no log de sucesso. Verifique o arquivo em disco depois de cada ação — re-gravações silenciosas podem desfazer trabalho anterior.

- **Achado #6** ("Auto-preservação de chave semântica"): Quando o seletor muda de verdade na página, a auto-preservação falha. Há um warning `[AEGIS]` ao final de `gravacao.json` que lista quais campos perderam a tradução semântica.

Se encontrar esses cenários, cite a lição no seu diagnóstico.
