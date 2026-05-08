# GobIA Auditor

Agente de auditoría de contratos públicos colombianos con análisis de riesgo y señales de alerta.

## Estructura

- `gobia_auditor/main.py`: flujo principal.
- `gobia_auditor/secop_client.py`: conexión y normalización de contratos desde SECOP II.
- `gobia_auditor/llm_analyzer.py`: integración opcional con OpenAI/GPT.
- `gobia_auditor/risk_scorer.py`: cálculo de score local y alertas.
- `gobia_auditor/reporter.py`: generación de informe HTML y envío por correo.
- `datos/`: carpeta para base de datos y reportes.

## Requisitos

- Python 3.10+
- Crear y activar entorno virtual:

```bash
python -m venv venv
venv\Scripts\activate
```

- Instalar dependencias:

```bash
pip install -r requirements.txt
```

## Configuración

1. Copia el archivo de ejemplo:

```bash
copy .env.example .env
```

2. Edita `.env` con tus credenciales:

- `API_KEY_SECOP` o `SECOP_APP_TOKEN`: opcional si la API de datos requiere autenticación.
- `LLM_API_KEY`: clave de OpenAI o de proveedor compatible.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- `EMAIL_FROM`, `EMAIL_TO`

## Ejecución

```bash
python gobia_auditor/main.py
```

También puedes usar la interfaz gráfica Streamlit:

```bash
streamlit run gobia_auditor/app.py
```

Al ejecutarlo se muestra una interfaz que permite:
- Analizar contratos recientes.
- Aplicar filtros avanzados por departamento, ciudad, tipo de contrato, valor y rango de días.
- Ejecutar un análisis con datos de ejemplo locales.

El sistema:

1. Descarga contratos recientes de SECOP II.
2. Normaliza los datos y llama al LLM si hay clave.
3. Calcula score de riesgo y señales de alerta.
4. Guarda resultados en SQLite y genera `reporte_riesgos_*.html`.
5. Intenta enviar un correo con el resumen.

## Notas

- Si no hay clave de LLM, el análisis se realiza con reglas locales.
- Si la API de SECOP II no está disponible o tu red no puede acceder a `datos.gov.co`, activa `SECOP_USE_SAMPLE_DATA=true` para usar datos de ejemplo locales.
- El endpoint por defecto es `https://www.datos.gov.co/resource/rtxx-3nky.json`.
- El reporte HTML se guarda en `datos/`.
- Ajusta `SECOP_DAYS_WINDOW` y `RISK_THRESHOLD` desde `.env` si lo deseas.
