import streamlit as st

from core.engine import ConsultaInvalida
from ui import estado
from ui.artefactos import dibujar_visual

almacen = estado.almacen()
st.title("Tableros")
st.caption("Cada elemento guarda su consulta: al abrir el tablero se recalcula con los datos cargados. "
           "Fija gráficas y tablas desde el Asistente o desde Explorar.")

tableros = {t["id"]: t for t in almacen.tableros()}
cabecera = st.columns([3, 1, 1], vertical_alignment="bottom")
with cabecera[1].popover("Nuevo tablero", icon=":material/add:", width="stretch"):
    with st.form("nuevo_tablero", border=False):
        nombre = st.text_input("Nombre", placeholder="Ej.: Pagos a proveedores 2025")
        descripcion = st.text_area("Descripción", height=80)
        if st.form_submit_button("Crear", type="primary"):
            st.session_state["tablero_activo"] = almacen.crear_tablero(nombre, descripcion)
            st.rerun()

if not tableros:
    st.info("Aún no hay tableros. Crea uno o fija una gráfica desde el Asistente.", icon=":material/dashboard:")
    st.stop()

ids = list(tableros)
actual = st.session_state.get("tablero_activo")
tablero_id = cabecera[0].selectbox("Tablero", ids, index=ids.index(actual) if actual in ids else 0,
                                   format_func=lambda i: tableros[i]["nombre"])
st.session_state["tablero_activo"] = tablero_id
tablero = tableros[tablero_id]
with cabecera[2].popover("Editar", icon=":material/edit:", width="stretch"):
    with st.form(f"editar_tablero_{tablero_id}", border=False):
        nombre = st.text_input("Nombre", value=tablero["nombre"])
        descripcion = st.text_area("Descripción", value=tablero["descripcion"], height=80)
        if st.form_submit_button("Guardar", type="primary"):
            almacen.renombrar_tablero(tablero_id, nombre, descripcion)
            st.rerun()
    confirmar = st.checkbox("Confirmo que quiero eliminar este tablero", key=f"conf_borrar_{tablero_id}")
    if st.button("Eliminar tablero", disabled=not confirmar, icon=":material/delete:"):
        almacen.eliminar_tablero(tablero_id)
        st.session_state.pop("tablero_activo", None)
        st.rerun()

if tablero["descripcion"]:
    st.caption(tablero["descripcion"])

widgets = almacen.widgets(tablero_id)
if not widgets:
    st.info("Este tablero está vacío. En el Asistente o en Explorar usa «Fijar en tablero».",
            icon=":material/push_pin:")
    st.stop()
if not estado.conjuntos():
    st.warning("Carga los conjuntos de datos para ver la información del tablero.", icon=":material/upload_file:")
    st.page_link("vistas/datos.py", label="Ir a Cargar y mapear datos", icon=":material/arrow_forward:")
    st.stop()

motor = estado.motor()
# Los indicadores (KPI) van en una fila arriba; el resto en una cuadrícula de dos columnas.
kpis = [w for w in widgets if w["spec"]["tipo"] == "kpi"]
otros = [w for w in widgets if w["spec"]["tipo"] != "kpi"]


def controles(widget: dict, posicion: int, total: int) -> None:
    columnas = st.columns([6, 1, 1, 1], vertical_alignment="center")
    columnas[0].markdown(f"**{widget['titulo']}**")
    if columnas[1].button("", key=f"sube_{widget['id']}", icon=":material/arrow_upward:", disabled=posicion == 0,
                          help="Mover antes"):
        almacen.mover_widget(widget["id"], -1)
        st.rerun()
    if columnas[2].button("", key=f"baja_{widget['id']}", icon=":material/arrow_downward:",
                          disabled=posicion == total - 1, help="Mover después"):
        almacen.mover_widget(widget["id"], 1)
        st.rerun()
    if columnas[3].button("", key=f"quita_{widget['id']}", icon=":material/close:", help="Quitar del tablero"):
        almacen.eliminar_widget(widget["id"])
        st.rerun()


def contenido(widget: dict) -> None:
    try:
        resultado = motor.ejecutar(widget["sql"])
        dibujar_visual(resultado.datos, {**widget["spec"], "titulo": "" if widget["spec"]["tipo"] != "kpi"
                                         else widget["titulo"]}, f"w{widget['id']}")
    except ConsultaInvalida as error:
        st.warning(f"No se pudo calcular: {error}. ¿Están cargados los conjuntos que usa?", icon=":material/warning:")
    except ValueError as error:
        st.warning(f"La visualización ya no coincide con los datos: {error}", icon=":material/warning:")
    with st.popover("SQL", icon=":material/code:"):
        st.code(widget["sql"], language="sql")


if kpis:
    columnas = st.columns(min(len(kpis), 4))
    for i, widget in enumerate(kpis):
        with columnas[i % len(columnas)]:
            contenido(widget)
            if st.button("Quitar", key=f"quita_{widget['id']}", icon=":material/close:"):
                almacen.eliminar_widget(widget["id"])
                st.rerun()

for fila in range(0, len(otros), 2):
    columnas = st.columns(2)
    for desplazamiento, widget in enumerate(otros[fila:fila + 2]):
        with columnas[desplazamiento].container(border=True):
            controles(widget, fila + desplazamiento, len(otros))
            contenido(widget)
