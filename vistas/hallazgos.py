import io
from datetime import date

import pandas as pd
import streamlit as st

from core.almacen import ESTADOS, SEVERIDADES
from core.datasets import ahora
from core.graficas import entero, pesos
from core.papeles import papel_de_trabajo
from core.pruebas import REGISTRO
from ui import estado
from ui.componentes import metricas, tabla

almacen = estado.almacen()
st.title("Registro de hallazgos")
st.caption("Hallazgos de auditoría con condición, criterio, causa, efecto y recomendación. Llegan desde las "
           "pruebas, desde el Asistente o se crean a mano.")

hallazgos = pd.DataFrame(almacen.hallazgos())
abiertos = hallazgos[hallazgos["estado"] != "Cerrado"] if len(hallazgos) else hallazgos
metricas({
    "Hallazgos": entero(len(hallazgos)),
    "Abiertos": entero(len(abiertos)),
    "Severidad alta abiertos": entero(int((abiertos["severidad"] == "Alta").sum()) if len(abiertos) else 0),
    "Valor afectado abierto": pesos(float(abiertos["valor_afectado"].fillna(0).sum()) if len(abiertos) else 0),
})

acciones = st.columns([2, 2, 1, 1], vertical_alignment="bottom")
filtro_estado = acciones[0].segmented_control("Estado", ["Todos", *ESTADOS], default="Todos")
filtro_severidad = acciones[1].multiselect("Severidad", SEVERIDADES, placeholder="Todas")
if acciones[2].button("Nuevo", icon=":material/add:", width="stretch"):
    st.session_state["hallazgo_edicion"] = "nuevo"

COLUMNAS = {"codigo": "Código", "titulo": "Título", "severidad": "Severidad", "estado": "Estado",
            "responsable": "Responsable", "fecha_compromiso": "Compromiso", "valor_afectado": "Valor afectado",
            "conjunto": "Conjunto", "prueba": "Prueba", "condicion": "Condición", "criterio": "Criterio",
            "causa": "Causa", "efecto": "Efecto", "recomendacion": "Recomendación", "comentarios": "Comentarios",
            "origen": "Origen", "creado_por": "Creado por", "creado": "Creado", "actualizado": "Actualizado",
            "huella_datos": "Huella SHA-256 de los datos"}

if len(hallazgos):
    contenido = papel_de_trabajo(
        "Informe de hallazgos",
        {"Empresa / espacio": almacen.espacio, "Generado": ahora().strftime("%Y-%m-%d %H:%M %Z"),
         "Generado por": st.session_state.get("auditor") or "(sin nombre)", "Hallazgos": entero(len(hallazgos)),
         "Abiertos": entero(len(abiertos))},
        {"Hallazgos": hallazgos[list(COLUMNAS)].rename(columns=COLUMNAS)},
        "Consolidado de hallazgos registrados en Dataudit.")
    acciones[3].download_button("Informe", contenido, f"Informe_hallazgos_{date.today():%Y%m%d}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                icon=":material/download:", width="stretch")

    vista = hallazgos
    if filtro_estado and filtro_estado != "Todos":
        vista = vista[vista["estado"] == filtro_estado]
    if filtro_severidad:
        vista = vista[vista["severidad"].isin(filtro_severidad)]
    seleccion = st.dataframe(
        vista[["codigo", "titulo", "severidad", "estado", "responsable", "fecha_compromiso", "valor_afectado",
               "origen"]].rename(columns=COLUMNAS),
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="tabla_hallazgos",
        column_config={"Valor afectado": st.column_config.NumberColumn(format="localized")})
    # Solo un cambio de selección abre otro hallazgo (así «Nuevo» no queda tapado por la fila marcada).
    filas = tuple(seleccion.selection.rows)
    if filas and filas != st.session_state.get("_seleccion_hallazgo"):
        st.session_state["hallazgo_edicion"] = int(vista.iloc[filas[0]]["id"])
    st.session_state["_seleccion_hallazgo"] = filas
    st.caption("Selecciona una fila para ver o editar el hallazgo.")
else:
    st.info("Aún no hay hallazgos. Regístralos desde una prueba, desde el Asistente o con «Nuevo».",
            icon=":material/bookmark:")

edicion = st.session_state.get("hallazgo_edicion")
if edicion is None:
    st.stop()
actual = {} if edicion == "nuevo" else (almacen.hallazgo(edicion) or {})
if edicion != "nuevo" and not actual:
    st.session_state.pop("hallazgo_edicion")
    st.stop()

st.divider()
st.subheader("Nuevo hallazgo" if edicion == "nuevo" else f"{actual['codigo']} · {actual['titulo']}")
if actual:
    st.caption(f"Origen: {actual['origen']} · creado {actual['creado']} por {actual['creado_por'] or '—'} · "
               f"actualizado {actual['actualizado']}")
with st.form(f"hallazgo_{edicion}"):
    titulo = st.text_input("Título", value=actual.get("titulo", ""))
    columnas = st.columns(4)
    severidad = columnas[0].selectbox("Severidad", SEVERIDADES,
                                      index=SEVERIDADES.index(actual.get("severidad", "Media")))
    estado_h = columnas[1].selectbox("Estado", ESTADOS, index=ESTADOS.index(actual.get("estado", "Abierto")))
    responsable = columnas[2].text_input("Responsable", value=actual.get("responsable", ""))
    compromiso_txt = actual.get("fecha_compromiso") or ""
    compromiso = columnas[3].date_input("Fecha de compromiso", value=date.fromisoformat(compromiso_txt)
                                        if compromiso_txt else None, format="YYYY-MM-DD")
    columnas = st.columns(3)
    conjuntos = ["", *sorted(set(estado.conjuntos()) | {actual.get("conjunto", "")} - {""})]
    conjunto = columnas[0].selectbox("Conjunto de datos", conjuntos,
                                     index=conjuntos.index(actual.get("conjunto", "")),
                                     format_func=lambda c: c or "— Ninguno —")
    pruebas = ["", *REGISTRO]
    prueba = columnas[1].selectbox("Prueba de origen", pruebas,
                                   index=pruebas.index(actual.get("prueba", "")) if actual.get("prueba", "") in pruebas else 0,
                                   format_func=lambda p: REGISTRO[p].nombre if p else "— Ninguna —")
    valor = columnas[2].number_input("Valor afectado ($)", value=float(actual.get("valor_afectado") or 0.0),
                                     step=100_000.0, format="%.0f", min_value=0.0)
    condicion = st.text_area("Condición (qué se encontró)", value=actual.get("condicion", ""))
    criterio = st.text_area("Criterio (qué debería ser)", value=actual.get("criterio", ""))
    columnas = st.columns(2)
    causa = columnas[0].text_area("Causa", value=actual.get("causa", ""))
    efecto = columnas[1].text_area("Efecto (riesgo o impacto)", value=actual.get("efecto", ""))
    recomendacion = st.text_area("Recomendación", value=actual.get("recomendacion", ""))
    comentarios = st.text_area("Comentarios y seguimiento", value=actual.get("comentarios", ""))
    if st.form_submit_button("Guardar", type="primary", icon=":material/save:"):
        datos = {"titulo": titulo, "severidad": severidad, "estado": estado_h, "responsable": responsable,
                 "fecha_compromiso": compromiso.isoformat() if compromiso else "", "conjunto": conjunto,
                 "prueba": prueba, "valor_afectado": valor or None, "condicion": condicion, "criterio": criterio,
                 "causa": causa, "efecto": efecto, "recomendacion": recomendacion, "comentarios": comentarios}
        if edicion == "nuevo":
            datos.update(origen="Manual", creado_por=st.session_state.get("auditor", ""),
                         huella_datos=estado.conjuntos()[conjunto].huella if conjunto in estado.conjuntos() else "")
        try:
            st.session_state["hallazgo_edicion"] = almacen.guardar_hallazgo(
                datos, None if edicion == "nuevo" else edicion)
            st.toast("Hallazgo guardado", icon=":material/check:")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

if actual.get("evidencia_json"):
    with st.expander("Evidencia adjunta", icon=":material/attach_file:"):
        evidencia = pd.read_json(io.StringIO(actual["evidencia_json"]), orient="records")
        st.caption(f"{len(evidencia)} filas guardadas al registrar el hallazgo"
                   + (f" · huella de los datos {actual['huella_datos'][:16]}…" if actual.get("huella_datos") else ""))
        tabla(evidencia, alto=300)
if actual:
    confirmar = st.checkbox("Confirmo que quiero eliminar este hallazgo", key=f"conf_h_{edicion}")
    if st.button("Eliminar hallazgo", disabled=not confirmar, icon=":material/delete:"):
        almacen.eliminar_hallazgo(edicion)
        st.session_state.pop("hallazgo_edicion")
        st.rerun()
