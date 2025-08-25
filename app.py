import streamlit as st
import pandas as pd
import pandasql as ps
from PIL import Image

# ----- CONFIGURACIÓN GENERAL -----
st.set_page_config(page_title="Dataudit", layout="wide")

# ----- COLORES CORPORATIVOS -----
color1 = "#2B4460"  # azul oscuro
color2 = "#49C1C3"  # verde agua

# ----- CSS PERSONALIZADO -----
st.markdown(f"""
    <style>
    /* Fondo claro general */
    .stApp {{
        background-color: white;
        color: black;
        font-family: 'Arial', sans-serif;
    }}

    /* Mensajes de éxito (st.success) */
    .stAlert {{
        background-color: #e6f4ff !important;
        color: black !important;
    }}

    /* Encabezados de tabla */
    thead tr th {{
        background-color: #f2f2f2 !important;
        color: black !important;
    }}

    /* Celdas del cuerpo de tabla */
    tbody tr td {{
        background-color: white !important;
        color: black !important;
    }}

    /* Botones */
    .stButton>button {{
        background-color: {color1};
        color: white;
        font-weight: bold;
        border-radius: 5px;
        padding: 0.5em 1em;
    }}
    </style>
""", unsafe_allow_html=True)

# ----- LOGO -----
logo = Image.open("logo.png")
st.image(logo, width=120)

# ----- TÍTULO -----
st.markdown(
    f"<h1 style='color:{color1};'>Data<span style='color:{color2};'>udit</span> - Plataforma de Auditoría BI</h1>",
    unsafe_allow_html=True
)

# ----- CARGA DE ARCHIVO -----
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
        st.dataframe(df.head())
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")

# ----- AUDITORÍA BÁSICA -----
if df is not None:
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicates = df[df.duplicated()]
        st.subheader("Registros duplicados")
        st.dataframe(duplicates)

    # Consulta SQL
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("Escribe una consulta SQL sobre la tabla 🧮")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            result = ps.sqldf(query, locals())
            st.dataframe(result)
        except Exception as e:
            st.error(f"Error en la consulta SQL: {e}")

    # Simular consulta en lenguaje natural
    st.sidebar.header("4. Consulta en lenguaje natural (dummy)")
    if st.sidebar.button("Simular: 'Muéstrame los clientes con más de 10000 ventas'"):
        st.subheader("Resultado de la consulta simulada (dummy)")
        if "ventas" in df.columns:
            st.dataframe(df[df["ventas"] > 10000])
        else:
            st.warning("No existe la columna 'ventas' en los datos cargados.")

    # Simular alerta por correo
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo con los datos.")
else:
    st.info("Carga un archivo para comenzar el análisis.")
