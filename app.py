import streamlit as st
import pandas as pd
import pandasql as ps
from io import StringIO
from PIL import Image


# ---------- CSS para fondo blanco ----------
st.markdown(
    """
    <style>
    .stApp {
        background-color: white;
        color: black;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Colores institucionales
color1 = "#2B4460"
color2 = "#49C1C3"

st.set_page_config(page_title="Dataudit", layout="wide")

# --- BLOQUE PARA CAMBIAR ESTILO ---
st.markdown("""
    <style>
    .stAlert-success {
        background-color: #e0f7fa !important;
        color: #004d40 !important;
    }
    .stDataFrame {
        background-color: #f9f9f9 !important;
        color: #000000 !important;
    }
    </style>
""", unsafe_allow_html=True)

# Cargar logo
logo = Image.open("logo.png")
st.image(logo, width=120)

# Título con estilos personalizados
st.markdown(f"<h1 style='color:{color1};'>Data<span style='color:{color2};'>udit</span> - Plataforma de Auditoría BI</h1>", unsafe_allow_html=True)

# Subir archivo
st.sidebar.header("1. Subir archivo")
file = st.sidebar.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx"])
df = None

if file:
    try:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        st.success("Archivo cargado correctamente ✅")
        st.subheader("Vista previa de los datos")
        st.dataframe(df)
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")

# Auditoría de duplicados
if df is not None:
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicates = df[df.duplicated()]
        st.subheader("Registros duplicados")
        st.dataframe(duplicates)

    # Consulta SQL manual
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("Escribe una consulta SQL sobre la tabla 🧮")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            result = ps.sqldf(query, locals())
            st.dataframe(result)
        except Exception as e:
            st.error(f"Error en la consulta SQL: {e}")

    # Simular lenguaje natural
    st.sidebar.header("4. Consulta en lenguaje natural (dummy)")
    if st.sidebar.button("Simular: 'Muéstrame los clientes con más de 10000 ventas'"):
        st.subheader("Resultado de la consulta simulada (dummy)")
        st.dataframe(df[df["ventas"] > 10000])

    # Simular envío de alerta
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo con los datos.")




