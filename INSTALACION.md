# GobIA Auditor - Instalación y Ejecución Completa

Sistema automatizado de detección de opacidad en contratos públicos del SECOP II.

## Descripción

GobIA Auditor es una herramienta que consume datos de contratos públicos desde la API del SECOP II (Sistema Electrónico para la Contratación Pública), los analiza en busca de señales de riesgo y genera reportes con alertas.

Características:
- Consulta automática de contratos recientes o filtrados.
- Análisis de riesgo con reglas locales o IA (OpenAI).
- Interfaz gráfica con Streamlit.
- Menú por consola para uso avanzado.
- Modo offline con datos simulados.

## Estructura del Proyecto

```
gobia_auditor/
├── app.py                 # Interfaz gráfica con Streamlit
├── main.py                # Menú por consola
├── secop_client.py        # Cliente para API del SECOP II
├── llm_analyzer.py        # Análisis con IA (OpenAI)
├── risk_scorer.py         # Reglas locales de riesgo
├── reporter.py            # Generación de reportes HTML y email
├── __init__.py
└── __pycache__/
datos/                     # Carpeta para reportes y base de datos
├── contracts.db           # SQLite con resultados
└── reporte_*.html         # Reportes generados
.env                       # Variables de entorno (copiar de .env.example)
.env.example               # Ejemplo de configuración
.gitignore                 # Archivos ignorados por Git
README.md                  # Este documento
requirements.txt           # Dependencias Python
```

## Requisitos Previos

- **Sistema Operativo**: Windows, macOS o Linux.
- **Python 3.10 o superior** (verifica con `python --version`).
- **Acceso a internet** para consultar la API del SECOP II (opcional: modo offline).
- **Cuenta OpenAI** (opcional, para análisis con IA).

## Instalación Paso a Paso

### 1. Obtener el Proyecto

Copia la carpeta completa del proyecto a tu equipo. Si usas Git:

```bash
git clone <url_del_repositorio>
cd gobia_auditor
```

### 2. Crear Entorno Virtual

```bash
# Crear entorno
python -m venv venv

# Activar entorno (Windows)
venv\Scripts\activate

# Activar entorno (macOS/Linux)
# source venv/bin/activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

Dependencias principales:
- `streamlit`: Interfaz gráfica.
- `pandas`: Manejo de datos.
- `requests`: Consultas HTTP.
- `python-dotenv`: Variables de entorno.
- `openai`: Análisis con IA (opcional).
- `transformers` y `torch`: Modelos locales de IA (opcional).

Si falta alguna, instala manualmente:
```bash
pip install streamlit pandas requests python-dotenv openai transformers torch
```

### 4. Configurar Variables de Entorno

Copia el archivo de ejemplo:
```bash
copy .env.example .env  # Windows
# cp .env.example .env  # macOS/Linux
```

Edita `.env` con un editor de texto:

```env
# API del SECOP
SECOP_API_URL=https://www.datos.gov.co/resource/rtxx-3nky.json
SECOP_APP_TOKEN=  # Opcional: Token para más consultas
SECOP_DAYS_WINDOW=30
SECOP_MAX_RECORDS=200
SECOP_USE_SAMPLE_DATA=false  # true para modo offline

# Análisis con IA
LLM_API_KEY=tu_clave_openai_aqui  # Opcional
LLM_MODEL=gpt-3.5-turbo

# Reportes por email (opcional)
SMTP_HOST=smtp.tu_proveedor.com
SMTP_PORT=587
SMTP_USER=tu_email@ejemplo.com
SMTP_PASSWORD=tu_contraseña
EMAIL_FROM=tu_email@ejemplo.com
EMAIL_TO=destinatario@ejemplo.com

# Umbral de riesgo
RISK_THRESHOLD=70
```


API KEYS:
Open AI:
`export OPENAI_API_KEY="tu_clave_openai"`

Deepseek:
`export DEEPSEEK_API_KEY="tu_clave_deepseek"`

Groq:
`export GROQ_API_KEY="tu_clave_groq"`



- **SECOP_APP_TOKEN**: Obtén uno en https://dev.socrata.com/ para evitar límites.
- **LLM_API_KEY**: De OpenAI (https://platform.openai.com/). Si no, usa análisis local.
- **SECOP_USE_SAMPLE_DATA**: `true` para datos simulados sin internet.

## Ejecución

### Opción 1: Interfaz Gráfica (Streamlit)

Ideal para usuarios finales. Abre en navegador.

```bash
streamlit run gobia_auditor/app.py
```

- Selecciona filtros desde menús desplegables (departamento, ciudad, tipo de contrato).
- Ajusta valor mínimo/máximo y días.
- Haz clic en "🚀 Analizar contratos".
- Ve métricas, tabla y descarga CSV.

### Opción 2: Menú por Consola

Para uso avanzado o scripting.

```bash
python gobia_auditor/main.py
```

Opciones del menú:
1. Analizar contratos recientes.
2. Analizar con filtros avanzados (ingresa manualmente).
3. Analizar con datos de ejemplo.
4. Salir.

### Modo Offline

- En `.env`: `SECOP_USE_SAMPLE_DATA=true`
- O en Streamlit: Opción "Analizar usando datos de ejemplo locales".
- Usa contratos simulados (TEST-0001, etc.).

## Funcionamiento Interno

1. **Consulta**: Obtiene contratos de la API o datos locales.
2. **Normalización**: Mapea campos del SECOP a esquema interno.
3. **Análisis**:
   - Si hay `LLM_API_KEY`: Usa OpenAI para score y alertas.
   - Si no: Usa reglas locales (objeto vago, contratista nuevo, etc.).
4. **Reporte**: Genera HTML con tabla, métricas y ranking de alertas.
5. **Persistencia**: Guarda en SQLite (`datos/contracts.db`).
6. **Notificación**: Envía email si está configurado.

## Solución de Problemas

### Error: ModuleNotFoundError
- Activa el entorno: `venv\Scripts\activate`
- Reinstala: `pip install -r requirements.txt`

### Error: 400 Bad Request en API
- Verifica filtros: Algunos campos no existen en el dataset.
- Usa modo offline: `SECOP_USE_SAMPLE_DATA=true`

### Error: Datetime comparison
- Ya corregido en el código (fechas aware/naive).

### Streamlit no abre
- `pip install streamlit`
- Ejecuta desde la raíz: `streamlit run gobia_auditor/app.py`

### Scores siempre 0 o 50
- Sin `LLM_API_KEY`: Usa reglas locales, que pueden dar scores bajos.
- Verifica contratos: Algunos son "limpios".

### No envía email
- Configura SMTP en `.env`.
- Prueba con un proveedor como Gmail (habilita "apps menos seguras").

## Desarrollo y Contribución

- Edita archivos en `gobia_auditor/`.
- Para cambios, crea rama Git.
- Prueba con datos simulados.

## Licencia

Proyecto open-source para auditoría pública.

---

Para soporte, abre un issue en el repositorio o contacta al desarrollador.