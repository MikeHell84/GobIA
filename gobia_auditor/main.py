import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from dotenv import load_dotenv

from gobia_auditor.llm_analyzer import LLMAnalyzer
from gobia_auditor.reporter import ReportBuilder
from gobia_auditor.risk_scorer import RiskScorer
from gobia_auditor.secop_client import SecopClient


def create_database(db_path: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_analysis (
            contrato_id TEXT PRIMARY KEY,
            objeto TEXT,
            valor_total REAL,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            contratista_nombre TEXT,
            entidad_nombre TEXT,
            score INTEGER,
            alertas TEXT,
            justificacion TEXT,
            fuente TEXT,
            analisis_fecha TEXT
        )
        """
    )
    conn.commit()
    return conn


def save_results(conn: sqlite3.Connection, results: list[dict]):
    cursor = conn.cursor()
    for item in results:
        cursor.execute(
            """
            INSERT OR REPLACE INTO contract_analysis (
                contrato_id, objeto, valor_total, fecha_inicio, fecha_fin,
                contratista_nombre, entidad_nombre, score, alertas,
                justificacion, fuente, analisis_fecha
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("contrato_id"),
                item.get("objeto"),
                item.get("valor_total"),
                item.get("fecha_inicio"),
                item.get("fecha_fin"),
                item.get("contratista_nombre"),
                item.get("entidad_nombre"),
                item.get("score"),
                "; ".join(item.get("alertas", [])),
                item.get("justificacion"),
                item.get("fuente", "local"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()


def parse_float_input(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def prompt_text(prompt: str, default: str | None = None) -> str | None:
    answer = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
    return answer or default


def format_filter_summary(filters: dict[str, Any]) -> str:
    if not filters:
        return "Sin filtros aplicados"
    parts: list[str] = []
    if filters.get("departamento"):
        parts.append(f"Departamento={filters['departamento']}")
    if filters.get("ciudad"):
        parts.append(f"Ciudad={filters['ciudad']}")
    if filters.get("tipo_contrato"):
        parts.append(f"Tipo de contrato={filters['tipo_contrato']}")
    if filters.get("valor_min") is not None:
        parts.append(f"Valor mínimo={filters['valor_min']}")
    if filters.get("valor_max") is not None:
        parts.append(f"Valor máximo={filters['valor_max']}")
    if filters.get("dias") is not None:
        parts.append(f"Últimos {filters['dias']} días")
    if filters.get("use_sample_data"):
        parts.append("Modo ejemplo local")
    return ", ".join(parts) if parts else "Sin filtros aplicados"


def run_analysis(
    secop: SecopClient,
    analyzer: LLMAnalyzer,
    scorer: RiskScorer,
    reporter: ReportBuilder,
    conn: sqlite3.Connection,
    filters: dict[str, Any],
    threshold: int,
    max_records: int,
):
    print("[GobIA Auditor] Iniciando análisis de contratos con filtros avanzados...")
    raw_contracts = secop.obtener_contratos(
        limite=max_records,
        departamento=filters.get("departamento"),
        ciudad=filters.get("ciudad"),
        tipo_contrato=filters.get("tipo_contrato"),
        valor_min=filters.get("valor_min"),
        valor_max=filters.get("valor_max"),
        dias=filters.get("dias"),
    )

    if not raw_contracts:
        print("No se encontraron contratos con esos filtros o hubo un error de conexión.")
        return

    results: list[dict] = []
    for raw in raw_contracts:
        contrato = secop.normalize_contract(raw)
        if not contrato["contrato_id"]:
            continue

        analysis = analyzer.analyze_contract(contrato)
        if analysis is None or analysis.get("score") is None:
            analysis = scorer.analyze_contract_with_rules(contrato)
            analysis["fuente"] = "local"
        else:
            backup = scorer.analyze_contract_with_rules(contrato)
            if backup.get("score", 0) > analysis.get("score", 0):
                analysis["score"] = backup["score"]
                analysis["alertas"] = list({*analysis.get("alertas", []), *backup.get("alertas", [])})[:5]
                analysis["justificacion"] = (
                    analysis.get("justificacion", "") + " | " + backup.get("justificacion", "")
                ).strip(" | ")
            analysis["fuente"] = "llm"

        results.append({**contrato, **analysis})

    if not results:
        print("No se pudo analizar ningún contrato después de normalizar.")
        return

    df = pd.DataFrame(results)
    save_results(conn, results)

    critical = df[df["score"] >= threshold].sort_values(by="score", ascending=False)
    alert_ranking = reporter.compute_alert_ranking(results)
    filter_summary = format_filter_summary(filters)

    html_report = reporter.build_html_report(
        results=results,
        critical_contracts=critical.to_dict(orient="records"),
        alert_ranking=alert_ranking,
        generated_at=datetime.now(timezone.utc),
        threshold=threshold,
        filtro_descripcion=filter_summary,
    )
    report_path = reporter.save_html_report(html_report)

    total = len(results)
    critical_count = len(critical)
    summary = reporter.build_summary_message(
        total_contracts=total,
        critical_count=critical_count,
        report_path=report_path,
        threshold=threshold,
    )

    print(summary)
    if critical_count > 0:
        print("Contratos críticos:")
        for row in critical.to_dict(orient="records"):
            print(f"- {row.get('contrato_id')} (score {row.get('score')}): {row.get('alertas')}")

    email_sent = reporter.send_email_report(summary, html_report)
    if email_sent:
        print("Correo enviado al capitán correctamente.")
    else:
        print("No se envió correo. Revisa la configuración de SMTP o usa el reporte HTML guardado.")

    print(f"Reporte guardado en: {report_path}")


def main():
    load_dotenv()

    api_url = os.getenv("SECOP_API_URL", "https://www.datos.gov.co/resource/rtxx-3nky.json")
    days_window = int(os.getenv("SECOP_DAYS_WINDOW", "30"))
    threshold = int(os.getenv("RISK_THRESHOLD", "70"))
    max_records = int(os.getenv("SECOP_MAX_RECORDS", "200"))

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "datos"))
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(output_dir, "contracts.db")
    conn = create_database(db_path)

    secop = SecopClient(api_base=api_url)
    analyzer = LLMAnalyzer()
    scorer = RiskScorer()
    reporter = ReportBuilder(output_dir=output_dir)

    while True:
        print("\n=== GobIA Auditor ===")
        print("1) Analizar contratos recientes")
        print("2) Analizar contratos con filtros avanzados")
        print("3) Analizar usando datos de ejemplo locales")
        print("4) Salir")
        choice = input("Selecciona una opción [1-4]: ").strip()

        if choice == "1":
            filters = {"dias": days_window}
            run_analysis(secop, analyzer, scorer, reporter, conn, filters, threshold, max_records)
        elif choice == "2":
            departamento = prompt_text("Departamento (ej: Antioquia)")
            ciudad = prompt_text("Ciudad (ej: Medellín)")
            tipo_contrato = prompt_text("Tipo de contrato/tipoproceso")
            valor_min = parse_float_input(prompt_text("Valor mínimo (solo dígitos)"))
            valor_max = parse_float_input(prompt_text("Valor máximo (solo dígitos)"))
            dias = int(prompt_text("Últimos días a buscar", str(days_window)) or days_window)
            filters = {
                "departamento": departamento,
                "ciudad": ciudad,
                "tipo_contrato": tipo_contrato,
                "valor_min": valor_min,
                "valor_max": valor_max,
                "dias": dias,
            }
            run_analysis(secop, analyzer, scorer, reporter, conn, filters, threshold, max_records)
        elif choice == "3":
            secop.use_sample_data = True
            filters = {"use_sample_data": True}
            run_analysis(secop, analyzer, scorer, reporter, conn, filters, threshold, max_records)
            secop.use_sample_data = False
        elif choice == "4":
            print("Saliendo. Hasta luego.")
            break
        else:
            print("Opción inválida. Intenta de nuevo.")


if __name__ == "__main__":
    main()
