# Fidelidade de Gravação — Mesmo Seletor Preenchido com Valores Diferentes na Mesma Sessão

**Status:** problema investigado e causa raiz confirmada; **design de solução NÃO decidido** — documento pra retomar em outra sessão, não implementar agora.
**Data:** 2026-07-10
**Origem:** reprodução ao vivo, projeto `fimm_finance/tests/001_login_navigation`, gravação real onde o usuário digitou a senha errada, viu o erro de login, corrigiu e avançou. O bot compilado a partir dessa gravação NÃO reproduz esse fluxo fielmente.

---

## O sintoma

Execução `run_20260710_092318` falhou em `st_004`:
```
[COGNITIVE FALHA] IA não encontrou o elemento. Justificativa: O campo de senha (#password)
não está visível na tela atual, pois o usuário já está autenticado e visualizando o painel
de controle (dashboard) 'Cash Position'.
```

## Cadeia de evidência (verificada, não suposição)

**`gravacao.json`** (eventos brutos, na ordem real capturada):
```
1 fill  #password           "admin1223"   <- senha ERRADA, digitada de propósito/engano
2 click button:has-text('Sign in')        <- falhou de verdade na gravação (erro na tela)
3 fill  #password           "admin123"    <- senha corrigida
4 click button:has-text('Sign in')        <- funcionou
```

**`dataset_inicial.json`**: só existe **uma** chave pra isso —
```json
"senha_acesso": "admin123"
```

**`bot_producao.py`** (código gerado, dois passos distintos, mesma chave):
```python
# st_002: Preencher a senha de acesso inicial do usuário
runner.fill_resilient(page, selector="#password", text_val=row.get("senha_acesso", ""), ..., step_id="st_002")
...
# st_004: Corrigir e preencher a senha de acesso correta do usuário
runner.fill_resilient(page, selector="#password", text_val=row.get("senha_acesso", ""), ..., step_id="st_004")
```

**Onde a informação morre** — `aegis_blackbox/recorder.py:1503` e `:1533`:
```python
self.schema_inputs[(self.active_scenario, selector)] = {
    "semantic_key": clean_sem_key,
    "observed_value": val,
    "type": ...
}
```
`schema_inputs` é um dict simples, chaveado por `(scenario, selector)`. Quando `#password` recebe um segundo `fill` no mesmo cenário, essa segunda escrita **sobrescreve** a primeira sem checar se o valor mudou. O evento bruto em `gravacao.json` preserva os dois valores reais — a perda acontece especificamente na montagem do dicionário semântico (`dicionario.json`), que assume implicitamente "1 seletor = 1 valor por cenário".

## Por que isso não é um bug do Sanitizer

Verificado e descartado antes de chegar aqui: o Sanitizer não decide remover nada nesse caso — ele nunca vê a informação da senha errada, porque ela já não existe mais no `schema_inputs` quando o Sanitizer processa a gravação. O código gerado até dá descrições de negócio diferentes pra `st_002`/`st_004` ("inicial" vs "corrigir e preencher a correta") — a camada de refinamento semântico (LLM, por passo) percebeu que são conceitualmente diferentes — mas ambos os passos foram amarrados à **mesma** chave de dataset, porque só existe uma entrada no dicionário pra `#password`.

## Por que isso importa (não é só sobre senha errada)

Reproduzir fielmente esse tipo de sequência pode ser **intencional** — testar que o sistema rejeita credencial errada e mostra o erro correto é um cenário de QA legítimo, não um acidente de gravação a ser "limpo". O framework hoje não consegue representar isso: **o modelo de dado (1 campo semântico = 1 valor por linha de dataset) não tem como guardar "este seletor foi preenchido duas vezes, de propósito, com valores diferentes"** dentro de uma mesma execução/linha.

Esse padrão não é exclusivo de senha — qualquer campo que um humano preencha, veja um erro de validação, e corrija (CPF mal digitado, email sem @, campo obrigatório esquecido) tem o mesmo problema estrutural.

## Direção candidata (não decidida — para discussão na próxima sessão)

Quando o Recorder detecta que o MESMO seletor recebe um valor DIFERENTE do já registrado no mesmo cenário, cunhar uma chave semântica nova e distinta em vez de sobrescrever — e essa chave precisaria virar coluna própria em `dataset_inicial.json` (populada com o valor observado, editável pelo usuário depois). O bot gerado replayaria: preenche valor A (dataset-driven) → clica → preenche valor B (outra chave, dataset-driven) → clica de novo — cada tentativa com seu próprio dado parametrizável.

**Perguntas em aberto que a próxima sessão precisa responder antes de desenhar a solução:**
1. Como nomear a chave nova de forma estável/determinística (não pode depender de LLM rodar de novo toda gravação — precisa ser algo que o Recorder consiga gerar sozinho, ex. sufixo incremental `_tentativa_2`)?
2. Como isso interage com `dataset_validator.py` (campos novos aparecendo no meio de uma gravação já em andamento) e com o fluxo de correção cirúrgica do `code_generator.py` (que hoje assume contagem de passos fixa contra o plano)?
3. Vale generalizar pra QUALQUER repetição de seletor com valor diferente, ou só faz sentido quando há um CLIQUE de submit/validação entre as duas tentativas (sinal de que é uma correção pós-erro, não só um segundo fill acidental sem consequência)?
4. Isso deveria ser opt-in (usuário marca no Cockpit "isso foi uma correção proposital, quero manter os dois valores") em vez de detecção automática — evitando o Recorder ter que adivinhar intenção?

## Fora de escopo deste documento

Este documento **não** propõe implementação — é registro de causa raiz + a pergunta certa pra próxima sessão decidir o design (provavelmente merece passar por `plan-critic` antes de virar backlog, dado que mexe no contrato central do Recorder/dicionário, usado por todo projeto já gravado).
