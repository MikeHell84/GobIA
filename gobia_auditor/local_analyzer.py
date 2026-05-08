"""
Motor de reglas heurísticas para detección de señales de opacidad en contratos públicos.

- No requiere API externa.
- Produce una salida compatible con el shape del LLM:
  { "score": int(0..100), "alertas": [str], "justificacion": str, ... }
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# Diccionario de alertas predefinidas (clave -> mensaje descriptivo profesional)
ALERTAS_DICT: dict[str, str] = {
    "objeto_vago": (
        "Objeto del contrato demasiado genérico o ambiguo. Indica posible falta de "
        "claridad en el alcance y dificulta la verificación de cumplimiento."
    ),
    "objeto_corto": (
        "Descripción del objeto muy breve (menos de 50 caracteres). Señal de baja "
        "transparencia o falta de especificidad."
    ),
    "valor_alto_sin_detalle": (
        "Valor del contrato superior a $500 millones COP con descripción insuficiente. "
        "Riesgo de sobreprecio o direccionamiento."
    ),
    "contratista_reciente": (
        "El contratista parece ser una empresa creada recientemente o con trazabilidad limitada "
        "(según la fecha disponible)."
    ),
    "modificaciones_excesivas": (
        "El contrato presenta más de 2 modificaciones/adiciones, lo que sugiere mala planeación "
        "o cambios discrecionales."
    ),
    "plazo_ajustado": (
        "Duración del contrato potencialmente corta para montos relevantes (señal de urgencia "
        "injustificada o direccionamiento)."
    ),
    "sin_anexos": (
        "No se encontraron documentos anexos (soportes) asociados al contrato. Falta de trazabilidad."
    ),
    "contratista_generico": (
        "El nombre del contratista contiene elementos genéricos (p.ej. 'servicios', 'consultoría', 'Ltda') "
        "sin evidencia de especialización clara."
    ),
    "entidad_generica": (
        "La entidad contratante tiene un nombre genérico o no está claramente identificada."
    ),
    "valor_extremo_bajo": (
        "Valor del contrato extremadamente bajo para el objeto descrito. Puede sugerir subvaloración "
        "o fraccionamiento."
    ),
}


# Pesos calibrados para score (suma simple acotada a 0..100)
ALERTA_PESOS: dict[str, int] = {
    "objeto_vago": 25,
    "objeto_corto": 15,
    "valor_alto_sin_detalle": 30,
    "contratista_reciente": 20,
    "modificaciones_excesivas": 20,
    "plazo_ajustado": 20,
    "sin_anexos": 15,
    "contratista_generico": 10,
    "entidad_generica": 10,
    "valor_extremo_bajo": 15,
}


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _parse_iso_date(value: Any) -> Optional[datetime]:
    """
    Intenta parsear strings comunes de fecha. Devuelve datetime (sin forzar tz).
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Normalizaciones comunes
        text = text.replace("Z", "+00:00")
        fmts = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        for fmt in fmts:
            try:
                return datetime.fromisoformat(text) if "T" in text else datetime.strptime(text, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None
    return None


def _texto_objeto(contrato: Dict[str, Any]) -> str:
    return (
        contrato.get("objeto")
        or contrato.get("objeto_a_contratar")
        or contrato.get("descripcion")
        or ""
    )


def _texto_contratista(contrato: Dict[str, Any]) -> str:
    return (
        contrato.get("contratista_nombre")
        or contrato.get("proveedor_adjudicado_nombre")
        or contrato.get("contratista")
        or ""
    )


def _texto_entidad(contrato: Dict[str, Any]) -> str:
    return (
        contrato.get("entidad_nombre")
        or contrato.get("entidad")
        or contrato.get("dependencia")
        or ""
    )


def detectar_alertas_locales(contrato: Dict[str, Any]) -> List[str]:
    """
    Analiza un contrato usando reglas heurísticas y retorna claves de alertas.
    """
    alertas: list[str] = []

    objeto = _texto_objeto(contrato)
    contratista = _texto_contratista(contrato)
    entidad = _texto_entidad(contrato)

    valor = _safe_float(
        contrato.get("valor_total")
        if contrato.get("valor_total") is not None
        else contrato.get("valor_contrato")
    )

    # Eventos de cambios
    modificaciones = contrato.get("modificaciones") or []
    adiciones = contrato.get("adiciones") or []
    num_cambios = (len(modificaciones) if isinstance(modificaciones, list) else 0) + (
        len(adiciones) if isinstance(adiciones, list) else 0
    )

    # Fechas
    fecha_inicio = contrato.get("fecha_inicio") or contrato.get("fecha_de_inicio_del_contrato")
    fecha_fin = contrato.get("fecha_fin") or contrato.get("fecha_de_fin_del_contrato")
    contratista_fecha_creacion = contrato.get("contratista_fecha_creacion")

    # Anexos
    anexos_urls = contrato.get("anexos_urls") or []
    tiene_anexos = isinstance(anexos_urls, list) and len(anexos_urls) > 0

    # --- REGLAS ---

    # 1) Objeto corto / vago
    if len(objeto.strip()) < 50:
        alertas.append("objeto_corto")
    generic_object = re.search(
        r"(prestación de servicios|consultoría|asesoría|apoyo|suministro|compra de|obra|contratación)",
        objeto,
        flags=re.IGNORECASE,
    )
    if generic_object and len(objeto.strip()) < 200:
        # Solo aplica como "vago" si además es relativamente corto/genérico
        alertas.append("objeto_vago")

    # 2) Valor alto con poca especificidad
    if valor > 500_000_000 and ("objeto_vago" in alertas or "objeto_corto" in alertas):
        alertas.append("valor_alto_sin_detalle")

    # 3) Contratista (reciente) por fecha creación si existe
    dt_created = _parse_iso_date(contratista_fecha_creacion)
    if dt_created:
        # Usar "ahora" naive para evitar problemas con tz
        now = datetime.now()
        if (now - dt_created).days < 365:
            alertas.append("contratista_reciente")

    # 4) Contratista genérico (heurística)
    if re.search(r"(servicios|consultoría|suministros|sasa|ltda|limitada|unipersonal)", contratista, flags=re.IGNORECASE):
        if len(contratista.split()) < 3:
            alertas.append("contratista_generico")

    # 5) Modificaciones/adiciones excesivas
    if num_cambios > 2:
        alertas.append("modificaciones_excesivas")

    # 6) Plazo ajustado (si hay fechas)
    dt_inicio = _parse_iso_date(fecha_inicio)
    dt_fin = _parse_iso_date(fecha_fin)
    if dt_inicio and dt_fin:
        duracion_dias = (dt_fin - dt_inicio).days
        if duracion_dias < 15 and valor > 100_000_000:
            alertas.append("plazo_ajustado")

    # 7) Sin anexos / soporte
    if not tiene_anexos:
        alertas.append("sin_anexos")

    # 8) Entidad genérica (si no hay o coincide con patrones)
    entidad_norm = entidad.strip().lower()
    if not entidad_norm:
        alertas.append("entidad_generica")
    else:
        if any(term in entidad_norm for term in ["entidad pública", "entidad estatal", "entidad estat", "secretaria", "alcaldia", "gobernacion"]):
            # No siempre es malo; lo tratamos como señal débil
            alertas.append("entidad_generica")

    # 9) Valor extremo bajo (heurística)
    if valor > 0 and valor < 10_000_000 and "suministro" in objeto.lower():
        alertas.append("valor_extremo_bajo")

    # Mantener orden determinista y máximo 6
    # (más de 6 hace que el texto sea difícil de leer)
    alertas_uniq: list[str] = []
    for a in alertas:
        if a not in alertas_uniq:
            alertas_uniq.append(a)
    return alertas_uniq[:6]


def calcular_score_local(alertas: List[str]) -> int:
    """
    Calcula score 0..100 basado en alertas detectadas.
    """
    total = 0
    for alerta in alertas:
        total += ALERTA_PESOS.get(alerta, 0)
    return max(0, min(total, 100))


def generar_justificacion(alertas: List[str]) -> str:
    """
    Convierte claves de alerta en texto legible para el frontend / reporte.
    """
    if not alertas:
        return "No se detectaron señales de opacidad significativas con las reglas heurísticas locales."

    mensajes = []
    for clave in alertas:
        mensajes.append(f"- {ALERTAS_DICT.get(clave, clave.replace('_', ' ').capitalize())}")
    return "Se encontraron las siguientes señales de opacidad:\n" + "\n".join(mensajes)


def analizar_contrato_local(contrato: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analiza el contrato usando reglas locales y retorna estructura compatible con LLM.
    """
    alertas = detectar_alertas_locales(contrato)
    score = calcular_score_local(alertas)
    return {
        "score": score,
        "alertas": [ALERTAS_DICT.get(a, a) for a in alertas],
        "justificacion": generar_justificacion(alertas),
        "modo": "local",
        "fallback": None,
    }
