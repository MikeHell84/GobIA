from datetime import datetime, timedelta, timezone

ALERTA_WEIGHTS = {
    "OBJETO_VAGO": 20,
    "CONTRATISTA_NUEVO": 15,
    "FALTA_ANEXOS": 15,
    "MODIFICACIONES_EXCESIVAS": 20,
    "FECHA_AJUSTADA": 15,
    "ENTIDAD_FANTASMA": 15,
    "SOBREPRECIO_SUBVALORACION": 20,
}

GENERIC_CONTRACT_OBJECTS = [
    "prestacion de servicios",
    "contratacion",
    "obra",
    "servicios profesionales",
    "apoyo",
    "asesoria",
    "consultoria",
]

GENERIC_ENTITIES = [
    "entidad estat",
    "entidad pública",
    "entidad estatal",
    "secretaria",
    "alcaldia",
    "gobernacion",
]


class RiskScorer:
    def analyze_contract_with_rules(self, contract: dict) -> dict:
        alertas = []
        score = 0
        justifications = []

        objeto = (contract.get("objeto") or "").lower()
        if self._is_objeto_vago(objeto):
            alertas.append("Objeto del contrato vago o genérico")
            score += ALERTA_WEIGHTS["OBJETO_VAGO"]
            justifications.append("La descripción del objeto es insuficiente o demasiado genérica.")

        if self._is_contratista_nuevo(contract):
            alertas.append("Contratista reciente o con poca trazabilidad")
            score += ALERTA_WEIGHTS["CONTRATISTA_NUEVO"]
            justifications.append("El contratista parece haber sido constituido recientemente o no tiene fecha de creación clara.")

        if self._has_missing_anexos(contract):
            alertas.append("Falta de anexos o soportes documentales")
            score += ALERTA_WEIGHTS["FALTA_ANEXOS"]
            justifications.append("No se encontraron anexos públicos asociados al contrato.")

        if self._has_excessive_modifications(contract):
            alertas.append("Modificaciones o adiciones excesivas")
            score += ALERTA_WEIGHTS["MODIFICACIONES_EXCESIVAS"]
            justifications.append("El contrato presenta múltiples cambios, adiciones o ajustes de plazos.")

        if self._has_fecha_ajustada(contract):
            alertas.append("Fecha ajustada o cercana a cambios institucionales")
            score += ALERTA_WEIGHTS["FECHA_AJUSTADA"]
            justifications.append("La firma del contrato se da en un momento sensible del calendario político o legal.")

        if self._is_entidad_fantasma(contract):
            alertas.append("Entidad estatal con trazabilidad débil")
            score += ALERTA_WEIGHTS["ENTIDAD_FANTASMA"]
            justifications.append("La entidad no contiene información clara o es demasiado genérica.")

        if self._has_precio_sospechoso(contract):
            alertas.append("Valor del contrato inusual o sospechoso")
            score += ALERTA_WEIGHTS["SOBREPRECIO_SUBVALORACION"]
            justifications.append("El valor total del contrato no parece alinearse con un proyecto transparente.")

        score = min(100, score)
        justificacion = " ".join(justifications).strip()

        return {
            "alertas": alertas[:5],
            "score": score,
            "justificacion": justificacion or "Evaluación local realizada con señales básicas de riesgo.",
        }

    def _is_objeto_vago(self, objeto: str) -> bool:
        if len(objeto) < 30:
            return True
        return any(term in objeto for term in GENERIC_CONTRACT_OBJECTS)

    def _is_contratista_nuevo(self, contract: dict) -> bool:
        fecha = contract.get("contratista_fecha_creacion")
        if not fecha:
            return False
        try:
            created = datetime.fromisoformat(fecha)
            # Normalizar a "aware" en UTC para evitar comparar naive vs aware
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=365)
            return created > cutoff
        except ValueError:
            return False

    def _has_missing_anexos(self, contract: dict) -> bool:
        anexos = contract.get("anexos_urls") or []
        raw = contract.get("fuente_raw") or {}
        has_document_fields = any(
            key in raw for key in ["anexos", "anexo", "documentos", "urls", "documento", "soporte"]
        )
        if not has_document_fields:
            return False
        return len(anexos) == 0

    def _has_excessive_modifications(self, contract: dict) -> bool:
        modificaciones = contract.get("modificaciones") or []
        adiciones = contract.get("adiciones") or []
        if len(modificaciones) > 2 or len(adiciones) > 2:
            return True
        if len(modificaciones) + len(adiciones) > 2:
            return True
        return False

    def _has_fecha_ajustada(self, contract: dict) -> bool:
        fecha_inicio = contract.get("fecha_inicio")
        if not fecha_inicio:
            return False
        try:
            start = datetime.fromisoformat(fecha_inicio)
            start = start.replace(tzinfo=timezone.utc)  # Make naive datetime aware
            if start.month in (11, 12) or start.month == 1:
                return True
            if start >= datetime.now(timezone.utc) - timedelta(days=60):
                return True
        except ValueError:
            return False
        return False

    def _is_entidad_fantasma(self, contract: dict) -> bool:
        entidad = (contract.get("entidad_nombre") or "").lower()
        if not entidad:
            return True
        return any(term in entidad for term in GENERIC_ENTITIES)

    def _has_precio_sospechoso(self, contract: dict) -> bool:
        valor = contract.get("valor_total")
        if valor is None:
            return False
        if valor <= 0:
            return True
        if valor > 10_000_000_000:
            return True
        return False
