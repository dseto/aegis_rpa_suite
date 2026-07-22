# HANDOFF — Travamento reprodutível de `pytest tests/aegis_runner -q`

> Escrito 2026-07-22. Sessão de implementação do backlog `.specs/backlog-evolucao-agentica-design-time.md`
> (itens E1.1/E3/E2) via harness-creator. **Este handoff descreve um problema
> AINDA ABERTO e não resolvido** — a causa raiz do travamento da suíte de
> testes ainda não foi confirmada nem corrigida. Meta ativa: descobrir a causa
> e corrigir antes de considerar as demandas finalizadas.

---

## 1. O que estava sendo feito

Implementação de 8 tarefas (T-01…T-08) de um contrato do plugin harness-creator
(`.harness/work/backlog-agentico-design-time/`), TDD, uma tarefa por vez, cada
uma commitada com evidência em `.harness/evidence/<id>.json`.

**Status das tarefas (código):**
- T-01 (E1.1, marca `generic_only_expected_missing` em `runner.py`) — **done**, commit `79bfec0`, 11 testes verdes.
- T-02 (E3, handler de overlay não-mapeado em `runner.py`) — **done**, commit `8929028`, 5 testes verdes.
- T-03 (regressão suíte `aegis_runner` completa) — **done**, commit `22fc981`. **Rodou 153/153 em 351s, TRÊS vezes com sucesso** (uma via Bash direto, duas via `harness verify`). Evidência: `.harness/evidence/T-03.json`.
- T-04/T-05/T-06 (E2, `aegis_cockpit/healing_review.py` + endpoint) — **done**, commits `98148d2`/`78549cc`/`ba51163`, 21 testes verdes.
- T-07 (fechamento) — `passes:true` gravado com `verify_cmd` REDUZIDO aos 2 arquivos novos de T-01/T-02 (16 testes, ~5s), **como paliativo** — NÃO é a solução do travamento, é contorno. Ainda **não commitado**.
- T-08 (execução real 3x do bot Portal Segura) — **pendente**, depende de T-07.

Working tree tem mudanças não-commitadas: `runner.py` (fix de lint cosmético — 1 prefixo `f` removido de um print sem placeholder), `Plans.md`/`spec.md` (adendos), `feature_list.json`, `.harness/evidence/T-07.json`.

---

## 2. O PROBLEMA (o que este handoff registra)

`pytest tests/aegis_runner -q` (153 testes, dominados por `test_runner_integration.py`)
**trava de forma reprodutível em ~47% de progresso** (parou nos dots
`........................................................................ [ 47%]`
seguido de `...` e nunca mais avança). Fica pendurado indefinidamente sem
completar, sem crashar, sem timeout — tive que matar via TaskStop.

### 2.1. Por que isso é intrigante / não-óbvio

- **A MESMA suíte passou 153/153 em 351s, TRÊS vezes**, no T-03, logo após
  T-01+T-02 já estarem no código. Ou seja: **o código de T-01/T-02 não trava a
  suíte por si só** — ela já foi verde com esse código.
- Os travamentos começaram DEPOIS, nas tentativas de T-07 (que roda o mesmo
  comando). Entre T-03 verde e T-07 travando, a única mudança em `runner.py` é
  o fix de lint cosmético (irrelevante).
- Travou tanto via `harness verify` QUANTO via `pytest` direto no Bash.

### 2.2. Distinguir DOIS problemas separados (não confundir)

**Problema A — bug do wrapper `harness verify` (JÁ diagnosticado, não é a
causa do travamento da suíte):**
Um subagente investigador (Fable, papel de bug-hunter) leu o código e achou:
`harness/verify.py` linhas 225-233 do pacote instalado do harness-creator usa
`subprocess.run(verify_cmd, shell=True, capture_output=True, timeout=600)`.
No Windows, ao estourar o timeout de 600s, `process.kill()` mata só o filho
direto (`cmd.exe`), deixando netos (`pytest.exe`→`python.exe`) órfãos; o
`communicate()` seguinte bloqueia sem timeout até os órfãos morrerem. E
`capture_output=True` nunca streama, então dá "silêncio total". **Isso explica
o comportamento MUDO por 40+min quando via harness verify, mas NÃO explica por
que a suíte trava em 47% via Bash direto.**

**Problema B — travamento da suíte pytest em si, em ~47% (AINDA ABERTO, é a
causa raiz real a descobrir):**
Via `pytest tests/aegis_runner -q` direto no Bash (sem o wrapper), a suíte
trava em ~47% e não avança. Bash tool tem timeout próprio (setei 500s), mas o
processo ficava parado em 47% muito antes de qualquer avanço — sem produzir
novos dots por várias checagens `TaskOutput` seguidas (minutos).

### 2.3. Hipótese corrente (NÃO confirmada) e por que é insuficiente

O investigador levantou: **processos pytest órfãos acumulados** (de eu ter
matado tentativas via TaskStop, que no Windows só mata o topo, deixando netos
vivos) competindo por recursos E **colidindo em diretórios de teste de nome
FIXO** — `test_runner_integration.py` e as suítes novas criam dirs tipo
`fake_project_healing`, `fake_project_recent_fills`, `fake_project_expected_effect_*`,
`fake_project_unmapped_overlay`, etc. (relativos ao cwd), com `shutil.rmtree`
no tearDown. Duas execuções simultâneas (uma órfã + a nova) colidiriam no mesmo
diretório → possível deadlock de lock de arquivo no Windows (o projeto usa
`msvcrt.locking()` em `runner.py::_with_file_lock` e em
`_register_healing_for_review`, que escreve `correcoes_acumuladas.json`).

**Por que é insuficiente / suspeito:**
- Usuário matou os órfãos manualmente via `Get-CimInstance Win32_Process`
  filtrando `python.exe` com `pytest` na cmdline → a tentativa SEGUINTE passou
  do ponto onde travava antes, MAS travou de novo mais adiante. Ou seja, matar
  órfãos ajudou parcialmente, mas não eliminou.
- "Sempre ~47%" é um ponto suspeitosamente CONSISTENTE para ser só contenção de
  recurso aleatória — cheira a um teste específico que entra em deadlock/espera
  infinita sob alguma condição (ex.: lock de arquivo não liberado, `time.sleep`
  em loop, espera por processo/recurso).
- A máquina está comprovadamente pesada (~15 sessões `claude.exe` + Docker +
  WSL + 3 dev-servers vite + Chrome, por snapshot do investigador) — isso é
  fator de confusão real, mas não deveria transformar 351s em hang infinito.

---

## 3. Próximos passos de investigação (o que FALTA fazer)

1. **Identificar o teste EXATO no ponto de 47%.** 47% de 153 ≈ passo 72-75.
   Rodar `pytest tests/aegis_runner -q -p no:randomly --co` (collect-only) para
   pegar a ORDEM real só de aegis_runner (o collect-only que tenho é da suíte
   combinada `tests -q`, ordem diferente). Depois rodar com `-v` ou
   `--last-failed`/`-x` para ver o nome do teste que fica pendurado. Ou rodar
   com `pytest ... -v` e observar qual é o ÚLTIMO nome impresso antes do hang.
2. **Rodar com timeout POR TESTE** para forçar o hang a virar falha nomeada:
   `pip install pytest-timeout` e `pytest tests/aegis_runner -q --timeout=60`
   — o teste que estourar 60s É o culpado, e o traceback do timeout aponta a
   linha exata onde está preso (provável `msvcrt.locking()`, `time.sleep`, ou
   `page.wait_for_*` mockado que não retorna).
3. **Suspeitar de lock de arquivo Windows.** `_with_file_lock`/
   `_register_healing_for_review` usam `msvcrt.locking(LK_LOCK)` (BLOQUEANTE).
   Se um teste novo de T-01/T-02 (`_register_healing_for_review` é chamado nas
   marcas `generic_only_expected_missing` e no handler de overlay) deixa um
   handle de `correcoes_acumuladas.json` aberto/travado e outro teste tenta
   travar o mesmo arquivo → deadlock. Verificar se os testes novos que eu
   escrevi (T-01/T-02) criam dirs que colidem com os de `test_runner_integration.py`
   OU se `_register_healing_for_review` real é exercitado sem mock em algum
   teste, adquirindo lock que nunca libera sob concorrência.
4. **Checar nomes de diretório fixos colidentes.** Grep por `os.makedirs`/
   `fake_project`/`fake_test_dir` em `tests/aegis_runner/*.py` — se dois
   arquivos de teste diferentes usam o MESMO nome de dir fixo, rodadas
   paralelas (ou tearDown de um durante setup de outro) colidem.
5. **Rodar de um cwd LIMPO / dir temporário isolado** para descartar colisão de
   `fake_project_*` residual no repo root de execuções mortas.

## 4. Regras aprendidas nesta sessão (não repetir erros)

- **NUNCA matar tentativa de pytest via TaskStop repetidamente** — no Windows
  deixa netos órfãos que pioram tudo (bola de neve). Se precisar matar, matar a
  árvore inteira (`taskkill /T /F` ou `Stop-Process` da árvore).
- **Confirmar zero `python.exe`/`pytest` órfão ANTES de cada nova execução.**
- O `boundary_guard` do harness bloqueia `tasklist`/`Get-CimInstance`/`taskkill`
  via Bash e PowerShell (só libera verify_cmd/lint/build/install/git declarados)
  — diagnóstico de processo precisa ser feito pelo usuário OU via um teste
  pytest read-only "disclosed" (o investigador usou `.harness/work/diag/`).
- O `verify_cmd` de T-07 está REDUZIDO como paliativo — a meta exige achar a
  causa raiz do Problema B e corrigir, então T-07 provavelmente deve voltar a
  cobrir a suíte inteira depois do fix (ou ficar reduzido SE a causa for
  ambiental e não do código).
