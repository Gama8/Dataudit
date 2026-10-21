import pandas as pd
import streamlit as st

from core.mapping import CAMPOS
from core.pruebas import CATEGORIAS, REGISTRO, Parametro, Prueba, por_categoria
from ui import estado
from ui.componentes import exportar_papel, metricas, tabla

conjunto = estado.requiere_datos()
st.title("Pruebas de auditoría")
st.caption(f"Sobre **{conjunto.nombre}** · {conjunto.filas:,} registros".replace(",", "."))

categoria = st.segmented_control("Categoría", ["Todas", *CATEGORIAS], default="Todas", label_visibility="collapsed")
pruebas = [p for c, lista in por_categoria().items() if categoria in (None, "Todas", c) for p in lista]

for i, prueba in enumerate(pruebas):
    if i % 3 == 0:  # una fila nueva cada 3 tarjetas para que queden alineadas
        columnas = st.columns(3)
    faltan = prueba.faltantes(conjunto.campos_mapeados)
    ejecutada = (conjunto.nombre, prueba.clave) in st.session_state["resultados"]
    with columnas[i % 3].container(border=True, height="stretch"):
        st.markdown(f"**{prueba.nombre}**" + (" :green-badge[Ejecutada]" if ejecutada else ""))
        st.caption(f"{prueba.categoria} · {prueba.nia}")
        st.write(prueba.objetivo)
        if faltan:
            st.caption(":material/link_off: Falta mapear: " + ", ".join(CAMPOS[c].etiqueta for c in faltan))
        elif st.button("Abrir", key=f"abrir_{prueba.clave}", icon=":material/play_arrow:",
                       type="primary" if st.session_state.get("prueba_activa") == prueba.clave else "secondary"):
            st.session_state["prueba_activa"] = prueba.clave

clave = st.session_state.get("prueba_activa")
if clave not in REGISTRO or REGISTRO[clave].faltantes(conjunto.campos_mapeados):
    st.info("Elige una prueba para configurarla y ejecutarla.", icon=":material/touch_app:")
    st.stop()

prueba: Prueba = REGISTRO[clave]
st.divider()
st.header(prueba.nombre)
st.write(f"**Objetivo:** {prueba.objetivo}")
with st.expander("Cómo interpretar los resultados", icon=":material/menu_book:"):
    st.write(prueba.interpretacion)
    st.caption(f"Referencia: {prueba.nia}. Campos requeridos: "
               + (", ".join(CAMPOS[c].etiqueta for c in prueba.requeridos) or "ninguno en particular")
               + (". Opcionales: " + ", ".join(CAMPOS[c].etiqueta for c in prueba.opcionales)
                  if prueba.opcionales else ""))


def widget(parametro: Parametro, llave: str):
    ayuda = parametro.ayuda or None
    if parametro.tipo == "entero":
        return st.number_input(parametro.etiqueta, value=int(parametro.defecto), step=1, help=ayuda, key=llave,
                               min_value=None if parametro.minimo is None else int(parametro.minimo),
                               max_value=None if parametro.maximo is None else int(parametro.maximo))
    if parametro.tipo == "numero":
        return st.number_input(parametro.etiqueta, value=float(parametro.defecto), step=100_000.0 if
                               parametro.defecto >= 100_000 else 1.0, format="%.0f", help=ayuda, key=llave,
                               min_value=None if parametro.minimo is None else float(parametro.minimo))
    if parametro.tipo == "porcentaje":
        valor = st.number_input(f"{parametro.etiqueta} (%)", value=float(parametro.defecto) * 100, step=5.0,
                                 format="%.0f", help=ayuda, key=llave, min_value=0.0,
                                max_value=None if parametro.maximo is None else float(parametro.maximo) * 100)
        return valor / 100
    if parametro.tipo == "fecha":
        return st.date_input(parametro.etiqueta, value=parametro.defecto, help=ayuda, key=llave, format="YYYY-MM-DD")
    if parametro.tipo == "opcion":
        opciones = [o for o in parametro.opciones if o not in CAMPOS or o in conjunto.campos_mapeados]
        return st.selectbox(parametro.etiqueta, opciones, help=ayuda, key=llave,
                            index=opciones.index(parametro.defecto) if parametro.defecto in opciones else 0,
                            format_func=lambda o: CAMPOS[o].etiqueta if o in CAMPOS else o)
    if parametro.tipo == "campos":
        mapeados = [c for c in conjunto.campos_mapeados if c not in ("dv",)]
        return st.multiselect(parametro.etiqueta, mapeados, help=ayuda, key=llave,
                              default=[c for c in parametro.defecto if c in mapeados],
                              format_func=lambda c: CAMPOS[c].etiqueta)
    raise ValueError(f"Tipo de parámetro desconocido: {parametro.tipo}")


with st.form(f"parametros_{clave}"):
    parametros = {}
    if prueba.parametros:
        columnas = st.columns(min(len(prueba.parametros), 3))
        for i, parametro in enumerate(prueba.parametros):
            with columnas[i % len(columnas)]:
                parametros[parametro.clave] = widget(parametro, f"param_{clave}_{parametro.clave}")
    ejecutar = st.form_submit_button("Ejecutar prueba", type="primary", icon=":material/play_arrow:")

llave_resultado = (conjunto.nombre, clave)
if ejecutar:
    try:
        with st.spinner("Analizando…"):
            resultado = prueba.ejecutar(conjunto.std, parametros)
        st.session_state["resultados"][llave_resultado] = (resultado, parametros)
    except ValueError as error:
        st.error(str(error), icon=":material/error:")
        st.stop()

if llave_resultado not in st.session_state["resultados"]:
    st.stop()

resultado, parametros_usados = st.session_state["resultados"][llave_resultado]
if resultado.hay_excepciones:
    st.warning(resultado.resumen, icon=":material/report:")
else:
    st.success(resultado.resumen, icon=":material/check_circle:")
metricas(resultado.metricas)

for figura in resultado.graficas:
    st.plotly_chart(figura, width="stretch", theme="streamlit")

st.markdown(f"**Excepciones para revisar** ({len(resultado.hallazgos):,})".replace(",", "."))
hallazgos = resultado.hallazgos
if "fila" in hallazgos.columns and len(hallazgos) and st.toggle("Mostrar todas las columnas del archivo original"):
    originales = conjunto.original.loc[hallazgos.index]
    hallazgos = pd.concat([hallazgos[["fila"]], originales,
                           hallazgos.drop(columns=["fila", *[c for c in CAMPOS if c in hallazgos]])], axis=1)
tabla(hallazgos, alto=min(420, 40 + 35 * max(len(hallazgos), 1)))

for titulo, df in resultado.tablas.items():
    with st.expander(titulo, expanded=len(resultado.tablas) == 1):
        tabla(df)

def texto_parametro(p: Parametro, valor) -> str:
    if valor is None or valor == "":
        return "Por defecto"
    if p.tipo == "porcentaje":
        return f"{valor * 100:.0f} %"
    if p.tipo == "campos":
        return ", ".join(CAMPOS[c].etiqueta for c in valor)
    if p.tipo == "opcion" and valor in CAMPOS:
        return CAMPOS[valor].etiqueta
    if isinstance(valor, float):
        return f"{valor:,.0f}".replace(",", ".")
    return str(valor)


encabezado = {"Objetivo": prueba.objetivo, "Referencia normativa": prueba.nia, **conjunto.ficha(),
              **{f"Parámetro: {p.etiqueta}": texto_parametro(p, parametros_usados.get(p.clave))
                 for p in prueba.parametros}}
hojas = {"Excepciones": resultado.hallazgos, **resultado.tablas}
exportar_papel(prueba.nombre, encabezado, hojas, resultado.resumen, f"{conjunto.nombre}_{clave}")
