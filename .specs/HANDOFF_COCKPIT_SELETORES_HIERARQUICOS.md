# Plano de Correção e Melhoria para Seletores Hierárquicos (Chained Locators)

Este plano descreve as correções e melhorias necessárias para que os seletores hierárquicos funcionem de forma robusta e confiável, eliminando erros comuns de "Parent não encontrado no DOM" e "cannot access local variable".

## User Review Required

> [!IMPORTANT]
> A causa raiz dos seletores hierárquicos falharem no autocomplete (Marca, Modelo, Versão) é a **inversão de eventos** no recorder (o clique na opção é gravado antes do preenchimento da busca). Nós corrigiremos isso tratando programaticamente na fase de saneamento (`sanitizer.py`).

## Proposed Changes

---

### [Core] [runner.py](file:///C:/Projetos/aegis_rpa_suite/aegis_runner/runner.py)

#### [MODIFY] [runner.py](file:///C:/Projetos/aegis_rpa_suite/aegis_runner/runner.py)
- Adicionar a função auxiliar `_get_relative_child_selector(parent_selector, child_selector)` para relativizar o seletor do filho removendo prefixos que repetem o pai.
- Modificar `click_chained` e `fill_chained` para usar o seletor do filho relativizado, evitando que o Playwright procure o seletor completo do pai dentro dele mesmo.

---

### [Sanitizer] [sanitizer.py](file:///C:/Projetos/aegis_rpa_suite/aegis_sanitizer/sanitizer.py)

#### [MODIFY] [sanitizer.py](file:///C:/Projetos/aegis_rpa_suite/aegis_sanitizer/sanitizer.py)
- Implementar inversão programática de eventos de Autocomplete na fase de saneamento (se houver um `CLICK` em autocomplete/opção seguido de um `FILL` no input, eles serão invertidos para que o `FILL` ocorra primeiro).
- Adicionar a função `fix_encoding(text)` para corrigir problemas de codificação de caracteres especiais (ex: `Ãlcool` -> `Álcool`) no seletor, valor e texto dos eventos.

## Verification Plan

### Automated Tests
- Executar o sanitizer no projeto `portal_segura/tests/001_teste`:
  ```powershell
  python aegis_sanitizer/sanitizer.py --project-dir projects/portal_segura/tests/001_teste
  ```
- Regenerar o código do robô usando o code generator:
  ```powershell
  python aegis_sanitizer/code_generator.py --project-dir projects/portal_segura/tests/001_teste
  ```
- Executar o robô de teste para validar o fluxo de ponta a ponta.
