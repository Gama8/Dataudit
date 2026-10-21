import streamlit as st

from core import visual
from core.engine import ConsultaInvalida
from ui import estado
from ui.artefactos import boton_fijar, dibujar_visual
from ui.componentes import tabla

conjunto = estado.requiere_datos()
motor = estado.motor()
st.title("Explorar con SQL")
st.caption("Consultas de solo lectura sobre los conjuntos cargados. La tabla `datos` es siempre el conjunto activo. "
           "Para preguntar en español usa el Asistente.")

with st.expander("Tablas y columnas disponibles", icon=":material/table_view:"):
    for nombre, columnas in motor.esquema().items():
        st.markdown(f"**{nombre}** — " + ", ".join(f"`{c}` ({t.lower()})" for c, t in columnas))

if "sql_editor" not in st.session_state:
    st.session_state["sql_editor"] = 'SELECT *\nFROM datos\nLIMIT 100'

with st.form("sql"):
    st.text_area("Consulta SQL (DuckDB)", key="sql_editor", height=180)
    ejecutar = st.form_submit_button("Ejecutar", type="primary", icon=":material/play_arrow:")

if ejecutar:
    try:
        st.session_state["resultado_sql"] = motor.ejecutar(st.session_state["sql_editor"])
    except ConsultaInvalida as error:
        st.session_state.pop("resultado_sql", None)
        st.error(str(error), icon=":material/error:")

resultado = st.session_state.get("resultado_sql")
if resultado is None:
    st.stop()

datos = resultado.datos
st.markdown(f"**Resultado** · {len(datos):,} filas".replace(",", "."))
if resultado.truncado:
    st.warning("El resultado se recortó a 10.000 filas. Agrega filtros o agregaciones.", icon=":material/warning:")
tabla(datos, alto=360)
acciones = st.columns([1, 1, 3])
acciones[0].download_button("Descargar CSV", datos.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                            "consulta.csv", "text/csv", icon=":material/download:")
with acciones[1]:
    boton_fijar("Consulta", resultado.sql, {"tipo": "tabla"}, "explorar_tabla")

numericas = [c for c in datos.columns if datos[c].dtype.kind in "if"]
if not numericas or not len(datos):
    st.stop()
with st.container(border=True):
    st.markdown("**Graficar el resultado**")
    columnas = st.columns(5)
    tipos = [t for t in visual.TIPOS if t != "tabla"]
    tipo = columnas[0].selectbox("Tipo", tipos, format_func=visual.TIPOS.get)
    eje_x = columnas[1].selectbox("Eje X / categoría", list(datos.columns), disabled=tipo == "kpi")
    eje_y = columnas[2].selectbox("Valor", numericas, index=len(numericas) - 1)
    serie = columnas[3].selectbox("Series por color", ["", *[c for c in datos.columns if c not in (eje_x, eje_y)]],
                                  format_func=lambda c: c or "— Ninguna —", disabled=tipo == "kpi")
    agregacion = columnas[4].selectbox("Agregación", list(visual.AGREGACIONES), index=1,
                                       format_func=str.capitalize, disabled=tipo == "dispersion")
    titulo = f"{eje_y} por {eje_x}" if tipo != "kpi" else eje_y
    spec = {"tipo": tipo, "x": "" if tipo == "kpi" else eje_x, "y": eje_y, "serie": "" if tipo == "kpi" else serie,
            "agregacion": "ninguna" if tipo == "dispersion" else agregacion, "titulo": titulo}
    try:
        dibujar_visual(datos, visual.validar(spec, datos.columns), "explorar")
        boton_fijar(titulo, resultado.sql, spec, "explorar_grafica")
    except (ValueError, KeyError) as error:
        st.warning(f"No se puede dibujar esta combinación: {error}")
