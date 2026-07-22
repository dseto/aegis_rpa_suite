> **NOTA:** este é o conteúdo da **Seção 6** a ser anexado em
> `.specs/plans/portal-segura.baseline-001.md`. Foi escrito aqui porque o
> `boundary_guard` do contrato ativo bloqueia escrita fora dos `files[]` de
> T-08 (o baseline não está declarado). Anexar ao fim do baseline ao fechar
> o contrato (ou via `harness task add-file T-08 .specs/plans/portal-segura.baseline-001.md`).

---

## Seção 6 — Gate pós-backlog E1.1 + E3 (marca de auditoria + handler de overlay não mapeado) — **APROVADO**

- **Data:** 2026-07-22. Branch: `unified-target-descriptor-6509308849546547825`, commit `2f5401a` (T-07). Mesmo bot 66-passos da Seção 5, rodado **sem regeneração**.
- **Mudança sob teste:** contrato do harness `backlog-agentico-design-time` — **E1.1** (marca de auditoria `generic_only_expected_missing` no runner, commit `79bfec0`) + **E3** (handler determinístico de overlay não mapeado na cadeia de recovery de clique, commit `8929028`). Ambos aditivos. É o "depois" da Seção 5 (o "antes").
- **Config:** mesma dos gates anteriores (`channel=msedge`, headed, `AEGIS_COGNITIVE_ENABLED=true`, provider `openrouter`). Nota: o `.env` atual aponta `AEGIS_COGNITIVE_MODEL=google/gemini-3.5-flash-lite` (Seção 5 usou `2.5-flash`) — irrelevante para o caminho determinístico (`st_054` resolve por coordenada/Shadow DOM, não por `visual_ai`).
- **Execução:** via `harness verify T-08` (cadeia `python bot && python bot && python bot` em um único subprocess `capture_output`). Isolamento por-execução (`AEGIS_EXECUTION_DIR` distinto) **não está disponível sob o `boundary_guard`** do contrato — status por-run extraído do stdout combinado; `correcoes_acumuladas.json`/telemetria acumulam no `project_dir`.

### Resultado (3 execuções)

| Execução | Status | `HEALED` | Ponto de falha |
|---|---|---|---|
| 1 | **SUCCESS** | 1 (`st_054`, coord/Shadow DOM) | — |
| 2 | **SUCCESS** | 1 (`st_054`, coord/Shadow DOM) | — |
| 3 | FAILED | 0 (falhou antes de `st_054`) | `st_026` "Uso do Veículo" (`select_option` — dropdown clicou mas não abriu o painel; cascata de seletores + coord de fallback + cognitivo, todos falharam; `TIMEOUT_SELECTOR`) |

**2/3 SUCCESS.** `correcoes_acumuladas.json` estável **24→24** (nenhuma entrada nova). `needs_review` estável **8→8**. `st_054` bumped `occurrences` 3→5 (dedup por `(action, failed_selector)` correto — não duplicou). Nenhum crash Python / traceback / ImportError. **Nenhuma marca `generic_only_expected_missing`** apareceu (E1.1 é no-op estrutural neste bot, exatamente como a Seção 5 previu — plano sem `expected_effect`). E3 disparou **uma vez** (execução 1, `st_018`, `baseline=0/atual=7`) e **se comportou**: não deu false-HEALED, o passo resolveu no retry 2 físico (`SUCCESS` identity, não `HEALED`) — idêntico ao padrão da Seção 5.

### Exoneração decisiva do código novo

A execução 3 falhou em `st_026` **sem que E1.1 ou E3 tivessem executado antes na transação**: o `st_018` da execução 3 rodou limpo (linha `SUCCESS` direta, sem `CLICK_NO_EFFECT` → E3 nunca disparou naquela transação), e E1.1 não dispara em nenhum passo deste bot. Ou seja, nenhum dos dois caminhos de código novo estava no fluxo antes do ponto de falha — **é mecanicamente impossível que E1.1/E3 tenham causado a falha de `st_026`**.

### Veredito

**APROVADO.** A falha única em `st_026` é a **flakiness pré-existente já documentada** (Seção 2, "st_026 select uso_veiculo"; Seção 4, execução 1 — mesmo ponto, mesmo perfil "dropdown clica mas não abre painel"), não uma classe nova de erro. 2/3 iguala ou supera o padrão histórico de não-determinismo do site (Seções 2 e 4 tiveram 1/3 bruto e foram APROVADAS pela mesma lógica). `st_054` (coord/Shadow DOM) e `st_018` (retry sem healing) idênticos ao baseline da Seção 5. `correcoes`/`needs_review` estáveis. Zero regressão atribuível a E1.1/E3.

### Ressalva mecânica (passes flag de T-08)

`harness verify T-08` saiu **exit 1** — a execução 3 falhou a transação, o bot sai com código não-zero, e a cadeia `&&` propaga exit 1. `run_verify` então **não gravou evidência** e T-08 permanece `passes:false`. O `verify_cmd` exige 3/3 sem exceção, mas o site tem ~1/3 de flakiness documentada em `st_026` — nessas condições o gate mecânico mede a **flakiness do site**, não o código (a própria desc de T-08 diz que exit 0 não decide APROVADO/REPROVADO; o veredito humano decide). Esta seção **é** a aceitação de T-08. Fechamento mecânico limpo (3/3) exige uma batelada sem a flakiness — o cenário fecha 100% de forma consistente via Cockpit (Seção 2, nota final), disparo que configura geometria/estado que o subprocess direto não reproduz.

### Confirmação via caminho de produção (Cockpit) — run limpo

Após reinício do Cockpit (pegando o código atual de T-04/05/06), o teste 001 foi executado pelo caminho de **produção** (`AEGIS COCKPIT` → `C:\Python314\python.exe -u .../bot_producao.py`, dir isolado `executions/run_20260722_092723/`):

- **57/57 passos, `[✓ SUCESSO] Transação 1`, `[AEGIS COCKPIT] Processo concluído com código: 0`.**
- `st_026` "Uso do Veículo" abriu de primeira (`label:has-text('Uso do Veículo') ~ div`) — o ponto flaky que travou os subprocessos crus. `st_052` idem.
- `st_054` (Shadow DOM fechado) HEALED por coordenada/SHADOW-PROBE, **idêntico ao baseline da Seção 5** (banda 396, efeito verificado em light DOM).
- Zero classe nova de erro, zero false-HEALED.

**Por que Cockpit passa e `harness verify` flaka — não é o código:** o `verify_cmd` de T-08 é `python bot && python bot && python bot` no mesmo `project_dir`, 3× back-to-back sem settle — run N sobe o browser enquanto run N-1 ainda derruba o dele, gerando contenção de startup nos passos timing-sensitive (render do overlay Angular Material). O Cockpit contorna por design: `AEGIS_EXECUTION_DIR` isolado por run + execução serial com settle. É confounder **estrutural do verify_cmd + carga de máquina**, a mesma classe do "hang" ambiental do pytest — não defeito de T-01/T-02 (que sequer tocam a lógica de abrir dropdown: E1.1 é marca de auditoria no-op neste bot; E3 é recovery de overlay em `click`, não em `select_option`).

### FECHAMENTO — T-08 ACEITO POR VEREDITO HUMANO (2026-07-22)

Decisão do usuário (Daniel Seto): T-08 **fechado por veredito humano APROVADO**. A própria desc de T-08 estabelece que o exit 0 do `verify_cmd` **não decide** APROVADO/REPROVADO — a leitura humana pós-execução decide. O caminho de produção (Cockpit) executa o cenário 57/57 exit 0, provando retrocompat; os subprocessos crus falham só nos pontos flaky pré-existentes documentados, com o código novo mecanicamente exonerado.

**Flag `passes:true` permanece `false` por design.** O `boundary_guard` (feature-lock) bloqueia a transição para `passes:true` sem evidência fresca de `harness verify` verde, e o `verify_cmd` não produz essa evidência de forma confiável por causa do defeito estrutural acima. Forçar o flag burlaria a integridade do harness. O estado correto é: **aceitação registrada por veredito humano (este documento), flag mecânico `false` com razão documentada.** Para fechar o flag mecânico no futuro sem replanejar o contrato, rodar `harness verify T-08` numa máquina ociosa até sair uma batelada 3/3 limpa; ou (opção 2, requer replanejamento) ajustar o `verify_cmd` para isolar/settle entre runs.
