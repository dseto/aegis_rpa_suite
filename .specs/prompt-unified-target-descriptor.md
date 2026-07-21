# Prompt para agente autônomo — Unified Target Descriptor (Aegis RPA Suite)

> Copie tudo abaixo da linha e envie ao agente de codificação.

---

## Missão

Implementar no **Aegis RPA Suite** (repositório em que você está) o recurso **Unified Target Descriptor**: cada elemento-alvo gravado passa a carregar um *bundle redundante de descritores* (seletor estrito, seletores alternativos, **âncora textual estável + geometria relativa**, e **efeito esperado pós-ação**), e o runner ganha um **tier determinístico de resolução por âncora** que roda antes dos tiers de coordenada/LLM. Inspiração direta: "unified targeting" / Object Repository do UiPath.

## Contexto arquitetural obrigatório (leia antes de codar)

O Aegis é um pipeline de 5 fases com **desacoplamento total entre design-time (com IA) e run-time (determinístico, zero-LLM por padrão)**. Leia `CLAUDE.md` na raiz — ele é a fonte de verdade. Módulos afetados:

1. **`aegis_blackbox/recorder.py`** — injeta listeners JS num browser headed e grava eventos em `gravacao.json`. Já captura `fallback_selectors` (linhas ~824 e ~909: `selectorCandidates.slice(1)`, cada um validado único no DOM no momento da gravação) e coordenadas normalizadas (`original_coords`).
2. **`aegis_sanitizer/sanitizer.py`** — classifica (nunca deleta) a telemetria e compila `plano_execucao.json` (schema v2, id spaces `st_`/`sup_`, `execution_hint`). Campos novos devem ser **propagados aditivamente** — mesma política de retrocompat do `weak_selector`/`confidence`: gravação sem o campo novo = comportamento atual, byte a byte.
3. **`aegis_code_generator/deterministic_emitter.py` + `code_generator.py`** — emitem `bot_producao.py`. Os novos campos do plano devem chegar às chamadas geradas (`click_resilient(...)`, `fill_resilient(...)`, `select_option_resilient(...)`) como kwargs novos e opcionais.
4. **`aegis_runner/runner.py`** — `TransactionRunner`. Pontos de integração exatos:
   - `click_resilient` (linha ~1180) e sua cadeia de fallback `_handle_unrecoverable_click` (linha ~1751);
   - `fill_resilient` (linha ~3136);
   - `select_option_resilient` (linha ~2305);
   - `_verify_action_effect(self, page, before_snapshot, expected=None)` (linha ~615) — **repare que o parâmetro `expected` já existe e está subutilizado**;
   - `_register_healing_for_review` (linha ~357) — Sensor F1: todo tier que resolve um passo por healing registra `needs_review` em `correcoes_acumuladas.json`.

## Doutrina inegociável (violar qualquer uma = PR rejeitado)

- **"Cauda Longa Verificada":** nenhum tier pode reportar `SUCCESS`/`HEALED` sem pós-condição observável via `_verify_action_effect`. O novo tier de âncora **também** verifica antes de aceitar.
- **Zero-LLM em runtime por padrão:** o tier de âncora é geometria + texto, puramente determinístico. Ele roda **antes** dos tiers de coordenada gravada e cognitivo, e **é permitido sob `strict=True`** (não é palpite — usa dado gravado e validado), mesmo critério do tier `fallback_selectors` existente.
- **NÃO endurecer o caminho identity:** o clique direto que funciona de primeira continua verificado pelos sinais genéricos atuais. O `expected_effect` gravado só entra como critério **adicional e preferencial quando presente** — nunca transforme ausência de match do expected_effect em rejeição de um clique identity que os sinais genéricos aprovam (falso negativo com efeito físico é pior que falso positivo de status; ver `.specs/backlog-achados-falso-sucesso.pending.md`).
- **Framework selado:** nenhum arquivo específico de projeto RPA em raiz ou dentro de `aegis_*`. Artefatos de teste vão em diretórios `fake_project_*` dentro de `aegis_runner/` (padrão já existente) ou em `projects/`.
- **Todo healing pelo novo tier registra Sensor F1** com `healing_method="anchor_geometry"`.
- **Todo erro novo de validação AST em `step_validator.py` (se criar algum) deve carregar `lineno` ou `step_id`** — sem isso ele fica invisível à correção cirúrgica (lição documentada em CLAUDE.md, Working Agreements item 5).

## Especificação por fase

### Fase A — Captura no recorder (aditiva, risco zero)

No JS injetado do `recorder.py`, para **cada** evento de `click` e `fill` capturado, adicionar dois campos novos ao evento:

**A1. `anchor`** (objeto ou `null`):
```json
{
  "selector": "label:has-text('Uso do Veículo')",
  "text": "Uso do Veículo",
  "dx": 12,
  "dy": 38,
  "anchor_bbox": {"x": 120, "y": 400, "w": 140, "h": 20},
  "target_bbox": {"x": 132, "y": 438, "w": 300, "h": 44},
  "strategy": "label_for | aria_labelledby | preceding_label | nearest_stable_text"
}
```
Estratégia de eleição da âncora, em ordem de preferência:
1. `label[for=<id do alvo>]` — vínculo semântico explícito;
2. elemento apontado por `aria-labelledby`/`aria-label` do alvo (quando aponta para nó de texto);
3. `<label>` ancestral ou irmão-precedente mais próximo;
4. nó de texto visível estável mais próximo geometricamente (distância euclidiana entre centros de bbox, raio máx. 250px), com filtros: texto não vazio, 2–60 chars, **não** numérico puro, **não** dentro de elemento com classe/id que contenha hash-like (`/[a-f0-9]{6,}/i`), visível (`offsetParent !== null`).

`dx`/`dy` = offset do **centro do alvo** relativo ao **centro da âncora**, em px. Se nenhuma âncora satisfaz os filtros → `anchor: null` (nunca invente).

**A2. `expected_effect`** (objeto ou `null`) — snapshot do delta que a ação causou **na gravação**:
- Capturar snapshot leve ANTES da ação (já existe infra de snapshot no runner; no recorder implemente equivalente JS): `{url, domNodeCount, overlayCount, activeElementValue}`.
- ~800ms depois da ação (com um segundo poll em 2s se nada mudou), capturar DEPOIS e gravar **somente o delta**:
```json
{
  "url_changed": true,
  "dom_delta": 42,
  "overlay_delta": 1,
  "value_changed": false,
  "new_visible_text": "Passo 2: Dados Estruturais"
}
```
`new_visible_text`: primeira linha de texto visível que existia no DEPOIS e não no ANTES (heurística: headings/elementos com role=heading novos), máx. 60 chars, ou `null`. Se nada mudou nos dois polls → `expected_effect: null`.

### Fase B — Propagação sanitizer → plano → emitter

- `sanitizer.py`: copiar `anchor` e `expected_effect` do evento para o step correspondente no `plano_execucao.json`, intactos. Steps merged (`merged_from`): herdam do evento vencedor.
- `deterministic_emitter.py` (`emit_step_block`/`_emit_click`) e o prompt do fluxo cognitivo em `code_generator.py`: emitir os kwargs `anchor={...}` e `expected_effect={...}` nas chamadas geradas **somente quando presentes** no step do plano.
- `step_validator.py`: os novos kwargs são permitidos, nunca exigidos (bots antigos sem eles continuam válidos).

### Fase C — Tier `anchor_geometry` no runner

Novo método `TransactionRunner._resolve_via_anchor(page, anchor, action_kind) -> locator|None`:
1. Localiza a âncora: primeiro por `anchor.selector`; se 0 matches, por texto exato `anchor.text` (via `get_by_text(exact=True)`, depois `exact=False` se 0); se ainda 0 → `None`.
2. Se 2+ matches da âncora, desambiguar pelo bbox mais próximo de `anchor.anchor_bbox` gravado.
3. Calcula ponto esperado do alvo: centro da âncora atual + (`dx`, `dy`) **escalados** pela razão entre viewport atual e viewport da gravação (gravar `viewport` junto no evento da Fase A para permitir isso).
4. `elementFromPoint` no ponto calculado; valida plausibilidade com a mesma lógica de `_hit_test_plausible` já existente (compara com `target_description`); se implausível, busca o elemento interativo (`input, button, select, [role=combobox], [role=button], a`) com centro de bbox mais próximo do ponto, raio máx. 80px.
5. Retorna locator do elemento ou `None`. **Nunca clica aqui** — só resolve.

Integração nas cadeias (padrão do tier 2.9 `fallback_selectors` existente — estude-o e replique o contrato):
- `click_resilient`/`_handle_unrecoverable_click`: novo tier **entre** `fallback_selectors` (2.9) e coordenada gravada (3). Baseline fresco por tier via `_tier_baseline` (obrigatório — leia a seção "Per-tier verified recovery" do CLAUDE.md), clique no locator resolvido, verificação via `_verify_action_effect`, e só então `HEALED` + `_register_healing_for_review(..., healing_method="anchor_geometry")`.
- `fill_resilient`: mesmo ponto da cadeia; preenche via locator resolvido com a mesma estratégia de digitação do passo original.
- `select_option_resilient`: **este é o alvo de maior valor** (flakiness real medida no gate — `st_023`/`st_026` do projeto de referência). Quando a cascata de seletores de trigger falha (`label:has-text(...) ~ div`, `.mat-select-trigger`, etc.), usar `_resolve_via_anchor` para achar o trigger do dropdown antes de cair para coordenadas. A verificação de painel aberto existente (que já detecta "clicou mas não abriu painel") continua sendo o critério de aceitação do tier.

### Fase D — `expected_effect` no verificador (aditivo)

Em `_verify_action_effect`, quando o kwarg `expected` (já existente na assinatura) receber um `expected_effect` gravado:
- Match **qualquer-um-de** (OR, não AND): `url_changed` bateu, `dom_delta` com mesmo sinal (cresceu/encolheu), `overlay_delta` com mesmo sinal, `value_changed` bateu, ou `new_visible_text` presente no DOM atual → aprovado com confiança alta.
- Nenhum sinal do expected bateu **mas** os sinais genéricos atuais aprovam → aprovado (comportamento atual preservado; loga `[AEGIS RUNNER] expected_effect não confirmado, aprovado por sinais genéricos` para telemetria).
- Registrar em `telemetria_resolucao.json` o campo novo `verify_source: "expected_effect" | "generic"` por passo.

## Testes exigidos

- Suítes existentes **intocadas e verdes**: `python aegis_runner/test_runner_integration.py` (118 testes), `python aegis_runner/test_cognitive_fallback.py` (7), `python aegis_sanitizer/test_sanitizer_execution_plan.py`, suítes de `aegis_code_generator/`. Rode com `python <arquivo>.py` (não pytest). Se um teste existente quebrar por asserção overspecified (ex.: `assert_called_once_with` num método que agora chama 2x), corrija a asserção — não reverta a feature (Working Agreement 3).
- Testes novos (mesmo estilo unittest+mock dos existentes):
  - eleição de âncora: cada uma das 4 estratégias + caso `null`;
  - `_resolve_via_anchor`: âncora única, âncora ambígua desambiguada por bbox, âncora sumida → `None`, escala de viewport;
  - tier na cadeia: só dispara após `fallback_selectors` falhar, registra F1, respeita `strict=True`, rejeita quando `_verify_action_effect` reprova;
  - `expected_effect` no verificador: OR dos sinais, fallback genérico preservado, passo sem o campo = código atual byte a byte;
  - retrocompat: `gravacao.json`/`plano_execucao.json` antigos (sem os campos) atravessam sanitizer → emitter → runner sem qualquer mudança de comportamento.
- **Aviso honesto no PR:** testes mockados não provam seletor/geometria contra DOM real (regra 1 dos Working Agreements). Declare explicitamente no corpo do PR que a validação live (gate de regressão contra o projeto de referência) será feita pelo mantenedor — não a simule.

## Entregável

- Branch própria + PR único contra `main`, título `feat(runner): unified target descriptor — âncora geométrica e efeito esperado gravado`.
- Corpo do PR: resumo por fase (A–D), lista de arquivos tocados com justificativa, saída completa das suítes, limitações conhecidas.
- Commits atômicos por fase (A, B, C, D), mensagens em português seguindo o padrão do histórico (`feat(recorder): ...`, `feat(sanitizer): ...`).
- Não tocar em: `aegis_cockpit/`, `aegis_devops/`, `aegis_mentor/`, arquivos `.specs/`, nem qualquer coisa sob `projects/`.
