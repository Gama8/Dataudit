import pandas as pd
import streamlit as st

from core import loader
from core.datasets import ConjuntoDatos
from core.mapping import CAMPOS
from core.pruebas import REGISTRO
from ui import estado
from ui.componentes import tabla

st.title("Cargar y mapear datos")

with st.container(border=True):
    st.markdown("**1. Sube un archivo**")
    archivo = st.file_uploader("Excel (.xlsx) o CSV exportado de tu ERP o paquete contable",
                               type=list(loader.EXTENSIONES))
    if archivo is not None:
        contenido = archivo.getvalue()
        hoja = None
        columnas = st.columns(2)
        if archivo.name.lower().endswith(".xlsx"):
            hojas = loader.hojas_excel(contenido)
            hoja = columnas[1].selectbox("Hoja", hojas) if len(hojas) > 1 else hojas[0]
        base = loader.nombre_tabla(archivo.name if not hoja or hoja == "Sheet1" else f"{archivo.name}_{hoja}")
        nombre = columnas[0].text_input("Nombre del conjunto (se usa como tabla en SQL)",
                                        value=estado.nombre_disponible(base))
        if st.button("Agregar conjunto de datos", type="primary", icon=":material/add:"):
            try:
                df = loader.leer_archivo(archivo.name, contenido, hoja)
                nombre = loader.nombre_tabla(nombre)
                if nombre in estado.conjuntos():
                    st.error(f"Ya existe un conjunto llamado «{nombre}».")
                else:
                    estado.agregar(ConjuntoDatos(nombre, archivo.name, loader.huella(contenido), df, hoja))
                    st.rerun()
            except Exception as error:  # el auditor necesita un mensaje claro, no un traceback
                st.error(f"No se pudo leer el archivo: {error}")
    if not estado.conjuntos():
        st.caption("¿Sin archivo a mano?")
        if st.button("Cargar datos de demostración", icon=":material/science:"):
            estado.cargar_demo()
            st.rerun()

conjunto = estado.activo()
if conjunto is None:
    st.stop()

st.subheader(f"Conjunto activo: {conjunto.nombre}")
st.caption(f"{conjunto.archivo} · {conjunto.filas:,} filas · {len(conjunto.original.columns)} columnas · "
           f"SHA-256 {conjunto.huella[:16]}…".replace(",", "."))

pestaña_mapeo, pestaña_vista, pestaña_ficha = st.tabs(["Mapeo de campos", "Vista previa", "Ficha y perfil"])

with pestaña_mapeo:
    st.write("Indica qué columna del archivo corresponde a cada campo. Dataudit propone un mapeo automático; "
             "revísalo. Solo necesitas los campos que usen las pruebas que vas a ejecutar.")
    sin_asignar = "— Sin asignar —"
    opciones = [sin_asignar, *conjunto.original.columns]
    with st.form(f"mapeo_{conjunto.nombre}"):
        columnas = st.columns(2)
        seleccion = {}
        for i, campo in enumerate(CAMPOS.values()):
            actual = conjunto.mapeo.get(campo.clave)
            seleccion[campo.clave] = columnas[i % 2].selectbox(
                campo.etiqueta, opciones, index=opciones.index(actual) if actual in opciones else 0,
                help=campo.ayuda, key=f"map_{conjunto.nombre}_{campo.clave}")
        if st.form_submit_button("Guardar mapeo", type="primary", icon=":material/save:"):
            elegidas = [c for c in seleccion.values() if c != sin_asignar]
            repetidas = {c for c in elegidas if elegidas.count(c) > 1}
            if repetidas:
                st.error(f"Una columna no puede asignarse a dos campos: {', '.join(repetidas)}.")
            else:
                conjunto.aplicar_mapeo({k: (None if v == sin_asignar else v) for k, v in seleccion.items()})
                estado.datos_modificados()
                st.toast("Mapeo guardado", icon=":material/check:")

    if conjunto.reporte_mapeo is not None and len(conjunto.reporte_mapeo):
        st.markdown("**Resultado de la conversión**")
        tabla(conjunto.reporte_mapeo)
        problemas = conjunto.reporte_mapeo[conjunto.reporte_mapeo["No convertidos"] > 0]
        for _, fila in problemas.iterrows():
            st.warning(f"«{fila['Columna del archivo']}»: {fila['No convertidos']:,} valores no se pudieron convertir "
                       f"a {CAMPOS[next(k for k, c in CAMPOS.items() if c.etiqueta == fila['Campo'])].tipo}. "
                       "Revisa el formato o el mapeo.", icon=":material/warning:")

    st.markdown("**Pruebas disponibles con este mapeo**")
    disponibles = []
    for prueba in REGISTRO.values():
        faltan = prueba.faltantes(conjunto.campos_mapeados)
        disponibles.append({"Prueba": prueba.nombre, "Categoría": prueba.categoria,
                            "Estado": "Lista" if not faltan else
                            "Falta: " + ", ".join(CAMPOS[c].etiqueta for c in faltan)})
    tabla(pd.DataFrame(disponibles))

with pestaña_vista:
    st.markdown("**Archivo original** (primeras 200 filas)")
    tabla(conjunto.original.head(200), alto=300)
    st.markdown("**Campos estandarizados** (así los ven las pruebas)")
    tabla(conjunto.std.head(200), alto=300)

with pestaña_ficha:
    st.markdown("**Ficha de trazabilidad**")
    tabla(pd.DataFrame(conjunto.ficha().items(), columns=["Dato", "Valor"]))
    st.markdown("**Perfil de columnas**")
    perfil = pd.DataFrame({
        "Columna": conjunto.original.columns,
        "Con valor": conjunto.original.notna().sum().to_numpy(),
        "Vacíos": conjunto.original.isna().sum().to_numpy(),
        "Valores distintos": conjunto.original.nunique().to_numpy(),
        "Ejemplo": [conjunto.original[c].dropna().astype(str).iloc[0] if conjunto.original[c].notna().any() else ""
                    for c in conjunto.original.columns],
    })
    tabla(perfil)

with st.expander(f"Conjuntos cargados ({len(estado.conjuntos())})"):
    for nombre, c in list(estado.conjuntos().items()):
        izquierda, derecha = st.columns([5, 1], vertical_alignment="center")
        izquierda.write(f"**{nombre}** · {c.archivo} · {c.filas:,} filas".replace(",", "."))
        if derecha.button("Quitar", key=f"quitar_{nombre}", icon=":material/delete:"):
            estado.eliminar(nombre)
            st.rerun()
