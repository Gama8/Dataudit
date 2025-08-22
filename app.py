import streamlit as st
import pandas as pd
import sqlite3

st.set_page_config(page_title="Dataudit Demo", layout="wide")

st.title("📊 Dataudit - Plataforma de Auditoría BI")

st.sidebar.header("1. Subir archivo")
uploaded_file = st.sidebar.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx"])

if uploaded_file:
    # Cargar archivo
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    
    st.success("Archivo cargado correctamente ✅")
    st.subheader("Vista previa de los datos")
    st.dataframe(df.head())

    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicados = df[df.duplicated()]
        if not duplicados.empty:
            st.warning("⚠️ Se encontraron duplicados")
            st.dataframe(duplicados)
        else:
            st.success("✅ No se encontraron duplicados")

    st.sidebar.header("3. Consulta SQL manual")
    st.markdown("Escribe una consulta SQL sobre la tabla `df`")

    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    try:
        conn = sqlite3.connect(":memory:")
        df.to_sql("df", conn, index=False)
        result = pd.read_sql_query(query, conn)
        conn.close()
        st.dataframe(result)
    except Exception as e:
        st.error(f"Error en la consulta SQL: {e}")

    st.sidebar.header("4. Consulta en lenguaje natural (dummy)")
    nat_lang = st.text_input("Describe qué quieres ver (ej: ventas mayores a 10000)")
    if nat_lang:
        st.info("🧠 Esta función convertirá lenguaje natural a SQL (simulada en el demo)")
        st.code("-- Ejemplo generado: SELECT * FROM df WHERE ventas > 10000", language="sql")

    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.success("✉️ Correo simulado enviado a auditor@example.com")
