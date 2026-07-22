# [bug][windows] `harness verify` órfã netos no timeout e não streama stdout — faz run lento parecer travado

## Resumo

No Windows, o wrapper `harness verify` roda o `verify_cmd` via algo equivalente a `subprocess.run(verify_cmd, shell=True, capture_output=True, timeout=...)`. Dois defeitos combinados transformam uma suíte **lenta** em uma **aparentemente travada**, e o kill subsequente piora o ambiente.

## Comportamento atual

1. **Órfãos no timeout.** Ao estourar o timeout, o kill atinge só o filho direto (`cmd.exe`); os **netos** (`pytest.exe` → `python.exe`) ficam **órfãos vivos**. O `communicate()` seguinte pode bloquear até os órfãos morrerem.
2. **Sem streaming.** `capture_output=True` só entrega stdout **no final** — durante a execução, silêncio total. Uma suíte de ~350–370s fica muda por minutos.
3. **Bola de neve.** O silêncio parece "travado" → o operador mata a árvore por fora (no meu caso, TaskStop), que no Windows também órfã netos → a **execução seguinte** compete por recursos (locks de arquivo/dir de teste, CPU) → mais lentidão → mais "travas".

## Evidência (sessão real de uso)

- A suíte `pytest tests -q` do projeto-alvo roda em **~360–370s** e passa (`360 passed / 369s / exit 0`) — não trava.
- Sob o wrapper `harness verify`, com `capture_output` + carga de máquina, a mesma suíte ficou muda por minutos e foi diagnosticada (erroneamente, a princípio) como "trava em ~47%". A investigação consumiu tempo significativo até isolar que a causa era **ambiental** (buffering + órfãos), não deadlock de código.
- Diagnóstico apontou `harness/verify.py` (~linhas 225–233 do pacote instalado, versão 0.17.x): `subprocess.run(..., shell=True, capture_output=True, timeout=600)`.

## Impacto

- Runs lentos legítimos são indistinguíveis de hangs → operador mata → órfãos → contenção → falsos "travamentos" em cascata.
- `verify_cmd` que roda N execuções encadeadas (`a && b && c`) sofre o pior caso: cada kill deixa resíduo para o próximo.
- Perda de tempo real de investigação; e no meu caso ainda mascarou um `verify_cmd` estruturalmente frágil (3× back-to-back sem isolamento).

## Proposta de correção

1. Trocar `subprocess.run(capture_output=True)` por `Popen` com **streaming** de stdout/stderr em tempo real (tee para o console + buffer), para que o operador veja progresso e distinga lento de travado.
2. Rodar o filho em **novo grupo de processos** (`CREATE_NEW_PROCESS_GROUP` no Windows / `start_new_session=True` no POSIX) e, no timeout, matar a **árvore inteira** (`taskkill /T /F <pid>` no Windows; `os.killpg` no POSIX) — nunca só o filho direto.
3. Opcional: expor `--stream`/`--timeout` e um aviso explícito quando o timeout dispara ("processo morto por timeout de Ns; árvore encerrada").

## Não-objetivo

Não mudar a semântica de exit-code do verify (exit 0 = passou). Só corrigir gestão de processo e visibilidade.
