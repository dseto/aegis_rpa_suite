# 🧠 Aegis Agent Skills: Documentação do Diretório de Skills

Este diretório contém as definições de skills e diretrizes operacionais executadas por agentes inteligentes dentro do ecossistema do **Aegis RPA Suite**. Cada subpasta mapeia uma skill específica que orienta o comportamento autônomo do agente em fases cruciais de testes, validações e triagens.

---

## 1. Mapeamento das Skills Disponíveis

| Skill | Escopo | Arquivo de Instruções |
| :--- | :--- | :--- |
| **Aegis Live Pilot** | Orquestração e homologação de fluxos RPA ponta a ponta contra novos sites. | [aegis-live-pilot/SKILL.md](file:///c:/Projetos/aegis_rpa_suite/.agents/skills/aegis-live-pilot/SKILL.md) |
| **Aegis Pipeline Forensics** | Diagnóstico forense passivo (read-only) de dessincronização de artefatos. | [aegis-pipeline-forensics/SKILL.md](file:///c:/Projetos/aegis_rpa_suite/.agents/skills/aegis-pipeline-forensics/SKILL.md) |
| **Aegis Regression Gate** | Validação automatizada de retrocompatibilidade do framework sem regeneração. | [aegis-regression-gate/SKILL.md](file:///c:/Projetos/aegis_rpa_suite/.agents/skills/aegis-regression-gate/SKILL.md) |

---

## 2. Detalhamento Funcional das Skills

### A. Aegis Live Pilot (`aegis-live-pilot`)
Esta skill instrui o agente a executar uma simulação completa do pipeline Aegis contra uma URL fornecida pelo usuário, gerando dados reais de comportamento e avaliando a precisão da automação gerada.

- **Missão:** Orquestrar o ciclo completo de 5 fases (**Record → Sanitize → Validate → Generate → Run**) contra um site-alvo, sem inventar seletores ou fabricar dados sintéticos.
- **Princípios Operacionais Chaves:**
  1. **URL fornecida pelo usuário:** O agente nunca deve chutar ou inventar uma URL de teste.
  2. **Parametrização dupla de metadados:** Garante obrigatoriamente a presença da propriedade `url` em duas camadas de configuração: `projects/<slug>/project.json` e `projects/<slug>/tests/<test_slug>/project.json`. Isso evita que a fase de execução caia no fallback padrão do Portal Segura.
  3. **Preservação de Integridade:** Não efetua alterações corretivas no código principal do framework (módulos `aegis_*`).
  4. **Navegador Homologado:** A execução ocorre obrigatoriamente através do canal do Microsoft Edge (`msedge`).
- **Mapeamento de Fluxo do Agente:**
  - **Sondagem Headless:** Varredura inicial de conectividade (curl) e descoberta de seletores estáveis no DOM via Playwright.
  - **Estruturação de Pastas:** Criação do scaffolding do projeto com `dataset_inicial.json` e `dicionario.json`.
  - **Driver de Gravação Automática:** Geração de um script temporário em `scratch/` que instancia o [recorder.py](file:///c:/Projetos/aegis_rpa_suite/aegis_blackbox/recorder.py) com `auto_simulate=True`.
  - **Execução Sequencial:** Disparo faseador:
    1. Gravação (telemetria bruta em `gravacao.json`).
    2. Sanitização ([sanitizer.py](file:///c:/Projetos/aegis_rpa_suite/aegis_sanitizer/sanitizer.py)).
    3. Validação do Dataset ([dataset_validator.py](file:///c:/Projetos/aegis_rpa_suite/aegis_sanitizer/dataset_validator.py)).
    4. Geração de Código ([code_generator.py](file:///c:/Projetos/aegis_rpa_suite/aegis_sanitizer/code_generator.py)).
    5. Execução do Bot (`bot_producao.py`).
  - **Relatório de Desempenho:** Geração do runbook final em `.specs/relatorio-piloto-<slug>.md` estruturado com métricas consolidadas (percentual de `weak_selector`, taxa de sucesso, etc.).

---

### B. Aegis Pipeline Forensics (`aegis-pipeline-forensics`)
Esta skill define o protocolo de auditoria e depuração técnica passiva. Ela é disparada quando o usuário relata problemas de inconsistência (ex: "o bot tenta ler um campo inexistente" ou "os dados não batem").

- **Missão:** Realizar auditoria estática passiva nos artefatos da esteira Aegis para identificar exatamente onde a cadeia de conversão foi quebrada.
- **Princípios Operacionais Chaves:**
  1. **Totalmente Read-Only:** O agente está terminantemente proibido de editar, rodar ou regenerar qualquer arquivo ou etapa de pipeline.
  2. **Evidência Científica:** Cada mismatch detectado deve ser obrigatoriamente reportado com o nome do arquivo, a linha exata e o trecho de código correspondente.
- **Ordem de Investigação na Cadeia de Artefatos:**
  1. `gravacao.json` (Fase 1 - Recorder): Extração dos seletores brutos capturados e mapeamento de chaves semânticas físicas.
  2. `dicionario.json` (Fase 1/2 - Sanitizer): Validação de correspondência entre os campos identificados (`fields`) e os seletores traduzidos.
  3. `dataset_inicial.json` (Dados): Mapeamento das chaves de colunas para garantir que cobrem todos os campos mapeados no dicionário.
  4. `plano_execucao.json` (Fase 2 - Sanitizer): Verificação da integridade de mapeamento dos identificadores de passo (`step_id`).
  5. `bot_producao.py` (Fase 4 - Generator): Inspeciona todas as chamadas `row.get("chave")` e os comentários de marcação de passo (`# [PASSO N]`) para cruzar com o plano.
- **Matriz de Comparações Cruzadas:**
  - `gravacao.json` vs `dicionario.json` (Detecta se o dicionário é de gravação antiga).
  - `dicionario.json` vs `dataset_inicial.json` (Identifica discrepâncias em nomes de colunas de dados).
  - `plano_execucao.json` vs `bot_producao.py` (Garante que os passos chamados existam no plano).
  - `dataset_inicial.json` vs `bot_producao.py` (Evita falhas de dicionário por colunas ausentes).

---

### C. Aegis Regression Gate (`aegis-regression-gate`)
Esta skill especifica o portão de controle de qualidade para integração contínua (CI). Deve ser executada sempre que o desenvolvedor realizar alterações no core do framework (nos módulos contidos em `aegis_*`).

- **Missão:** Executar automações de referência e comparar seu comportamento contra baselines históricos congelados para identificar regressões técnicas ou de retrocompatibilidade.
- **Princípios Operacionais Chaves:**
  1. **NUNCA regenera o bot:** O gate testa obrigatoriamente o código do bot exatamente como compilado anteriormente. Isso blinda o teste contra possíveis alterações do [code_generator.py](file:///c:/Projetos/aegis_rpa_suite/aegis_sanitizer/code_generator.py), isolando exclusivamente alterações do runner.
  2. **Isolamento de Alterações:** O agente não tenta corrigir falhas. Se o robô de referência falhar, a skill reporta o erro e interrompe a esteira.
  3. **Persistência Incremental de Baseline:** Os resultados de novas baterias de teste são adicionados ao final do arquivo `.specs/plans/<nome-do-baseline>.md` via *append*, mantendo o histórico de execuções passadas intacto.
- **Critérios Rigorosos de Aprovação (Veredito):**
  - **Taxa de Sucesso:** Não pode haver queda na taxa de conclusão de transações com relação à última execução estável (baseline).
  - **Erro Inédito:** A reemergência de erros conhecidos é tolerada (variância do ambiente de staging), mas qualquer exceção Python inédita ou falha de import do runner reprova o gate.
  - **Needs Review Count:** A geração de novos alertas em `correcoes_acumuladas.json` com status `needs_review` é restrita a uma tolerância de no máximo +1 entrada com relação ao baseline.
  - **Tempo de Execução:** O tempo médio cumulativo das execuções não pode ser superior a 2x o tempo registrado no baseline.
- **Configuração e Parâmetros:**
  - `--project-dir`: Caminho do teste de referência (Padrão: `projects/portal_segura/tests/001_teste`).
  - `--runs`: Quantidade de baterias de testes consecutivos (Padrão: 3).
  - `--baseline`: Nome do arquivo de baseline markdown correspondente.
