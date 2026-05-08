import os
import sys
from datetime import datetime
from typing import Optional, List, Dict

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from gobia_auditor.llm_analyzer import LLMAnalyzer, get_llm_client, analizar_con_llm, calcular_score_local
from gobia_auditor.risk_scorer import RiskScorer
from gobia_auditor.secop_client import SecopClient

load_dotenv()

DEFAULT_LLM_API_KEYS = {
    "OpenAI": os.getenv("OPENAI_API_KEY", ""),
    "Deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
    "Groq": os.getenv("GROQ_API_KEY", ""),
    "Google Gemini": os.getenv("GOOGLE_GEMINI_API_KEY", ""),
    "Google AI Studio": os.getenv("GOOGLE_AI_STUDIO_API_KEY", ""),
}

DEFAULT_LLM_MODELS = {
    "OpenAI": "gpt-3.5-turbo",
    "Deepseek": "deepseek-chat",
    "Groq": "mixtral-8x7b-32768",
    "Google Gemini": "gemini-2.0-flash",
    "Google AI Studio": "gemini-2.0-flash",
}

SECOP_API_URL = os.getenv("SECOP_API_URL", "https://www.datos.gov.co/resource/rtxx-3nky.json")
client = SecopClient(api_base=SECOP_API_URL)

LOCAL_CONTRATOS_PATH = os.path.join(project_root, "datos", "contratos_muestra.json")

@st.cache_data(show_spinner=False)
def cargar_departamentos():
    try:
        valores = client.listar_departamentos()
        return ["Todos"] + valores if valores else ["Todos"]
    except Exception as e:
        st.warning(f"No se pudieron cargar departamentos: {e}. Usa 'Todos' o ingresa manualmente.")
        return ["Todos"]

@st.cache_data(show_spinner=False)
def cargar_ciudades():
    try:
        valores = client.listar_ciudades()
        return ["Todos"] + valores if valores else ["Todos"]
    except Exception as e:
        st.warning(f"No se pudieron cargar ciudades: {e}. Usa 'Todos' o ingresa manualmente.")
        return ["Todos"]

@st.cache_data(show_spinner=False)
def cargar_tipos_contrato():
    try:
        valores = client.listar_tipos_contrato()
        return ["Todos"] + valores if valores else ["Todos"]
    except Exception as e:
        st.warning(f"No se pudieron cargar tipos de contrato: {e}. Usa 'Todos' o ingresa manualmente.")
        return ["Todos"]


@st.cache_data(show_spinner=False)
def cargar_contratos_locales_raw() -> list[dict]:
    try:
        import json

        if not os.path.exists(LOCAL_CONTRATOS_PATH):
            return []
        with open(LOCAL_CONTRATOS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        st.warning(f"No se pudieron cargar contratos locales: {exc}")
        return []


def _filtrar_contratos_locales(
    contratos: list[dict],
    departamento: str | None,
    ciudad: str | None,
    tipo_contrato: str | None,
    valor_min: float | None,
    valor_max: float | None,
    dias: int | None,
) -> list[dict]:
    from datetime import datetime, timedelta

    now = datetime.now()
    limite_fecha = None
    if dias is not None:
        limite_fecha = (now - timedelta(days=dias)).date()

    def parse_date(d: object) -> object:
        if not d or not isinstance(d, str):
            return None
        try:
            return datetime.fromisoformat(d).date()
        except Exception:
            return None

    out: list[dict] = []
    for c in contratos:
        dep = (c.get("departamento") or "").strip()
        ciu = (c.get("ciudad") or "").strip()
        tip = (c.get("tipo_contrato") or "").strip()

        if departamento and departamento != "Todos" and dep != departamento:
            continue
        if ciudad and ciudad != "Todos" and ciu != ciudad:
            continue
        if tipo_contrato and tipo_contrato != "Todos" and tip != tipo_contrato:
            continue

        val = c.get("valor_total")
        try:
            val_num = float(val) if val is not None else None
        except Exception:
            val_num = None

        if valor_min is not None and val_num is not None and val_num < valor_min:
            continue
        if valor_max is not None and val_num is not None and val_num > valor_max:
            continue

        if limite_fecha is not None:
            fi = parse_date(c.get("fecha_inicio"))
            ff = parse_date(c.get("fecha_fin"))
            if fi is not None and fi < limite_fecha and (ff is not None and ff < limite_fecha):
                continue

        out.append(c)

    return out


def guardar_llm_key_en_env(provider: str, api_key: str, model: str | None = None) -> bool:
    env_path = os.path.join(project_root, ".env")
    try:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []

        key_name = "LLM_API_KEY"
        model_name = "LLM_MODEL"
        provider_name = "LLM_PROVIDER"

        updated = {
            key_name: False,
            model_name: False,
            provider_name: False,
        }

        for idx, line in enumerate(lines):
            if line.startswith(f"{key_name}="):
                lines[idx] = f"{key_name}={api_key}\n"
                updated[key_name] = True
            elif line.startswith(f"{model_name}=") and model:
                lines[idx] = f"{model_name}={model}\n"
                updated[model_name] = True
            elif line.startswith(f"{provider_name}="):
                lines[idx] = f"{provider_name}={provider}\n"
                updated[provider_name] = True

        if not updated[key_name]:
            lines.append(f"{key_name}={api_key}\n")
        if model and not updated[model_name]:
            lines.append(f"{model_name}={model}\n")
        if not updated[provider_name]:
            lines.append(f"{provider_name}={provider}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


@st.cache_data(show_spinner=False)
def buscar_contratos_con_filtros(
    departamento=None,
    ciudad=None,
    tipo_contrato=None,
    valor_min=None,
    valor_max=None,
    limite=20,
    dias=30,
):
    if departamento == "Todos":
        departamento = None
    if ciudad == "Todos":
        ciudad = None
    if tipo_contrato == "Todos":
        tipo_contrato = None

    client = SecopClient(api_base=SECOP_API_URL)
    return client.obtener_contratos(
        limite=limite,
        departamento=departamento,
        ciudad=ciudad,
        tipo_contrato=tipo_contrato,
        valor_min=valor_min,
        valor_max=valor_max,
        dias=dias,
    )


st.set_page_config(
    page_title="GobIA Auditor - SECOP II",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("GobIA Auditor")
st.markdown(
    """
    <style>
    .big-font { font-size:18px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="big-font">Sistema automatizado de detección de opacidad en los contratos del '
    '<a href="https://www.colombiacompra.gov.co/" target="_blank">SECOP II</a>.</p>',
    unsafe_allow_html=True,
)
st.divider()

with st.sidebar:
    st.header("⚙️ Configuración del LLM")
    st.divider()

    st.header("📦 Origen de datos")
    fuente_datos = st.radio(
        "Selecciona de dónde cargar contratos",
        options=["Remote (API)", "Local (JSON)"],
        index=0,
        help="Remote usa la API de SECOP II. Local carga datos simulados y filtra en memoria.",
        horizontal=False,
    )
    modo_activo = "REMOTE" if fuente_datos.startswith("Remote") else "LOCAL"
    st.caption(f"Modo activo: **{modo_activo}**")
    st.session_state["modo_datos"] = modo_activo

    # Solo mostramos warning en local para evitar confusión
    if modo_activo == "LOCAL":
        st.info("Se cargan contratos de `datos/contratos_muestra.json` y se filtran en memoria. (No hay llamadas a SECOP).")

    llm_provider_label = st.selectbox(
        "Selecciona el proveedor de IA",
        options=[
            "OpenAI - ChatGPT",
            "OpenAI - API",
            "Google Gemini",
            "Google AI Studio",
            "Groq",
            "Deepseek",
            "Modelo local (experimental)",
        ],
        index=0,
    )

    if llm_provider_label == "OpenAI - ChatGPT":
        llm_provider = "OpenAI"
        llm_model = st.selectbox(
            "Modelo ChatGPT",
            options=["gpt-4o-mini", "gpt-3.5-turbo"],
            index=0,
        )
    elif llm_provider_label == "OpenAI - API":
        llm_provider = "OpenAI"
        llm_model = st.selectbox(
            "Modelo OpenAI",
            options=["gpt-3.5-turbo", "gpt-4o-mini"],
            index=0,
        )
    elif llm_provider_label == "Google Gemini":
        llm_provider = "Google Gemini"
        llm_model = st.selectbox(
            "Modelo Gemini",
            options=["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
            index=0,
        )
    elif llm_provider_label == "Google AI Studio":
        llm_provider = "Google AI Studio"
        llm_model = st.selectbox(
            "Modelo AI Studio",
            options=["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
            index=0,
        )
        st.caption("Usa modelos Gemini compatibles con la versión actual de la librería google.generativeai.")
    elif llm_provider_label == "Groq":
        llm_provider = "Groq"
        llm_model = st.selectbox(
            "Modelo Groq",
            options=["mixtral-8x7b-32768", "llama3-70b-8192"],
            index=0,
        )
        st.caption("Groq es ideal para demos en vivo debido a su alta velocidad de inferencia.")
    elif llm_provider_label == "Deepseek":
        llm_provider = "Deepseek"
        llm_model = st.selectbox(
            "Modelo Deepseek",
            options=["deepseek-chat", "deepseek-reasoner"],
            index=0,
        )
        st.caption("Deepseek ofrece una alternativa si tu cuota de OpenAI se agota.")
    else:
        llm_provider = "Modelo local (experimental)"
        llm_model = None
        st.caption("El modelo local puede usar reglas heurísticas si no hay cliente local compatible.")

    api_key = None
    if llm_provider in ["Google Gemini", "Google AI Studio", "OpenAI", "Groq", "Deepseek"]:
        default_key = DEFAULT_LLM_API_KEYS.get(llm_provider, "")
        current_key = st.session_state.get('llm_api_key') or default_key
        api_key = st.text_input(
            f"API Key para {llm_provider_label}",
            value=current_key,
            type="password",
            help="Tu clave no se guarda en disco, solo en memoria durante esta sesión. Puedes editarla si la clave por defecto expira.",
        )
        if api_key:
            st.success("✅ Key cargada en memoria")
        else:
            st.warning("⚠️ Ingresa una API key para poder analizar con este proveedor.")
        if api_key:
            st.success("✅ Key cargada en memoria")
        else:
            st.warning("⚠️ Ingresa una API key para poder analizar con este proveedor.")

        if api_key and st.button("Guardar API Key en .env (solo desarrollo)", width='stretch'):
            if guardar_llm_key_en_env(llm_provider_label, api_key, llm_model):
                st.success("🔒 Key guardada en .env local. No es seguro en producción.")
            else:
                st.error("No se pudo guardar la API Key en .env. Revisa permisos de escritura.")

    st.session_state['llm_provider'] = llm_provider
    st.session_state['llm_model'] = llm_model
    st.session_state['llm_api_key'] = api_key

    st.markdown("---")
    st.header("🔎 Filtros de búsqueda")

with st.spinner("Cargando filtros de búsqueda... Si tarda más de unos segundos, puede que la conexión al SECOP esté lenta o bloqueada."):
    if modo_activo == "LOCAL":
        contratos_locales = cargar_contratos_locales_raw()
        departamentos = ["Todos"] + sorted(
            {c.get("departamento") for c in contratos_locales if c.get("departamento")},
            key=str.casefold,
        )
        ciudades = ["Todos"] + sorted(
            {c.get("ciudad") for c in contratos_locales if c.get("ciudad")},
            key=str.casefold,
        )
        tipos_contrato = ["Todos"] + sorted(
            {c.get("tipo_contrato") for c in contratos_locales if c.get("tipo_contrato")},
            key=str.casefold,
        )
    else:
        departamentos = cargar_departamentos()
        ciudades = cargar_ciudades()
        tipos_contrato = cargar_tipos_contrato()

departamento = st.selectbox(
    "**Departamento / Localización**",
    options=departamentos,
    index=0,
    help="Selecciona una localización real desde datos del SECOP II.",
)
ciudad = st.selectbox(
    "**Ciudad**",
    options=ciudades,
    index=0,
    help="Selecciona una ciudad disponible en el dataset.",
)
tipo_contrato = st.selectbox(
    "**Tipo de contrato**",
    options=tipos_contrato,
    index=0,
    help="Selecciona el tipo de contrato disponible en los datos.",
)
valor_min = st.number_input(
    "**Valor mínimo (COP)**", min_value=0.0, value=0.0, step=100000.0
)
valor_max = st.number_input(
    "**Valor máximo (COP)**", min_value=0.0, value=1000000000.0, step=1000000.0
)
dias = st.slider("**Últimos días**", min_value=1, max_value=365, value=30)

limite = st.slider(
    "**Cantidad de contratos a analizar**", min_value=5, max_value=100, value=20
)

analysis_enabled = llm_provider == "Modelo local (experimental)" or bool(api_key)
if not analysis_enabled:
    st.error("Debes ingresar una API key válida para el proveedor seleccionado.")

analizar_btn = st.button(
    "Analizar contratos",
    type="primary",
    width='stretch',
    disabled=not analysis_enabled,
)

if analizar_btn:
    llm_provider = st.session_state.get('llm_provider', 'OpenAI')
    llm_model = st.session_state.get('llm_model', 'gpt-3.5-turbo')
    llm_api_key = st.session_state.get('llm_api_key')
    llm_client = None

    if llm_provider in ["OpenAI", "Google Gemini", "Google AI Studio", "Groq", "Deepseek"]:
        effective_key = llm_api_key or DEFAULT_LLM_API_KEYS.get(llm_provider, "")
        if not effective_key:
            st.error(f"No hay API key disponible para {llm_provider}. Usa una manual o un proveedor con clave activa.")
            st.stop()
        try:
            llm_client = get_llm_client(llm_provider, effective_key, llm_model)
        except Exception as exc:
            st.error(f"No se pudo configurar el cliente LLM: {exc}")
            st.stop()

    with st.spinner('Cargando contratos...'):
        if st.session_state.get("modo_datos", "REMOTE") == "LOCAL":
            contratos_raw = cargar_contratos_locales_raw()
            contratos = _filtrar_contratos_locales(
                contratos_raw,
                departamento=departamento,
                ciudad=ciudad,
                tipo_contrato=tipo_contrato,
                valor_min=valor_min if valor_min > 0 else None,
                valor_max=valor_max if valor_max > 0 else None,
                dias=dias,
            )[:limite]

            if not contratos:
                st.warning("No se encontraron contratos locales con los filtros seleccionados.")
                st.stop()
        else:
            contratos = buscar_contratos_con_filtros(
                departamento=departamento or None,
                ciudad=ciudad or None,
                tipo_contrato=tipo_contrato or None,
                valor_min=valor_min if valor_min > 0 else None,
                valor_max=valor_max if valor_max > 0 else None,
                limite=limite,
                dias=dias,
            )

            if not contratos:
                st.warning("No se encontraron contratos con los filtros seleccionados.")
                st.stop()

        st.success(f"✅ Se encontraron {len(contratos)} contratos para analizar.")

        resultados = []
        progress_bar = st.progress(0, text="Analizando contratos...")
        status_text = st.empty()

        for i, contrato in enumerate(contratos):
            status_text.text(f"Analizando contrato {i+1} de {len(contratos)}...")
            contrato_normalizado = client.normalize_contract(contrato)
            objeto = contrato_normalizado.get("objeto", "")
            valor = contrato_normalizado.get("valor_total", 0.0)

            proveedores_para_intentar = [
                llm_provider,
                *[p for p in ["Google Gemini", "Deepseek", "Groq", "OpenAI"] if p != llm_provider],
            ]

            analisis = None
            for nombre_proveedor in proveedores_para_intentar:
                if nombre_proveedor == "Modelo local (experimental)":
                    continue

                key_manual = llm_api_key if nombre_proveedor == llm_provider else None
                effective_key = key_manual or DEFAULT_LLM_API_KEYS.get(nombre_proveedor, "")
                if not effective_key:
                    continue

                provider_model = llm_model if nombre_proveedor == llm_provider else DEFAULT_LLM_MODELS.get(nombre_proveedor)
                try:
                    st.write(f"Intentando proveedor: {nombre_proveedor}")
                    cliente_llm = get_llm_client(nombre_proveedor, effective_key, provider_model)
                    analisis = analizar_con_llm(
                        objeto,
                        valor,
                        contrato_normalizado,
                        cliente_llm,
                        nombre_proveedor,
                        provider_model,
                    )
                    st.write(f"✅ Análisis exitoso con {nombre_proveedor}.")
                    break
                except Exception as exc:
                    st.write(f"❌ Falló {nombre_proveedor}: {exc}")
                    analisis = None
                    continue

            if analisis is None:
                st.warning(
                    f"⚠️ Todos los proveedores fallaron para el contrato "
                    f"{contrato_normalizado.get('contrato_id', 'N/A')}. Usando análisis local."
                )
                analisis = calcular_score_local(objeto, valor, contrato_normalizado)

            resultados.append({
                "contrato_id": contrato_normalizado.get("contrato_id", "N/A"),
                "entidad": contrato_normalizado.get("entidad_nombre", "N/A"),
                "entidad_nombre": contrato_normalizado.get("entidad_nombre", "N/A"),
                "contratista_nombre": contrato_normalizado.get("contratista_nombre", "N/A"),
                "objeto": objeto[:150] + ("..." if len(objeto) > 150 else ""),
                "valor_total": valor,
                "valor_formateado": f"${valor:,.0f}",
                "departamento": contrato_normalizado.get("departamento", "N/A"),
                "ciudad": contrato_normalizado.get("ciudad", "N/A"),
                "tipo_contrato": contrato_normalizado.get("tipo_contrato", "N/A"),
                "score": int(analisis.get("score", 0) or 0),
                "alertas": ", ".join(analisis.get("alertas", [])) or "Ninguna",
                "justificacion": analisis.get("justificacion") or analisis.get("justificación") or "",
                "fuente": analisis.get("fuente", "local"),
                "url_secop": contrato_normalizado.get("url_secop"),
                "url_contrato": contrato_normalizado.get("url_contrato"),
                "origen": analisis.get("origen", analisis.get("fuente", "local")),
                "exito_llm": bool(analisis.get("exito_llm", analisis.get("fuente", "local") == "api")),
            })

            progress_bar.progress((i + 1) / len(contratos))

        progress_bar.empty()
        status_text.empty()

    df_resultados = pd.DataFrame(resultados)
    st.session_state.df_resultados = df_resultados

if 'df_resultados' in st.session_state:
    df_resultados = st.session_state.df_resultados

    # --- ESTADO DEL MOTOR DE IA (LLM vs Local) ---
    with st.sidebar:
        st.markdown("---")
        st.subheader("🤖 Estado del Motor de IA")

        if "Origen" in df_resultados.columns:
            llm_count = int((df_resultados["Origen"].astype(str).str.contains("LLM", na=False)).sum())
            local_count = int((df_resultados["Origen"].astype(str).str.contains("Local", na=False)).sum())
        else:
            llm_count = 0
            local_count = len(df_resultados)

        total = max(1, len(df_resultados))
        tasa_llm = llm_count / total

        if llm_count > 0 and llm_count == len(df_resultados):
            st.success(f"✅ LLM funcionó en {llm_count}/{len(df_resultados)} contratos")
        elif llm_count > 0:
            st.warning(f"⚠️ LLM funcionó en {llm_count}/{len(df_resultados)} contratos")
        else:
            st.error(f"❌ LLM no disponible. {len(df_resultados)} contratos con motor local.")

        st.progress(tasa_llm, text=f"Tasa de análisis por LLM: {int(tasa_llm*100)}%")
        st.caption(f"🤖 LLM: {llm_count} | 📋 Local: {local_count}")

    # --- PANEL DE RIESGOS MEJORADO ---
    st.subheader("📊 Análisis de Riesgos de Opacidad")
    st.markdown("---")

    def categorizar_riesgo(score: float) -> str:
        if score >= 70:
            return "Alto"
        elif score >= 40:
            return "Medio"
        return "Bajo"

    df_resultados["nivel_riesgo"] = df_resultados["score"].apply(categorizar_riesgo)

    # Crear columnas para métricas clave
    metricas_col1, metricas_col2, metricas_col3, metricas_col4 = st.columns(4)

    with metricas_col1:
        riesgo_promedio = df_resultados["score"].mean() if not df_resultados.empty else 0
        st.metric(
            label="📈 Riesgo Promedio",
            value=f"{riesgo_promedio:.1f} / 100",
            delta="Crítico > 70" if riesgo_promedio > 70 else "Moderado" if riesgo_promedio > 40 else "Aceptable",
            delta_color="inverse" if riesgo_promedio > 40 else "normal",
        )

    with metricas_col2:
        contratos_criticos = int((df_resultados["score"] >= 70).sum())
        total = max(1, len(df_resultados))
        st.metric(
            label="⚠️ Contratos Críticos (Score ≥ 70)",
            value=contratos_criticos,
            delta=f"{(contratos_criticos/total)*100:.0f}% del total",
            delta_color="inverse",
        )

    with metricas_col3:
        contratos_sanos = int((df_resultados["score"] < 40).sum())
        total = max(1, len(df_resultados))
        st.metric(
            label="✅ Contratos con Bajo Riesgo",
            value=contratos_sanos,
            delta=f"{(contratos_sanos/total)*100:.0f}% del total",
            delta_color="normal",
        )

    with metricas_col4:
        # En la app actual 'alertas' viene como string con comas (", "). Aseguramos robustez.
        def contar_alertas(alertas_val: object) -> int:
            if alertas_val is None:
                return 0
            if isinstance(alertas_val, str):
                if alertas_val.strip() == "Ninguna" or not alertas_val.strip():
                    return 0
                return len([a for a in alertas_val.split(", ") if a.strip()])
            return 0

        total_alertas = int(df_resultados["alertas"].apply(contar_alertas).sum())
        st.metric(label="🚨 Total de Alertas Detectadas", value=total_alertas)

    st.markdown("---")

    # Gráficos en dos columnas
    col_graf1, col_graf2 = st.columns(2)

    with col_graf1:
        st.subheader("🎯 Niveles de Riesgo por Contrato")
        riesgo_counts = df_resultados["nivel_riesgo"].value_counts().reindex(["Alto", "Medio", "Bajo"], fill_value=0)
        # Nota: st.bar_chart() no acepta dict para el argumento `color`.
        # Para evitar errores, dejamos que Streamlit use su paleta por defecto.
        st.bar_chart(riesgo_counts)

        if riesgo_counts.get("Alto", 0) > len(df_resultados) * 0.3:
            st.error("🔴 ¡ALERTA! Más del 30% de los contratos analizados tienen riesgo ALTO.")
        elif riesgo_counts.get("Alto", 0) > 0:
            st.warning("🟡 Atención: Existen contratos con riesgo alto que requieren revisión.")
        else:
            st.success("🟢 En esta muestra no se encontraron contratos de alto riesgo.")

    with col_graf2:
        st.subheader("📋 Top Alertas Más Frecuentes")
        todas_alertas: list[str] = []
        for alerta_str in df_resultados["alertas"]:
            if alerta_str != "Ninguna":
                if isinstance(alerta_str, str):
                    for al in alerta_str.split(", "):
                        if al.strip():
                            todas_alertas.append(al[:50])

        if todas_alertas:
            from collections import Counter

            contador_alertas = Counter(todas_alertas)
            top_alertas_df = pd.DataFrame(contador_alertas.most_common(5), columns=["Alerta", "Frecuencia"])
            st.bar_chart(top_alertas_df.set_index("Alerta"))
            alerta_top, frecuencia_top = contador_alertas.most_common(1)[0]
            st.info(f"🔔 La alerta más frecuente es: **{alerta_top}** (aparece en {frecuencia_top} contratos)")
        else:
            st.info("No se detectaron alertas en los contratos analizados.")

    st.markdown("---")
    st.divider()
    st.subheader("Detalle de Contratos Analizados")

    # Columna visual 'Origen' para UX (🤖 LLM vs 📋 Local)
    # - LLM: exito_llm == True
    # - Local: fallback o reglas heurísticas
    def construir_origen(origen_val: object, exito_llm_val: object) -> str:
        if exito_llm_val is True:
            return "🤖 LLM"
        return "📋 Local"

    df_resultados["Origen"] = df_resultados.apply(
        lambda r: construir_origen(r.get("origen"), r.get("exito_llm")),
        axis=1,
    )

    # Filtro adicional por score
    score_min = st.slider("Filtrar contratos con score mínimo:", 0, 100, 0, help="Muestra solo contratos con score >= este valor")
    df_filtrado = df_resultados[df_resultados['score'] >= score_min]

    # Columnas clickeables
    if 'url_contrato' in df_filtrado.columns:
        df_filtrado = df_filtrado.copy()
        df_filtrado['Enlace al Contrato'] = df_filtrado['url_contrato'].apply(
            lambda x: f"{x}" if x and str(x).startswith("http") else "No disponible"
        )

    if 'url_secop' in df_filtrado.columns:
        df_filtrado = df_filtrado.copy()
        df_filtrado['Ver en SECOP II'] = df_filtrado['url_secop'].apply(
            lambda x: f"{x}" if x and str(x).startswith("http") else "No disponible"
        )

    all_columns = df_filtrado.columns.tolist()
    default_columns = ['entidad', 'objeto', 'valor_formateado', 'score', 'alertas', 'Origen', 'Ver en SECOP II', 'Enlace al Contrato']
    selected_columns = st.multiselect(
        "Selecciona las columnas a mostrar en la tabla:",
        options=all_columns,
        default=[col for col in default_columns if col in all_columns],
    )

    if selected_columns:
        column_config = {}
        if 'Enlace al Contrato' in selected_columns:
            column_config['Enlace al Contrato'] = st.column_config.LinkColumn("Enlace al Contrato")

        if 'Ver en SECOP II' in selected_columns:
            column_config['Ver en SECOP II'] = st.column_config.LinkColumn("Ver en SECOP II")

        # Click directo sobre el ID del contrato -> SECOP II (url_secop) incluso en modo local
        if 'contrato_id' in selected_columns and 'url_secop' in df_filtrado.columns:
            df_filtrado = df_filtrado.copy()
            df_filtrado['_contrato_id_secop_link'] = df_filtrado.apply(
                lambda r: r['url_secop'] if r.get('url_secop') and str(r.get('url_secop')).startswith('http') else None,
                axis=1,
            )
            df_filtrado['contrato_id'] = df_filtrado['_contrato_id_secop_link']
            column_config['contrato_id'] = st.column_config.LinkColumn("contrato_id")

            selected_columns = [
                'contrato_id' if c == 'contrato_id' else c
                for c in selected_columns
            ]

        st.dataframe(
            df_filtrado[selected_columns],
            width='stretch',
            column_config=column_config if column_config else None,
        )
        st.info(f"Mostrando {len(df_filtrado)} contratos (filtrados de {len(df_resultados)} totales)")
        # Panel expander "Ver en SECOP II" por selección (usa url_secop)
        if 'url_secop' in df_filtrado.columns:
            if 'url_seleccionada' not in st.session_state:
                st.session_state['url_seleccionada'] = None

            st.divider()
            st.subheader("Ver en SECOP II")

            for idx, row in df_filtrado.iterrows():
                url = row.get('url_secop')
                if not url or str(url) == "nan":
                    continue

                contrato_id = row.get('contrato_id', str(idx))
                unique_key = f"btn_secop_{contrato_id}_{idx}"

                c1, c2 = st.columns([0.8, 0.2])
                with c1:
                    # contrato_id ya puede estar reemplazado por link; mostramos id real si existe
                    st.write(f"**{row.get('contrato_id', contrato_id)}** — {row.get('entidad_nombre', row.get('entidad', 'N/A'))}")
                with c2:
                    if st.button("Ver en SECOP II", key=unique_key):
                        st.session_state['url_seleccionada'] = url
                        st.session_state['id_seleccionada'] = row.get('contrato_id', contrato_id)

                if st.session_state.get('url_seleccionada') == url:
                    with st.expander(f"SECOP II — {st.session_state.get('id_seleccionada', contrato_id)}", expanded=True):
                        st.markdown(
                            f"Enlace a SECOP II (detalle de proceso): [Haz clic aquí]({url})"
                        )
    else:
        st.info("Selecciona al menos una columna para mostrar la tabla.")

    st.subheader("Exportar resultados")
    csv = df_resultados.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Descargar reporte en CSV",
        data=csv,
        file_name=f"gobia_reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
