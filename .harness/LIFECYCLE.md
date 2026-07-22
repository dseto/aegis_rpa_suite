# Agent Session Lifecycle — Detalhe dos 16 Passos

Este arquivo é o detalhe de progressive disclosure do bloco "Agent Session
Lifecycle" em `AGENTS.md`. Cada passo abaixo corresponde ao ciclo de 16
passos descrito no `docs/project/ROADMAP.md` (Fase 2 — "Execução Autônoma no Raio de
Impacto"): a sessão nasce sabendo onde parou, trabalha dentro do contrato
aprovado e só devolve o controle ao humano em estado retomável.

1. **Ler `AGENTS.md`.** Primeiro passo de toda sessão: carregar a
   governança compilada (permissions, hooks, este próprio lifecycle) antes
   de tocar em qualquer arquivo do projeto.

2. **Rodar `init.sh`/`init.ps1` (deps + health check do profile).** Script
   gerado a partir do profile do projeto: instala dependências e roda um
   health check para confirmar que o ambiente está utilizável antes de
   começar a trabalhar.

3. **Ler `claude-progress.md`.** Resumo do estado da sessão anterior — o
   que já foi feito, o que ficou pendente, o que quebrou. Evita retrabalho
   e recontagem de contexto pelo humano.

4. **Ler `feature_list.json`.** Lista de features do plano aprovado, cada
   uma com seu status (`pending`/`done`) e critério de verificação
   (`verify_cmd`).

5. **Checar `git log`.** Confirma o que já foi commitado de fato, cruzando
   com o que `claude-progress.md`/`feature_list.json` alegam — detecta
   divergência entre estado declarado e estado real do repositório.

6. **Escolher exatamente UMA feature pendente.** Disciplina de escopo: a
   sessão trabalha em uma única feature por vez, nunca em paralelo dentro
   da mesma sessão — isso mantém o raio de impacto pequeno e revisável.

7. **Planejar a implementação da feature escolhida.** Antes de editar
   código, esboçar a abordagem: quais arquivos mudam, que testes cobrem a
   mudança, qual é o critério de pronto.

8. **Implementar a mudança dentro do raio de impacto declarado.** Editar
   apenas os arquivos ligados à feature escolhida — o `boundary_guard`
   (Fase 2) nega qualquer edição fora dessa superfície.

9. **Rodar `verify_cmd` da tarefa.** Comando de verificação vindo do
   contrato (build, lint, suíte de teste) — a prova executável de que a
   implementação funciona.

10. **Se falhar: autocorrigir e re-rodar `verify_cmd` até passar.** Loop de
    autocorreção (Fase 3): o agente conserta a própria falha e testa de
    novo, sem envolver o humano, respeitando as stop conditions (N falhas
    consecutivas ou sinal de impossibilidade interrompe o loop). A fonte
    dessas stop conditions é explícita: o campo `stop_conditions:` do
    frontmatter do `spec.md` ativo (`.harness/work/<slug>/spec.md`),
    acessível via `harness.contract.get_stop_conditions` — esse campo é o
    disjuntor do loop. Satisfazer QUALQUER uma das condições listadas ali
    interrompe a autocorreção, registra o estado em `claude-progress.md` e
    devolve o controle ao humano junto com o diagnóstico da falha.

11. **Registrar a prova (evidência da verificação bem-sucedida).** Grava a
    evidência de que `verify_cmd` passou (timestamp, comando, hash) — é o
    que autoriza marcar a feature como concluída no passo 13.

12. **Atualizar `claude-progress.md` com o estado atual.** Documenta o que
    foi feito nesta sessão, para que a próxima sessão (passo 3) retome sem
    perder contexto.

13. **Marcar a feature concluída em `feature_list.json`.** Só acontece com
    evidência fresca do passo 11 — marcar sem evidência é enfraquecer a
    garantia que todo o lifecycle existe para proteger.

14. **Documentar o que ficou quebrado, se houver.** Transparência: se algo
    ficou incompleto ou quebrado, isso é registrado explicitamente — nunca
    escondido atrás de um commit "limpo".

15. **Commit apenas em estado retomável.** O commit local (`git add`/
    `git commit`) só acontece quando o repositório está em um estado que a
    próxima sessão (ou o humano) consegue retomar sem arqueologia.

16. **Deixar a working tree limpa.** Fim de sessão: nenhuma mudança solta
    fora de commit, nenhum arquivo temporário esquecido — o handoff para a
    próxima sessão (ou para o humano) começa de um estado previsível.
