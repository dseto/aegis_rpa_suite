# Relatório de Timing — Diagnóstico de Timeout de fill() no Campo Celular

Data: 2026-07-09
Escopo: SUBAGENTE 03 (Feature 2) — diagnosticar correlação entre o
monkey-patch de `EventTarget.prototype.addEventListener` (bloco "AEGIS
ANTI-BOT DETECTOR", `aegis_blackbox/recorder.py`) e o timeout de `fill()`
reportado no campo Celular do Portal Segura, sem propor fix.

## Instrumentação adicionada

- `aegis_blackbox/recorder.py`, dentro do bloco AEGIS ANTI-BOT DETECTOR
  (`EventTarget.prototype.addEventListener` interceptado): loga
  `[AEGIS_TIMING] addEventListener type=<tipo> tag=<tag> el=<id/name/seletor>
  t=<performance.now()>` para **toda** chamada interceptada (sem filtrar por
  `keydown`/`keyup`), condicionado a `window.__aegis_debug_timing__`.
- Flag Python `AEGIS_RECORDER_DEBUG_TIMING` (default `false`), lida em
  `AegisRecorder.__init__` (`self.debug_timing_enabled`) e injetada via
  `context.add_init_script("window.__aegis_debug_timing__ = true;")` /
  `page.evaluate(...)` **antes** de `JS_MINIMAL_LISTENERS`, para garantir que
  a flag já exista quando o monkey-patch é instalado. Default OFF — nenhuma
  mudança de comportamento em execução normal.
- Os logs `[AEGIS_TIMING]` chegam automaticamente em
  `<output_dir>/browser_console.log` via o listener `console` já existente
  no recorder (`on_console_msg` → `log_browser_message`), sem infraestrutura
  Python adicional.

## Reprodução ao vivo

- Comando: `AEGIS_RECORDER_DEBUG_TIMING=true python scratch/record_portal_segura_pilot.py`
  contra `http://localhost:5173/` (site local confirmado ativo, HTTP 200).
- Driver reaproveitado sem alterações (`scratch/record_portal_segura_pilot.py`),
  incluindo o clique defensivo via `evaluate("el => el.click()")` nos
  dropdowns Sexo/Estado Civil/Isenção, já corrigido em tarefa anterior.
- Saída completa e `browser_console.log` capturados em
  `projects/portal_segura_pilot/tests/001_flaky_test/`.

## Achado

**Correlação DESCARTADA nesta reprodução.** O campo Celular
(`mat-input-cel-ng-tns-*`) foi preenchido via `page.fill()` **sem qualquer
timeout ou exceção Playwright**. A sequência de eventos capturada em
`browser_console.log` mostra:

```
[CONSOLE LOG] [AEGIS_TIMING] addEventListener type=focus  tag=INPUT el=mat-input-cel-ng-tns-c6105320-43713-5 t=3711.300
[CONSOLE LOG] [AEGIS_TIMING] addEventListener type=blur   tag=INPUT el=mat-input-cel-ng-tns-c6105320-43713-5 t=3711.300
[CONSOLE LOG] [AEGIS_TIMING] addEventListener type=keydown tag=INPUT el=mat-input-cel-ng-tns-c6105320-43713-5 t=3722.900
[CONSOLE LOG] [AEGIS_TIMING] addEventListener type=paste   tag=INPUT el=mat-input-cel-ng-tns-c6105320-43713-5 t=3723.000
[CONSOLE LOG] [AEGIS_TIMING] addEventListener type=input   tag=INPUT el=mat-input-cel-ng-tns-c6105320-43713-5 t=3723.000
```

Todos os campos do formulário (CPF, Nome, Data Nascimento, E-mail, Celular)
registram seus listeners de focus/blur num intervalo de ~0.3ms entre si
(t≈3711.1 a t≈3711.3 — provavelmente renderização Angular do formulário
inteiro de uma vez), e os eventos reais de digitação (`keydown`/`paste`/
`input`) do campo Celular ocorrem ~11.6ms depois (t≈3722.9-3723.0), também
com deltas de fração de milissegundo entre chamadas. Não há nenhum gap de
segundos nos logs `[AEGIS_TIMING]` ao redor do preenchimento do Celular —
o overhead observado do monkey-patch em si é desprezível (sub-milissegundo
a poucos milissegundos por chamada), incompatível com o tempo necessário
para acionar um timeout de 30s do Playwright.

O timeout real observado nesta execução (`Page.click: Timeout 30000ms
exceeded`) ocorreu **depois**, no clique da opção "Isenção de ICMS" do
terceiro dropdown — exatamente o bug de viewport já documentado e
explicitamente fora do escopo desta tarefa (elemento fica fora da área
visível: `element is outside of the viewport`, confirmado nos logs do
Playwright). Como o campo Celular é preenchido *antes* desse ponto do
fluxo, a observação do Celular não foi bloqueada por esse bug conhecido —
o preenchimento do Celular foi observado com sucesso e sem timeout.

## Achado secundário (fora do escopo desta tarefa — não investigado a fundo)

O valor do campo Celular **não aparece no array `events` de
`gravacao.json`** gerado por esta execução, apesar de:
- não ter havido exceção Python/Playwright na chamada `page.fill()` desse
  campo (nenhum erro nos logs entre o preenchimento do Celular e o timeout
  posterior na Isenção de ICMS);
- o seletor do campo Celular constar corretamente em
  `anti_bot_fields` do próprio `gravacao.json` (ou seja, o detector
  identificou os listeners `keydown`/`keyup` do campo normalmente).

Isso sugere uma possível falha na captura/flush do evento (não relacionada
ao monkey-patch de timing, que mostrou latência desprezível) — mas **não
foi investigada nesta tarefa**, que tinha escopo restrito à instrumentação
de timing e ao diagnóstico da hipótese de overhead do monkey-patch. Fica
registrado aqui como pista para uma tarefa futura separada.

## Conclusão

- Hipótese "overhead do monkey-patch do AEGIS ANTI-BOT DETECTOR causa
  timeout de `fill()` no Celular": **descartada** nesta reprodução — o
  preenchimento do Celular completou normalmente e a instrumentação de
  timing não mostra nenhuma latência anômala ao redor desse campo.
- O único timeout real observado nesta execução foi o bug de viewport já
  conhecido (fora de escopo), num ponto do fluxo posterior ao Celular.
- Achado secundário (Celular ausente do `events` capturado apesar de
  `fill()` bem-sucedido) é um indício de outro possível problema — de
  captura/flush, não de timing/overhead — e deve ser tratado como item
  separado, não coberto por esta tarefa.
