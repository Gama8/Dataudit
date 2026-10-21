"""Dataudit: BI y auditoría de datos para pymes.

    streamlit run app.py
"""
import streamlit as st

from ui import estado

st.set_page_config(page_title="Dataudit", page_icon=":material/fact_check:", layout="wide")
st.logo(str(estado.RAIZ / "logo.png"), size="large")
estado.inicializar()

pagina = st.navigation({
    "": [
        st.Page("vistas/inicio.py", title="Inicio", icon=":material/home:", default=True),
        st.Page("vistas/asistente.py", title="Asistente", icon=":material/auto_awesome:"),
    ],
    "Datos": [st.Page("vistas/datos.py", title="Cargar y mapear", icon=":material/upload_file:")],
    "Auditoría": [
        st.Page("vistas/pruebas.py", title="Pruebas de auditoría", icon=":material/fact_check:"),
        st.Page("vistas/muestreo.py", title="Muestreo", icon=":material/filter_alt:"),
        st.Page("vistas/hallazgos.py", title="Hallazgos", icon=":material/bookmark:"),
    ],
    "BI": [
        st.Page("vistas/tableros.py", title="Tableros", icon=":material/dashboard:"),
        st.Page("vistas/explorar.py", title="Explorar con SQL", icon=":material/query_stats:"),
    ],
})
estado.barra_lateral()
pagina.run()
