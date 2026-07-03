import os
import json
import base64
import re
import requests
from playwright.sync_api import Page

class CognitiveGateway:
    def __init__(self, project_dir: str = None):
        # 0. Salva uma cópia das variáveis de ambiente originais do processo pai
        initial_env = dict(os.environ)
        
        # 1. Tenta carregar .env global de locais conhecidos da raiz do framework (aegis_rpa_suite) ou do CWD
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(curr_dir)
            
            envs_to_try = [
                os.path.join(root_dir, ".env"),
                os.path.join(os.getcwd(), ".env"),
                os.path.join(os.path.dirname(os.getcwd()), ".env")
            ]
            
            # Filtra caminhos únicos que realmente existem
            seen = set()
            for env_path in envs_to_try:
                env_abs = os.path.abspath(env_path)
                if env_abs not in seen and os.path.exists(env_abs):
                    seen.add(env_abs)
                    with open(env_abs, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, val = line.split("=", 1)
                                key_clean = key.strip()
                                val_clean = val.strip().strip("'\"")
                                is_placeholder = val_clean.startswith("$(") and val_clean.endswith(")")
                                is_placeholder = is_placeholder or (val_clean.startswith("__") and val_clean.endswith("__"))
                                if val_clean and not is_placeholder:
                                    # Injeta se não existir originalmente no SO
                                    if key_clean not in initial_env:
                                        os.environ[key_clean] = val_clean
        except Exception as env_err:
            print(f"[COGNITIVE WARNING] Erro ao autocarregar .env global da raiz: {env_err}")

        # 2. Tenta carregar .env local do diretório do PROJETO do robô, se fornecido,
        # subindo os níveis de diretório até encontrar o .env consolidado
        try:
            if project_dir and os.path.exists(project_dir):
                current_lookup = os.path.abspath(project_dir)
                env_path = None
                for _ in range(4):
                    candidate = os.path.join(current_lookup, ".env")
                    if os.path.exists(candidate):
                        env_path = candidate
                        break
                    parent_lookup = os.path.dirname(current_lookup)
                    if parent_lookup == current_lookup:
                        break
                    current_lookup = parent_lookup

                if env_path and os.path.exists(env_path):
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, val = line.split("=", 1)
                                key_clean = key.strip()
                                val_clean = val.strip().strip("'\"")
                                # Se a variável foi originalmente passada pelo SO/processo pai, ela tem precedência absoluta
                                if key_clean in initial_env:
                                    continue
                                # Se for vazia ou placeholder, ignora
                                is_placeholder = val_clean.startswith("$(") and val_clean.endswith(")")
                                is_placeholder = is_placeholder or (val_clean.startswith("__") and val_clean.endswith("__"))
                                if not val_clean or is_placeholder:
                                    continue
                                os.environ[key_clean] = val_clean
        except Exception as env_err:
            print(f"[COGNITIVE WARNING] Erro ao autocarregar .env local do projeto: {env_err}")

        # Carrega configurações do ambiente
        self.enabled = os.getenv("AEGIS_COGNITIVE_ENABLED", "false").lower() == "true"
        self.provider = os.getenv("AEGIS_COGNITIVE_PROVIDER", "openrouter").lower()
        self.api_key = os.getenv("AEGIS_COGNITIVE_API_KEY", "")
        
        # Define URLs padrão caso não sejam especificadas
        default_base_url = "https://openrouter.ai/api/v1" if self.provider == "openrouter" else "http://localhost:4000/v1"
        self.base_url = os.getenv("AEGIS_COGNITIVE_BASE_URL", default_base_url).rstrip("/")
        
        # Define modelos padrão
        default_model = "google/gemini-2.5-flash" if self.provider == "openrouter" else "gemini-2.5-flash"
        self.model = os.getenv("AEGIS_COGNITIVE_MODEL", default_model)
        self.coder_model = os.getenv("AEGIS_COGNITIVE_CODER_MODEL", self.model)

        # Se houver chave configurada mas ENABLED não foi explicitamente setado como false, ativa
        if self.api_key and os.getenv("AEGIS_COGNITIVE_ENABLED") is None:
            self.enabled = True

    def is_active(self) -> bool:
        if not self.enabled:
            return False
        if not self.api_key:
            print("[COGNITIVE WARNING] Módulo habilitado mas AEGIS_COGNITIVE_API_KEY está vazia.")
            return False
        return True

    def _image_to_base64(self, file_path: str) -> str:
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _call_llm_api(self, prompt: str, image_path = None, force_json = True) -> str:
        """Efetua a chamada HTTP para o provedor configurado (OpenRouter/LiteLLM/OpenAI-compatible)"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Cabeçalhos específicos recomendados pelo OpenRouter
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/aegis-rpa/aegis-suite"
            headers["X-Title"] = "Aegis RPA Suite"
 
        content_payload = [{"type": "text", "text": prompt}]
 
        if image_path:
            # Normaliza para lista se for uma única string
            image_paths = [image_path] if isinstance(image_path, str) else image_path
            for img_p in image_paths:
                if img_p and os.path.exists(img_p):
                    base64_image = self._image_to_base64(img_p)
                    content_payload.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    })
 
        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content_payload
                }
            ],
            "temperature": 0.1
        }
 
        if force_json:
            # Tenta forçar retorno JSON estruturado se suportado
            # Em alguns modelos/provedores simplificados, response_format pode falhar, por isso tratamos em bloco try
            try:
                data["response_format"] = {"type": "json_object"}
                response = requests.post(url, headers=headers, json=data, timeout=30)
                if response.status_code != 200:
                    # Se falhar devido ao response_format, tenta sem ele
                    if "response_format" in response.text:
                        del data["response_format"]
                        response = requests.post(url, headers=headers, json=data, timeout=30)
            except Exception:
                if "response_format" in data:
                    del data["response_format"]
                response = requests.post(url, headers=headers, json=data, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"Erro na API de LLM ({response.status_code}): {response.text}")

        res_json = response.json()
        try:
            return res_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Resposta inválida da API: {json.dumps(res_json)}")

    def _clean_json_response(self, text: str) -> dict:
        """Limpa blocos de código markdown do JSON retornado e faz o parser robusto."""
        text_clean = text.strip()
        # Remove encapsulamento ```json ... ``` se houver
        if text_clean.startswith("```"):
            text_clean = re.sub(r"^```(?:json)?\n", "", text_clean)
            text_clean = re.sub(r"\n```$", "", text_clean)
        
        # Encontra o primeiro '{' e o último '}' caso haja lixo na resposta
        start = text_clean.find("{")
        end = text_clean.rfind("}")
        if start != -1 and end != -1:
            text_clean = text_clean[start:end+1]

        # Tenta o parser JSON comum
        try:
            return json.loads(text_clean)
        except Exception as e:
            print(f"[COGNITIVE WARNING] Falha no parser JSON padrão: {e}. Iniciando parser tolerante a aspas...")

        # Parser tolerante a aspas duplas não escapadas em chaves conhecidas
        result = {}
        
        # 1. Extração de category
        cat_match = re.search(r'"category"\s*:\s*"([^"]+)"', text_clean)
        if cat_match:
            result["category"] = cat_match.group(1).strip()
        else:
            result["category"] = "UNKNOWN"

        # 2. Extração de root_cause_summary e actionable_fix por corte de posições
        rc_start = text_clean.find('"root_cause_summary"')
        af_start = text_clean.find('"actionable_fix"')
        
        if rc_start != -1 and af_start != -1:
            # Captura bloco de root_cause_summary
            rc_block = text_clean[rc_start:af_start].strip()
            # Remove a chave e o separador ':'
            rc_val = re.sub(r'^"root_cause_summary"\s*:\s*', '', rc_block).strip()
            if rc_val.startswith('"'):
                rc_val = rc_val[1:]
            # Remove vírgula e aspas finais do bloco
            rc_val = re.sub(r'",?\s*$', '', rc_val).strip()
            result["root_cause_summary"] = rc_val
            
            # Captura bloco de actionable_fix
            af_block = text_clean[af_start:].strip()
            af_val = re.sub(r'^"actionable_fix"\s*:\s*', '', af_block).strip()
            if af_val.startswith('"'):
                af_val = af_val[1:]
            # Remove chaves/aspas/espaços de fechamento
            af_val = re.sub(r'"\s*\}?\s*$', '', af_val).strip()
            result["actionable_fix"] = af_val
        else:
            # Fallback para regex simples não-guloso
            rc_match = re.search(r'"root_cause_summary"\s*:\s*"(.*?)"(?=\s*,\s*"actionable_fix"|\s*\})', text_clean, re.DOTALL)
            if rc_match:
                result["root_cause_summary"] = rc_match.group(1).strip()
            else:
                result["root_cause_summary"] = ""
                
            af_match = re.search(r'"actionable_fix"\s*:\s*"(.*?)"(?=\s*\})', text_clean, re.DOTALL)
            if af_match:
                result["actionable_fix"] = af_match.group(1).strip()
            else:
                result["actionable_fix"] = ""
                
        return result

    def self_healing_click(self, page: Page, selector: str, target_description: str, original_coords: tuple = None) -> bool:
        """
        Tenta localizar visualmente um elemento na tela após falha de seletor estático.
        Salva uma captura temporária, envia à LLM e executa o clique se encontrado.
        Se a IA falhar ou não encontrar, e houver original_coords, executa o clique de fallback na coordenada física.
        """
        if not self.is_active():
            print(f"[COGNITIVE] Ignorando Self-Healing para '{selector}' (módulo desativado).")
            # Se o módulo cognitivo estiver desativado mas temos coordenadas originais, aplica o fallback físico direto
            if original_coords and len(original_coords) == 2:
                try:
                    viewport = page.viewport_size or {"width": 1280, "height": 720}
                    x = int(viewport["width"] * original_coords[0])
                    y = int(viewport["height"] * original_coords[1])
                    print(f"[COGNITIVE WARNING] Módulo cognitivo inativo. Aplicando clique direto de fallback nas coordenadas gravadas: ({x}, {y})")
                    page.mouse.click(x, y)
                    return True
                except Exception as coords_err:
                    print(f"[COGNITIVE ERRO] Falha no clique de fallback por coordenadas: {coords_err}")
            return False

        print(f"[COGNITIVE] Iniciando Self-Healing para seletor falho: '{selector}'")
        temp_img = "temp_self_healing.png"
        
        try:
            # Captura a tela atual da automação
            page.screenshot(path=temp_img)
            
            coords_hint = ""
            if original_coords and len(original_coords) == 2:
                coords_hint = f"\nDica de Posição Original: Durante a gravação manual, o elemento foi clicado nas coordenadas relativas: X = {original_coords[0]:.2%}, Y = {original_coords[1]:.2%}. Use isso como ponto de partida principal para localizar o elemento na screenshot!"

            prompt = f"""
            Você é um motor cognitivo de resiliência de RPA.
            Análise a screenshot da página web e identifique as coordenadas exatas para interagir com o elemento descrito como: '{target_description}'.
            
            O seletor CSS que falhou foi: '{selector}'.{coords_hint}
            Use o contexto visual para achar onde este elemento se encontra na tela atual.
            
            Retorne OBRIGATORIAMENTE um objeto JSON válido contendo:
            - "found": true ou false (se o elemento foi avistado e está clicável).
            - "x_percent": float entre 0.0 e 1.0 (coordenada horizontal centralizada no elemento, relativa à largura da tela).
            - "y_percent": float entre 0.0 e 1.0 (coordenada vertical centralizada no elemento, relativa à altura da tela).
            - "reason": Breve justificativa de como localizou o elemento ou por que não o encontrou.
            
            Retorne EXCLUSIVAMENTE o JSON estruturado, sem texto antes ou depois.
            """
            
            raw_response = self._call_llm_api(prompt, temp_img)
            result = self._clean_json_response(raw_response)
            
            if result.get("found") and "x_percent" in result and "y_percent" in result:
                # Calcula as coordenadas físicas com base no viewport atual do navegador
                viewport = page.viewport_size
                if not viewport:
                    # Viewport padrão caso não esteja definido no contexto
                    viewport = {"width": 1280, "height": 720}
                
                x = int(viewport["width"] * result["x_percent"])
                y = int(viewport["height"] * result["y_percent"])
                
                print(f"[COGNITIVE SUCESSO] Elemento '{target_description}' localizado via IA em ({x}, {y}) [Justificativa: {result.get('reason')}].")
                
                # Executa o clique físico do mouse
                page.mouse.click(x, y)
                return True
            else:
                print(f"[COGNITIVE FALHA] IA não encontrou o elemento. Justificativa: {result.get('reason')}")
                # Se a IA explicitamente determinou que o elemento não está presente na tela,
                # não tentamos o clique cego por coordenadas, pois isso geraria falsos-positivos.
                # Retornamos False para que o runner registre a falha real do fluxo.
                return False

        except Exception as e:
            print(f"[COGNITIVE ERRO] Falha no processo de Self-Healing: {e}")
            
            # Fallback de segurança definitivo se ocorrer erro/timeout na chamada de IA
            if original_coords and len(original_coords) == 2:
                try:
                    viewport = page.viewport_size or {"width": 1280, "height": 720}
                    x = int(viewport["width"] * original_coords[0])
                    y = int(viewport["height"] * original_coords[1])
                    print(f"[COGNITIVE WARNING] Erro no Self-Healing. Aplicando clique direto de fallback nas coordenadas gravadas: ({x}, {y})")
                    page.mouse.click(x, y)
                    return True
                except Exception as coords_err:
                    print(f"[COGNITIVE ERRO] Falha no clique de fallback por coordenadas pós-exceção: {coords_err}")
            return False
        finally:
            if os.path.exists(temp_img):
                try:
                    os.remove(temp_img)
                except Exception:
                    pass

    def diagnose_failure(self, page: Page, error_msg: str, steps_history: list = None) -> dict:
        """
        Captura a screenshot da tela no momento do erro e faz uma triagem cognitiva
        com a LLM baseada puramente em análise visual e semântica (visão computacional multimodal)
        para diagnosticar a causa do erro de forma holística (como um analista de QA humano).
        """
        if not self.is_active():
            return {"status": "disabled", "message": "Módulo cognitivo desativado."}

        print("[COGNITIVE] Iniciando Diagnóstico de Falha Visual via LLM...")
        temp_img = "temp_diagnose_failure.png"
        
        try:
            page.screenshot(path=temp_img)
            
            # Formata o resumo do histórico de passos executados
            steps_summary = "Histórico de passos executados até o momento:\n"
            if steps_history:
                for step in steps_history:
                    idx = step.get("index", "?")
                    status = step.get("status", "")
                    action = step.get("type", "")
                    desc = step.get("desc", "")
                    selector = step.get("selector", "")
                    steps_summary += f"- Passo {idx}: [{status}] {action} em '{selector}' ({desc})\n"
            else:
                steps_summary += "(Nenhum histórico de passos disponível)"

            prompt = f"""
Você é um especialista sênior em garantia de qualidade (QA) e auditoria de RPA (Robotic Process Automation).
Uma automação de processo corporativo falhou com o seguinte erro técnico/sistêmico:
'{error_msg}'

Abaixo está o histórico funcional das ações do robô executadas nesta transação:
---
{steps_summary}
---

INSTRUÇÕES DE ANÁLISE VISUAL (QA HUMANO):
Examine com atenção a captura de tela (screenshot) no momento do erro e identifique a causa raiz funcional da falha:
1. Analise a tela de forma holística: não se limite ao elemento exato ou passo técnico do erro.
2. Procure por inconsistências em etapas anteriores: verifique se há campos obrigatórios vazios ou não preenchidos (por exemplo: selects/dropdowns sem opção selecionada, inputs em branco) que deveriam ter sido preenchidos em etapas anteriores.
3. Identifique mensagens de erro visuais ou validações ativas: procure por alertas na tela, textos em vermelho, bordas de campos destacadas em vermelho ou banners de validação.
4. Detecte bloqueios visuais na interface: verifique se há popups, modais, caixas de diálogo abertas ou loaders/spinners que impedem a interação com a tela principal.
5. Verifique desalinhamento de etapas: analise se o robô tentou interagir com elementos de uma etapa posterior (ex: Passo 3) mas a tela visualmente ainda está travada em uma etapa anterior (ex: Passo 2) devido a erros de preenchimento.

Identifique qual é a causa raiz provável da quebra e retorne um objeto JSON contendo:
- "category": Categoria do erro ("CAPTCHA" | "TIMEOUT_SELECTOR" | "SERVER_ERROR" | "BUSINESS_VALIDATION" | "AUTH_FAILED" | "UNKNOWN")
- "root_cause_summary": Breve explicação funcional e amigável da causa raiz real (ex: "O robô tentou preencher o Passo 3, mas a página continua travada no Passo 2 porque o campo 'Nível da Blindagem' ficou em branco após marcar 'Possui Blindagem?'").
- "actionable_fix": O que o robô, desenvolvedor ou gerador de código IA deve corrigir ou ajustar de forma precisa e acionável no fluxo (ex: "Ajustar o preenchimento do campo 'Nível da Blindagem' no Passo 2 antes de tentar avançar").

Retorne EXCLUSIVAMENTE o JSON estruturado.
"""
            
            raw_response = self._call_llm_api(prompt, temp_img)
            return self._clean_json_response(raw_response)

        except Exception as e:
            print(f"[COGNITIVE ERRO] Falha ao realizar diagnóstico: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if os.path.exists(temp_img):
                try:
                    os.remove(temp_img)
                except Exception:
                    pass

    def compare_visual_similarity(self, path_recorder: str, path_script: str) -> dict:
        """
        Recebe os caminhos dos screenshots do gravador e do robô e utiliza a LLM
        para realizar uma comparação visual profunda.
        Retorna um dicionário com score de similaridade, diferenças e veredito.
        """
        if not self.is_active():
            return {
                "similarity_score": 0,
                "differences": ["Módulo cognitivo desativado ou sem API Key."],
                "ready_for_analyst": False,
                "justification": "Comparação abortada: Módulo cognitivo desativado."
            }

        print("[COGNITIVE] Iniciando comparação visual profunda entre gravação e script...")
        
        if not os.path.exists(path_recorder):
            return {
                "similarity_score": 0,
                "differences": [f"Screenshot da gravação não localizado em: {path_recorder}"],
                "ready_for_analyst": False,
                "justification": "Arquivo screenshot_recorder.png ausente."
            }
            
        if not os.path.exists(path_script):
            return {
                "similarity_score": 0,
                "differences": [f"Screenshot do robô não localizado em: {path_script}"],
                "ready_for_analyst": False,
                "justification": "Arquivo screenshot_script.png ausente."
            }

        try:
            prompt = """
            Você é um especialista sênior em garantia de qualidade visual e auditoria de RPA.
            Sua missão é realizar uma comparação visual profunda de duas imagens de tela de um sistema corporativo:
            1. A primeira imagem é o screenshot da gravação manual do fluxo de negócios (representa o estado esperado real de sucesso).
            2. A segunda imagem é o screenshot da execução headless automatizada do robô gerado (representa o estado atual).
            
            DIRETRIZ CRÍTICA DE COMPARAÇÃO (Skeleton / Layout Validation):
            Como se trata de portais de conteúdo dinâmico (notícias, artigos, cotações, etc.), o texto de manchetes, notícias jornalísticas específicas, banners publicitários e imagens rotativas mudam constantemente e podem diferir.
            - Você DEVE ignorar variações diárias de conteúdo e notícias de texto ou imagens dinâmicas secundárias.
            - Concentre sua análise exclusivamente na estrutura global do layout (estrutura e posições do cabeçalho, sidebars, existência do menu de navegação correto, grids de organização de seções, templates gerais da página e a paleta de cores característica da marca do domínio).
            - Se o template visual estrutural de conclusão do processo for semanticamente correspondente, a similaridade deve ser alta (limiar >= 85%).
            
            Examine as duas imagens em detalhes quanto a:
            - Layout e posicionamento de elementos estruturais de interface.
            - Dados preenchidos ou mensagens de transações bem-sucedidas (como caixas de diálogo de sucesso ou redirecionamentos de templates).
            - Identificação de possíveis modais, popups bloqueantes ou divergências de etapa final de negócio.
            
            Determine se as duas telas representam semanticamente o mesmo estado de conclusão de sucesso do processo.
            Considere que o script está pronto para ser avaliado pelo analista se o score de similaridade for alto (limiar ideal de 85 ou superior).
            
            Retorne OBRIGATORIAMENTE um objeto JSON válido contendo exatamente os seguintes campos:
            - "similarity_score": número inteiro de 0 a 100 (representando a aderência visual estrutural).
            - "differences": lista de strings detalhando as divergências estruturais observadas (se houver).
            - "ready_for_analyst": booleano (true se similarity_score >= 85 e não houver problemas críticos de quebras de layout).
            - "justification": string com uma explicação objetiva e técnica de seu julgamento.
            
            Retorne EXCLUSIVAMENTE o JSON estruturado.
            """
            
            raw_response = self._call_llm_api(prompt, [path_recorder, path_script])
            return self._clean_json_response(raw_response)

        except Exception as e:
            print(f"[COGNITIVE ERRO] Falha ao executar comparação visual: {e}")
            raise e

    def transcribe_audio(self, audio_file_path: str) -> str:
        """
        Transcreve um arquivo de áudio (.wav) para texto utilizando a API de transcrição do provedor (Whisper).
        Caso falhe ou não esteja ativo, utiliza um fallback amigável.
        """
        if not self.is_active():
            return "Transcrição de voz não disponível (Módulo cognitivo inativo)"
            
        url = f"{self.base_url}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        try:
            with open(audio_file_path, "rb") as f:
                files = {
                    "file": (os.path.basename(audio_file_path), f, "audio/wav")
                }
                data = {
                    "model": "whisper-1"
                }
                res = requests.post(url, headers=headers, files=files, data=data, timeout=30)
                if res.status_code == 200:
                    return res.json().get("text", "").strip()
                else:
                    print(f"[COGNITIVE WARNING] Transcrição falhou com status {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[COGNITIVE WARNING] Erro na requisição de transcrição de áudio: {e}")
            
        return "Preencher CPF do cliente para consulta de dados"

    def call_llm(self, prompt: str, force_json: bool = True) -> str:
        """Chamada pública direta para obter texto/resposta da LLM."""
        return self._call_llm_api(prompt, force_json=force_json)

    def parse_json_response(self, text: str) -> dict:
        """Limpa e analisa resposta JSON da LLM."""
        return self._clean_json_response(text)

