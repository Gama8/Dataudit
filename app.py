import streamlit as st
import pandas as pd
import pandasql as psql
from PIL import Image

# ---------- ESTILOS ----------
# Cargar logo
logo = Image.open("logo.png")  # Asegúrate de que el archivo se llame exactamente así

# Colores oficiales
COLOR_PRIMARIO = "#2B4460"
COLOR_SECUNDARIO = "#49C1C3"
COLOR_FONDO = "#1E1E1E"
COLOR_TEXTO = "#FFFFFF"

st.set_page_config(
    page_title="Dataudit - Plataforma de Auditoría BI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------- CSS personalizado ----------
st.markdown(
    f"""
    <style>
    body {{
        background-color: {COLOR_FONDO};
        color: {COLOR_TEXTO};
    }}
    .stApp {{
        background-color: {COLOR_FONDO};
        color: {COLOR_TEXTO};
        font-family: 'Arial', sans-serif;
    }}
    .css-1v0mbdj {{
        color: {COLOR_TEXTO};
    }}
    .stButton>button {{
        background-color: {COLOR_PRIMARIO};
        color: white;
        font-weight: bold;
        border-radius: 5px;
        margin-top: 10px;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

# ---------- INTERFAZ ----------
col1, col2 = st.columns([1, 8])
with col1:
    st.image(logo, width=80)
with col2:
    st.markdown(f"<h1 style='color:{COLOR_PRIMARIO}'>Dataudit <span style='color:{COLOR_SECUNDARIO}'>Corporate</span></h1>", unsafe_allow_html=True)

# ---------- 1. SUBIR ARCHIVO ----------
st.sidebar.title("1. Subir archivo")
archivo = st.sidebar.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx"])

if archivo:
    st.success("Archivo cargado correctamente ✅")
    
    if archivo.name.endswith(".csv"):
        df = pd.read_csv(archivo)
    else:
        df = pd.read_excel(archivo)

    st.subheader("Vista previa de los datos")
    st.dataframe(df)

    # ---------- 2. AUDITORÍA POR DEFECTO ----------
    st.sidebar.title("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicados = df[df.duplicated()]
        st.subheader("Registros duplicados encontrados:")
        st.dataframe(duplicados)

    # ---------- 3. CONSULTA SQL ----------
    st.sidebar.title("3. Consulta SQL manual")
    st.markdown("Escribe una consulta SQL sobre la tabla `df` 🧠")
    sql_query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")

    try:
        resultado = psql.sqldf(sql_query, locals())
        st.dataframe(resultado)
    except Exception as e:
        st.error(f"Error en la consulta SQL: {e}")

    # ---------- 4. LENGUAJE NATURAL (dummy) ----------
    st.sidebar.title("4. Consulta en lenguaje natural (dummy)")
    input_natural = st.sidebar.text_input("Ejemplo: ¿Qué cliente vendió más?")
    if input_natural:
        st.info("🧠 Módulo dummy. Aquí se mostrará la conversión a SQL próximamente.")
        st.code("SELECT cliente, SUM(ventas) as total_ventas FROM df GROUP BY cliente ORDER BY total_ventas DESC LIMIT 1")

    # ---------- 5. ENVÍO DE ALERTA (dummy) ----------
    st.sidebar.title("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.success("✅ Alerta enviada exitosamente a: auditor@datacorp.com (simulado)")
else:
    st.warning("Por favor, sube un archivo CSV o Excel para comenzar.")
