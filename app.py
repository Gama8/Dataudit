import streamlit as st
import pandas as pd
import pandasql as ps
from PIL import Image
import openai
import os

# Configurar la clave de OpenAI desde secretos o entorno local
openai.api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))

# Colores institucionales
color1 = "#2B4460"
color2 = "#49C1C3"

st.set_page_config(page_title="Dataudit", layout="wide")

# Cargar logo
logo = Image.open("logo.png")
st.image(logo, width=120)

# Título con estilo
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
        st.dataframe(df.head())
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")

# --- Función para convertir lenguaje natural a SQL usando OpenAI ---
def convertir_lenguaje_a_sql(pregunta, df_sample):
    try:
        columnas = ", ".join([f"{col} ({dtype})" for col, dtype in df_sample.dtypes.items()])
        context = f"""La tabla se llama 'df' y tiene las siguientes columnas con sus tipos de datos:
{columnas}

Escribe una consulta SQL válida en dialecto SQLite que responda a la siguiente pregunta en español:"""

        prompt = f"{context}\n\nPregunta: {pregunta}\n\nSQL:"

        respuesta = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un experto en SQL y vas a generar una consulta a partir de una pregunta."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=250
        )

        sql_generado = respuesta["choices"][0]["message"]["content"].strip()
        return sql_generado

    except Exception as e:
        return f"-- Error al generar SQL: {e}"

# --- Funcionalidades solo si hay archivo cargado ---
if df is not None:

    # Auditoría de duplicados
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicates = df[df.duplicated()]
        st.subheader("Registros duplicados encontrados:")
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

    # Consulta en lenguaje natural (GPT)
    st.sidebar.header("4. Consulta en lenguaje natural")
    pregunta = st.sidebar.text_input("Pregunta en lenguaje natural", placeholder="¿Qué cliente vendió más?")
    if pregunta:
        st.info("🧠 Generando SQL con GPT...")
        sql_convertido = convertir_lenguaje_a_sql(pregunta, df)
        st.subheader("Consulta generada automáticamente")
        st.code(sql_convertido)

        if "error" not in sql_convertido.lower():
            try:
                resultado = ps.sqldf(sql_convertido, locals())
                st.dataframe(resultado)
            except Exception as e:
                st.error(f"Error al ejecutar la consulta generada: {e}")
        else:
            st.error(sql_convertido)

    # Envío de alerta simulado
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo con los datos.")
else:
    st.warning("Por favor, sube un archivo para comenzar.")
