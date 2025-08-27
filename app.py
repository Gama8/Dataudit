import streamlit as st
import pandas as pd
import pandasql as ps
import openai
from io import StringIO
from PIL import Image
import os

# ------------------------ CONFIG ------------------------

# Leer API key de OpenAI desde variable de entorno
openai.api_key = os.getenv("OPENAI_API_KEY")

# Colores institucionales
color1 = "#2B4460"
color2 = "#49C1C3"

st.set_page_config(page_title="Dataudit", layout="wide")

# Cargar logo
logo = Image.open("logo.png")
st.image(logo, width=120)

# Título con estilos personalizados
st.markdown(f"<h1 style='color:{color1};'>Data<span style='color:{color2};'>udit</span> - Plataforma de Auditoría BI</h1>", unsafe_allow_html=True)

# ------------------------ CARGA DE ARCHIVO ------------------------

st.sidebar.header("1. Subir archivo")
file = st.sidebar.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx"])
df = None

if file:
    try:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        st.success("✅ Archivo cargado correctamente")
        st.subheader("Vista previa de los datos")
        st.dataframe(df.head())
    except Exception as e:
        st.error(f"❌ Error al leer el archivo: {e}")

# ------------------------ FUNCIONES ------------------------

def natural_to_sql(user_input, columns, table="df"):
    prompt = f"""
Eres un asistente que convierte lenguaje natural a SQL para analizar datos en un DataFrame de pandas llamado '{table}'.
Las columnas disponibles son: {', '.join(columns)}.

Convierte esta petición en SQL:
\"{user_input}\"

Devuelve solo la consulta SQL sin explicaciones.
"""
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150,
            temperature=0
        )
        return response.choices[0].text.strip()
    except Exception as e:
        return f"-- Error al generar SQL: {e}"

# ------------------------ FUNCIONALIDAD ------------------------

if file and df is not None:
    # Auditoría de duplicados
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicates = df[df.duplicated()]
        st.subheader("🔍 Registros duplicados")
        st.dataframe(duplicates)

    # Consulta SQL manual
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("🧮 Escribe una consulta SQL sobre el DataFrame")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            result = ps.sqldf(query, locals())
            st.dataframe(result)
        except Exception as e:
            st.error(f"❌ Error en la consulta SQL: {e}")

    # Consulta en lenguaje natural con IA
    st.sidebar.header("4. Consulta en lenguaje natural (IA)")
    consulta_natural = st.sidebar.text_input("Ejemplo: ¿Qué producto se vendió más?")
    if st.sidebar.button("Generar SQL con IA"):
        if consulta_natural:
            columnas = df.columns.tolist()
            sql = natural_to_sql(consulta_natural, columnas)
            st.subheader("🔁 Consulta generada por IA")
            st.code(sql)
            try:
                resultado = ps.sqldf(sql, locals())
                st.dataframe(resultado)
            except Exception as e:
                st.error(f"❌ Error al ejecutar SQL generado: {e}")
        else:
            st.warning("⚠️ Escribe una pregunta en lenguaje natural")

    # Simular envío de alerta
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo con los datos.")
