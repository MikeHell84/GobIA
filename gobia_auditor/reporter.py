import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class ReportBuilder:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def compute_alert_ranking(self, results: list[dict]) -> list[tuple[str, int]]:
        counter: dict[str, int] = {}
        for item in results:
            for alert in item.get("alertas", []):
                counter[alert] = counter.get(alert, 0) + 1
        return sorted(counter.items(), key=lambda pair: pair[1], reverse=True)

    def build_html_report(
        self,
        results: list[dict],
        critical_contracts: list[dict],
        alert_ranking: list[tuple[str, int]],
        generated_at: datetime,
        threshold: int,
        filtro_descripcion: str = "Sin filtros aplicados",
    ) -> str:
        rows = ""
        for item in results:
            rows += (
                "<tr>"
                f"<td>{item.get('contrato_id')}</td>"
                f"<td>{item.get('entidad_nombre')}</td>"
                f"<td>{item.get('contratista_nombre')}</td>"
                f"<td>{item.get('score')}</td>"
                f"<td>{', '.join(item.get('alertas', []))}</td>"
                f"<td>{item.get('justificacion')}</td>"
                "</tr>"
            )

        ranking_rows = "".join(
            f"<tr><td>{alert}</td><td>{count}</td></tr>" for alert, count in alert_ranking
        )

        return f"""
        <html>
        <head>
            <meta charset='utf-8'>
            <title>Reporte GobIA Auditor</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 24px; }}
                table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
                th {{ background: #f3f3f3; }}
                .critical {{ background: #ffe6e6; }}
            </style>
        </head>
        <body>
            <h1>Reporte GobIA Auditor</h1>
            <p>Fecha de generación: {generated_at.isoformat()}</p>
            <p>Total contratos: {len(results)}</p>
            <p>Umbral crítico: {threshold}</p>
            <p>Filtros aplicados: {filtro_descripcion}</p>
            <h2>Contratos críticos</h2>
            <ul>
                {''.join(f"<li>{item.get('contrato_id')} - Score {item.get('score')} - {', '.join(item.get('alertas', []))}</li>" for item in critical_contracts)}
            </ul>
            <h2>Ranking de alertas</h2>
            <table>
                <thead><tr><th>Alerta</th><th>Frecuencia</th></tr></thead>
                <tbody>{ranking_rows}</tbody>
            </table>
            <h2>Contratos analizados</h2>
            <table>
                <thead><tr><th>ID</th><th>Entidad</th><th>Contratista</th><th>Score</th><th>Alertas</th><th>Justificación</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </body>
        </html>
        """.strip()

    def save_html_report(self, html_content: str) -> str:
        filename = f"reporte_riesgos_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        file_path = os.path.join(self.output_dir, filename)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(html_content)
        return file_path

    def build_summary_message(self, total_contracts: int, critical_count: int, report_path: str, threshold: int) -> str:
        return (
            f"Reporte GobIA Auditor - Fecha {datetime.utcnow().date()} - Total contratos: {total_contracts}"
            f" - Contratos críticos (score > {threshold}): {critical_count}."
            f" Archivo de reporte: {report_path}"
        )

    def send_email_report(self, summary: str, html_report: str) -> bool:
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        email_from = os.getenv("EMAIL_FROM")
        email_to = os.getenv("EMAIL_TO")

        if not all([smtp_host, smtp_user, smtp_password, email_from, email_to]):
            return False

        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = "Reporte GobIA Auditor"
            message["From"] = email_from
            message["To"] = email_to
            message.attach(MIMEText(summary, "plain", "utf-8"))
            message.attach(MIMEText(html_report, "html", "utf-8"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(email_from, [email_to], message.as_string())
            return True
        except Exception as exc:
            print(f"[Email] No se pudo enviar el correo: {exc}")
            return False
