# 🛡️ Manual Completo de Instalação e Configuração — Aegis RPA Suite

Este guia descreve os pré-requisitos, etapas de instalação de dependências, configuração de variáveis de ambiente e a inicialização de todos os componentes da **Aegis RPA Suite**.

---

## 📋 1. Requisitos de Sistema

Antes de iniciar, certifique-se de que a máquina possui:
1. **Python**: Versão **3.8 ou superior** instalada e adicionada ao PATH do sistema.
2. **Git**: Para controle de versão e download do código.
3. **Node.js** *(Opcional)*: Necessário apenas se você desejar rodar o CLI do Claude Code globalmente na máquina.
4. **Navegador**: Microsoft Edge ou Google Chrome instalados para os modos de execução monitorada (headed).

---

## ⚙️ 2. Instalação Passo a Passo

### Passo 1: Obter o Código Fonte
Clone o repositório do GitHub em sua pasta de trabalho:
```powershell
git clone https://github.com/dseto/aegis_rpa_suite.git
cd aegis_rpa_suite
```

### Passo 2: Criar o Ambiente Virtual (venv)
É altamente recomendável isolar as dependências do projeto em um ambiente virtual:
```powershell
# Criar o ambiente virtual (.venv)
python -m venv .venv

# Ativar o ambiente virtual
# No Windows (PowerShell):
.venv\Scripts\activate
# No Windows (CMD):
.venv\Scripts\activate.bat
# No Linux / macOS:
source .venv/bin/activate
```

### Passo 3: Instalar as Dependências do Python
Com o ambiente virtual ativo, instale os pacotes necessários especificados no `requirements.txt`:
```powershell
pip install -r requirements.txt
```

### Passo 4: Instalar os Navegadores do Playwright
O Playwright precisa baixar seus binários de navegador dedicados para rodar de forma isolada:
```powershell
# Instalação básica (Chromium)
playwright install chromium

# (Opcional) Instalar o suporte ao Microsoft Edge corporativo
playwright install msedge
```

---

## 🔑 3. Configuração de Credenciais e Variáveis de Ambiente

O core da Aegis RPA Suite é blindado e não aceita chaves ou credenciais fixas (hardcode) nos scripts de robô. Toda a parametrização é realizada por meio de arquivos `.env` locais para cada projeto.

### Configurando o arquivo .env
1. Cada subpasta em `projects/` possui um arquivo modelo chamado `.env.example`.
2. Duplique este arquivo e renomeie-o para `.env` no diretório do seu robô específico (ex: `projects/seu_projeto/.env`).
3. Preencha as chaves necessárias:

```env
# ==============================================================================
# CONFIGURAÇÕES DO BROWSER (AEGIS RUNNER)
# ==============================================================================
AEGIS_BROWSER_HEADLESS=false
AEGIS_BROWSER_SLOW_MO=50
AEGIS_BROWSER_CHANNEL=msedge

# ==============================================================================
# CONFIGURAÇÕES COGNITIVAS (IA SELF-HEALING)
# ==============================================================================
# Ative true para habilitar recuperação visual com IA caso um seletor quebre
AEGIS_COGNITIVE_ENABLED=true

# Provedor da API de LLM ('openrouter' ou 'litellm')
AEGIS_COGNITIVE_PROVIDER=openrouter
AEGIS_COGNITIVE_BASE_URL=https://openrouter.ai/api/v1
AEGIS_COGNITIVE_MODEL=google/gemini-2.5-flash

# Sua chave de API secreta (Ex: OpenRouter ou LiteLLM)
AEGIS_COGNITIVE_API_KEY=sua_api_key_aqui

# ==============================================================================
# CREDENCIAIS DO PORTAL ALVO
# ==============================================================================
PORTAL_USER=usuario_de_teste
PORTAL_PASSWORD=senha_de_teste
```

---

## 🖥️ 4. Como Executar e Utilizar a Suite

A Aegis RPA Suite pode ser operada de forma visual via painel web ou diretamente via terminal CLI:

### Opção A: Operação Visual via Aegis Cockpit (Recomendado)
O **Aegis Cockpit** é uma interface Flask moderna para gerenciar gravações, sanitizações, compilação de código e execuções:

1. Inicie o painel Flask:
   ```powershell
   python aegis_cockpit/cockpit.py
   ```
2. Abra o navegador no endereço indicado (por padrão: `http://localhost:5000`).
3. Use o painel para iniciar gravações, inspecionar relatórios estruturados e ver o progresso dos robôs.

---

### Opção B: Operação via Linha de Comando (CLI)

#### 1. Gravar um Novo Processo (Aegis BlackBox)
Inicie a gravação instrumentada guiada de uma página web:
```powershell
python aegis_blackbox/recorder.py --url "https://site-alvo.com" --output-dir "projects/meu_novo_bot" --control-port 9900
```
*Execute o processo manualmente no navegador que se abrirá, preenchendo os campos do formulário.*

#### 2. Sanitizar os Logs e Gerar o Dicionário (Aegis Sanitizer)
Limpe ruídos da gravação e compile o dicionário de seletores e dados:
```powershell
python aegis_sanitizer/sanitizer.py --project-dir projects/meu_novo_bot
```
*Isso gerará os arquivos `dicionario.json`, `relatorio.md` e `dataset_inicial.json` dentro da pasta do projeto.*

#### 3. Validar a Fila de Entrada (Dataset Firewall)
Valide dados de entrada (CSV ou JSON) contra as regras do dicionário de dados gerado:
```powershell
python aegis_sanitizer/dataset_validator.py --dataset projects/meu_novo_bot/dataset_inicial.json --project-dir projects/meu_novo_bot
```

#### 4. Compilar o Robô Resiliente com IA
Dispare a geração cognitiva do script final de produção:
```powershell
python aegis_code_generator/code_generator.py --project-dir projects/meu_novo_bot
```
*Isso criará o script executável final `bot_producao.py` na pasta do seu projeto.*

#### 5. Executar o Robô de Produção (Aegis Runner)
Rode a automação resiliente em lote:
```powershell
python projects/meu_novo_bot/bot_producao.py
```

---

## 🤖 5. Integração com Assistentes de IA (Claude Code / Antigravity)

Esta suíte inclui **Skills Locais** pré-configuradas para guiar assistentes agenticos a programar e auditar seus robôs seguindo as melhores práticas.

Se você utilizar o **Claude Code** ou **Antigravity**:
1. Inicie a ferramenta dentro do diretório raiz:
   ```powershell
   claude
   ```
2. O assistente detectará automaticamente as diretrizes de desenvolvimento localizadas no diretório de skills e aplicará as regras de resiliência e blindagem de código da Aegis de forma nativa.
