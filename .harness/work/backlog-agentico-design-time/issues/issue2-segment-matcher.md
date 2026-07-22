# [DX] `cd dir && cmd` e `| head` quebram o matcher de segmentos do boundary_guard

## Contexto

O `boundary_guard.py` divide comandos Bash em segmentos (por `;`, `&&`, `|`, etc.) e exige que **cada segmento** prefixe uma sequência de tokens permitida (`seg_tokens[:len(seq)] == seq`).

## Comportamento atual

Dois padrões universais de shell quebram o matcher, mesmo inofensivos:

1. **`cd <dir> && <comando permitido>`** — o segmento `cd ...` não prefixa nenhuma sequência permitida → comando inteiro negado, mesmo que `<comando permitido>` sozinho passasse. O `cd` é redundante (o cwd já é fixado pelo host), mas é muscle-memory universal.
2. **`<comando permitido> | head -N`** (ou `| tail`, `| wc`) — o segmento do filtro read-only não está na superfície → negado.

## Evidência (sessão real de uso)

- `cd "C:/Projetos/<repo>" && python -m harness.cli verify --help` → negado (por causa do `cd`).
- `python -m harness.cli verify --help | head -40` → negado (por causa do `| head`).
- Os mesmos comandos sem `cd` e sem pipe passaram.

## Impacto

- Papercut recorrente por sessão.
- A mensagem genérica (`comando fora da superficie...`) não aponta **qual segmento** falhou → atrasa o diagnóstico.

## Proposta

1. Ignorar prefixo `cd <dir> &&` na análise (cwd já fixado; `cd` é no-op semântico) — ou allowlistar quando o alvo é o cwd/subdir do projeto.
2. Permitir filtros read-only (`head`/`tail`/`wc`/`grep`) após pipe de um comando permitido (casa com a issue de shell read-only).
3. Ao negar por segmento, citar **qual segmento** falhou (`segmento "cd ..." fora da superfície`).

## Não-objetivo

Não afrouxar floor/feature-lock. Só reduzir falso-negativo de sintaxe shell trivial.
