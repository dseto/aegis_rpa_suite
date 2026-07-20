import os
import sys
import time
import json
import argparse
import re
import signal
import threading
import queue
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from playwright.sync_api import sync_playwright

# Reconfigura stdout para utf-8
sys.stdout.reconfigure(encoding='utf-8')

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)

# Constante contendo o Javascript que é injetado no browser para capturar interações
JS_MINIMAL_LISTENERS = """
(function() {
    if (window.__aegis_recorder_active__) return;
    window.__aegis_recorder_active__ = true;
    window.__aegis_recording_paused__ = false;

    // Função auxiliar para verificar a quantidade de correspondências do seletor.
    // Suporta pseudo-classe do Playwright :has-text() que não é nativa do browser.
    function queryLength(selector, root) {
        if (!root) root = document;
        try {
            let match = selector.match(/^(.*?):has-text\\('([^']*)'\\)(.*)$/);
            if (match) {
                let part1 = match[1].trim() || "*";
                let textToFind = match[2];
                textToFind = textToFind.replace(/\\\\'/g, "'");
                let part2 = match[3].trim();

                let containers = (root.querySelectorAll) ? root.querySelectorAll(part1) : [];
                let matchingContainers = [];
                for (let i = 0; i < containers.length; i++) {
                    let el = containers[i];
                    let txt = el.innerText || el.textContent || "";

                    // Alinha semântica com Playwright :has-text e nova lógica do recorder:
                    // extrai primeira linha não vazia (evita falso match com texto que cruza
                    // fronteira de elemento). Se textToFind é primeira linha de um elemento
                    // multi-linha, casa. Se textToFind é colapsado (.g. "A B C D"),
                    // precisa estar completamente em uma linha única do elemento.
                    let firstLine = txt.split('\\n').map(l => l.trim()).filter(l => l.length > 0)[0] || '';

                    if (firstLine.includes(textToFind)) {
                        matchingContainers.push(el);
                    }
                }
                
                if (!part2) {
                    return matchingContainers.length;
                }
                
                let totalCount = 0;
                if (part2.startsWith('~') || part2.startsWith('+')) {
                    let isAdjacent = part2.startsWith('+');
                    let siblingSelector = part2.substring(1).trim();
                    for (let c of matchingContainers) {
                        let sibling = c.nextElementSibling;
                        while (sibling) {
                            if (sibling.matches && sibling.matches(siblingSelector)) {
                                totalCount++;
                                if (isAdjacent) break;
                            }
                            if (isAdjacent) break;
                            sibling = sibling.nextElementSibling;
                        }
                    }
                } else {
                    // Descendente
                    for (let c of matchingContainers) {
                        let descendants = c.querySelectorAll ? c.querySelectorAll(part2) : [];
                        totalCount += descendants.length;
                    }
                }
                return totalCount;
            } else {
                return (root.querySelectorAll) ? root.querySelectorAll(selector).length : 0;
            }
        } catch (err) {
            return 0;
        }
    }

    // Seletores resilientes Aegis V4
    //
    // Normaliza o elemento-alvo (redireciona SVG/path, sobe até o elemento
    // interativo mais próximo ou ancestral com atributo de teste). Usado
    // tanto pela cascata de geração de seletor quanto pela coleta de
    // candidatos múltiplos, para garantir que ambas operem sobre o MESMO
    // elemento resolvido.
    function resolveAegisTargetElement(element) {
        if (!element || element === document.body || element === document.documentElement) return null;

        // Redireciona cliques em caminhos de SVG para o elemento gráfico raiz SVG
        if (element.tagName && element.tagName.toLowerCase() === 'path') {
            element = element.closest('svg') || element;
        }

        // Redireciona para o elemento interativo mais próximo se o clique foi em um elemento interno (ex: mat-icon ou span)
        let interactive = element.closest('button, a, [role="button"], [role="menuitem"], [role="tab"], [role="option"], [role="checkbox"], [role="radio"], [role="switch"], [role="combobox"], [role="listbox"], [role="treeitem"], [role="gridcell"], [role="link"], mat-option, .mat-option, .mat-menu-item');
        if (interactive) {
            element = interactive;
        } else {
            // Se não for um elemento interativo padrão, tenta encontrar o ancestral mais próximo que possua um atributo de teste
            let testIdAncestor = element.closest("[data-testid], [data-test-id], [data-test], [data-qa]");
            if (testIdAncestor) {
                element = testIdAncestor;
            }
        }
        return element;
    }

    // Provedores de estratégia de seletor (cascata Aegis V4), extraídos do
    // corpo original de getAegisSelector SEM alterar nenhuma heurística —
    // cada provedor reproduz byte-a-byte o trecho equivalente da versão
    // anterior, apenas isolado para poder ser tentado independentemente por
    // getAegisSelectorCandidates. A ORDEM da lista é a ordem de prioridade
    // original (data-testid → id → has-text/label → genérico).
    const AEGIS_SELECTOR_STRATEGY_PROVIDERS = [
        // 1) data-testid / data-test-id / data-test / data-qa
        function testIdStrategy(el) {
            const testIdAttrs = ['data-testid', 'data-test-id', 'data-test', 'data-qa'];
            for (let attr of testIdAttrs) {
                let val = el.getAttribute(attr);
                if (val) {
                    return `[${attr}='${val}']`;
                }
            }
            return null;
        },
        // 2) id estável (ignora ids dinâmicos numéricos ou gerados pelo Angular Material)
        function idStrategy(el) {
            if (el.id && !/\\d{8,}/.test(el.id) && !el.id.startsWith('mat-input-') && !el.id.startsWith('mat-select-')) {
                return `#${el.id}`;
            }
            return null;
        },
        // 3) texto visível em botão/link/item de menu/role interativo
        function textStrategy(el) {
            let elementRole = el.getAttribute('role') || '';
            let isInteractiveRole = ['button', 'menuitem', 'tab', 'option', 'checkbox', 'radio', 'switch', 'combobox', 'listbox', 'treeitem', 'gridcell', 'link'].includes(elementRole);
            let isMenuClass = el.classList.contains('mat-option') || el.classList.contains('mat-menu-item');

            if ((el.tagName === 'BUTTON' || el.tagName === 'A' || isMenuClass || isInteractiveRole) &&
                el.innerText && el.innerText.trim().length > 0 && el.innerText.trim().length < 45) {

                // Extrai primeira linha não vazia (evita :has-text colapsando \n em espaço).
                // Playwright :has-text nunca casa texto que cruza fronteira de elemento.
                let lines = el.innerText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                if (lines.length === 0) return null;
                let firstLine = lines[0];

                // Se truncado (len >= 50) e linha única, descarta último token.
                let isTruncated = firstLine.length >= 50;
                if (isTruncated && lines.length === 1) {
                    let tokens = firstLine.split(/\\s+/);
                    if (tokens.length < 2) return null;
                    firstLine = tokens.slice(0, -1).join(' ');
                }

                // Normaliza espaços internos (colapsa múltiplos espaços) e escapa aspas simples.
                let cleanText = firstLine.replace(/\\s+/g, ' ').trim().replace(/'/g, "\\\\'");
                if (cleanText.length < 3) return null;

                let tagPrefix = isInteractiveRole ? `[role='${elementRole}']` : el.tagName.toLowerCase();
                return `${tagPrefix}:has-text('${cleanText}')`;
            }
            return null;
        },
        // 4) placeholder / name / rótulo de formulário (input, textarea, select, dropdown trigger)
        function formFieldStrategy(el) {
            let isDropdownTrigger = (el.tagName === 'DIV' || el.tagName === 'SPAN') &&
                el.innerText &&
                (/selecione/i.test(el.innerText) || /escolha/i.test(el.innerText) || el.classList.contains('select-trigger') || el.classList.contains('mat-select-trigger') || el.classList.contains('mat-select-value-text'));

            if (!(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || isDropdownTrigger)) {
                return null;
            }

            if (el.tagName !== 'DIV' && el.tagName !== 'SPAN' && el.getAttribute('placeholder')) {
                return `${el.tagName.toLowerCase()}[placeholder='${el.getAttribute('placeholder')}']`;
            }
            if (el.tagName !== 'DIV' && el.tagName !== 'SPAN' && el.getAttribute('name')) {
                return `${el.tagName.toLowerCase()}[name='${el.getAttribute('name')}']`;
            }

            // Resolvedor Universal de Rótulo de Formulário
            let labelText = "";
            let selectorType = "";
            let labelNode = null;

            if (el.id) {
                let label = document.querySelector(`label[for='${el.id}']`);
                if (label) {
                    labelText = label.innerText || label.textContent || "";
                    selectorType = "explicit-label";
                    labelNode = label;
                }
            }
            if (!labelText) {
                let parentLabel = el.closest('label');
                if (parentLabel) {
                    let tempLabel = parentLabel.cloneNode(true);
                    let innerInput = tempLabel.querySelector('input, textarea, select');
                    if (innerInput) innerInput.remove();
                    labelText = tempLabel.innerText || tempLabel.textContent || "";
                    selectorType = "implicit-label";
                    labelNode = parentLabel;
                }
            }
            if (!labelText) {
                let sibling = el.previousElementSibling;
                while (sibling) {
                    if (sibling.tagName === 'LABEL') {
                        labelText = sibling.innerText || sibling.textContent || "";
                        selectorType = "sibling-label";
                        labelNode = sibling;
                        break;
                    }
                    sibling = sibling.previousElementSibling;
                }
            }
            if (!labelText) {
                // Fix 3: procura label dentro do parent imediato (DIV wrapper case)
                let parentDiv = el.parentElement;
                if (parentDiv) {
                    let labelInParent = parentDiv.querySelector('label');
                    if (labelInParent) {
                        labelText = labelInParent.innerText || labelInParent.textContent || "";
                        selectorType = "parent-div-label";
                        labelNode = labelInParent;
                    }
                }
            }
            if (!labelText) {
                const formField = el.closest('mat-form-field');
                if (formField) {
                    const labelEl = formField.querySelector('.mat-form-field-label');
                    if (labelEl) {
                        labelText = labelEl.innerText || labelEl.textContent || "";
                        selectorType = "mat-form-field";
                        labelNode = formField;
                    }
                }
            }
            if (!labelText) {
                let formGroup = el.closest('.form-group, .form-control-container, .field, .mb-3, .form-row, .form-field');
                if (formGroup) {
                    let label = formGroup.querySelector('label, .label');
                    if (label) {
                        labelText = label.innerText || label.textContent || "";
                        selectorType = "form-group";
                        labelNode = formGroup;
                    }
                }
            }

            labelText = labelText.trim();
            if (labelText && labelText.length < 45) {
                let cleanLabel = labelText.replace(/\\s+/g, ' ').trim().replace(/'/g, "\\\\'");
                let tag = el.tagName.toLowerCase();
                if (selectorType === "mat-form-field") {
                    return `mat-form-field:has-text('${cleanLabel}') ${tag}`;
                } else if (selectorType === "implicit-label") {
                    return `label:has-text('${cleanLabel}') ${tag}`;
                } else if (selectorType === "explicit-label" || selectorType === "sibling-label") {
                    return `label:has-text('${cleanLabel}') ~ ${tag}`;
                } else if (selectorType === "form-group") {
                    let classList = Array.from(labelNode.classList);
                    let semClass = classList.find(cls => cls.includes('form-group') || cls.includes('field') || cls.includes('mb-3'));
                    if (semClass) {
                        return `.${semClass}:has-text('${cleanLabel}') ${tag}`;
                    }
                    return `div:has-text('${cleanLabel}') ${tag}`;
                }
            }
            return null;
        },
        // 4.5) Fix 1: input com tipo específico (range, color, etc) sem identidade textual
        function typeSpecificInputStrategy(el) {
            if (el.tagName !== 'INPUT') return null;
            let inputType = el.getAttribute('type') || 'text';
            if (['range', 'color', 'file', 'hidden'].includes(inputType)) {
                // Tenta achar label no parent imediato (Fix 1)
                let labelText = "";
                let parentDiv = el.parentElement;
                if (parentDiv) {
                    let label = parentDiv.querySelector('label');
                    if (label) {
                        labelText = (label.innerText || label.textContent || "").trim();
                    }
                }
                if (labelText && labelText.length < 45) {
                    return `div:has(label:has-text('${labelText}')) input[type='${inputType}']`;
                }
                // Fallback: tipo é identidade única
                return `input[type='${inputType}']`;
            }
            return null;
        },
        // 5) fallback genérico: apenas a tag do elemento
        function tagStrategy(el) {
            return el.tagName.toLowerCase();
        }
    ];

    // Sobe a árvore DOM adicionando prefixos de ancestrais estáveis até o
    // seletor ficar único (ou esgotar a profundidade/máx de tentativas) —
    // reproduz byte-a-byte a lógica de "ancestor-climbing" original.
    function makeAegisSelectorUnique(el, baseSelector) {
        const testIdAttrs = ['data-testid', 'data-test-id', 'data-test', 'data-qa'];

        let genericTags = ['img', 'span', 'div', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'i', 'b', 'strong', 'em', 'small', 'a', 'svg', 'mat-icon'];
        let isGeneric = genericTags.includes(el.tagName.toLowerCase());
        let isButtonOrMenu = el.tagName.toLowerCase() === 'button' || el.classList.contains('mat-option') || el.classList.contains('mat-menu-item');
        let isSemanticRole = ['button', 'menuitem', 'tab', 'option', 'checkbox', 'radio', 'switch', 'combobox', 'listbox', 'treeitem', 'gridcell', 'link'].includes(el.getAttribute('role') || '');
        let isFormFieldWithLabel = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') &&
            (baseSelector.startsWith('mat-form-field:has-text') || baseSelector.startsWith('label:has-text') || baseSelector.startsWith('div:has-text') || baseSelector.includes(':has-text'));

        if ((isGeneric || isButtonOrMenu || isSemanticRole || isFormFieldWithLabel) && (!el.id || /\\d{8,}/.test(el.id))) {
            let parent = el.parentElement;
            let depth = 0;
            let root = el.getRootNode();
            let isUnique = queryLength(baseSelector, root) === 1;

            while (parent && depth < 5 && !isUnique) {
                let parentTag = parent.tagName.toLowerCase();
                let parentTestId = null;
                for (let attr of testIdAttrs) {
                    if (parent.getAttribute(attr)) {
                        parentTestId = `[${attr}='${parent.getAttribute(attr)}']`;
                        break;
                    }
                }

                let prefix = null;
                if (parentTestId) {
                    prefix = parentTestId;
                } else if (parent.id && !/\\d{8,}/.test(parent.id) && !parent.id.startsWith('mat-input-')) {
                    prefix = `#${parent.id}`;
                } else if (['article', 'section', 'nav', 'aside', 'header', 'footer', 'form', 'table', 'tr', 'fieldset', 'details', 'summary'].includes(parentTag)) {
                    prefix = parentTag;
                } else {
                    let classList = Array.from(parent.classList);
                    let semanticClass = classList.find(cls =>
                        cls.includes('post') || cls.includes('card') || cls.includes('item') ||
                        cls.includes('thumbnail') || cls.includes('menu') || cls.includes('wrapper') ||
                        cls.includes('container') || cls.includes('block') || cls.includes('grid')
                    );
                    if (semanticClass) {
                        prefix = `.${semanticClass}`;
                    }
                }

                if (prefix) {
                    let candidateSelector = `${prefix} ${baseSelector}`;
                    let matchesCount = queryLength(candidateSelector, root);
                    baseSelector = candidateSelector; // Mantém o mais restritivo obtido
                    if (matchesCount === 1) {
                        isUnique = true;
                        break;
                    }
                }
                parent = parent.parentElement;
                depth++;
            }

            if (!isUnique) {
                console.warn(`[Aegis Recorder] Seletor gerado pode ser ambíguo na página: "${baseSelector}"`);
                return { selector: baseSelector, ambiguous: true };
            }
        }
        return { selector: baseSelector, ambiguous: false };
    }

    // Computa o seletor "primário" reproduzindo EXATAMENTE a cascata
    // original: para cada elemento, apenas UM provedor de estratégia se
    // aplica (é um if/else-if, não um "tenta todos até achar único") —
    // seguido da subida de ancestrais para tentar unicidade. Retorna o
    // baseSelector mesmo se a unicidade não puder ser garantida (apenas
    // emite o console.warn de aviso), IDÊNTICO ao getAegisSelector antigo.
    // Retorna também o rawSelector (pré-climbing) para permitir que o
    // coletor de candidatos evite reprocessar a mesma estratégia (e
    // duplicar o console.warn de ambiguidade).
    function computeAegisPrimarySelectorRaw(el) {
        let baseSelector = "";
        let hasTestId = false;

        let testIdResult = AEGIS_SELECTOR_STRATEGY_PROVIDERS[0](el); // testIdStrategy
        if (testIdResult) {
            baseSelector = testIdResult;
            hasTestId = true;
        }

        if (!hasTestId) {
            let idResult = AEGIS_SELECTOR_STRATEGY_PROVIDERS[1](el); // idStrategy
            if (idResult) {
                baseSelector = idResult;
            } else {
                baseSelector = el.tagName.toLowerCase();
                let textResult = AEGIS_SELECTOR_STRATEGY_PROVIDERS[2](el); // textStrategy
                let formFieldResult = AEGIS_SELECTOR_STRATEGY_PROVIDERS[3](el); // formFieldStrategy
                let typeSpecificResult = AEGIS_SELECTOR_STRATEGY_PROVIDERS[4](el); // typeSpecificInputStrategy (Fix 1)
                if (textResult) {
                    baseSelector = textResult;
                } else if (formFieldResult) {
                    baseSelector = formFieldResult;
                } else if (typeSpecificResult) {
                    baseSelector = typeSpecificResult;
                }
                // Se nenhuma estratégia específica se aplicou, mantém o fallback de tag (5).
            }
        }

        return baseSelector;
    }

    function computeAegisPrimarySelector(el) {
        return makeAegisSelectorUnique(el, computeAegisPrimarySelectorRaw(el)).selector;
    }

    // Coleta até 3 candidatos de seletor ÚNICOS gerados por estratégias
    // DISTINTAS (data-testid, id, texto/rótulo, tag genérica...), na mesma
    // ordem de prioridade da cascata original. O candidato [0] é sempre o
    // seletor primário — mesmo que ele não seja único (mantendo o
    // comportamento antigo de getAegisSelector); os demais candidatos
    // (fallback_selectors) SÃO exigidos únicos.
    function getAegisSelectorCandidates(element, isNested) {
        let resolved = resolveAegisTargetElement(element);
        if (!resolved) return [];

        // --- DETECÇÃO DE SUBMENU / DROPDOWN HOVER-TO-REVEAL ---
        // Mantém o comportamento recursivo original: quando aplicável, o
        // resultado é o seletor combinado único (sem candidatos alternativos).
        if (!isNested) {
            let subMenuContainer = resolved.closest('.sub-menu, .dropdown-menu, .dropdown, [role="menu"], .hfe-has-submenu');
            if (subMenuContainer) {
                let parentMenu = subMenuContainer.parentElement;
                if (parentMenu && parentMenu !== resolved) {
                    let parentSelector = getAegisSelector(parentMenu, true);
                    let childSelector = getAegisSelector(resolved, true);
                    if (parentSelector && childSelector) {
                        if (childSelector.startsWith(parentSelector + " ")) {
                            childSelector = childSelector.substring(parentSelector.length).trim();
                        }
                        return [parentSelector + " >> " + childSelector];
                    }
                }
            }
        }

        let shadowPath = "";
        let current = resolved;
        while (current) {
            let parent = current.parentNode || current.host;
            if (parent && parent.nodeType === 11) {
                let host = parent.host;
                let hostSelector = getAegisSelector(host);
                shadowPath = hostSelector + " >> ";
                current = parent.host;
                break;
            }
            current = parent;
        }

        let el = resolved;
        let root = el.getRootNode();

        let primaryRaw = computeAegisPrimarySelectorRaw(el);
        let primaryResult = makeAegisSelectorUnique(el, primaryRaw);
        let primarySelector = shadowPath + primaryResult.selector;
        if (!primarySelector) return [];

        let candidates = [primarySelector];
        let seen = new Set([primarySelector]);
        let rawSeen = new Set([primaryRaw]);

        for (let provider of AEGIS_SELECTOR_STRATEGY_PROVIDERS) {
            if (candidates.length >= 3) break;
            let rawSelector = provider(el);
            if (!rawSelector) continue;
            // Já processado como candidato primário — evita repetir o
            // climbing (e o console.warn de ambiguidade) para a mesma estratégia.
            if (rawSeen.has(rawSelector)) continue;
            rawSeen.add(rawSelector);

            let finalSelector = shadowPath + makeAegisSelectorUnique(el, rawSelector).selector;
            if (seen.has(finalSelector)) continue;

            try {
                if (queryLength(finalSelector, root) === 1) {
                    seen.add(finalSelector);
                    candidates.push(finalSelector);
                }
            } catch (err) {
                // Seletor inválido para esta estratégia — ignora e tenta a próxima
            }
        }

        // Ambiguidade do PRIMÁRIO detectada pelo próprio climbing de ancestrais
        // (isUnique nunca virou true) é anexada ao array como propriedade extra
        // -- não muda o contrato de retorno (array de strings) que getAegisSelector
        // e os handlers de click/fill já consomem. Consumida em record_action
        // (Python) para rebaixar confidence/ativar weak_selector: achado real do
        // piloto de site novo (.specs/relatorio-piloto-site-novo.md) -- o console.warn
        // de ambiguidade já existia mas nunca chegava no confidence/plano.
        candidates.primaryAmbiguous = primaryResult.ambiguous;
        return candidates;
    }
    window.getAegisSelectorCandidates = getAegisSelectorCandidates;

    // Wrapper: comportamento byte-idêntico ao getAegisSelector original —
    // retorna sempre o candidato primário (mesma cascata de antes), ou ""
    // se o elemento não resolver (ex.: elemento raiz/coordenada pura).
    function getAegisSelector(element, isNested) {
        let candidates = getAegisSelectorCandidates(element, isNested);
        return candidates.length > 0 ? candidates[0] : "";
    }
    window.getAegisSelector = getAegisSelector;

    function getSemanticFieldName(el) {
        let name = el.getAttribute('name') || el.getAttribute('placeholder') || "";
        const isDynamicId = el.id && (el.id.startsWith('mat-input-') || el.id.startsWith('mat-select-') || /\\d{4,}/.test(el.id));
        if (!name || isDynamicId) {
            const formField = el.closest('mat-form-field');
            if (formField) {
                const labelEl = formField.querySelector('.mat-form-field-label');
                if (labelEl) {
                    name = labelEl.innerText || labelEl.textContent || "";
                }
            }
        }
        if (!name) {
            name = el.id || "";
        }
        return name;
    }
    window.getSemanticFieldName = getSemanticFieldName;

    // ── AEGIS PARENT DATA EXTRACTOR ──────────────────────────────────────────
    // Detecta se o seletor base é ambíguo e sobe a árvore DOM para encontrar
    // um ancestral estável que sirva como escopo hierárquico (chained locator).
    // Retorna null se o seletor já for único — sem necessidade de parent.
    function getAegisParentData(element) {
        if (!element || element === document.body || element === document.documentElement) return null;

        // Aplica as mesmas normalizações do getAegisSelector
        if (element.tagName && element.tagName.toLowerCase() === 'path') {
            element = element.closest('svg') || element;
        }

        let interactive = element.closest('button, a, [role="button"], [role="menuitem"], [role="tab"], [role="option"], [role="checkbox"], [role="radio"], [role="switch"], [role="combobox"], [role="listbox"], [role="treeitem"], [role="gridcell"], [role="link"], mat-option, .mat-option, .mat-menu-item');
        if (interactive) {
            element = interactive;
        } else {
            let testIdAncestor = element.closest("[data-testid], [data-test-id], [data-test], [data-qa]");
            if (testIdAncestor) {
                element = testIdAncestor;
            }
        }

        // Gera o seletor base (sem pais) para testar unicidade
        let baseSelector = "";
        const testIdAttrs = ['data-testid', 'data-test-id', 'data-test', 'data-qa'];
        let hasTestId = false;
        for (let attr of testIdAttrs) {
            let val = element.getAttribute(attr);
            if (val) {
                baseSelector = `[${attr}='${val}']`;
                hasTestId = true;
                break;
            }
        }

        if (!hasTestId) {
            if (element.id && !/\\d{8,}/.test(element.id) && !element.id.startsWith('mat-input-') && !element.id.startsWith('mat-select-')) {
                baseSelector = `#${element.id}`;
            } else {
                baseSelector = element.tagName.toLowerCase();
                let elementRole = element.getAttribute('role') || '';
                let isInteractiveRole = ['button', 'menuitem', 'tab', 'option', 'checkbox', 'radio', 'switch', 'combobox', 'listbox', 'treeitem', 'gridcell', 'link'].includes(elementRole);
                let isMenuClass = element.classList.contains('mat-option') || element.classList.contains('mat-menu-item');

                if ((element.tagName === 'BUTTON' || element.tagName === 'A' || isMenuClass || isInteractiveRole) &&
                    element.innerText && element.innerText.trim().length > 0 && element.innerText.trim().length < 45) {
                    let cleanText = element.innerText.replace(/\\s+/g, ' ').trim().replace(/'/g, "\\\\'");
                    let tagPrefix = isInteractiveRole ? `[role='${elementRole}']` : element.tagName.toLowerCase();
                    baseSelector = `${tagPrefix}:has-text('${cleanText}')`;
                } else if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || element.tagName === 'SELECT') {
                    if (element.getAttribute('placeholder')) {
                        baseSelector = `${element.tagName.toLowerCase()}[placeholder='${element.getAttribute('placeholder')}']`;
                    } else if (element.getAttribute('name')) {
                        baseSelector = `${element.tagName.toLowerCase()}[name='${element.getAttribute('name')}']`;
                    } else if (element.id) {
                        baseSelector = `#${element.id}`;
                    }
                }
            }
        }

        let root = element.getRootNode();

        // Testa unicidade do seletor base
        let isUnique = false;
        try {
            isUnique = queryLength(baseSelector, root) === 1;
        } catch (e) {
            isUnique = false;
        }

        // Se já é único, não precisa de parent
        if (isUnique) return null;

        // Seletor ambíguo — sobe a árvore DOM procurando ancestral estável
        let parent = element.parentElement;
        let depth = 0;
        const semanticTags = ['article', 'section', 'nav', 'aside', 'header', 'footer', 'form', 'table', 'tr', 'fieldset', 'details', 'summary'];
        const semanticClasses = ['card', 'item', 'row', 'container', 'grid', 'panel', 'block', 'wrapper', 'post', 'thumbnail', 'menu'];

        while (parent && depth < 5) {
            let parentTag = parent.tagName.toLowerCase();

            // Verifica data-testid no ancestral
            for (let attr of testIdAttrs) {
                let val = parent.getAttribute(attr);
                if (val) {
                    return { selector: `[${attr}='${val}']`, has_text: null };
                }
            }

            // Verifica ID estável
            if (parent.id && !/\\d{8,}/.test(parent.id) && !parent.id.startsWith('mat-input-') && !parent.id.startsWith('mat-select-')) {
                return { selector: `#${parent.id}`, has_text: null };
            }

            // Verifica tag semântica
            let isSemanticTag = semanticTags.includes(parentTag);

            // Verifica classes semânticas
            let classList = Array.from(parent.classList);
            let semanticClass = classList.find(cls => semanticClasses.some(sc => cls.toLowerCase().includes(sc)));

            if (isSemanticTag || semanticClass) {
                // Extrai texto curto do ancestral (prefere headings, limita a ~40 chars)
                let parentText = null;

                // Tenta encontrar heading filho primeiro
                let heading = parent.querySelector('h1, h2, h3, h4, h5, h6, strong');
                if (heading) {
                    let txt = (heading.innerText || heading.textContent || "").replace(/\\s+/g, ' ').trim();
                    if (txt.length > 0 && txt.length <= 40) {
                        parentText = txt;
                    } else if (txt.length > 40) {
                        parentText = txt.substring(0, 40);
                    }
                }

                // Fallback: primeiro text node ou textContent limitado
                if (!parentText) {
                    let txt = (parent.innerText || parent.textContent || "").replace(/\\s+/g, ' ').trim();
                    if (txt.length > 0 && txt.length <= 40) {
                        parentText = txt;
                    } else if (txt.length > 40) {
                        parentText = txt.substring(0, 40);
                    }
                }

                let parentSelector = semanticClass ? `.${semanticClass}` : parentTag;
                return {
                    selector: parentSelector,
                    has_text: parentText
                };
            }

            parent = parent.parentElement;
            depth++;
        }

        // Nenhum ancestral estável encontrado — mantém fallback de coordenadas
        return null;
    }
    window.getAegisParentData = getAegisParentData;

    // Injeção do Indicador Micro-LED via Shadow DOM Fechado
    function injectIndicator() {
        if (document.getElementById('aegis-indicator-host')) return;
        const host = document.createElement('div');
        host.id = 'aegis-indicator-host';
        host.style.position = 'fixed';
        host.style.top = '16px';
        host.style.right = '16px';
        host.style.zIndex = '2147483647';
        host.style.pointerEvents = 'none';

        const shadow = host.attachShadow({mode: 'closed'});
        
        const badge = document.createElement('div');
        badge.id = 'aegis-badge';
        badge.style.display = 'flex';
        badge.style.alignItems = 'center';
        badge.style.gap = '8px';
        badge.style.background = 'rgba(15, 10, 25, 0.85)';
        badge.style.backdropFilter = 'blur(8px)';
        badge.style.border = '1px solid rgba(124, 58, 237, 0.5)';
        badge.style.padding = '6px 12px';
        badge.style.borderRadius = '20px';
        badge.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.1)';
        badge.style.fontFamily = 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        badge.style.userSelect = 'none';
        
        const led = document.createElement('div');
        led.id = 'aegis-led';
        led.style.width = '8px';
        led.style.height = '8px';
        led.style.borderRadius = '50%';
        led.style.backgroundColor = '#ff5555';
        led.style.boxShadow = '0 0 8px #ff5555';
        led.style.transition = 'all 0.3s ease';
        
        const label = document.createElement('span');
        label.id = 'aegis-label';
        label.innerText = 'AEGIS REC';
        label.style.color = '#ffffff';
        label.style.fontSize = '10px';
        label.style.fontWeight = '700';
        label.style.letterSpacing = '1px';
        label.style.textShadow = '0 0 2px rgba(255,255,255,0.3)';
        
        const style = document.createElement('style');
        style.textContent = `
            @keyframes pulse {
                0% { opacity: 0.5; transform: scale(0.95); }
                50% { opacity: 1; transform: scale(1.05); }
                100% { opacity: 0.5; transform: scale(0.95); }
            }
            .recording {
                animation: pulse 1.5s infinite ease-in-out;
            }
        `;
        led.classList.add('recording');
        
        badge.appendChild(led);
        badge.appendChild(label);
        shadow.appendChild(badge);
        shadow.appendChild(style);
        document.body.appendChild(host);

        window.__aegis_update_indicator__ = function(paused) {
            window.__aegis_recording_paused__ = paused;
            if (paused) {
                led.style.backgroundColor = '#33cc99';
                led.style.boxShadow = '0 0 8px #33cc99';
                led.classList.remove('recording');
                label.innerText = 'PAUSADO';
                label.style.color = '#33cc99';
                badge.style.border = '1px solid rgba(51, 204, 153, 0.5)';
            } else {
                led.style.backgroundColor = '#ff5555';
                led.style.boxShadow = '0 0 8px #ff5555';
                led.classList.add('recording');
                label.innerText = 'AEGIS REC';
                label.style.color = '#ffffff';
                badge.style.border = '1px solid rgba(124, 58, 237, 0.5)';
            }
        };
    }

    if (document.body) {
        injectIndicator();
    } else {
        document.addEventListener('DOMContentLoaded', injectIndicator);
    }

    window.__aegis_last_recorded_values__ = {};
    const EXCLUDED_INPUT_TYPES = ['checkbox', 'radio', 'submit', 'button', 'image', 'hidden', 'file'];

    function recordFill(target) {
        if (!target) return;
        if (target.tagName !== 'INPUT' && target.tagName !== 'TEXTAREA' && target.tagName !== 'SELECT') return;
        if (target.tagName === 'INPUT' && EXCLUDED_INPUT_TYPES.includes(target.type)) return;
        
        let selectorCandidates = getAegisSelectorCandidates(target);
        let selector = selectorCandidates.length > 0 ? selectorCandidates[0] : "";
        // <select multiple>: .value só retorna a 1a opção selecionada (spec
        // do HTMLSelectElement) — descartaria silenciosamente as demais.
        // Lê todas via .selectedOptions quando for multi-select.
        let val = (target.tagName === 'SELECT' && target.multiple)
            ? Array.from(target.selectedOptions).map(o => o.value)
            : target.value;
        let valKey = Array.isArray(val) ? JSON.stringify(val) : val;

        // Evita duplicar se o valor já foi gravado recentemente
        if (window.__aegis_last_recorded_values__[selector] === valKey) {
            return;
        }
        window.__aegis_last_recorded_values__[selector] = valKey;

        let parentData = getAegisParentData(target);
        let name = getSemanticFieldName(target);
        let fillEvent = {
            type: 'fill',
            tag: target.tagName,
            selector: selector,
            value: val,
            name: name,
            placeholder: target.getAttribute('placeholder') || "",
            id: target.id || ""
        };
        if (parentData !== null) {
            fillEvent.parent = parentData;
        }
        // Seletor primário é coordenada pura ou vazio — sem base confiável
        // para propor fallbacks.
        if (selector && selectorCandidates.length > 1) {
            fillEvent.fallback_selectors = selectorCandidates.slice(1);
        }
        if (selectorCandidates.primaryAmbiguous) {
            fillEvent.selector_ambiguous = true;
        }
        window.pythonRecordAction(JSON.stringify(fillEvent));
    }

    function flushAllInputs() {
        // 'select' excluído aqui de propósito: já é coberto de forma
        // confiável pelo listener nativo 'change' (dispara sempre que o
        // usuário de fato escolhe uma opção) — não passa por flush.
        //
        // input/textarea usam baseline PREGUIÇOSA (lazy) por selector: a 1a
        // vez que um campo é visto aqui, seu valor atual vira baseline
        // silenciosa (sem emitir evento) — só a partir da 2a leitura, se o
        // valor mudou em relação a essa baseline, é tratado como ação real
        // do usuário. Isso evita gravar como "ação do usuário" um valor
        // pré-preenchido no HTML (`value="X"` no markup) ou hidratado
        // tardiamente por um SPA (ex.: Angular renderizando um campo depois
        // do load inicial, sem reload de página) — mesma classe de bug já
        // corrigida para <select> nativo, generalizada aqui sem depender de
        // timing de carregamento da página.
        const inputs = document.querySelectorAll('input, textarea');
        for (let input of inputs) {
            if (input.closest('#aegis-indicator-host')) continue;
            if (input.tagName === 'INPUT' && EXCLUDED_INPUT_TYPES.includes(input.type)) continue;
            let selector = getAegisSelector(input);
            let val = input.value;
            if (!(selector in window.__aegis_last_recorded_values__)) {
                window.__aegis_last_recorded_values__[selector] = val;
                continue;
            }
            if (val && window.__aegis_last_recorded_values__[selector] !== val) {
                recordFill(input);
            }
        }
    }
    window.flushAllInputs = flushAllInputs;

    let lastClickTime = 0;
    let lastClickSelector = "";

    // Listeners em fase de captura
    document.addEventListener('click', function(e) {
        if (window.__aegis_recording_paused__) return;
        if (e.target.closest('#aegis-indicator-host')) return;
        
        // Evita gravar cliques programáticos/sintéticos disparados por frameworks
        if (!e.isTrusted) return;
        
        let now = Date.now();
        let clickCandidates = getAegisSelectorCandidates(e.target);
        let selector = clickCandidates.length > 0 ? clickCandidates[0] : "";

        // Evita gravação de cliques duplicados consecutivos (double-clicks rápidos) no mesmo seletor ou sub-seletor dentro de 250ms
        if (now - lastClickTime < 250 && (selector === lastClickSelector || selector.includes(lastClickSelector) || lastClickSelector.includes(selector))) {
            return;
        }
        lastClickTime = now;
        lastClickSelector = selector;

        // Garante a gravação de todos os inputs pendentes antes do clique
        flushAllInputs();

        let parentData = getAegisParentData(e.target);

        let x_percent = e.clientX / window.innerWidth;
        let y_percent = e.clientY / window.innerHeight;

        let clickEvent = {
            type: 'click',
            tag: e.target.tagName,
            selector: selector,
            text: e.target.innerText ? e.target.innerText.trim().substring(0, 50) : "",
            x_percent: x_percent,
            y_percent: y_percent
        };

        if (parentData !== null) {
            clickEvent.parent = parentData;
        }
        // Seletor primário é coordenada pura ou vazio — sem base confiável
        // para propor fallbacks.
        if (selector && clickCandidates.length > 1) {
            clickEvent.fallback_selectors = clickCandidates.slice(1);
        }
        if (clickCandidates.primaryAmbiguous) {
            clickEvent.selector_ambiguous = true;
        }

        window.pythonRecordAction(JSON.stringify(clickEvent));
    }, true);

    document.addEventListener('change', function(e) {
        if (window.__aegis_recording_paused__) return;
        if (e.target.closest('#aegis-indicator-host')) return;
        recordFill(e.target);
    }, true);

    document.addEventListener('blur', function(e) {
        if (window.__aegis_recording_paused__) return;
        if (e.target.closest('#aegis-indicator-host')) return;
        recordFill(e.target);
    }, true);

    // Não gravamos no evento 'input' imediatamente para evitar gravar valores parciais enquanto digita (ex: "admin" -> "admin@...")
    // O valor final será coletado socraticamente no 'blur', 'change', 'click' ou 'beforeunload'
    document.addEventListener('input', function(e) {
        if (window.__aegis_recording_paused__) return;
        if (e.target.closest('#aegis-indicator-host')) return;
    }, true);

    window.addEventListener('beforeunload', function() {
        flushAllInputs();
    });

    // ── AEGIS ANTI-BOT DETECTOR ──────────────────────────────────────────────
    // Intercepta addEventListener para detectar campos input que registram
    // listeners de keydown/keyup — padrão típico de detecção de cadência
    // humana (Zone.js, Angular Material, formulários bancários e gov).
    // Campos detectados receberão fill_strategy: "HUMAN_LIKE" no dicionário.
    (function() {
        if (window.__aegis_keydown_detector_active__) return;
        window.__aegis_keydown_detector_active__ = true;
        window.__aegis_keydown_fields__ = new Set();

        const _original_addEventListenerFn = EventTarget.prototype.addEventListener;
        EventTarget.prototype.addEventListener = function(type, listener, options) {
            // ── AEGIS_DEBUG_TIMING (instrumentação temporária, default OFF) ──
            // Ativada via window.__aegis_debug_timing__ (injetado pelo lado
            // Python quando AEGIS_RECORDER_DEBUG_TIMING=true). Loga TODA
            // chamada interceptada pelo monkey-patch (não só keydown/keyup —
            // a filtragem por tipo abaixo é análise de negócio, não captura
            // de custo) para medir o overhead do próprio monkey-patch.
            // Diagnóstico de timeout de fill() no campo Celular (Portal
            // Segura). NUNCA ativa em execução normal (flag default false).
            if (window.__aegis_debug_timing__) {
                try {
                    const __t0 = performance.now();
                    let __elId = "";
                    if (this instanceof Element) {
                        __elId = this.id || this.getAttribute('name') ||
                            (window.getAegisSelector ? window.getAegisSelector(this) : "") || "";
                    }
                    const __tag = (this && this.tagName) ? this.tagName : "";
                    console.log("[AEGIS_TIMING] addEventListener type=" + type +
                        " tag=" + __tag + " el=" + __elId + " t=" + __t0.toFixed(3));
                } catch (e) {
                    // Instrumentação de diagnóstico nunca deve quebrar o fluxo real
                }
            }
            try {
                if ((type === 'keydown' || type === 'keyup') &&
                    this instanceof Element &&
                    (this.tagName === 'INPUT' || this.tagName === 'TEXTAREA')) {

                    const selector = window.getAegisSelector
                        ? window.getAegisSelector(this)
                        : (this.getAttribute('data-testid') || this.id || this.name || '');

                    if (selector) {
                        window.__aegis_keydown_fields__.add(selector);
                    }
                }
            } catch (e) {
                // Protege a inicialização de bibliotecas externas (ex: Zone.js) silenciando exceções
            }
            return _original_addEventListenerFn.call(this, type, listener, options);
        };
    })();
    // ── FIM AEGIS ANTI-BOT DETECTOR ──────────────────────────────────────────

    // Atalho Ctrl+Shift+V para gravação de áudio do microfone
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.shiftKey && e.code === 'KeyV') {
            e.preventDefault();
            if (window.pythonToggleVoice) {
                window.pythonToggleVoice().then(res => {
                    if (res.status === 'started') {
                        showAegisToast("🎙️ Gravação de Voz Iniciada... Fale agora!");
                    } else if (res.status === 'stopped') {
                        showAegisToast("✅ Voz Gravada!\\nTranscrição: " + res.transcription, 6000);
                    }
                });
            }
        }
    });

    // Atalho Ctrl+Shift+A para caixa de diálogo flutuante de anotação de texto
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.shiftKey && e.code === 'KeyA') {
            e.preventDefault();
            showAegisAnnotationModal();
        }
    });

    function showAegisAnnotationModal() {
        let modal = document.getElementById('aegis-annotation-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'aegis-annotation-modal';
            modal.style.position = 'fixed';
            modal.style.top = '50%';
            modal.style.left = '50%';
            modal.style.transform = 'translate(-50%, -50%)';
            modal.style.backgroundColor = 'rgba(15, 10, 25, 0.98)';
            modal.style.color = '#fff';
            modal.style.padding = '20px';
            modal.style.borderRadius = '10px';
            modal.style.border = '2px solid #7c3aed';
            modal.style.zIndex = '2147483647';
            modal.style.fontFamily = 'sans-serif';
            modal.style.boxShadow = '0 10px 25px rgba(0,0,0,0.8)';
            modal.style.width = '350px';
            
            modal.innerHTML = `
                <h4 style="margin: 0 0 10px 0; font-size: 14px; color: #a78bfa; display: flex; align-items: center; gap: 6px;">📝 Anotação de Negócio Aegis</h4>
                <p style="margin: 0 0 12px 0; font-size: 11px; color: #cbd5e1;">Descreva a intenção de negócio do passo atual:</p>
                <textarea id="aegis-annotation-input" rows="3" style="width: 100%; box-sizing: border-box; background: #0f0a19; border: 1px solid #4c1d95; color: #fff; padding: 8px; border-radius: 6px; font-size: 12px; resize: none; outline: none; margin-bottom: 12px;"></textarea>
                <div style="display: flex; justify-content: flex-end; gap: 8px;">
                    <button id="aegis-annotation-cancel" style="background: transparent; border: 1px solid #cbd5e1; color: #cbd5e1; padding: 6px 12px; border-radius: 4px; font-size: 11px; cursor: pointer;">Cancelar</button>
                    <button id="aegis-annotation-save" style="background: #7c3aed; border: none; color: #fff; padding: 6px 12px; border-radius: 4px; font-size: 11px; cursor: pointer; font-weight: bold;">Salvar</button>
                </div>
            `;
            document.body.appendChild(modal);
            
            document.getElementById('aegis-annotation-cancel').addEventListener('click', () => {
                modal.style.display = 'none';
            });
            
            document.getElementById('aegis-annotation-save').addEventListener('click', () => {
                const text = document.getElementById('aegis-annotation-input').value.trim();
                if (text) {
                    if (window.pythonAddAnnotation) {
                        window.pythonAddAnnotation(text);
                    }
                    showAegisToast("📝 Anotação salva: " + text);
                }
                modal.style.display = 'none';
                document.getElementById('aegis-annotation-input').value = '';
            });
        }
        
        modal.style.display = 'block';
        setTimeout(() => {
            document.getElementById('aegis-annotation-input').focus();
        }, 100);
    }

    function showAegisToast(text, duration = 3000) {
        let toast = document.getElementById('aegis-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'aegis-toast';
            toast.style.position = 'fixed';
            toast.style.bottom = '20px';
            toast.style.right = '20px';
            toast.style.backgroundColor = 'rgba(15, 10, 25, 0.95)';
            toast.style.color = '#fff';
            toast.style.padding = '12px 18px';
            toast.style.borderRadius = '8px';
            toast.style.border = '1px solid #7c3aed';
            toast.style.fontSize = '12px';
            toast.style.zIndex = '2147483647';
            toast.style.fontFamily = 'sans-serif';
            toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.5)';
            toast.style.transition = 'all 0.3s ease';
            document.body.appendChild(toast);
        }
        toast.innerText = text;
        toast.style.opacity = '1';
        toast.style.display = 'block';
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => { toast.style.display = 'none'; }, 300);
        }, duration);
    }
})();
"""

def evaluate_selector_reliability(selector):
    """Calcula o score de confiabilidade do seletor e retorna (score, tipo)."""
    if not selector:
        return 0, "empty"
        
    test_attributes = ["data-testid", "data-test-id", "data-test", "data-qa"]
    if any(attr in selector for attr in test_attributes):
        if " >> " in selector:
            return 90, "data-testid-anchor"
        return 100, "data-testid"
        
    if "#" in selector and not re.search(r"\d{4,}", selector) and not "mat-input-" in selector and not "mat-select-" in selector:
        return 90, "id"
        
    if "[name=" in selector or "[placeholder=" in selector:
        return 80, "name-or-placeholder"
        
    if ":has-text(" in selector:
        return 70, "has-text"
        
    if "." in selector:
        return 60, "class"
        
    return 40, "tag"


class AegisControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        response = {"success": True}

        try:
            if path == "/api/status":
                response = self.server.control_callbacks["get_status"]()
            elif path == "/api/pause":
                self.server.control_callbacks["set_paused"](True)
                response["message"] = "Paused"
            elif path == "/api/resume":
                self.server.control_callbacks["set_paused"](False)
                response["message"] = "Resumed"
            elif path == "/api/scenario":
                name = query.get("name", [""])[0]
                if name:
                    self.server.control_callbacks["set_scenario"](name)
                    response["message"] = f"Scenario updated to {name}"
                else:
                    self.send_response(400)
                    response = {"success": False, "error": "Missing 'name' parameter"}
            elif path == "/api/annotation":
                text = query.get("text", [""])[0]
                if text:
                    self.server.control_callbacks["add_annotation"](text)
                    response["message"] = "Annotation recorded"
                else:
                    self.send_response(400)
                    response = {"success": False, "error": "Missing 'text' parameter"}
            elif path == "/api/voice/start":
                success = self.server.control_callbacks["start_voice"]()
                response["message"] = "Voice recording started" if success else "Failed to start voice recording"
                response["success"] = success
            elif path == "/api/voice/stop":
                transcription = self.server.control_callbacks["stop_voice"]()
                response["message"] = "Voice recording stopped"
                response["transcription"] = transcription
            elif path == "/api/scan":
                self.server.control_callbacks["trigger_scan"]()
                response["message"] = "Scan triggered"
            elif path == "/api/finish":
                self.server.control_callbacks["finish_session"]()
                response["message"] = "Session finishing"
            else:
                self.send_response(404)
                response = {"success": False, "error": "Not Found"}
        except Exception as e:
            response = {"success": False, "error": str(e)}

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))


def start_control_server(callbacks, port=9900):
    server = HTTPServer(('localhost', port), AegisControlHandler)
    server.control_callbacks = callbacks
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def scan_fields_python(page, record_action_fn):
    try:
        inputs = page.locator("input, textarea, select, .mat-select-trigger").all()
        for el in inputs:
            if not el.is_visible():
                continue
            
            is_aegis = el.evaluate("el => el.closest('#aegis-indicator-host') !== null")
            if is_aegis:
                continue

            tag_name = el.evaluate("el => el.tagName.toLowerCase()")
            is_mat_select = el.evaluate("el => el.classList.contains('mat-select-trigger')")
            
            value = ""
            field_type = tag_name
            if is_mat_select:
                field_type = "select"
                val_el = el.locator(".mat-select-value").first
                if val_el.is_visible():
                    value = val_el.inner_text().strip()
                if value == "Selecione":
                    value = ""
            else:
                value = el.input_value() if tag_name in ("input", "textarea") else el.evaluate("el => el.value")
                el_type = el.evaluate("el => el.type")
                if el_type in ('checkbox', 'radio'):
                    value = "true" if el.is_checked() else "false"

            selector = el.evaluate("el => window.getAegisSelector ? window.getAegisSelector(el) : ''")
            if not selector:
                continue

            name = el.evaluate("el => window.getSemanticFieldName ? window.getSemanticFieldName(el) : ''")
            placeholder = el.get_attribute("placeholder") or ""
            id_val = el.get_attribute("id") or ""

            record_action_fn(json.dumps({
                "type": "scan_field",
                "tag": tag_name.upper(),
                "selector": selector,
                "value": value,
                "name": name,
                "placeholder": placeholder,
                "id": id_val,
                "fieldType": field_type
            }, ensure_ascii=False))
    except Exception:
        pass


class AegisRecorder:
    def __init__(self, url: str, output_dir: str, auto_simulate: bool = False, control_port: int = None):
        self.url = url
        self.output_dir = os.path.abspath(output_dir) if output_dir else r"C:\Projetos\Lab\telemetry_data"
        self.auto_simulate = auto_simulate
        self.control_port = control_port

        os.makedirs(self.output_dir, exist_ok=True)

        self.events_log = []
        self.captured_network = {}
        
        self.active_scenario = "default"
        self.schema_inputs = {}   # key: (scenario, selector) -> {semantic_key, observed_value, type}
        self.schema_outputs = {}  # key: (scenario, selector) -> semantic_key
        
        self.recording_paused = False
        self.session_finished = False
        self.browser_closed = False
        self.finish_requested = False
        self.force_scan_requested = False
        self.reset_requested = False
        self.recording_voice = False
        self.voice_note_counter = 0
        
        self.recording_paused_requested = None
        self.voice_recording_requested = None
        self.new_scenario_requested = None
        self.new_annotation_requested = None

        self.anti_bot_fields_cache = []

        # Flag de diagnóstico temporária (default OFF): quando true, injeta
        # window.__aegis_debug_timing__ = true na página, ligando o log
        # [AEGIS_TIMING] no monkey-patch de addEventListener (bloco AEGIS
        # ANTI-BOT DETECTOR). Nunca ativa em execução normal.
        self.debug_timing_enabled = os.environ.get("AEGIS_RECORDER_DEBUG_TIMING", "false").lower() in ("true", "1", "yes")

        # Instâncias de infraestrutura Playwright e Servidor
        self.browser = None
        self.context = None
        self.page = None
        self.http_server = None

    def get_default_regex(self, sem_key: str, field_type: str) -> str:
        sem_key_lower = sem_key.lower()
        if "cpf" in sem_key_lower:
            return r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"
        if "cnpj" in sem_key_lower:
            return r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"
        if "cep" in sem_key_lower:
            return r"^\d{5}-?\d{3}$"
        if "email" in sem_key_lower:
            return r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if field_type == "date":
            return r"^\d{2}/\d{2}/\d{4}$|^\d{4}-\d{2}-\d{2}$"
        return ""

    def save_telemetry_files_disk(self, active_evaluate: bool = False):
        """Salva a telemetria, o dicionário estruturado e o dataset inicial no disco."""
        try:
            # Consolida e limpa a lista de eventos para eliminar digitações parciais/duplicadas e cliques repetidos
            cleaned_events = []
            for event in self.events_log:
                ev_type = event.get("type")
                selector = event.get("selector")
                
                if ev_type == "fill" and selector:
                    # Varre a lista de trás para frente para encontrar e remover preenchimentos anteriores redundantes do mesmo campo
                    idx_to_remove = None
                    for i in range(len(cleaned_events) - 1, -1, -1):
                        prev_ev = cleaned_events[i]
                        prev_type = prev_ev.get("type")
                        prev_sel = prev_ev.get("selector")
                        
                        if prev_type == "fill" and prev_sel == selector:
                            idx_to_remove = i
                            break
                        
                        # Barreira de navegação/submissão: cliques em botões, links ou submissões reais
                        if prev_type == "click" and prev_sel and ("button" in prev_sel or "submit" in prev_sel or "btn" in prev_sel or prev_ev.get("tag") in ["BUTTON", "A"]):
                            break
                            
                    if idx_to_remove is not None:
                        cleaned_events.pop(idx_to_remove)
                        
                    # Remove cliques/fills consecutivos remanescentes no próprio seletor
                    while cleaned_events and cleaned_events[-1].get("selector") == selector and cleaned_events[-1].get("type") in ["fill", "click"]:
                        cleaned_events.pop()
                        
                    cleaned_events.append(event)
                else:
                    cleaned_events.append(event)
            self.events_log = cleaned_events

            # Coleta campos com keydown listeners detectados pelo interceptor JS
            anti_bot_detected = []
            if active_evaluate and not self.browser_closed and self.page:
                try:
                    # Força a gravação de qualquer input pendente na página antes de processar a telemetria
                    self.page.evaluate("() => { if (window.flushAllInputs) { window.flushAllInputs(); } }")
                except Exception:
                    pass
                
                try:
                    anti_bot_detected = self.page.evaluate(
                        "() => window.__aegis_keydown_fields__ ? [...window.__aegis_keydown_fields__] : []"
                    )
                    self.anti_bot_fields_cache = anti_bot_detected
                except Exception:
                    pass
            else:
                anti_bot_detected = self.anti_bot_fields_cache

            # Auto-preservação de tradução semântica prévia (por seletor): se
            # este projeto já foi sanitizado antes (dicionario.json tem chaves
            # de negócio como "usuario_login" em vez de "username"), regravar
            # o fluxo NÃO deve perder essa tradução. Antes de montar os
            # dicionários novos, carrega o dicionario.json existente e monta
            # um mapa selector -> chave_semantica_antiga; abaixo, cada campo
            # novo que casar pelo MESMO seletor físico herda a chave antiga em
            # vez da chave crua recém-capturada — bot já gerado continua
            # lendo os mesmos nomes de campo do dataset sem precisar re-rodar
            # Sanitizer manualmente só por causa da regravação. Casamento por
            # seletor (não por nome) porque é o único identificador estável
            # entre uma gravação e outra do mesmo elemento.
            old_input_key_by_selector = {}
            old_output_key_by_selector = {}
            existing_dict_path = os.path.join(self.output_dir, "dicionario.json")
            if os.path.exists(existing_dict_path):
                try:
                    with open(existing_dict_path, "r", encoding="utf-8") as f:
                        existing_dict = json.load(f) or {}
                    for old_key, old_info in (existing_dict.get("fields") or {}).items():
                        old_sel = old_info.get("selector")
                        if old_sel:
                            old_input_key_by_selector[old_sel] = old_key
                    for old_key, old_info in (existing_dict.get("outputs") or {}).items():
                        old_sel = old_info.get("selector")
                        if old_sel:
                            old_output_key_by_selector[old_sel] = old_key
                except Exception:
                    pass

            # Compila o dicionário estruturado e a primeira linha do dataset
            fields_schema = {}
            dataset_row = {
                "id": 1,
                "aegis_scenario": "default",
                "expected_result": "SUCCESS",
                "expected_error_token": None
            }
            csv_headers = ["id", "aegis_scenario", "expected_result", "expected_error_token"]
            csv_first_row = ["1", "default", "SUCCESS", ""]

            for (scenario, selector), info in self.schema_inputs.items():
                sem_key = old_input_key_by_selector.get(selector, info["semantic_key"])
                val = info["observed_value"]
                field_type = info["type"]

                score, sel_type = evaluate_selector_reliability(selector)
                fill_strategy = "HUMAN_LIKE" if selector in anti_bot_detected else "DIRECT"

                fields_schema[sem_key] = {
                    "selector": selector,
                    "type": field_type,
                    "observed_value": val,
                    "required": True,
                    "confidence": score,
                    "selector_type": sel_type,
                    "fill_strategy": fill_strategy,
                    "description": f"Campo de entrada {sem_key} mapeado na tela",
                    "validation_rules": {
                        "regex": self.get_default_regex(sem_key, field_type),
                        "enum": []
                    }
                }

                dataset_row[sem_key] = val
                if sem_key not in csv_headers:
                    csv_headers.append(sem_key)
                    csv_first_row.append(str(val))

            # Compila dicionario de saídas
            outputs_schema = {}
            for (scenario, selector), sem_key in self.schema_outputs.items():
                sem_key = old_output_key_by_selector.get(selector, sem_key)
                score, sel_type = evaluate_selector_reliability(selector)
                outputs_schema[sem_key] = {
                    "selector": selector,
                    "confidence": score,
                    "selector_type": sel_type,
                    "description": f"Dado extraído da tela para o campo {sem_key}"
                }
                dataset_row[sem_key] = ""
                if sem_key not in csv_headers:
                    csv_headers.append(sem_key)
                    csv_first_row.append("")

            # 1. Salva gravação bruta
            telemetry_file = os.path.join(self.output_dir, "gravacao.json")
            with open(telemetry_file, "w", encoding="utf-8") as f:
                json.dump({
                    "initial_url": self.url,
                    "events": self.events_log,
                    "network_payloads": self.captured_network,
                    "anti_bot_fields": anti_bot_detected
                }, f, indent=4, ensure_ascii=False)

            # Aviso residual: a auto-preservação acima (old_input_key_by_selector/
            # old_output_key_by_selector) já reaplica a tradução semântica prévia
            # para todo campo cujo SELETOR físico bateu com o dicionario.json
            # anterior — cobre o caso comum de regravar o mesmo fluxo sem
            # dessincronizar o bot já gerado. Este aviso só dispara pro que
            # sobrou sem casar: campo genuinamente novo, ou o seletor do campo
            # mudou de verdade na página (mudança estrutural real do site) — aí
            # sim a tradução antiga não tem como ser recuperada automaticamente
            # e Sanitizer + Code Generator precisam rodar de novo.
            dict_file = os.path.join(self.output_dir, "dicionario.json")
            if os.path.exists(dict_file):
                try:
                    with open(dict_file, "r", encoding="utf-8") as f:
                        existing_dict = json.load(f)
                    existing_fields = set((existing_dict or {}).get("fields", {}).keys())
                    new_fields = set(fields_schema.keys())
                    unresolved = existing_fields - new_fields
                    if unresolved:
                        print(
                            "[AEGIS] [WARNING] Alguns campos do dicionario.json anterior não foram "
                            f"encontrados pelo mesmo seletor nesta nova gravação: {sorted(unresolved)}. "
                            "A tradução semântica desses campos específicos NÃO pôde ser preservada "
                            "automaticamente (seletor mudou ou campo saiu da tela) — se o bot já "
                            "gerado depende deles, rode Sanitizer + Code Generator novamente."
                        )
                except Exception:
                    pass

            # 2. Salva dicionário de dados estruturado
            with open(dict_file, "w", encoding="utf-8") as f:
                json.dump({
                    "initial_url": self.url,
                    "fields": fields_schema,
                    "outputs": outputs_schema
                }, f, indent=4, ensure_ascii=False)

            # 3. Salva dataset inicial em JSON
            dataset_file = os.path.join(self.output_dir, "dataset_inicial.json")
            with open(dataset_file, "w", encoding="utf-8") as f:
                json.dump([dataset_row], f, indent=4, ensure_ascii=False)

            # 4. Salva template CSV com as colunas
            template_file = os.path.join(self.output_dir, "template.csv")
            with open(template_file, "w", encoding="utf-8") as f:
                f.write(",".join(csv_headers) + "\n")
                f.write(",".join(csv_first_row) + "\n")

            # 5. Atualiza project.json se existir no output_dir
            project_json_path = os.path.join(self.output_dir, "project.json")
            if os.path.exists(project_json_path):
                try:
                    with open(project_json_path, "r", encoding="utf-8") as f:
                        proj = json.load(f)
                    proj["status"] = "recorded"
                    proj["last_activity"] = datetime.now().isoformat(timespec="seconds")
                    with open(project_json_path, "w", encoding="utf-8") as f:
                        json.dump(proj, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"[WARNING] Não foi possível atualizar project.json: {e}")
        except Exception as e:
            print(f"[WARNING] Erro ao gravar telemetria no disco: {e}")
            sys.stdout.flush()

    def record_action(self, event_json_str: str):
        """Callback acionado pela página via JavaScript exposto para registrar ações do usuário."""
        if self.recording_paused or self.session_finished:
            return
        try:
            ev = json.loads(event_json_str)
            ev["timestamp"] = datetime.now().isoformat()
            ev["scenario"] = self.active_scenario

            # Tratamentos específicos de tipos de ação
            ev_type = ev.get("type", "").lower()
            selector = ev.get("selector", "")
            val = ev.get("value", "")
            name = ev.get("name", "")

            if ev_type == "fill":
                is_date = bool((ev.get("tag", "").lower() == "input" and ev.get("id", "").lower().endswith("-date")) or \
                          (isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val)))
                ev["is_date"] = is_date

                if is_date and isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                    parts = val.split("-")
                    val = f"{parts[2]}/{parts[1]}/{parts[0]}"
                    ev["value"] = val
                
                # C4: Priorização de data-testid
                semantic_key = name or selector
                if "data-testid" in selector:
                    match = re.search(r"data-testid='([^']+)'", selector)
                    if match:
                        semantic_key = match.group(1)
                elif "data-test-id" in selector:
                    match = re.search(r"data-test-id='([^']+)'", selector)
                    if match:
                        semantic_key = match.group(1)

                clean_sem_key = semantic_key.replace("-", "_").lower()
                
                # Registra como campo de entrada no dicionário de dados estruturado
                self.schema_inputs[(self.active_scenario, selector)] = {
                    "semantic_key": clean_sem_key,
                    "observed_value": val,
                    "type": "date" if is_date else ("select" if ev.get("tag", "").lower() == "select" else "string")
                }

            elif ev_type == "scan_field":
                # Varredura cooperativa: campos detectados já preenchidos
                if val:
                    is_date = bool((ev.get("fieldType") == "date") or \
                               (isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val)))
                              
                    if is_date and isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                        parts = val.split("-")
                        val = f"{parts[2]}/{parts[1]}/{parts[0]}"
                        ev["value"] = val

                    semantic_key = name or selector
                    if "data-testid" in selector:
                        match = re.search(r"data-testid='([^']+)'", selector)
                        if match:
                            semantic_key = match.group(1)
                    elif "data-test-id" in selector:
                        match = re.search(r"data-test-id='([^']+)'", selector)
                        if match:
                            semantic_key = match.group(1)

                    clean_sem_key = semantic_key.replace("-", "_").lower()
                    
                    is_select = ev.get("fieldType") == "select" or ev.get("tag", "").lower() == "select"
                    self.schema_inputs[(self.active_scenario, selector)] = {
                        "semantic_key": clean_sem_key,
                        "observed_value": val,
                        "type": "date" if is_date else ("select" if is_select else "string")
                    }
                return

            if selector:
                score = evaluate_selector_reliability(selector)[0]
                # O JS já detecta ambiguidade real durante o climbing de
                # ancestrais (isUnique nunca vira true) e emitia só um
                # console.warn descartado -- achado real do piloto de site
                # novo (.specs/relatorio-piloto-site-novo.md): seletores
                # `:has-text(...)` pontuam 70 fixo (nunca < 70, nunca vira
                # weak_selector) mesmo quando o próprio recorder já sabe que
                # são ambíguos. Rebaixa o score abaixo do limiar de
                # weak_selector (70) quando `selector_ambiguous` vem true no
                # evento, herdando o sinal de unicidade real em vez de só a
                # estratégia usada.
                if ev.get("selector_ambiguous") and score >= 70:
                    score = 60
                ev["confidence"] = score

            self.events_log.append(ev)
            print(f"[AEGIS CAPTURE] Ação: {ev_type.upper()} | Seletor: {selector} | Valor/Texto: {val or ev.get('text', '')}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[AEGIS CAPTURE WARNING] Falha ao processar evento JSON: {e}")
            sys.stdout.flush()

    def record_annotation(self, note_text: str):
        """Callback acionado pela CLI ou HTTP para criar anotações de negócio/extração."""
        if self.session_finished:
            return
        
        # Casos especiais de anotações (ex: extract)
        if note_text.startswith("extract:"):
            parts = note_text.split(":")
            if len(parts) >= 3:
                selector = parts[1].strip()
                semantic_key = parts[2].strip().replace("-", "_").lower()
                self.schema_outputs[(self.active_scenario, selector)] = semantic_key
                print(f"[AEGIS ANNOTATION] Campo de extração de saída cadastrado: {semantic_key} -> {selector}")
                sys.stdout.flush()

        ev = {
            "type": "annotation",
            "text": note_text,
            "scenario": self.active_scenario,
            "timestamp": datetime.now().isoformat()
        }
        self.events_log.append(ev)
        print(f"[AEGIS ANNOTATION] Regra anotada no cenário '{self.active_scenario}': {note_text}")
        sys.stdout.flush()

    def start_voice_recording(self):
        """Inicia a gravação de áudio do microfone usando a API MCI do Windows."""
        if sys.platform != "win32":
            print("[AEGIS VOICE WARNING] Gravação de voz MCI é suportada apenas em ambiente Windows.")
            return False
            
        if self.recording_voice:
            print("[AEGIS VOICE WARNING] Já existe uma gravação de voz em andamento.")
            return False

        try:
            import ctypes
            winmm = ctypes.windll.winmm
            # Abre o canal de gravação waveaudio
            winmm.mciSendStringW("open new type waveaudio alias aegisvoice", None, 0, 0)
            # Configura qualidade aceitável (16-bit, 16kHz, Mono para Whisper)
            winmm.mciSendStringW("set aegisvoice bitspersample 16 samplespersec 16000 channels 1", None, 0, 0)
            # Inicia gravação de forma assíncrona
            winmm.mciSendStringW("record aegisvoice", None, 0, 0)
            self.recording_voice = True
            print("[AEGIS VOICE] Gravação de voz iniciada...")
            return True
        except Exception as e:
            print(f"[AEGIS VOICE ERROR] Falha ao iniciar gravação MCI: {e}")
            return False

    def stop_voice_recording(self) -> str:
        """Para a gravação de áudio, salva em .wav, transcreve usando CognitiveGateway e registra anotação."""
        if not self.recording_voice or sys.platform != "win32":
            return ""

        try:
            import ctypes
            winmm = ctypes.windll.winmm
            
            self.voice_note_counter += 1
            filename = f"voice_note_{self.voice_note_counter}.wav"
            filepath = os.path.join(self.output_dir, filename)
            
            # Para a gravação
            winmm.mciSendStringW("stop aegisvoice", None, 0, 0)
            # Salva no arquivo filepath (usando aspas para caminhos com espaço)
            winmm.mciSendStringW(f'save aegisvoice "{filepath}"', None, 0, 0)
            winmm.mciSendStringW("close aegisvoice", None, 0, 0)
            
            self.recording_voice = False
            print(f"[AEGIS VOICE] Gravação de voz parada. Arquivo salvo em: {filepath}")
            
            # Executa transcrição cognitiva via CognitiveGateway
            from aegis_runner.cognitive_fallback import CognitiveGateway
            gateway = CognitiveGateway(project_dir=self.output_dir)
            
            transcription = gateway.transcribe_audio(filepath)
            
            # Registra anotação transcrita
            self.record_annotation(transcription)
            
            # Adiciona marcação de voz para o Sanitizer cruzar posteriormente
            if self.events_log:
                self.events_log[-1]["voice_annotation"] = transcription
                
            return transcription
            
        except Exception as e:
            print(f"[AEGIS VOICE ERROR] Falha ao parar gravação MCI: {e}")
            self.recording_voice = False
            return ""

    def toggle_voice_from_page(self):
        """Invocado via Playwright exposto para a página browser do usuário."""
        if self.recording_voice:
            text = self.stop_voice_recording()
            return {"status": "stopped", "transcription": text}
        else:
            success = self.start_voice_recording()
            return {"status": "started", "success": success}

    def update_scenario(self, new_scenario_name: str):
        self.active_scenario = new_scenario_name
        print(f"\n[AEGIS SCENARIO] >>> Alterando Cenário Ativo para: '{self.active_scenario.upper()}' <<<")
        sys.stdout.flush()

    def set_recording_paused(self, paused: bool):
        self.recording_paused = paused
        state_str = "PAUSADO (Indicador Verde)" if paused else "ATIVO (Indicador Vermelho)"
        print(f"[AEGIS STATE] Monitoramento de Gravação: {state_str}")
        sys.stdout.flush()

    def reset_recorder_session(self):
        self.events_log.clear()
        self.captured_network.clear()
        self.schema_inputs.clear()
        self.schema_outputs.clear()
        self.active_scenario = "default"
        print("[AEGIS RECORDER] Gravação resetada com sucesso!")
        sys.stdout.flush()

    def finish_recorder_session(self):
        self.session_finished = True
        print("[AEGIS RECORDER] Solicitação de encerramento de sessão recebida.")
        sys.stdout.flush()

    def handle_response(self, response):
        """Intercepta requisições de rede para documentar payloads de validação (API)."""
        try:
            url = response.url
            # Filtra apenas requisições AJAX típicas do Portal do projeto
            if "/api/" in url or "consulta" in url or "valida" in url or "dados" in url:
                status = response.status
                if status == 200:
                    method = response.request.method
                    try:
                        text = response.text()
                        # Armazena em cache para documentação de rede
                        self.captured_network[url] = {
                            "method": method,
                            "status": status,
                            "response_preview": text[:1000]
                        }
                    except Exception:
                        pass
        except Exception:
            pass

    def handle_filechooser(self, file_chooser):
        """Registra a ocorrência de diálogos de input do tipo file."""
        ev = {
            "type": "filechooser",
            "timestamp": datetime.now().isoformat(),
            "scenario": self.active_scenario
        }
        self.events_log.append(ev)
        print("[AEGIS CAPTURE] Diálogo de seleção de arquivos interceptado.")
        sys.stdout.flush()

    def handle_termination_signal(self, signum, frame):
        self.finish_requested = True
        print(f"\n[AEGIS] Sinal {signum} de término recebido. Finalizando gravação de forma limpa...")
        sys.stdout.flush()

    def get_status_callback(self):
        return {
            "success": True,
            "paused": self.recording_paused,
            "scenario": self.active_scenario,
            "events_count": len(self.events_log),
            "recording_voice": self.recording_voice
        }

    def start_voice_callback(self):
        self.voice_recording_requested = 'start'
        start_time = time.time()
        while self.voice_recording_requested == 'start' and time.time() - start_time < 3.0:
            time.sleep(0.05)
        return self.recording_voice

    def stop_voice_callback(self):
        self.voice_recording_requested = 'stop'
        start_time = time.time()
        # Aguarda até 15s para a transcrição da LLM concluir
        while self.voice_recording_requested == 'stop' and time.time() - start_time < 15.0:
            time.sleep(0.05)
        # Localiza a transcrição no último evento
        if self.events_log:
            for ev in reversed(self.events_log):
                if ev.get("type") == "annotation" and ev.get("voice_annotation"):
                    return ev.get("voice_annotation")
        return "Gravação finalizada sem transcrição."

    def set_paused_callback(self, paused):
        self.recording_paused_requested = paused

    def set_scenario_callback(self, name):
        self.new_scenario_requested = name

    def add_annotation_callback(self, text):
        self.new_annotation_requested = text

    def trigger_scan_callback(self):
        self.force_scan_requested = True

    def finish_session_callback(self):
        self.finish_requested = True

    def process_cli_command(self, cmd: str):
        cmd_lower = cmd.lower().strip()
        if cmd_lower == "p":
            self.recording_paused_requested = not self.recording_paused
        elif cmd_lower == "v":
            if self.recording_voice:
                self.voice_recording_requested = 'stop'
            else:
                self.voice_recording_requested = 'start'
        elif cmd_lower.startswith("s "):
            name = cmd[2:].strip()
            if name:
                self.new_scenario_requested = name
        elif cmd_lower.startswith("n "):
            text = cmd[2:].strip()
            if text:
                self.new_annotation_requested = text
        elif cmd_lower == "scan":
            self.force_scan_requested = True
        elif cmd_lower == "reset":
            self.reset_requested = True
        elif cmd_lower in ("q", "f"):
            self.finish_requested = True

    def start(self):
        """Inicia e gerencia o ciclo de vida completo do gravador blackbox."""
        print("\n" + "=" * 60)
        print("🛡️ AEGIS BLACKBOX V4: PERSISTÊNCIA ATIVA E FECHAMENTO BASEADO EM EVENTOS")
        print("=" * 60)
        print(f"[TARGET URL] Alvo: {self.url}")
        print(f"[OUTPUT DIR] Destino: {self.output_dir}")
        print("-" * 60)

        # Captura de sinal para término limpo
        try:
            signal.signal(signal.SIGTERM, self.handle_termination_signal)
            if sys.platform == "win32":
                signal.signal(signal.SIGBREAK, self.handle_termination_signal)
        except Exception:
            pass

        with sync_playwright() as p:
            self.browser = p.chromium.launch(
                headless=False, channel="msedge",
                args=[
                    "--disable-features=Translate,TranslateUI",
                    "--disable-translate",
                    "--lang=pt-BR",
                ]
            )
            self.context = self.browser.new_context(locale="pt-BR")

            # Inicia trace de auditoria
            self.context.tracing.start(screenshots=True, snapshots=True, sources=True)

            self.page = self.context.new_page()

            # Console Logger e tratamento de erros do navegador (salva de forma discreta em arquivo)
            browser_log_path = os.path.join(self.output_dir, "browser_console.log")

            def log_browser_message(msg_text):
                try:
                    os.makedirs(self.output_dir, exist_ok=True)
                    with open(browser_log_path, "a", encoding="utf-8") as lf:
                        lf.write(msg_text + "\n")
                except Exception:
                    pass

            def on_console_msg(msg):
                text = msg.text
                msg_type = msg.type
                # Salva no arquivo de auditoria
                log_browser_message(f"[CONSOLE {msg_type.upper()}] {text}")
                
                # Só exibe no terminal do usuário se for erro do próprio Aegis
                if "aegis" in text.lower():
                    print(f"[BROWSER CONSOLE {msg_type.upper()}] {text}")
                    sys.stdout.flush()

            def on_page_error(err):
                err_str = str(err)
                # Salva no arquivo de auditoria
                log_browser_message(f"[PAGE ERROR] {err_str}")
                
                # Só exibe no terminal do usuário se for erro do próprio Aegis
                if "aegis" in err_str.lower():
                    print(f"[BROWSER PAGE ERROR] {err}")
                    sys.stdout.flush()

            self.page.on("console", on_console_msg)
            self.page.on("pageerror", on_page_error)

            self.page.expose_function("pythonRecordAction", self.record_action)
            self.page.expose_function("pythonToggleVoice", self.toggle_voice_from_page)
            self.page.expose_function("pythonAddAnnotation", self.record_annotation)

            # Listeners de fechamento voluntário do usuário
            def on_page_close(_):
                self.browser_closed = True
                print("\n[AEGIS] O navegador do projeto foi fechado pelo usuário.")
                sys.stdout.flush()

            self.page.on("close", on_page_close)
            self.page.on("response", self.handle_response)
            self.page.on("filechooser", self.handle_filechooser)

            # Suporte a Multi-Abas: configura dinamicamente novas abas criadas no contexto
            def on_new_page(new_page):
                print(f"[AEGIS] Nova aba detectada: {new_page.url}")
                sys.stdout.flush()
                try:
                    new_page.expose_function("pythonRecordAction", self.record_action)
                    new_page.expose_function("pythonToggleVoice", self.toggle_voice_from_page)
                    new_page.expose_function("pythonAddAnnotation", self.record_annotation)
                    new_page.on("close", lambda _: print(f"[AEGIS] Aba fechada: {new_page.url}"))
                    new_page.on("console", on_console_msg)
                    new_page.on("pageerror", on_page_error)
                    new_page.on("response", self.handle_response)
                    new_page.on("filechooser", self.handle_filechooser)
                except Exception as e:
                    print(f"[AEGIS WARNING] Erro ao configurar nova aba: {e}")
                    sys.stdout.flush()

            self.context.on("page", on_new_page)

            # Injeta a flag de diagnóstico ANTES do JS_MINIMAL_LISTENERS, para que
            # window.__aegis_debug_timing__ já exista quando o monkey-patch do
            # bloco AEGIS ANTI-BOT DETECTOR é instalado. Default OFF (string
            # vazia/ausente = falsy no JS) — não altera o comportamento normal.
            if self.debug_timing_enabled:
                self.context.add_init_script("window.__aegis_debug_timing__ = true;")
                print("[AEGIS] Diagnóstico AEGIS_RECORDER_DEBUG_TIMING ativo — logs [AEGIS_TIMING] serão gravados em browser_console.log")
                sys.stdout.flush()

            # Adiciona script de inicialização para injetar nas navegações futuras
            self.context.add_init_script(JS_MINIMAL_LISTENERS)

            print(f"Navegando para: {self.url}...")
            try:
                self.page.goto(self.url, timeout=60000, wait_until="domcontentloaded")
            except Exception as goto_err:
                print(f"[AEGIS WARNING] Limite de tempo de carregamento da página excedido: {goto_err}. Prosseguindo com carregamento parcial...")

            # Garante injeção na página inicial ativa
            try:
                if self.debug_timing_enabled:
                    self.page.evaluate("window.__aegis_debug_timing__ = true;")
                self.page.evaluate(JS_MINIMAL_LISTENERS)
            except Exception:
                pass

            print("\n[OK] Monitoramento discreto ativo. Navegue pelo Microsoft Edge.")
            print("Use comandos no console (p, s, n, scan, reset, f) ou a API HTTP (localhost:9900/api) para controlar.")
            sys.stdout.flush()

            callbacks = {
                "get_status": self.get_status_callback,
                "set_paused": self.set_paused_callback,
                "set_scenario": self.set_scenario_callback,
                "add_annotation": self.add_annotation_callback,
                "start_voice": self.start_voice_callback,
                "stop_voice": self.stop_voice_callback,
                "trigger_scan": self.trigger_scan_callback,
                "finish_session": self.finish_session_callback
            }

            # Inicializa o servidor HTTP na porta especificada
            if self.control_port:
                server_port = self.control_port
                try:
                    self.http_server = start_control_server(callbacks, port=server_port)
                    print(f"[AEGIS] Servidor HTTP de Controle ativo de forma estrita em http://localhost:{server_port}")
                    sys.stdout.flush()
                except Exception as e:
                    print(f"[AEGIS ERROR] Falha crítica ao iniciar servidor HTTP de controle na porta {server_port}: {e}")
                    sys.stdout.flush()
                    raise e
            else:
                server_port = 9900
                while server_port < 10000:
                    try:
                        self.http_server = start_control_server(callbacks, port=server_port)
                        print(f"[AEGIS] Servidor HTTP de Controle ativo em http://localhost:{server_port}")
                        sys.stdout.flush()
                        break
                    except Exception:
                        server_port += 1

            # Thread de leitura de stdin não bloqueante
            cmd_queue = queue.Queue()
            def stdin_reader_thread(q):
                while True:
                    try:
                        line = sys.stdin.readline()
                        if not line:
                            break
                        q.put(line.strip())
                    except Exception:
                        break
            t_stdin = threading.Thread(target=stdin_reader_thread, args=(cmd_queue,), daemon=True)
            t_stdin.start()

            # Loop principal cooperativo thread-safe
            if self.auto_simulate:
                print("[AEGIS AUTO-SIMULATOR] Iniciando simulação automática de preenchimento do portal...")
                sys.stdout.flush()
                try:
                    import aegis_blackbox.recorder as ab_rec
                    ab_rec.run_auto_simulation(self.page, self.update_scenario, self.record_annotation)
                except Exception as sim_err:
                    # Nao reexecuta run_auto_simulation aqui: a pagina ja avancou do
                    # estado inicial, entao rodar de novo do zero so produz um erro
                    # secundario (ex.: timeout em campo de login) que mascara sim_err,
                    # a causa real. Ver .specs/relatorio-piloto-portal_segura_pilot_unhappy.md.
                    print(f"[AEGIS AUTO-SIMULATOR ERROR] Erro na simulação: {sim_err}")
                    sys.stdout.flush()
                self.session_finished = True
            else:
                last_scan_time = time.time()
                while True:
                    if self.session_finished or self.browser_closed:
                        break
                    try:
                        self.page.wait_for_timeout(100)

                        # 1. Trata comandos da fila stdin
                        while not cmd_queue.empty():
                            cmd = cmd_queue.get_nowait()
                            self.process_cli_command(cmd)

                        # 2. Trata comandos solicitados (do servidor HTTP ou CLI)
                        if self.recording_paused_requested is not None:
                            new_state = self.recording_paused_requested
                            self.recording_paused_requested = None
                            self.set_recording_paused(new_state)
                            try:
                                self.page.evaluate(f"if (window.__aegis_update_indicator__) window.__aegis_update_indicator__({json.dumps(new_state)})")
                            except Exception:
                                pass

                        if self.new_scenario_requested is not None:
                            scenario_name = self.new_scenario_requested
                            self.new_scenario_requested = None
                            self.update_scenario(scenario_name)

                        if self.new_annotation_requested is not None:
                            annotation_text = self.new_annotation_requested
                            self.new_annotation_requested = None
                            self.record_annotation(annotation_text)

                        if self.voice_recording_requested is not None:
                            action = self.voice_recording_requested
                            self.voice_recording_requested = None
                            if action == 'start':
                                self.start_voice_recording()
                            elif action == 'stop':
                                self.stop_voice_recording()

                        if self.reset_requested:
                            self.reset_requested = False
                            self.reset_recorder_session()
                            try:
                                self.page.reload()
                            except Exception:
                                pass

                        if self.finish_requested:
                            self.finish_requested = False
                            self.finish_recorder_session()

                        if self.force_scan_requested:
                            self.force_scan_requested = False
                            scan_fields_python(self.page, self.record_action)

                        # 3. Varredura cooperativa periódica do DOM (a cada 3s)
                        if time.time() - last_scan_time >= 3.0:
                            if not self.recording_paused and not self.session_finished and not self.browser_closed:
                                scan_fields_python(self.page, self.record_action)
                                try:
                                    self.anti_bot_fields_cache = self.page.evaluate(
                                        "() => window.__aegis_keydown_fields__ ? [...window.__aegis_keydown_fields__] : []"
                                    )
                                except Exception:
                                    pass
                            last_scan_time = time.time()

                    except Exception as loop_ex:
                        err_str = str(loop_ex)
                        if "closed" in err_str.lower() or self.browser_closed:
                            self.browser_closed = True
                        else:
                            print(f"[AEGIS RECORDER ERROR] Erro no loop cooperativo: {loop_ex}")
                            sys.stdout.flush()

            print("\nFinalizando gravação de forma limpa e compilando telemetrias...")
            sys.stdout.flush()
            
            if self.session_finished and not self.browser_closed:
                try:
                    # Ocultar o micro-LED indicador Aegis para tirar um screenshot limpo
                    self.page.evaluate("() => { const w = document.getElementById('aegis-indicator-host'); if (w) w.style.display = 'none'; }")
                    screenshot_path = os.path.join(self.output_dir, "screenshot_recorder.png")
                    self.page.screenshot(path=screenshot_path)
                    print(f"[AEGIS] Screenshot da última tela gravado em: {screenshot_path}")
                    sys.stdout.flush()
                except Exception as e:
                    print(f"[WARNING] Não foi possível capturar o screenshot da última tela: {e}")
                    sys.stdout.flush()
            
            # Consolida e grava ativamente antes de fechar o browser
            self.save_telemetry_files_disk(active_evaluate=True)
            
            trace_path = os.path.join(self.output_dir, "trace.zip")
            self.context.tracing.stop(path=trace_path)
            
            try:
                self.browser.close()
            except Exception:
                pass

            print(f"\n[SUCESSO] Gravação salva em: {os.path.join(self.output_dir, 'gravacao.json')}")
            print(f"[SUCESSO] Dicionário gerado em: {os.path.join(self.output_dir, 'dicionario.json')}")
            print(f"[SUCESSO] Template gerado em:   {os.path.join(self.output_dir, 'template.csv')}")
            print("=" * 60)
            sys.stdout.flush()


# Simulação E2E mantida como função auxiliar legada para retrocompatibilidade
def run_auto_simulation(page, update_scenario, record_annotation):
    def fill_reactive_text_local(selector, text_val, delay_ms=35):
        if isinstance(selector, str):
            element = page.locator(selector).first
        else:
            element = selector
        element.scroll_into_view_if_needed()
        element.click(force=True)
        element.press("Control+A")
        element.press("Backspace")
        time.sleep(0.1)
        for char in text_val:
            page.keyboard.type(char)
            time.sleep(delay_ms / 1000.0)
        element.evaluate("el => { "
                         "let nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set; "
                         "let nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set; "
                         "if (nativeInputValueSetter && el.tagName.toLowerCase() === 'input') { nativeInputValueSetter.call(el, el.value); } "
                         "else if (nativeTextAreaValueSetter && el.tagName.toLowerCase() === 'textarea') { nativeTextAreaValueSetter.call(el, el.value); } "
                         "el.dispatchEvent(new Event('input', { bubbles: true })); "
                         "el.dispatchEvent(new Event('change', { bubbles: true })); "
                         "}")
        time.sleep(0.2)

    def select_dropdown_local(field_selector, target_option_text=None):
        try:
            page.locator(".cdk-overlay-pane").wait_for(state="detached", timeout=2000)
        except Exception:
            pass

        form_field = page.locator(field_selector).first
        form_field.scroll_into_view_if_needed()
        select_trigger = form_field.locator("mat-select, .mat-select-trigger, div[role='combobox']").first
        
        overlay_option_selector = "#cdk-overlay-container .mat-option, .cdk-overlay-pane .mat-option, mat-option"
        
        opened = False
        for attempt in range(3):
            select_trigger.evaluate("el => el.click()")
            time.sleep(0.6)
            
            options_count = page.evaluate(f"""() => document.querySelectorAll('{overlay_option_selector}').length""")
            if options_count > 0:
                opened = True
                break
            print(f"[AEGIS SIMULATOR WARNING] Tentativa {attempt + 1}: Dropdown {field_selector} não abriu. Retentando...")
            time.sleep(0.4)

        if not opened:
            print(f"[AEGIS SIMULATOR ERROR] Falha grave ao abrir dropdown {field_selector} após 3 tentativas.")
            return

        options_data = page.evaluate(f"""() => {{
            const elms = Array.from(document.querySelectorAll('{overlay_option_selector}'));
            return elms.map((el, idx) => ({{
                index: idx,
                text: el.innerText || el.textContent || '',
                visible: el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none'
            }}));
        }}""")
        
        options = [opt for opt in options_data if opt['visible']]
        if not options:
            options = options_data
            
        best_opt = None
        if target_option_text:
            target_norm = target_option_text.lower().strip()
            for opt in options:
                if target_norm in opt['text'].lower():
                    best_opt = opt
                    break
                    
        if not best_opt and options:
            best_opt = options[0]
            
        if best_opt:
            best_idx = best_opt['index']
            page.evaluate("""([idx, selector]) => {
                const elms = document.querySelectorAll(selector);
                const el = elms[idx];
                if (el) {
                    el.scrollIntoView({ block: 'center', behavior: 'instant' });
                    el.click();
                }
            }""", [best_idx, overlay_option_selector])
        else:
            print(f"[AEGIS SIMULATOR WARNING] Nenhuma opção encontrada para o dropdown {field_selector}.")
        time.sleep(0.6)

    def click_next_step_local():
        print("[AEGIS SIMULATOR] Aguardando o botão 'Avançar' ser habilitado no DOM...")
        page.wait_for_function("() => { const btn = document.getElementById('btn-next-step'); return btn && !btn.disabled; }", timeout=15000)
        time.sleep(0.4)
        page.locator("#btn-next-step").first.evaluate("el => el.click()")
        print("[AEGIS SIMULATOR] Botão 'Avançar' clicado.")
        time.sleep(1.5)

    def fill_autocomplete_local(field_selector, search_text, option_text):
        input_el = page.locator(field_selector).first
        input_el.scroll_into_view_if_needed()
        fill_reactive_text_local(input_el, search_text)
        time.sleep(0.6)
        
        # Aguarda aparecer a lista de sugestões (ex: mat-option)
        option_selector = ".mat-autocomplete-panel .mat-option, mat-option, .cdk-overlay-pane mat-option"
        try:
            page.locator(option_selector).first.wait_for(state="visible", timeout=3000)
        except Exception:
            print(f"[AEGIS SIMULATOR WARNING] Opções do autocomplete {field_selector} não apareceram. Forçando enter...")
            input_el.press("Enter")
            time.sleep(0.5)
            return

        options_data = page.evaluate(f"""() => {{
            const elms = Array.from(document.querySelectorAll('{option_selector}'));
            return elms.map((el, idx) => ({{
                index: idx,
                text: el.innerText || el.textContent || '',
                visible: el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none'
            }}));
        }}""")
        
        options = [opt for opt in options_data if opt['visible']]
        if not options:
            options = options_data
            
        best_opt = None
        target_norm = option_text.lower().strip()
        for opt in options:
            if target_norm in opt['text'].lower():
                best_opt = opt
                break
        if not best_opt and options:
            best_opt = options[0]
            
        if best_opt:
            best_idx = best_opt['index']
            page.evaluate("""([idx, selector]) => {
                const elms = document.querySelectorAll(selector);
                const el = elms[idx];
                if (el) {
                    el.scrollIntoView({ block: 'center', behavior: 'instant' });
                    el.click();
                }
            }""", [best_idx, option_selector])
        else:
            input_el.press("Enter")
        time.sleep(0.5)

    # Bloco de Login no Portal de Exemplo (se necessário)
    try:
        if page.locator("#username").is_visible(timeout=2000):
            print("[AEGIS SIMULATOR] Efetuando login no portal...")
            sys.stdout.flush()
            fill_reactive_text_local("#username", "admin@portalsegura.com")
            fill_reactive_text_local("#password", "Segura@2026")
            
            # Clica no botão Entrar
            btn_entrar = page.locator("#btn-login").first
            btn_entrar.click()
            time.sleep(1.5)
            
            # Se cair no painel inicial pós-login, clica em Nova Cotação
            btn_nova = page.locator("#btn-new-quote").first
            btn_nova.wait_for(state="visible", timeout=15000)
            btn_nova.click()
            time.sleep(1.5)
    except Exception as log_err:
        print(f"[AEGIS SIMULATOR WARNING] Ignorando etapa de login: {log_err}")
        sys.stdout.flush()

    print("[AEGIS SIMULATOR] Iniciando preenchimento da Etapa 1: Dados do Cliente...")
    sys.stdout.flush()
    fill_reactive_text_local("input[data-testid='client-document-input']", "123.456.789-00")
    fill_reactive_text_local("input[data-testid='client-name-input']", "Antigravity Dev")
    fill_reactive_text_local("input[data-testid='client-birth-input']", "15/08/1990")
    fill_reactive_text_local("input[data-testid='client-email-input']", "anti_gravity@deepmind.com")
    select_dropdown_local("mat-form-field:has-text('Estado Civil')", "Solteiro")
    click_next_step_local()

    print("[AEGIS SIMULATOR] Iniciando preenchimento da Etapa 2: Dados do Veículo...")
    sys.stdout.flush()
    fill_reactive_text_local("input[data-testid='vehicle-plate-input']", "ABC1234")
    fill_reactive_text_local("input[data-testid='vehicle-chassis-input']", "9BWZZZ99Z99999999")
    click_next_step_local()

    print("[AEGIS SIMULATOR] Iniciando preenchimento da Etapa 3: Perfil e Risco...")
    sys.stdout.flush()
    fill_reactive_text_local("input[data-testid='risk-zipcode-input']", "01311-200")
    click_next_step_local()

    print("[AEGIS SIMULATOR] Iniciando preenchimento da Etapa 4: Coberturas...")
    sys.stdout.flush()
    click_next_step_local()

    print("[AEGIS SIMULATOR] Iniciando preenchimento da Etapa 5: Vistoria...")
    sys.stdout.flush()
    
    # Datepicker/Calendário
    page.locator("#btn-open-datepicker").first.click(force=True)
    time.sleep(0.5)
    page.locator(".mat-calendar-day-cell:has-text('25')").first.evaluate("el => el.click()")
    time.sleep(0.5)

    # Upload de arquivo de vistoria
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(b"Aegis E2E validation upload file.")
        temp_pdf_path = tmp.name
    try:
        page.set_input_files("#file-picker-input", temp_pdf_path)
        time.sleep(0.8)
    finally:
        try:
            os.remove(temp_pdf_path)
        except Exception:
            pass

    # Finaliza e emite a proposta, indo para a tela de resultados
    click_next_step_local()

    print("[AEGIS SIMULATOR] Iniciando etapa de Pagamento...")
    sys.stdout.flush()
    btn_pagamento = page.locator("#btn-go-to-payment").first
    btn_pagamento.wait_for(state="visible", timeout=15000)
    btn_pagamento.click()
    time.sleep(1.5)

    # Confirmar Cobrança via PIX (Aba Padrão do Portal)
    btn_emitir = page.locator("#btn-confirm-payment-progress").first
    btn_emitir.wait_for(state="visible", timeout=15000)
    
    print("[AEGIS SIMULATOR] Aguardando conciliação do PIX (6s)...")
    sys.stdout.flush()
    page.wait_for_function("() => !document.getElementById('btn-confirm-payment-progress').disabled", timeout=15000)
    time.sleep(0.5)
    
    btn_emitir.click()
    time.sleep(1.5)

    print("[AEGIS SIMULATOR] Iniciando Validação SMS Token...")
    sys.stdout.flush()
    page.locator("#btn-send-sms").first.click()
    time.sleep(1.5)
    
    # Fecha dialog de confirmação de envio se abrir para liberar a tela
    try:
        page.locator("mat-dialog-container button:has-text('Entendi'), mat-dialog-container button:has-text('Fechar'), .mat-dialog-container button").first.click(force=True)
        time.sleep(0.5)
    except Exception:
        pass
    
    fill_reactive_text_local("input[data-testid='sms-token-input']", "882091")
    time.sleep(0.5)
    
    # 1ª Tentativa de Validação (Falha simulada na SPA)
    print("[AEGIS SIMULATOR] Validando SMS - 1ª Tentativa...")
    sys.stdout.flush()
    page.locator("#btn-verify-sms").first.evaluate("el => el.click()")
    time.sleep(2.0)
    
    # 2ª Tentativa de Validação (Sucesso na SPA)
    print("[AEGIS SIMULATOR] Validando SMS - 2ª Tentativa...")
    sys.stdout.flush()
    page.locator("#btn-verify-sms").first.evaluate("el => el.click()")
    time.sleep(2.0)
    
    # Aguarda o modal de sucesso final
    sucesso_el = page.locator("h3.mat-dialog-title, .mat-dialog-container h3, .mat-dialog-title").first
    sucesso_el.wait_for(state="visible", timeout=12000)
    print(f"[AEGIS SIMULATOR] Emissão concluída com sucesso: {sucesso_el.inner_text().strip()}")
    sys.stdout.flush()
    
    record_annotation("extract: .mat-dialog-title : Emissão Concluída")
    time.sleep(2.0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Aegis BlackBox V4 Recorder")
    parser.add_argument("--url", required=True, help="URL para gravação")
    parser.add_argument("--output-dir", default=None, help="Diretório de saída dos artefatos (projeto isolado)")
    parser.add_argument("--auto-simulate", action="store_true", help="Executa gravação automática simulada")
    parser.add_argument("--control-port", type=int, default=None, help="Porta estrita para o servidor HTTP de controle")
    args = parser.parse_args()

    recorder = AegisRecorder(
        url=args.url,
        output_dir=args.output_dir,
        auto_simulate=args.auto_simulate,
        control_port=args.control_port
    )
    recorder.start()
