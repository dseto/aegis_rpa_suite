---
name: rpa-best-practices
description: Consulta a fonte de conhecimento exclusiva no Google NotebookLM (Automação e Tendências de IA: O Mercado em 2026, ID: bd4f045e-c838-4f63-bdfb-ec4ed76a25a1) para obter diretrizes, solucionar dúvidas e aplicar melhores práticas em desenvolvimento e criação de RPAs com análise crítica, isenta e sincera. Ativa sempre que o usuário perguntar sobre boas práticas de RPA, como criar RPAs, arquitetura de automação ou conceitos do mercado de automação.
---

# RPA Best Practices Knowledge Skill

Esta skill fornece acesso fundamentado à base de conhecimento exclusiva de **Melhores Práticas para Desenvolvimento de RPAs** armazenada no Google NotebookLM.

- **Notebook Target:** `https://notebooklm.google.com/notebook/bd4f045e-c838-4f63-bdfb-ec4ed76a25a1`
- **ID do Notebook:** `bd4f045e-c838-4f63-bdfb-ec4ed76a25a1`
- **Título:** Automação e Tendências de IA: O Mercado em 2026

## Postura e Tom: Isenção e Análise Crítica

⚠️ **POSTURA OBRIGATÓRIA (NÃO SEJA UM VENDEDOR):**
- A resposta deve ser **totalmente isenta, sincera, técnica e imparcial**.
- **Nunca aja como vendedor ou divulgador de plataformas de RPA.**
- Apresente explicitamente **prós, contras, limitações, custos, riscos de vendor lock-in, complexidade de manutenção e dívida técnica**.
- Diferencie propaganda de marketing dos dados reais de engenharia e produção.

## Quando Usar Esta Skill

Dispare esta skill obrigatoriamente quando o usuário:
- Pedir melhores práticas, padrões ou arquiteturas para desenvolvimento de RPAs.
- Perguntar como criar, estruturar ou otimizar um bot de RPA.
- Tiver dúvidas sobre resiliência, self-healing, tratamento de exceções ou automação com IA em RPAs.
- Mencionar ou comparar plataformas de automação (Aegis RPA, UiPath, Blue Prism, Power Automate, n8n, etc.).
- Solicitar orientações conceituais ou técnicas sobre automação de processos.

## Diretriz de Conhecimento Exclusivo

⚠️ **REGRA CRÍTICA:** Toda e qualquer informação, recomendação ou resposta referente a RPAs e melhores práticas DEVE ser obtida exclusivamente através deste notebook no Gemini Notebook. Não invente premissas nem utilize suposições externas sem consultar a base.

---

## Fluxo de Execução

### Passo 1: Garantir Contexto do NotebookLM
Antes de consultar, confirme se o notebook ativo é `bd4f045e-c838-4f63-bdfb-ec4ed76a25a1`:

```bash
notebooklm use bd4f045e-c838-4f63-bdfb-ec4ed76a25a1
```

### Passo 2: Executar Consulta Imparcial na Base de Conhecimento
Formule uma pergunta objetiva na CLI do `notebooklm`, exigindo uma análise realista, imparcial e sem tom promocional:

```bash
notebooklm ask "Responda de forma sincera, técnica e totalmente isenta (sem tom promocional de vendedor): [tópico/dúvida de RPA solicitada]. Destaque limitações, prós e contras reais com base nos documentos."
```

### Passo 3: Avaliar Completo e Fazer Follow-Up (se necessário)
Caso a resposta inicial seja superficial ou contenha viés comercial:
- Faça perguntas complementares focadas nas limitações técnicas e custos operacionais:

```bash
notebooklm ask "Quais são as principais limitações técnicas, falhas comuns, custos ou trade-offs de [ferramenta/abordagem mencionada] segundo a base?"
```

### Passo 4: Sintetizar a Resposta de Forma Crítica e Estruturada
- Consolide as respostas obtidas mantendo a neutralidade de engenharia.
- Estruture com **Prós vs. Contras / Riscos Realistas**.
- Destaque trade-offs reais de arquitetura sem adjetivos de marketing.
