# Golden Fixture — real_portal_segura_001

## O que é isto

Snapshot golden do comportamento ATUAL (pré-refatoração) do `aegis_sanitizer/sanitizer.py`,
rodado contra uma cópia isolada dos artefatos reais do projeto `portal_segura/tests/001_teste`.
("V2" no banner impresso em runtime pelo próprio script é o nome interno da versão do
Sanitizer, não relacionado ao "pré-refatoração" deste snapshot — refere-se à refatoração
planejada em `.specs/plano-sanitizer-alta-fidelidade.md`.)

Existe para servir de baseline byte-a-byte a uma tarefa futura (T2) que precisa provar
que uma refatoração do Sanitizer não mudou o comportamento observável.

## Commit capturado

- **Hash:** `dc32ab3ffff26e5ea093ceae4947fbeb033eb291`
- **Branch:** main
- Confirmado que `aegis_sanitizer/sanitizer.py` e `aegis_runner/cognitive_fallback.py`
  (o único módulo interno que `sanitizer.py` importa — usado dentro de
  `refine_semantics_with_llm`) estavam **sem alterações não commitadas** em relação a
  este HEAD no momento da captura
  (`git status --porcelain -- aegis_sanitizer/sanitizer.py aegis_runner/cognitive_fallback.py`
  → saída vazia). Havia outras alterações não commitadas no working tree no momento da
  captura (`docs/aegis_architecture_manual.md`, `docs/aegis_rpa_suite_walkthrough.md`,
  vários arquivos `.md` novos e diretórios de config `.claude/`, `.gemini/`, `.mcp.json`),
  mas nenhuma delas é importada pelo caminho de execução do Sanitizer.

## Data/hora da captura

`2026-07-12T00:43:47Z` (UTC, ambiente de execução do subagente que gerou este snapshot).

## Comando exato executado

Da raiz do framework (`C:\Projetos\aegis_rpa_suite`), em shell POSIX (Git Bash):

```bash
AEGIS_COGNITIVE_ENABLED=false python aegis_sanitizer/sanitizer.py --project-dir "<pasta_temporaria_isolada>"
```

Python usado: `Python 3.14.2`.

`AEGIS_COGNITIVE_ENABLED=false` é **obrigatório** para reprodução determinística: existe
um `.env` na raiz do framework com `AEGIS_COGNITIVE_API_KEY` preenchida, e
`CognitiveGateway.__init__` (`aegis_runner/cognitive_fallback.py:96-98`) auto-ativa o
gateway sempre que há chave e a variável `AEGIS_COGNITIVE_ENABLED` não foi setada
explicitamente no ambiente. Com o gateway ativo, `sanitize()` chama
`refine_semantics_with_llm()` incondicionalmente (`sanitizer.py:218`), que reescreve
TODAS as `business_description` do dicionário e dos eventos a cada execução via LLM —
tornando a saída não-determinística entre capturas. Setar a env var explicitamente no
processo pai (shell) garante precedência absoluta sobre o `.env`: ver
`cognitive_fallback.py:70-72` — `if key_clean in initial_env: continue` — uma variável
já presente no ambiente do processo pai nunca é sobrescrita pelo valor lido do `.env`.

Confirmado no log real da execução usada para gerar este snapshot:

```
[INFO] Gateway Cognitivo não configurado ou ativo. Ignorando refinamento semântico via LLM.
```

## Procedimento

1. Copiados os 4 arquivos-fonte de `projects/portal_segura/tests/001_teste/`
   (verificado byte-a-byte com `cmp` antes de rodar) para uma pasta temporária isolada
   **fora do repositório** (scratchpad da sessão do subagente), contendo apenas:
   - `gravacao.json`
   - `dicionario.json`
   - `dataset_inicial.json`
   - `project.json`

   Nenhum outro arquivo do projeto real (`template.csv`, `correcoes_acumuladas.json`,
   `code/`, `screenshots/`, etc.) foi copiado — o Sanitizer verifica existência antes de
   tocar em qualquer um desses e ignora silenciosamente o que não está presente.
2. Executado o comando da seção acima contra essa pasta temporária isolada.
3. Copiados os 3 artefatos resultantes (pós-sanitização) da pasta temporária para
   `.specs/golden/real_portal_segura_001/`:
   - `gravacao.json`
   - `dicionario.json`
   - `plano_execucao.json`
4. Pasta temporária apagada ao final.
5. `projects/portal_segura/tests/001_teste/` **nunca foi tocado** — o Sanitizer rodou
   exclusivamente contra a cópia isolada, nunca contra o diretório real do projeto.

## Checksums (SHA-256)

### Entradas (originais, intocadas, em `projects/portal_segura/tests/001_teste/`)

```
8398a0b197f6b4ba4bfdae008195efdf664af76dc6caefa108af356133e31263  gravacao.json
29e4cb3fe5285062d28107d1f92cd6bcf0041f167a55048c9eb8708994dd5e86  dicionario.json
1195ccdaaff7d4457e97e1e9720be48429a5c7d13ac232cd62ef0d61d2345d12  dataset_inicial.json
c8d1ca04220617fada4485df59eefd533e814de59e4ac363f394c3b351218d0f  project.json
```

### Saídas (golden, em `.specs/golden/real_portal_segura_001/`)

```
8398a0b197f6b4ba4bfdae008195efdf664af76dc6caefa108af356133e31263  gravacao.json
29e4cb3fe5285062d28107d1f92cd6bcf0041f167a55048c9eb8708994dd5e86  dicionario.json
9aa0967ea7d20c4a04255fbf11657874a62019652136e37c490acdcac89c66e7  plano_execucao.json
```

**Observação importante para quem for comparar (T2):** `gravacao.json` e `dicionario.json`
saíram com o SHA-256 **idêntico** ao de entrada — ou seja, para este dataset específico
(já sanitizado em ciclos anteriores — ver "Working Agreements" no `CLAUDE.md` da raiz
sobre re-sanitização), o Sanitizer não teve nenhuma correção de encoding/data/dedup de
evento para de fato aplicar nesta rodada; a passagem por `sanitize()` foi um no-op
byte-a-byte nesses dois arquivos especificamente PARA ESTE INPUT. Isso não é garantido
para outro projeto/gravação. O único artefato que carrega conteúdo efetivamente gerado
pela lógica de transformação do Sanitizer (dedup de cliques consecutivos, reorder de
pares de dropdown, colapso de select, `weak_selector`, `fallback_selectors`, Padrão Q de
`has_text` dinâmico removido, etc.) é `plano_execucao.json`. Um teste de regressão
"byte-idêntico" que só comparasse `gravacao.json`/`dicionario.json` não pegaria uma
quebra na lógica de geração do plano — a comparação que realmente importa está
concentrada em `plano_execucao.json`.

## Campos não-determinísticos em `plano_execucao.json` (schema, não bug)

Dois campos no topo de `plano_execucao.json` **nunca** serão byte-idênticos entre duas
capturas, mesmo com Sanitizer byte-a-byte idêntico e o mesmo input:

- `"generated_at"` — timestamp `datetime.now().isoformat(...)` gerado no momento da
  execução (`sanitizer.py:1075`).
- `"test_dir"` — `os.path.basename(self.telemetry_dir)` (`sanitizer.py:1074`), ou seja,
  o nome da **pasta temporária** usada na captura, não o nome do teste original
  (`001_teste`). Nesta captura o valor gravado foi `"golden_run_001"` — o nome da pasta
  temporária desta execução, não um identificador estável do projeto.

**Para T2 obter uma comparação byte-idêntica válida em `plano_execucao.json`**, é
necessário reproduzir o mesmo nome de pasta temporária (`golden_run_001`) OU excluir/
normalizar esses 2 campos antes do diff (ex.: comparar apenas `total_steps` + o array
`steps` inteiro, ou fazer replace por regex nesses 2 campos antes de comparar). O
`"total_steps": 63` e todo o array `"steps"` são determinísticos dado o mesmo input e
devem bater byte-a-byte com um Sanitizer comportamentalmente inalterado.

## Confirmação

Estes são os artefatos (`gravacao.json`, `dicionario.json`, `plano_execucao.json`)
gerados pelo Sanitizer pré-refatoração (commit `dc32ab3ffff26e5ea093ceae4947fbeb033eb291`) rodando contra os
dados reais do projeto `portal_segura/tests/001_teste`, com o Gateway Cognitivo
desativado explicitamente (`AEGIS_COGNITIVE_ENABLED=false`) para garantir determinismo.
