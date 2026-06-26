---
name: rpa-copilot-analyst
description: "Expert RPA Analyst for application mapping, telemetry analysis, and user process discovery. ACTIVATE this skill when you need to analyze smart recordings, sanitise network telemetry logs, map DOM anomalies, or conduct socratic diagnostics on complex target systems."
---

# 🕵️ Antigravity RPA Analyst: Análise de DOM, Telemetria e Diagnóstico

Este documento define o conhecimento especializado, metodologias de gravação e os protocolos de diagnóstico socrático necessários para mapear sistemas corporativos instáveis ou mal documentados antes da fase de codificação do robô.

---

## 🛠️ 1. O Pipeline Smart Recorder & Sanitizer

Para novos portais ou fluxos não mapeados, a engenharia RPA deve evitar ferramentas ingênuas de gravação baseadas em XPath ou seletores absolutos dinâmicos. Em vez disso, utilize a gravação estruturada com instrumentação e telemetria:

1. **Voo Manual Instrumentado (`smart_recorder.py`):**
   * Execute o processo manualmente em um navegador Edge instrumentado com captura profunda de DOM (Shadow DOM e eventos reativos) e interceptação de tráfego de rede (APIs de backend).
   * Insira anotações de negócio nos passos críticos (ex: sinalizar etapas que requerem envio de SMS ou validações de token).
2. **Sanitização de logs (`telemetry_sanitizer.py`):**
   * Remova cliques redundantes, oscilações de foco de inputs e requisições HTTP duplicadas.
   * Gere um relatório de requisitos técnicos enxuto contendo o **Golden Path** (Caminho Feliz), o mapeamento das rotas das APIs de backend e as validações anotadas.
3. **Manifesto de Seletores (Runbook):**
   * Forneça uma lista semântica de IDs de campos, classes e labels invariantes que servirão de gabarito para a codificação resiliente.

---

## 🔍 2. Protocolo de Diagnóstico Socrático de Portais Confusos

Ao ser acionada para analisar um novo portal ou investigar um erro inexplicável de comportamento de tela, a skill deve atuar de forma socrática, levantando as seguintes questões chaves para formular o mapeamento estrutural:

### 🌐 A. Roteamento de URL e Navegação
* A barra de endereços do navegador é atualizada conforme a automação navega pelas telas ou o portal é uma Single Page Application (SPA) que mascara todas as transições sob o mesmo estado global?
* Existem iframes aninhados protegendo elementos das telas secundárias?

### 🧱 B. Anatomia do DOM e Seletores
* Ao recarregar a tela, os identificadores dos elementos (IDs e names) permanecem os mesmos ou são gerados de forma dinâmica (ex: `mat-input-0`, `usr-177945`)?
* A página faz uso de barreiras de Shadow DOM encapsulando inputs ou elementos de interação?
* Existem elementos homônimos (como múltiplos botões "Salvar" ou "+ Adicionar" renderizados no plano de fundo e em modais ao mesmo tempo), gerando conflitos de clique?

### ⏳ C. Comportamento Assíncrono e Estado
* Como o sistema reporta processamento em andamento? Ocorre renderização de loaders/spinners síncronos na viewport ou a página simplesmente congela sem dar feedback visual claro?
* Há dependência lógica assíncrona entre campos do formulário (ex: preencher o campo A desabilita temporariamente o campo B até que uma validação de backend termine)?

---

## 🛰️ 3. Planejamento de Desvio Estratégico (Bypass de Canal)

Durante a fase de análise de processos, identifique gargalos físicos ou voláteis na jornada do robô:
* **Problema:** Etapas que exigem agendamento presencial, vistoria física com calendários reativos flutuantes ou preenchimento de checklists dependentes de humanos.
* **Solução:** Mapeie se a aplicação suporta canais digitais paralelos (como **Autovistoria via link SMS** ou **Autenticação via QR Code**). Documente o desvio para que o desenvolvedor do robô programe o acionamento direto do bypass digital, pulando a agendamento físico.

---

## 🔒 4. Protocolo de Segurança e Sanitização de Configurações
* **Mapeamento de Variáveis de Ambiente:** Durante a fase de análise, mapeie todas as credenciais, tokens, URLs de portais, rotas e caminhos de arquivos com os quais o robô precisará interagir. Especifique formalmente quais dessas variáveis devem ser configuradas externamente via arquivos `.env` ou variáveis de ambiente de forma isolada do código-fonte.
* **Proibição de Hardcode no Design:** Ao desenhar fluxos de processo ou propor layouts de entrada/saída, instrua explicitamente o desenvolvedor a não utilizar strings estáticas (hardcoded) para dados confidenciais ou parâmetros de infraestrutura/ambiente específicos de cada processo (RPA).
* **Diretriz de Isolamento de RPAs e Proteção do Core Framework:**
  * **Zero Arquivos na Raiz:** Durante o planejamento do pipeline ou da estrutura de novos projetos, planeje para que nenhum arquivo temporário, CSV de carga ou relatório final seja escrito na raiz da suíte do Aegis (exceto requisitos de extrema necessidade autorizados).
  * **Isolamento de Diretórios de Processos (Projects):** Todos os artefatos gerados pelo robô (screenshots, datasets refinados, relatórios de execução do Portal Segura, etc.) devem ser gerados dentro de subpastas do próprio projeto (em `projects/`) ou em pastas de telemetria específicas que estejam fisicamente desacopladas do motor core da suíte Aegis. As pastas `projects/` e `telemetry_data/` devem ser tratadas como áreas externas e independentes em relação à estrutura blindada do Aegis (`aegis_runner`, `aegis_blackbox`, `aegis_cockpit`).
