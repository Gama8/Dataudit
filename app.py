import streamlit as st
import pandas as pd
import pandasql as ps
from io import StringIO
from PIL import Image
import openai
import os

# ---------- CONFIGURACIÓN ----------
# Colores institucionales
color1 = "#2B4460"  # Azul oscuro
color2 = "#49C1C3"  # Verde claro

# Configurar la página
st.set_page_config(page_title="Dataudit", layout="wide")

# Cargar logo
logo = Image.open("logo.png")
st.image(logo, width=120)

# Título estilizado
st.markdown(f"<h1 style='color:{color1};'>Data<span style='color:{color2};'>udit</span> - Plataforma de Auditoría BI</h1>", unsafe_allow_html=True)

# ---------- SUBIDA DE ARCHIVO ----------
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

# ---------- AUDITORÍA POR DEFECTO ----------
if df is not None:
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicates = df[df.duplicated()]
        st.subheader("Registros duplicados encontrados")
        st.dataframe(duplicates)

    # ---------- CONSULTA SQL MANUAL ----------
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("Escribe una consulta SQL sobre la tabla 🧮")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            result = ps.sqldf(query, locals())
            st.dataframe(result)
        except Exception as e:
            st.error(f"Error en la consulta SQL: {e}")

    # ---------- CONVERSIÓN DE LENGUAJE NATURAL A SQL ----------
    st.sidebar.header("4. Consulta en lenguaje natural (OpenAI GPT)")
    natural_prompt = st.sidebar.text_input("Ejemplo: ¿Qué cliente vendió más?")
    if natural_prompt:
        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")  # Asegúrate de setear esto en el entorno

            prompt = f"""
Convierte esta instrucción en una consulta SQL válida para una tabla llamada 'df'. Muestra solo el SQL.
INSTRUCCIÓN: {natural_prompt}
"""

            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un experto en SQL."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.2
            )

            sql_generated = response.choices[0].message.content.strip()
            st.code(sql_generated, language='sql')

            try:
                result = ps.sqldf(sql_generated, locals())
                st.subheader("Resultado")
                st.dataframe(result)
            except Exception as e:
                st.error(f"Error al ejecutar el SQL generado: {e}")

        except Exception as e:
            st.error(f"-- Error al generar SQL: {e}")

    # ---------- ENVÍO DE ALERTA (DUMMY) ----------
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo a: auditor@datacorp.com")
