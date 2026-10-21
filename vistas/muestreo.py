import pandas as pd
import streamlit as st

from core import muestreo
from core.graficas import entero, pesos
from ui import estado
from ui.componentes import exportar_papel, metricas, tabla

conjunto = estado.requiere_datos()
std = conjunto.std
tiene_monto = "monto" in std
st.title("Muestreo de auditoría")
st.caption(f"Población: **{conjunto.nombre}** · {entero(conjunto.filas)} elementos"
           + (f" · {pesos(std['monto'].abs().sum())}" if tiene_monto else "") + " · NIA 530")

st.subheader("1. Tamaño de la muestra")
confianzas = {f"{c:.0%}": c for c in muestreo.CONFIANZAS}
atributos, mus, manual = st.tabs(["Pruebas de controles (atributos)", "Pruebas de detalle (MUS)", "Definir manualmente"])
with atributos:
    columnas = st.columns(3)
    confianza = confianzas[columnas[0].selectbox("Nivel de confianza", list(confianzas), index=1, key="conf_atr")]
    tolerable = columnas[1].number_input("Tasa tolerable de desviación (%)", 1.0, 20.0, 5.0, 0.5) / 100
    esperada = columnas[2].number_input("Tasa esperada de desviación (%)", 0.0, 19.0, 0.0, 0.25) / 100
    try:
        n_atributos = muestreo.tamano_atributos(confianza, tolerable, esperada)
        st.metric("Tamaño sugerido", entero(n_atributos), border=True)
        if st.button("Usar este tamaño", key="usar_atr"):
            st.session_state["n_muestra"] = n_atributos
    except ValueError as error:
        st.error(str(error))
    st.caption("Cálculo binomial: menor tamaño con el que, si se hallan a lo sumo las desviaciones esperadas, se "
               "concluye con la confianza elegida que la tasa real no supera la tolerable.")
with mus:
    if not tiene_monto:
        st.info("Mapea el campo «Valor / monto» para usar el muestreo por unidad monetaria.")
    else:
        valor_libros = float(std.loc[std["monto"] > 0, "monto"].sum())
        columnas = st.columns(4)
        confianza_mus = confianzas[columnas[0].selectbox("Nivel de confianza", list(confianzas), index=1,
                                                         key="conf_mus")]
        valor = columnas[1].number_input("Valor en libros", value=valor_libros, format="%.0f", step=1_000_000.0)
        tolerable_mus = columnas[2].number_input("Error tolerable (materialidad de ejecución)",
                                                 value=round(valor_libros * 0.05, -3), format="%.0f",
                                                 step=1_000_000.0)
        esperado_mus = columnas[3].number_input("Error esperado", value=0.0, format="%.0f", step=1_000_000.0)
        try:
            n_mus, intervalo = muestreo.tamano_mus(valor, tolerable_mus, esperado_mus, confianza_mus)
            metricas({"Tamaño sugerido": entero(n_mus), "Intervalo de muestreo": pesos(intervalo)})
            if st.button("Usar este tamaño", key="usar_mus"):
                st.session_state["n_muestra"] = n_mus
                st.session_state["metodo_muestra"] = "mus"
        except ValueError as error:
            st.error(str(error))
with manual:
    st.write("Si tu metodología define el tamaño por juicio profesional, indícalo directamente en el paso 2.")

st.subheader("2. Selección")
with st.form("seleccion"):
    columnas = st.columns(3)
    metodos = [m for m in muestreo.METODOS if tiene_monto or m in ("aleatorio", "sistematico")]
    actual = st.session_state.get("metodo_muestra", "aleatorio")
    metodo = columnas[0].selectbox("Método", metodos, format_func=muestreo.METODOS.get,
                                   index=metodos.index(actual) if actual in metodos else 0)
    n = columnas[1].number_input("Tamaño de la muestra", min_value=1, max_value=conjunto.filas,
                                 value=min(int(st.session_state.get("n_muestra", 25)), conjunto.filas))
    semilla = columnas[2].number_input("Semilla", min_value=0, max_value=999_999, step=1,
                                       value=st.session_state.setdefault("semilla", muestreo.nueva_semilla()),
                                       help="Con la misma semilla y los mismos datos se obtiene la misma muestra.")
    columnas = st.columns(3)
    usar_clave = columnas[0].checkbox("Examinar partidas clave al 100 %", disabled=not tiene_monto,
                                      help="Partidas individualmente significativas, fuera del muestreo.")
    umbral = columnas[1].number_input("Partidas clave desde", value=50_000_000.0, step=1_000_000.0, format="%.0f",
                                      disabled=not tiene_monto)
    estratos = columnas[2].number_input("Número de estratos (solo estratificado)", 2, 10, 4)
    seleccionar = st.form_submit_button("Seleccionar muestra", type="primary", icon=":material/filter_alt:")

if seleccionar:
    try:
        st.session_state["muestra"] = (conjunto.nombre, muestreo.seleccionar(
            std, metodo, int(n), int(semilla), umbral if usar_clave else None, int(estratos)))
        st.session_state["semilla"] = int(semilla)
    except ValueError as error:
        st.error(str(error))

guardada = st.session_state.get("muestra")
if not guardada or guardada[0] != conjunto.nombre:
    st.stop()
resultado = guardada[1]

st.subheader("3. Muestra seleccionada")
st.success(resultado.resumen, icon=":material/check_circle:")
resumen_metricas = {"Elementos": entero(len(resultado.muestra))}
if tiene_monto:
    resumen_metricas["Valor de la muestra"] = pesos(resultado.muestra["monto"].abs().sum())
    resumen_metricas["Cobertura de valor"] = resultado.parametros["Cobertura de valor"]
resumen_metricas["Semilla"] = resultado.parametros["Semilla"]
metricas(resumen_metricas)

muestra = resultado.muestra
originales = conjunto.original.loc[muestra.index]
extra = [c for c in ("estrato", "unidades_seleccionadas") if c in muestra]
vista = pd.concat([muestra[["fila", "motivo", *extra]], originales], axis=1)
tabla(vista, alto=420)

# Columnas vacías para que el auditor documente el examen de cada elemento.
papel = vista.assign(**{"Soporte revisado": "", "Valor auditado": "", "Diferencia": "", "Observaciones": ""})
encabezado = {"Objetivo": "Selección de elementos para pruebas de detalle o de controles (NIA 530).",
              **conjunto.ficha(), **resultado.parametros}
exportar_papel("Muestra de auditoría", encabezado, {"Muestra": papel}, resultado.resumen,
               f"{conjunto.nombre}_muestra")
