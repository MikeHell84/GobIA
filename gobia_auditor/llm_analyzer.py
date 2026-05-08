import json
import os
import requests
import time

from typing import Any, Optional, Dict

try:
    import openai
except ImportError:
    openai = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class DeepSeekClient:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def generate_content(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1000,
        }
        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            elif response.status_code == 401:
                raise Exception("API key inválida o sin crédito. Revisa tu cuenta en deepseek.com")
            elif response.status_code == 402:
                raise Exception("Insufficient Balance: tu cuenta DeepSeek no tiene saldo suficiente.")
            elif response.status_code == 429:
                raise Exception("Rate limit exceeded. Espera un momento.")
            else:
                raise Exception(f"Error HTTP {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error de conexión con DeepSeek: {e}")


def get_llm_client(provider: str, api_key: Optional[str] = None, model: Optional[str] = None):
    if provider == "Deepseek":
        if not api_key:
            raise ValueError("API key requerida para Deepseek")
        return DeepSeekClient(api_key, model=model or "deepseek-chat")
    elif provider == "Google Gemini":
        if not genai:
            raise ImportError("google-generativeai no está instalado")
        if not api_key:
            raise ValueError("API key requerida para Google Gemini")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model or "gemini-2.0-flash")
    elif provider == "OpenAI":
        if not openai:
            raise ImportError("openai no está instalado")
        if not api_key:
            raise ValueError("API key requerida para OpenAI")
        if hasattr(openai, "OpenAI"):
            return openai.OpenAI(api_key=api_key)
        openai.api_key = api_key
        return openai
    else:
        raise ValueError(f"Proveedor no soportado: {provider}")


def analizar_con_llm(objeto: str, valor: float, contrato: Dict[str, Any], llm_client, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
    """
    Analiza usando LLM remoto. Si falla por cualquier motivo, aplica fallback local
    usando gobia_auditor/local_analyzer.py de forma transparente.

    Retorna siempre un dict con shape compatible:
      { "score": int, "alertas": [str], "justificacion": str, "modo": "llm|local", "fallback": ... }

    Extensión para UX:
      - origen: "LLM ({provider})" o "Local (heurístico)"
      - exito_llm: True/False
    """
    # Import tardío para no acoplar hard la app si el archivo no existe en algún build parcial
    from gobia_auditor.local_analyzer import analizar_contrato_local

    prompt = f"""
Eres un auditor de contratos públicos en Colombia. Analiza el siguiente contrato y responde SOLO con un JSON válido (sin texto adicional, sin markdown). El JSON debe tener estos campos:
{{
  "score": <entero entre 0 y 100>,
  "alertas": ["alerta1", "alerta2", ...],
  "justificacion": "texto breve"
}}

Contrato:
- Objeto: {objeto}
- Valor: ${valor:,.0f} COP
- Entidad: {contrato.get('entidad_nombre', 'N/A')}
- Contratista: {contrato.get('contratista_nombre', 'N/A')}
- Departamento: {contrato.get('departamento', 'N/A')}
- Ciudad: {contrato.get('ciudad', 'N/A')}
"""
    try:
        if provider == "Deepseek":
            respuesta_texto = llm_client.generate_content(prompt)
        elif provider == "Google Gemini":
            response = llm_client.generate_content(prompt)
            respuesta_texto = response.text
        elif provider == "OpenAI":
            if hasattr(llm_client, "chat"):
                response = llm_client.chat.completions.create(
                    model=model or "gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
            else:
                response = llm_client.ChatCompletion.create(
                    model=model or "gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
            respuesta_texto = response.choices[0].message.content
        else:
            raise ValueError(f"Proveedor no soportado: {provider}")

        respuesta_texto = respuesta_texto.strip()
        if respuesta_texto.startswith("```json"):
            respuesta_texto = respuesta_texto[7:]
        if respuesta_texto.startswith("```"):
            respuesta_texto = respuesta_texto[3:]
        if respuesta_texto.endswith("```"):
            respuesta_texto = respuesta_texto[:-3]
        respuesta_texto = respuesta_texto.strip()

        resultado = json.loads(respuesta_texto)
        # Metadatos para UI / debugging
        resultado["modo"] = "llm"
        resultado["fallback"] = None
        resultado["origen"] = f"LLM ({provider})"
        resultado["exito_llm"] = True
        return resultado
    except Exception as e:
        # Fallback local transparente
        local_resultado = analizar_contrato_local(contrato)
        local_resultado["fallback"] = str(e)
        local_resultado["origen"] = "Local (heurístico)"
        local_resultado["exito_llm"] = False
        local_resultado["error_llm"] = str(e)
        return local_resultado




def calcular_score_local(objeto, valor, contrato):
    """Reglas heurísticas locales como fallback"""
    score = 0
    alertas = []

    if objeto and len(objeto.split()) < 5:
        score += 30
        alertas.append("Objeto del contrato muy breve o vago")

    try:
        val_num = float(str(valor).replace('$', '').replace(',', ''))
        if val_num > 1000000000:
            score += 40
            alertas.append("Valor del contrato muy alto")
    except Exception:
        pass

    if contrato.get('contratista_fecha_creacion'):
        try:
            from datetime import datetime

            fecha = datetime.fromisoformat(contrato['contratista_fecha_creacion'])
            if (datetime.now() - fecha).days < 365:
                score += 20
                alertas.append("Contratista registrado recientemente")
        except Exception:
            pass

    return {
        "score": min(score, 100),
        "alertas": alertas,
        "justificación": "Análisis basado en reglas locales",
        "fuente": "local",
    }


class LLMAnalyzer:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        if openai and self.api_key:
            openai.api_key = self.api_key

    def analyze_contract(self, contract: dict[str, Any]) -> dict | None:
        if not openai or not self.api_key:
            return None

        prompt = self._build_prompt(contract)
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Eres un auditor de riesgos de contratos públicos colombianos."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=350,
            )
        except Exception as exc:
            print(f"[LLM] Error al llamar la API: {exc}")
            return None

        content = response.choices[0].message.content
        parsed = self._parse_response(content)
        if parsed is None:
            return None
        parsed["fuente"] = "api"
        return parsed

    def _build_prompt(self, contract: dict[str, Any]) -> str:
        dia_total = None
        if contract.get("fecha_inicio") and contract.get("fecha_fin"):
            try:
                from datetime import datetime

                inicio = datetime.fromisoformat(contract["fecha_inicio"])
                fin = datetime.fromisoformat(contract["fecha_fin"])
                dia_total = (fin - inicio).days
            except ValueError:
                dia_total = None

        prompt = """Analiza el siguiente contrato público colombiano y responde exclusivamente en JSON con las claves:
alertas, score, justificacion. Usa un máximo de 5 alertas.

Contrato:
Objeto: {objeto}
Valor: {valor}
Duración: {duracion}
Modificaciones: {num_modificaciones}
Adiciones: {num_adiciones}
Contratista: {contratista} (fecha_creacion: {fecha_creacion})
Entidad: {entidad}
URL anexos: {anexos}

Respuesta:
{{
  "alertas": ["..."],
  "score": 0,
  "justificacion": "..."
}}"""

        return prompt.format(
            objeto=contract.get("objeto") or "No disponible",
            valor=contract.get("valor_total") or "No disponible",
            duracion=f"{dia_total} días" if dia_total is not None else "No disponible",
            num_modificaciones=len(contract.get("modificaciones", [])),
            num_adiciones=len(contract.get("adiciones", [])),
            contratista=contract.get("contratista_nombre") or "No disponible",
            fecha_creacion=contract.get("contratista_fecha_creacion") or "No disponible",
            entidad=contract.get("entidad_nombre") or "No disponible",
            anexos=contract.get("anexos_urls") or "No disponible",
        )

    def _parse_response(self, content: str) -> dict | None:
        text = content.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                candidate = text[start:end]
                return json.loads(candidate)
            except Exception:
                print("[LLM] No se pudo parsear la respuesta JSON del LLM.")
                return None
