import streamlit as st
import pandas as pd
import pandasql as ps
from PIL import Image

# ---------- ESTILOS Y CONFIGURACIÓN ----------
st.set_page_config(page_title="Dataudit", layout="wide")

# Colores institucionales
color_primario = "#2B4460"
color_secundario = "#49C1C3"
color_fondo_exito = "#D1F0F1"  # Fondo para mensajes de éxito
color_texto = "#000000"

# Logo
logo = Image.open("logo.png")
st.image(logo, width=120)

# Título con colores institucionales
st.markdown(
    f"<h1 style='color:{color_primario};'>Data<span style='color:{color_secundario};'>udit</span> - Plataforma de Auditoría BI</h1>",
    unsafe_allow_html=True
)

# ---------- 1. SUBIR ARCHIVO ----------
st.sidebar.header("1. Subir archivo")
file = st.sidebar.file_uploader("Sube un archivo CSV o Excel", type=["csv", "xlsx"])
df = None

if file:
    try:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        st.markdown(
            f"<div style='background-color:{color_fondo_exito}; padding:10px; border-radius:5px;'>"
            f"<strong style='color:{color_primario};'>✅ Archivo cargado correctamente</strong>"
            f"</div>",
            unsafe_allow_html=True
        )

        st.subheader("Vista previa de los datos")
        st.dataframe(df.head())
    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")

# ---------- 2. AUDITORÍA DE DUPLICADOS ----------
if df is not None:
    st.sidebar.header("2. Auditoría por defecto")
    if st.sidebar.button("Ejecutar auditoría de duplicados"):
        duplicados = df[df.duplicated()]
        st.subheader("Registros duplicados encontrados")
        st.dataframe(duplicados)

    # ---------- 3. CONSULTA SQL MANUAL ----------
    st.sidebar.header("3. Consulta SQL manual")
    st.subheader("Escribe una consulta SQL sobre los datos")
    query = st.text_area("Consulta SQL", "SELECT * FROM df LIMIT 10")
    if query:
        try:
            resultado = ps.sqldf(query, locals())
            st.dataframe(resultado)
        except Exception as e:
            st.error(f"Error en la consulta SQL: {e}")

    # ---------- 4. CONSULTA EN LENGUAJE NATURAL (DUMMY) ----------
    st.sidebar.header("4. Consulta en lenguaje natural")
    consulta_natural = st.sidebar.text_input("Ejemplo: ¿Qué cliente vendió más?")
    if consulta_natural:
        st.subheader("🧠 Conversión estimada (dummy):")
        st.markdown(f"**Consulta original:** _{consulta_natural}_")
        st.code("SELECT cliente, SUM(ventas) as total_ventas FROM df GROUP BY cliente ORDER BY total_ventas DESC LIMIT 1")

        # Resultado simulado si existen las columnas
        if "cliente" in df.columns and "ventas" in df.columns:
            try:
                dummy_result = df.groupby("cliente")["ventas"].sum().reset_index().sort_values(by="ventas", ascending=False).head(1)
                st.dataframe(dummy_result)
            except:
                st.warning("No se pudo calcular el ejemplo por estructura inesperada del archivo.")
        else:
            st.info("Este ejemplo solo funciona si el archivo contiene columnas llamadas 'cliente' y 'ventas'.")

    # ---------- 5. ALERTA POR CORREO (DUMMY) ----------
    st.sidebar.header("5. Enviar alerta por correo")
    if st.sidebar.button("Simular envío de alerta"):
        st.success("📧 Alerta simulada enviada a auditor@datacorp.com")
