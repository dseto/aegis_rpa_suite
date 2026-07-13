# Golden Fixture — real_portal_segura_001_v2

## O que é isto

Snapshot golden RICO do `plano_execucao.json` v2 (schema `"version": "2.0"`) produzido pelo
`aegis_sanitizer/sanitizer.py` **já commitado** no HEAD atual (não uma modificação de working
tree), rodando contra a MESMA gravação golden de `real_portal_segura_001` (`gravacao.json` +
`dicionario.json`, ambos copiados sem alteração daquela pasta — não dos artefatos atuais em
`projects/portal_segura/tests/001_teste/`, que já divergem por re-gravações posteriores).

Existe para servir de insumo obrigatório ao round-trip da demanda "code generator híbrido"
([SUBAGENTE 04]), que precisa de um plano v2 com a matriz completa de casos especiais
(`optional`, `parent+has_text`, `select` com coords de trigger/option, `weak_selector`,
Padrão Q, cliques de autocomplete com valor de negócio no seletor, steps suprimidos, etc.)
para validar que a geração híbrida de código cobre cada forma real do plano.

## Commit capturado

- **Hash:** `b5cc4e79f27fba399c66406201b5058cb03133a6`
- **Branch:** main
- Confirmado válido via `git cat-file -e b5cc4e79f27fba399c66406201b5058cb03133a6`.
- Neste HEAD, `aegis_sanitizer/sanitizer.py` já contém a lógica que emite
  `"version": "2.0"` em `plano_execucao.json` (linha 1600 do arquivo no momento da captura) —
  ou seja, o "sanitizer v2" mencionado na tarefa está commitado, não é uma alteração pendente
  de working tree. No momento da captura, `git status --porcelain` não mostrava nenhuma
  modificação (`M`) em arquivos `aegis_*` — apenas arquivos novos não rastreados (`??`), nenhum
  dos quais é importado pelo caminho de execução do Sanitizer.

## Data/hora da captura

`2026-07-13T02:49:30Z` (UTC, ambiente de execução do subagente que gerou este snapshot).

## Comando exato executado

Da raiz do framework (`C:\Projetos\aegis_rpa_suite`), em shell POSIX (Git Bash):

```bash
AEGIS_COGNITIVE_ENABLED=false python aegis_sanitizer/sanitizer.py --project-dir "<pasta_temporaria_isolada>"
```

Python usado: `Python 3.14.2`.

`AEGIS_COGNITIVE_ENABLED=false` é **obrigatório** para reprodução determinística: com o
Gateway Cognitivo ativo, `sanitize()` chama `refine_semantics_with_llm()` incondicionalmente,
reescrevendo `business_description` a cada execução via LLM. Confirmado no log real desta
execução:

```
[INFO] Gateway Cognitivo não configurado ou ativo. Ignorando refinamento semântico via LLM.
```

## Origem dos dados de entrada

Re-sanitização da `gravacao.json`/`dicionario.json` do golden real
(`.specs/golden/real_portal_segura_001/{gravacao.json,dicionario.json}`) com o Sanitizer v2
já commitado neste HEAD (`b5cc4e79f27fba399c66406201b5058cb03133a6`) — **não** os artefatos
atuais em `projects/portal_segura/tests/001_teste/` (que já divergem, `gravacao.json` tem
SHA-256 diferente do golden por re-gravação posterior; ver ponto 4 de "Working Agreements"
no `CLAUDE.md` da raiz).

## Procedimento

1. Criada pasta temporária isolada **fora do repositório** (scratchpad da sessão do
   subagente), contendo apenas:
   - `gravacao.json` (copiado de `.specs/golden/real_portal_segura_001/gravacao.json`)
   - `dicionario.json` (copiado de `.specs/golden/real_portal_segura_001/dicionario.json`)
   - `dataset_inicial.json` (copiado de `projects/portal_segura/tests/001_teste/dataset_inicial.json`,
     apenas para satisfazer a estrutura de diretórios esperada — o Sanitizer não lê este
     arquivo durante `sanitize()`)
   - `project.json` (copiado de `projects/portal_segura/tests/001_teste/project.json`, mesmo
     motivo)
2. Executado o comando da seção acima contra essa pasta temporária isolada.
3. Confirmado no log: 63 steps emitíveis, 4 suprimidos (`sup_001`–`sup_004`), 1 warning de
   token dinâmico hardcoded (Padrão Q removendo `'PRO-80935'` de um `has_text`).
4. Copiado o `plano_execucao.json` resultante para
   `.specs/golden/real_portal_segura_001_v2/plano_execucao.json`.
5. Confirmado `"version": "2.0"` no JSON copiado.
6. Pasta temporária apagada ao final.
7. `projects/portal_segura/tests/001_teste/` e
   `.specs/golden/real_portal_segura_001/` **nunca foram tocados** — apenas lidos.

## Checksum (SHA-256)

### Entradas (golden real, intocadas)

```
8398a0b197f6b4ba4bfdae008195efdf664af76dc6caefa108af356133e31263  gravacao.json (de real_portal_segura_001/)
29e4cb3fe5285062d28107d1f92cd6bcf0041f167a55048c9eb8708994dd5e86  dicionario.json (de real_portal_segura_001/)
```

### Saída (golden v2, neste diretório)

```
409213e5f829dbfa6be8d73ef2dbd74841aa20a4869f3b94bc3bcceae9c5036d  plano_execucao.json
```

## Schema resumido

- `"version"`: `"2.0"`
- `"test_dir"`: `"golden_run_v2"` (nome da pasta temporária desta execução — não um
  identificador estável do projeto; não-determinístico entre capturas, junto com
  `"generated_at"`, exatamente como documentado em `real_portal_segura_001/META.md`)
- `"total_steps"`: `63` (steps emitíveis; existem mais 4 entradas `sup_*` suprimidas no array
  `"steps"`, totalizando 67 entradas)

## Confirmação

Estes são os artefatos (`plano_execucao.json`) gerados pelo Sanitizer v2 já commitado
(commit `b5cc4e79f27fba399c66406201b5058cb03133a6`) rodando contra a gravação golden real
(`real_portal_segura_001`), com o Gateway Cognitivo desativado explicitamente
(`AEGIS_COGNITIVE_ENABLED=false`) para garantir determinismo.
