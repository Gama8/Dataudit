import streamlit as st
import pandas as pd
import pandasql as ps
import os
from openai import OpenAI
from PIL import Image

# Configurar la página
st.set_page_config(page_title="Dataudit", layout="wide")

# Colores institucionales
color1 = "#2B4460"
color2 = "#49C1C3"

# Cargar logo
try:
    logo = Image.open("logo.png")
    st.image(logo, width=120)
except:
    st.write("⚠️ No se encontró el logo (logo.png)")

# Título
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

# Configurar cliente OpenAI
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY")))

def convertir_lenguaje_a_sql(pregunta, df_sample):
    try:
        prompt = (
            f"Convierte la siguiente pregunta a una consulta SQL compatible con pandasql:\n"
            f"Pregunta: \"{pregunta}\"\n"
            f"Columnas disponibles: {', '.join(df_sample.columns)}\n"
            f"Usa nombres de columnas exactos. No inventes columnas."
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un generador de SQL para pandasql."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=200
        )

        sql_generado = response.choices[0].message.content.strip()
        return sql_generado
    except Exception as e:
        return f"-- Error al generar SQL: {e}"


# --- Funcionalidades cuando hay archivo cargado ---
if file and df is not None:

    # Auditoría de duplicados
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicados = df[df.duplicated()]
        st.subheader("🔎 Registros duplicados encontrados:")
        st.dataframe(duplicados if not duplicados.empty else pd.DataFrame({"Resultado": ["No se encontraron duplicados."]}))

    # Consulta SQL manual
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("🧮 Escribe una consulta SQL sobre la tabla")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            resultado = ps.sqldf(query, locals())
            st.dataframe(resultado)
        except Exception as e:
            st.error(f"❌ Error en la consulta SQL: {e}")

    # Consulta en lenguaje natural (GPT)
    st.sidebar.header("4. Consulta en lenguaje natural")
    pregunta = st.sidebar.text_input("Ejemplo: ¿Qué cliente vendió más?")
    if pregunta:
        st.subheader("💬 Pregunta en lenguaje natural")
        st.write(pregunta)
        st.subheader("🔄 Consulta SQL generada automáticamente")
        sql_generado = convertir_lenguaje_a_sql(pregunta, df)
        st.code(sql_generado, language="sql")

        if not sql_generado.startswith("-- Error"):
            try:
                resultado = ps.sqldf(sql_generado, locals())
                st.subheader("📊 Resultado de la consulta")
                st.dataframe(resultado)
            except Exception as e:
                st.error(f"❌ Error al ejecutar el SQL generado: {e}")
        else:
            st.error(sql_generado)

    # Simular envío de alerta
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.info("🔔 Se simuló el envío de un correo con los datos.")
else:
    st.warning("📁 Por favor, sube un archivo CSV o Excel para comenzar.")

