# Lições Aprendidas — Ciclo de Melhorias de Precisão (M1-M5 + hotfixes)

**Período:** 2026-07-06 a 2026-07-09
**Referências:** `.specs/plans/melhorias-precisao-bots-gerados.md`, `.specs/plans/melhorias-precisao-bots-gerados.backlog.md`, `.specs/relatorio-piloto-site-novo.md`
**Commit:** `e917482`

---

## 1. Lições aprendidas (processo)

### 1.1. Testes unitários provam lógica isolada, não comportamento real
Duas vezes declarei um fix "pronto" com base só em suíte unitária + inspeção de diff, e as duas vezes a validação ao vivo revelou o oposto:
- O sensor `CLICK_NO_EFFECT` v1 (4º sinal) usava `document.querySelector(sel)` — nunca detectava nada porque seletores Playwright (`:has-text()`) não são CSS válido. Suíte passava (mockada), comportamento real quebrado.
- O "achado" de que `weak_selector` não capturava ambiguidade era um diagnóstico errado — os warnings eram de estratégias de fallback descartadas, não do seletor usado. Só descobri comparando `count()` real no Playwright contra a página viva.

**Regra prática:** para qualquer mudança que toca seletor/DOM/timing, rodar contra um browser real (mesmo que headless) é obrigatório antes de declarar concluído. Suíte mockada é necessária, não suficiente.

### 1.2. Causa raiz exige comparar dado real, não só ler o log de sucesso
O bug do `dataset_inicial.json` (`usuario_login` vs `username`) foi diagnosticado errado da primeira vez ("sanitizer não persiste") porque confiei no log `[AEGIS SANITIZER] dataset_inicial.json atualizado...` sem checar o arquivo em disco depois de uma ação POSTERIOR (uma segunda gravação) que silenciosamente desfez o trabalho. Só reproduzindo o pipeline do zero, 2x, em pasta limpa, achei que o sanitizer estava certo e o recorder era quem regredia.

**Regra prática:** quando o sintoma reaparece depois de eu já ter "corrigido" algo, a primeira hipótese deve ser "minha própria ação recente desfez o fix", não "o fix era insuficiente".

### 1.3. Regressão em suíte pode ser da mudança de comportamento esperada, não bug
Ao adicionar o 4º sinal do sensor, a suíte quebrou (`mock_page.locator` chamado mais vezes que o esperado por `assert_called_once_with`). Não era bug — era a suíte testando uma implicação implícita ("só uma chamada a locator") que deixou de ser verdade por design. Corrigir a asserção (`assert_any_call`) foi certo; teria sido errado reverter a funcionalidade para fazer o teste antigo passar.

### 1.4. `/reflect` como gate, não como formalidade
As duas vezes que apliquei `/reflect` de verdade (não superficialmente) encontraram causa raiz que a resposta anterior tinha errado — uma vez porque o log colado pelo usuário era idêntico a um log anterior (evidência de reexecução indevida, não bug novo), outra vez porque não tinha verificado a QUAL seletor um `console.warn` se referia. Reflexão rasa ("os testes passam, deve estar certo") teria fechado os dois com bug real aberto.

---

## 2. Pontos ainda frágeis (conhecidos, não corrigidos)

| # | Fragilidade | Onde | Risco |
|---|---|---|---|
| 1 | `fallback_selectors`/`weak_selector` nunca exercitados em produção no `portal_segura/001_teste` — o plano desse teste é anterior à melhoria | `projects/portal_segura/tests/001_teste/plano_execucao.json` | Médio — mecanismo provado no piloto Fimm, mas não no projeto histórico de referência. Só via re-gravação. |
| 2 | Fallback de seletor fica pobre em elementos só-texto (sem `data-testid`/`id`) — nada a ganhar de M5 nesses casos | `aegis_blackbox/recorder.py` (cascata de estratégias) | Baixo-Médio — limitação estrutural de app sem `data-testid`, não corrigível sem mudar a própria aplicação alvo. |
| 3 | Dedup do Sensor F1 ainda pode mascarar 2ª regressão *dentro da mesma janela* de "needs_review" ativo (só reabre depois de `resolved`/`applied`) | `aegis_runner/runner.py::_register_healing_for_review` | Baixo — comportamento intencional (evita spam), mas nunca testado sob alta frequência de regressão em curto prazo. |
| 4 | `CLICK_NO_EFFECT`: 4º sinal (fingerprint de classe) cobre troca de estado em irmãos diretos; não cobre mudança de estado em elemento **não-irmão** (ex.: painel lateral distante do botão clicado) | `aegis_runner/runner.py::_capture_click_effect_snapshot` | Médio — só validado em padrão de abas/toggle lado a lado; layouts com "clique aqui, muda lá longe" ainda são pontos cegos. |
| 5 | 3 dos 5 hotfixes desta sessão (seleção de step_id real, dedup reabertura, feature marcar-como-falho) **não têm teste automatizado dedicado** — só validados por execução ao vivo pontual | `aegis_cockpit/cockpit.py`, `aegis_runner/runner.py` | Médio-Alto — nada impede regressão silenciosa numa mudança futura nesses trechos. `cockpit.py` não tem suíte de testes no repo (gap estrutural pré-existente, não introduzido aqui). |
| 6 | Auto-preservação de chave semântica (recorder) casa por **seletor físico exato** — se o seletor mudar mesmo que o campo semântico continue o mesmo (ex.: app trocou de `#username` pra `#user-field`), a tradução se perde silenciosamente de novo, só que agora sem warning claro de "por quê" | `aegis_blackbox/recorder.py` (bloco de auto-preservação) | Baixo — caso de borda real, mas o warning residual pelo menos aponta os campos não-casados. |
| 7 | Métrica do plano "chamadas de LLM vision em runtime ≤ baseline" (critério 8.3.2) nunca foi medida numericamente — só observada qualitativamente (Fimm: 0 chamadas; Portal Segura: ainda usa self-healing nos pontos flaky conhecidos) | `.specs/plans/melhorias-precisao-bots-gerados.md` §8.3 | Baixo — critério de aceite do plano original ficou sem número fechado. |
| 8 | `evaluate_selector_reliability` pontua `:has-text(` fixo em 70, sem diferenciar "único de cara" de "único só depois do climbing de ancestrais" — a segunda situação é estruturalmente mais frágil (depende de mais DOM ao redor não mudar) mas pontua igual | `aegis_blackbox/recorder.py` | Baixo — não causou bug observado, mas é uma imprecisão de sinal deixada como está. |

---

## 3. Melhorias propostas (não implementadas, ordenadas por impacto/esforço)

### Alto impacto, esforço médio
1. **Re-gravar `portal_segura/001_teste`** e rodar o gate de regressão completo com M3/M5 realmente ativos — fecha a única ressalva não-bloqueante do fechamento desta demanda.
2. **Testes automatizados para os 3 hotfixes sem cobertura** (seleção de step_id real vs `auto_N`, dedup reabertura pós-`resolved`, endpoint `mark-failed`) — hoje dependem 100% de validação manual ao vivo.

### Médio impacto, esforço baixo
3. **4º sinal do `CLICK_NO_EFFECT` cobrindo mais que irmãos diretos** — expandir escopo pra um container ancestral configurável (ex.: `closest('[role=tabpanel], .panel, main')`) quando o clique não muda nada nos irmãos, antes de declarar `CLICK_NO_EFFECT`.
4. **Warning quando o fallback de URL hardcoded do runner é usado** já foi feito nesta sessão — próximo passo natural é o mesmo tratamento para outros fallbacks silenciosos do pipeline (ex.: `error_message_selector` default, seletor de overlay do sensor M2) — auditoria dedicada a "fallbacks silenciosos" no runner.

### Baixo impacto, esforço baixo
5. **Propagar resultado do climbing de ancestrais pro score de confiança** (achado #8 acima) — pequena mudança em `evaluate_selector_reliability` ou no ponto de captura, diferenciando "único direto" de "único só com prefixo de ancestral".
6. **Medir numericamente "chamadas de LLM vision ≤ baseline"** em vez de só observar qualitativamente — adicionar essa métrica ao relatório de gate de regressão como número, não como "0 chamadas" solto.

### Estrutural / fora do ciclo atual
7. **Suíte de testes para `aegis_cockpit/cockpit.py`** — módulo crítico (todos os endpoints de correção, marcação de passo, diagnóstico automático) sem nenhum teste no repo hoje. Pré-existente, mas ficou mais evidente porque 2 dos 5 hotfixes desta sessão foram nesse arquivo.
8. **Auto-preservação semântica por seletor** poderia evoluir para um fallback secundário por **posição/tipo de campo** (ex.: "2º input tipo password na tela") quando o seletor muda mas o papel do campo é o mesmo — reduziria a fragilidade do achado #6 acima. Maior escopo, decidir se vale a pena dado quão raro é o caso.

---

## 4. O que funcionou bem (vale manter)

- **Piloto em site novo (Fimm) como critério de aceite real** — achou 3 bugs genuínos que nenhuma quantidade de teste no Portal Segura (viés Angular Material) revelaria: seletor não-CSS no sensor, tradução semântica perdida ao regravar, e a própria confirmação de que M5 funciona fora do viés original.
- **Reprodução em pasta limpa** como técnica de diagnóstico — separou definitivamente "bug de código" de "efeito colateral de ordem de operações minha" nos dois casos de diagnóstico errado.
- **Gate de DoD reverificado na thread principal** (não confiar no `SUCESSO=true` do subagente) pegou pelo menos 1 caso onde a alegação batia mas a inspeção de diff revelou nuance real.
