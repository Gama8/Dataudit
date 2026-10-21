import streamlit as st

from core.pruebas import por_categoria
from ui import estado

st.markdown(
    "<h1 style='margin-bottom:0'><span style='color:#2B4460'>Data</span><span style='color:#49C1C3'>udit</span></h1>",
    unsafe_allow_html=True)
st.markdown("#### Auditoría de datos y BI para pymes, sin escribir código")
st.write("Carga los reportes de tu cliente, ejecuta pruebas de auditoría precargadas, selecciona muestras "
         "estadísticas y exporta papeles de trabajo con trazabilidad completa.")

pasos = st.columns(3)
for columna, (numero, titulo, texto, destino, icono) in zip(pasos, (
    (1, "Carga y mapea", "Sube un Excel o CSV de tu ERP e indica qué columna es la fecha, el valor, el NIT…",
     "vistas/datos.py", ":material/upload_file:"),
    (2, "Ejecuta pruebas", "Benford, duplicados, fraccionamiento, festivos, antigüedad de saldos y más.",
     "vistas/pruebas.py", ":material/fact_check:"),
    (3, "Muestrea y documenta", "Muestreo aleatorio, sistemático, MUS o estratificado con semilla reproducible.",
     "vistas/muestreo.py", ":material/filter_alt:"),
)):
    with columna.container(border=True, height="stretch"):
        st.markdown(f"**{numero}. {titulo}**")
        st.caption(texto)
        st.page_link(destino, label="Ir", icon=icono)

st.divider()
izquierda, derecha = st.columns([3, 2], gap="large")
with izquierda:
    st.markdown("##### Catálogo de pruebas")
    for categoria, pruebas in por_categoria().items():
        st.markdown(f"**{categoria}**")
        st.markdown("\n".join(f"- {p.nombre} · <span style='color:gray'>{p.nia}</span>" for p in pruebas),
                    unsafe_allow_html=True)
with derecha:
    st.markdown("##### ¿Quieres probar sin tus datos?")
    st.write("Carga un año de pagos a proveedores y una cartera de clientes ficticios, con anomalías sembradas "
             "para que cada prueba encuentre algo.")
    if st.button("Cargar datos de demostración", icon=":material/science:", type="primary"):
        cargados = estado.cargar_demo()
        st.toast(f"Cargados: {', '.join(cargados)}" if cargados else "Los datos de demostración ya estaban cargados.")
        st.switch_page("vistas/pruebas.py")
    if estado.conjuntos():
        st.success(f"{len(estado.conjuntos())} conjunto(s) de datos cargado(s). Activo: "
                   f"**{st.session_state['activo']}**", icon=":material/check_circle:")
