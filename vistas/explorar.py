import os

import plotly.graph_objects as go
import streamlit as st

from core import nl2sql
from core.engine import ConsultaInvalida
from core.graficas import SERIE_1, barras, estilo
from ui import estado
from ui.componentes import tabla

conjunto = estado.requiere_datos()
motor = estado.motor()
st.title("Explorar (SQL e IA)")
st.caption("Consultas de solo lectura sobre los conjuntos cargados. La tabla `datos` es siempre el conjunto activo.")

with st.expander("Tablas y columnas disponibles", icon=":material/table_view:"):
    for nombre, columnas in motor.esquema().items():
        st.markdown(f"**{nombre}** — " + ", ".join(f"`{c}` ({t.lower()})" for c, t in columnas))


def configuracion(clave: str, defecto: str | None = None) -> str | None:
    try:
        valor = st.secrets.get(clave)
    except Exception:  # no hay secrets.toml
        valor = None
    return valor or os.getenv(clave) or defecto


@st.cache_resource
def cliente_openai(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key)


if "sql_editor" not in st.session_state:
    st.session_state["sql_editor"] = 'SELECT *\nFROM datos\nLIMIT 100'

pregunta_tab, sql_tab = st.tabs(["Preguntar en lenguaje natural", "Escribir SQL"])
with pregunta_tab:
    api_key = configuracion("OPENAI_API_KEY")
    if not api_key:
        st.info("Para hacer preguntas en lenguaje natural configura `OPENAI_API_KEY` en `.streamlit/secrets.toml` "
                "o como variable de entorno. Mientras tanto puedes usar la pestaña «Escribir SQL».",
                icon=":material/key:")
    else:
        with st.form("pregunta"):
            pregunta = st.text_input("Pregunta", placeholder="¿Cuáles son los 10 proveedores con mayor valor pagado?")
            ejemplos = st.checkbox("Enviar hasta 3 valores de ejemplo por columna al modelo", value=True,
                                   help="Mejora la consulta generada. Nunca se envían los datos completos.")
            generar = st.form_submit_button("Generar y ejecutar", type="primary", icon=":material/auto_awesome:")
        if generar and pregunta.strip():
            cache = st.session_state.setdefault("cache_nl", {})
            llave = (pregunta.strip(), ejemplos, st.session_state["version_datos"])
            try:
                if llave not in cache:
                    with st.spinner("Generando consulta…"):
                        cache[llave] = nl2sql.generar_sql(cliente_openai(api_key), pregunta, motor.tablas,
                                                          configuracion("OPENAI_MODEL", nl2sql.MODELO_POR_DEFECTO),
                                                          ejemplos)
                st.session_state["sql_editor"] = cache[llave]
                st.session_state["ejecutar_sql"] = True
                st.session_state["pregunta_actual"] = pregunta.strip()
            except ConsultaInvalida as error:
                st.error(f"El modelo generó una consulta no permitida: {error}")
            except Exception as error:
                st.error(f"No se pudo generar la consulta: {error}")
        if st.session_state.get("pregunta_actual"):
            st.caption(f"Consulta generada para: «{st.session_state['pregunta_actual']}». "
                       "Puedes ajustarla en la pestaña «Escribir SQL».")
            st.code(st.session_state["sql_editor"], language="sql")

with sql_tab:
    with st.form("sql"):
        st.text_area("Consulta SQL (DuckDB)", key="sql_editor", height=180)
        if st.form_submit_button("Ejecutar", type="primary", icon=":material/play_arrow:"):
            st.session_state["ejecutar_sql"] = True
            st.session_state.pop("pregunta_actual", None)

if st.session_state.pop("ejecutar_sql", False):
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
st.download_button("Descargar CSV", datos.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                   "consulta.csv", "text/csv", icon=":material/download:")

numericas = [c for c in datos.columns if datos[c].dtype.kind in "if"]
if not numericas or len(datos) < 2:
    st.stop()
with st.container(border=True):
    st.markdown("**Graficar el resultado**")
    columnas = st.columns(4)
    tipo = columnas[0].selectbox("Tipo", ["Barras", "Líneas", "Dispersión"])
    eje_x = columnas[1].selectbox("Eje X", list(datos.columns))
    eje_y = columnas[2].selectbox("Eje Y (valor)", numericas, index=len(numericas) - 1)
    agregacion = columnas[3].selectbox("Agregación", ["Suma", "Promedio", "Conteo", "Ninguna"],
                                       disabled=tipo == "Dispersión")
    if tipo == "Dispersión" or agregacion == "Ninguna":
        serie = datos[[eje_x, eje_y]].dropna()
    else:
        funcion = {"Suma": "sum", "Promedio": "mean", "Conteo": "count"}[agregacion]
        serie = datos.groupby(eje_x, dropna=False)[eje_y].agg(funcion).reset_index()
    titulo = f"{eje_y} por {eje_x}" if tipo != "Dispersión" else f"{eje_y} vs. {eje_x}"
    if tipo == "Barras":
        serie = serie.sort_values(eje_y, ascending=False)
        if len(serie) > 25:
            st.caption(f"Se muestran las 25 categorías con mayor valor de {len(serie)}.")
            serie = serie.head(25)
        figura = barras(serie[eje_x].astype(str), serie[eje_y], titulo, eje_x, eje_y,
                        texto_hover="%{x}: %{y:,.2f}<extra></extra>")
    elif tipo == "Líneas":
        serie = serie.sort_values(eje_x)
        figura = estilo(go.Figure(go.Scatter(x=serie[eje_x], y=serie[eje_y], mode="lines+markers",
                                             line=dict(color=SERIE_1, width=2), marker=dict(size=8))),
                        titulo, eje_x, eje_y)
    else:
        figura = estilo(go.Figure(go.Scatter(x=serie[eje_x], y=serie[eje_y], mode="markers",
                                             marker=dict(color=SERIE_1, size=8, line=dict(width=1, color="white")))),
                        titulo, eje_x, eje_y)
    st.plotly_chart(figura, width="stretch")
