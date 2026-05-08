import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)
BASE_URL = os.getenv("SECOP_API_URL", "https://www.datos.gov.co/resource/rtxx-3nky.json")
APP_TOKEN = os.getenv("SOCATA_APP_TOKEN", "")
DEFAULT_TIMEOUT = 8


class SecopClient:
    def __init__(self, api_base: str):
        self.api_base = api_base
        self.session = requests.Session()
        self.api_key = os.getenv("API_KEY_SECOP")
        self.app_token = os.getenv("SOCATA_APP_TOKEN") or os.getenv("SECOP_APP_TOKEN")
        self.use_sample_data = os.getenv("SECOP_USE_SAMPLE_DATA", "false").lower() in ("1", "true", "yes")

    def _build_where_filter(
        self,
        departamento: str | None = None,
        ciudad: str | None = None,
        tipo_contrato: str | None = None,
        valor_min: float | None = None,
        valor_max: float | None = None,
        since_date: str | None = None,
    ) -> str:
        condiciones: list[str] = []
        if departamento:
            # El dataset actual no expone un campo 'departamento' directo, usamos localizaci_n como aproximación.
            condiciones.append(f"localizaci_n LIKE '%{departamento}%'")
        if ciudad:
            condiciones.append(f"ciudad = '{ciudad}'")
        if tipo_contrato:
            condiciones.append(f"tipo_de_contrato = '{tipo_contrato}'")
        if valor_min is not None:
            condiciones.append(f"valor_del_contrato >= {valor_min}")
        if valor_max is not None:
            condiciones.append(f"valor_del_contrato <= {valor_max}")
        if since_date:
            condiciones.append(
                f"(fecha_de_inicio_del_contrato >= '{since_date}' OR fecha_de_firma >= '{since_date}')"
            )
        if not condiciones:
            return ""
        return " AND ".join(f"({cond})" for cond in condiciones)

    def obtener_contratos(
        self,
        limite: int = 100,
        departamento: str | None = None,
        ciudad: str | None = None,
        tipo_contrato: str | None = None,
        valor_min: float | None = None,
        valor_max: float | None = None,
        dias: int | None = None,
    ) -> list[dict[str, Any]]:
        if self.use_sample_data:
            print("[SECOP] Modo offline activo: usando datos de ejemplo locales.")
            return self._load_sample_contracts()

        params = {
            "$limit": min(1000, max(1, limite)),
            "$order": "fecha_de_inicio_del_contrato DESC",
        }
        headers = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        elif self.api_key:
            headers["X-App-Token"] = self.api_key

        since_date = None
        if dias is not None:
            since_date = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")

        where = self._build_where_filter(
            departamento=departamento,
            ciudad=ciudad,
            tipo_contrato=tipo_contrato,
            valor_min=valor_min,
            valor_max=valor_max,
            since_date=since_date,
        )
        if where:
            params["$where"] = where

        logger.info("[SECOP] Consultando contratos con filtros: %s", where or "sin filtros")
        try:
            response = self.session.get(self.api_base, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
        except RequestException as exc:
            logger.error("Error al consultar SECOP: %s", exc)
            return []

        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("results") or payload.get("data") or []

    def obtener_valores_distintos(self, field: str, limite: int = 200) -> list[str]:
        if self.use_sample_data:
            return []

        params = {
            "$select": f"distinct {field}",
            "$limit": min(1000, max(1, limite)),
            "$order": field,
        }
        headers = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        elif self.api_key:
            headers["X-App-Token"] = self.api_key

        for attempt in range(2):  # Retry up to 2 times
            try:
                response = self.session.get(self.api_base, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
                break
            except RequestException as exc:
                if attempt == 1:  # Last attempt
                    logger.error("Error al obtener valores distintos de '%s': %s", field, exc)
                    return []
                time.sleep(1)  # Wait 1 second before retry

        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("results") or payload.get("data") or []
        values: list[str] = []
        for row in rows:
            value = row.get(field)
            if isinstance(value, str):
                value = self._normalize_location_string(value)
                if value:
                    values.append(value)
        return sorted(set(values), key=str.casefold)

    def listar_departamentos(self) -> list[str]:
        return self.obtener_valores_distintos("localizaci_n")

    def listar_ciudades(self) -> list[str]:
        return self.obtener_valores_distintos("ciudad")

    def listar_tipos_contrato(self) -> list[str]:
        return self.obtener_valores_distintos("tipo_de_contrato")

    def _normalize_location_string(self, value: str) -> str:
        value = value.strip()
        if value.lower().startswith("colombia,"):
            normalized = value[len("colombia,"):].strip()
        else:
            normalized = value
        return re.sub(r"\s+", " ", normalized)

    def fetch_recent_contracts(self, days: int = 30, max_records: int = 200) -> list[dict[str, Any]]:
        return self.obtener_contratos(limite=max_records, dias=days)

    def _load_sample_contracts(self) -> list[dict[str, Any]]:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sample_path = os.path.join(base_dir, "datos", "sample_contracts.json")
        if os.path.exists(sample_path):
            try:
                import json

                with open(sample_path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:
                print(f"[SECOP] No se pudo cargar el archivo de prueba: {exc}")

        print("[SECOP] Usando ejemplos internos de contratos.")
        return [
            {
                "contrato_id": "TEST-0001",
                "objeto": "Consultoría para la elaboración de estudios técnicos de infraestructura educativa.",
                "valor_total": 150000000.0,
                "fecha_inicio": "2026-04-10",
                "fecha_fin": "2026-07-10",
                "contratista_nombre": "Proveedor Ejemplo SA",
                "contratista_fecha_creacion": "2024-09-15",
                "entidad_nombre": "Secretaría de Educación Municipal",
                "url_contrato": "https://www.datos.gov.co/",
                "modificaciones": [],
                "adiciones": [],
                "anexos_urls": ["https://www.datos.gov.co/ejemplo/anexo.pdf"],
            },
            {
                "contrato_id": "TEST-0002",
                "objeto": "Suministro de mobiliario para oficinas administrativas.",
                "valor_total": 32000000.0,
                "fecha_inicio": "2026-04-20",
                "fecha_fin": "2026-06-20",
                "contratista_nombre": "Muebles y Servicios LTDA",
                "contratista_fecha_creacion": "2025-11-10",
                "entidad_nombre": "Entidad Estatal de Compras",
                "url_contrato": "https://www.datos.gov.co/",
                "modificaciones": [{"descripcion": "Adición de plazo 15 días."}],
                "adiciones": [{"descripcion": "Adición valor 3.200.000."}],
                "anexos_urls": [],
            },
        ]

    def _build_url_secop(self, raw: dict[str, Any]) -> str | None:
        """
        Construye un enlace directo a SECOP II (community.secop.gov.co) por IdProceso.

        Endpoint recomendado (dataset SECOP II):
          https://www.datos.gov.co/resource/p6dx-8zbt.json
        Campo clave:
          - id_del_proceso

        Enlace:
          https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index
            ?currentLanguage=es-CO&Page=login&Country=CO&SkinName=CCE&IdProceso={id_del_proceso}
        """
        # Para ir al detalle exacto del contrato en SECOP II usamos:
        # https://community.secop.gov.co/Public/Tendering/ContractDetailView/Index?UniqueIdentifier={id_contrato}
        id_contrato = self._get_first_value(
            raw,
            [
                "id_contrato",
                "contrato_id",
                "referencia_del_contrato",
                "numero_contrato",
                "numero",
                "id",
            ],
        )
        if not id_contrato:
            # fallback: si no hay id_contrato, intentamos con el id del proceso como último recurso
            id_del_proceso = self._get_first_value(
                raw,
                [
                    "id_del_proceso",
                    "IdProceso",
                    "id_proceso",
                    "numConstancia",
                    "codigo_proceso",
                    "codigo_contrato",
                ],
            )
            if not id_del_proceso:
                return None

            return (
                "https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index"
                "?currentLanguage=es-CO&Page=login&Country=CO&SkinName=CCE&IdProceso="
                f"{id_del_proceso}"
            )

        return (
            "https://community.secop.gov.co/Public/Tendering/ContractDetailView/Index"
            f"?UniqueIdentifier={id_contrato}"
        )

    def normalize_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        contrato_id = self._get_first_value(
            raw,
            ["id_contrato", "contrato_id", "referencia_del_contrato", "id", "numero_contrato", "numero"],
        )

        departamento = self._get_first_value(raw, ["departamento", "departamento_nombre", "localizaci_n"])
        ciudad = self._get_first_value(raw, ["ciudad", "municipio"])
        tipo_contrato = self._get_first_value(
            raw,
            [
                "tipo_de_contrato",
                "tipo_contrato",
                "tipoproceso",
                "tipo_proceso",
                "modalidad",
            ],
        )

        url_secop = self._build_url_secop(raw)

        return {
            "contrato_id": contrato_id,
            "departamento": departamento,
            "ciudad": ciudad,
            "tipo_contrato": tipo_contrato,
            "objeto": self._get_first_value(raw, ["descripcion_del_proceso", "objeto", "descripcion_objeto", "descripcion"]),
            "valor_total": self._parse_float(
                self._get_first_value(raw, ["valor_del_contrato", "valor_total", "valor_contrato", "valor", "monto"])
            ),
            "fecha_inicio": self._parse_date(
                self._get_first_value(raw, ["fecha_de_inicio_del_contrato", "fecha_inicio", "fecha_firma", "inicio"])
            ),
            "fecha_fin": self._parse_date(
                self._get_first_value(raw, ["fecha_de_fin_del_contrato", "fecha_fin", "fecha_culminacion", "fin", "fecha_terminacion"])
            ),
            "contratista_nombre": self._get_first_value(
                raw,
                ["nombre_representante_legal", "contratista_nombre", "nombre_contratista", "contratista", "empresa"],
            ),
            "contratista_fecha_creacion": self._parse_date(
                self._get_first_value(raw, ["contratista_fecha_creacion", "fecha_creacion", "fecha_constitucion"])
            ),
            "entidad_nombre": self._get_first_value(raw, ["nombre_entidad", "entidad_nombre", "entidad", "dependencia"]),
            "modificaciones": self._normalize_events(
                raw, ["modificaciones", "modificacion", "cambios_plazo", "cambios_valor", "dias_adicionados"]
            ),
            "adiciones": self._normalize_events(
                raw, ["adiciones", "adicion", "incrementos", "sumas_adicionales", "valor_amortizado", "valor_facturado"]
            ),
            "anexos_urls": self._extract_urls(
                self._get_first_value(
                    raw,
                    ["anexos", "anexo", "documentos", "urls", "descripcion_del_proceso", "referencia_del_contrato"],
                )
            ),
            # Best-effort: en el dataset real puede venir con otro nombre de campo
            "url_contrato": self._get_first_value(
                raw,
                ["url_contrato", "url", "link", "url_documento", "url_proceso", "enlace"],
            ),
            "url_secop": url_secop,
            "fuente_raw": raw,
        }

    def _get_first_value(self, mapping: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in mapping and mapping[key] not in (None, "", [], {}):
                return mapping[key]
        return None

    def _parse_date(self, value: Any) -> str | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, str):
            value = value.strip()
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    return datetime.strptime(value, fmt).date().isoformat()
                except ValueError:
                    continue
        return None

    def _parse_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r"[^0-9.-]", "", value)
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _normalize_events(self, raw: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        value = self._get_first_value(raw, keys)
        if value is None:
            return []
        if isinstance(value, list):
            return [self._normalize_event(item) for item in value]
        if isinstance(value, dict):
            return [self._normalize_event(value)]
        if isinstance(value, (int, float)):
            if value == 0:
                return []
            return [{"descripcion": f"Total eventos: {int(value)}"}]
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.isdigit():
                if int(cleaned) == 0:
                    return []
                return [{"descripcion": f"Total eventos: {cleaned}"}]
            return [{"descripcion": cleaned}]
        return []

    def _normalize_event(self, event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            return event
        return {"descripcion": str(event)}

    def _extract_urls(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            urls = []
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    urls.extend(self._extract_urls(list(item.values())))
            return urls
        if isinstance(value, dict):
            urls = []
            for item in value.values():
                urls.extend(self._extract_urls(item))
            return urls
        if isinstance(value, str):
            return re.findall(r"https?://\S+", value)
        return []
