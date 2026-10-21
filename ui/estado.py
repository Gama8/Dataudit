"""Estado de la sesión de Streamlit: conjuntos de datos cargados, motor SQL y datos del auditor."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import loader
from core.datasets import ConjuntoDatos
from core.engine import MotorSQL

RAIZ = Path(__file__).resolve().parents[1]
DEMO = RAIZ / "datos_demo"


def inicializar() -> None:
    st.session_state.setdefault("conjuntos", {})
    st.session_state.setdefault("activo", None)
    st.session_state.setdefault("version_datos", 0)
    st.session_state.setdefault("resultados", {})
    st.session_state.setdefault("auditor", "")


def conjuntos() -> dict[str, ConjuntoDatos]:
    return st.session_state["conjuntos"]


def activo() -> ConjuntoDatos | None:
    return conjuntos().get(st.session_state["activo"])


def datos_modificados() -> None:
    """Invalida el motor SQL y los resultados que dependían de los datos anteriores."""
    st.session_state["version_datos"] += 1
    st.session_state["resultados"] = {}


def agregar(conjunto: ConjuntoDatos) -> None:
    conjuntos()[conjunto.nombre] = conjunto
    st.session_state["activo"] = conjunto.nombre
    datos_modificados()


def eliminar(nombre: str) -> None:
    conjuntos().pop(nombre, None)
    if st.session_state["activo"] == nombre:
        st.session_state["activo"] = next(iter(conjuntos()), None)
    datos_modificados()


def nombre_disponible(base: str) -> str:
    nombre, i = base, 2
    while nombre in conjuntos():
        nombre, i = f"{base}_{i}", i + 1
    return nombre


def cargar_demo() -> list[str]:
    cargados = []
    for archivo in sorted(DEMO.glob("*.*")):
        contenido = archivo.read_bytes()
        nombre = loader.nombre_tabla(archivo.name)
        if nombre in conjuntos():
            continue
        agregar(ConjuntoDatos(nombre, archivo.name, loader.huella(contenido),
                              loader.leer_archivo(archivo.name, contenido)))
        cargados.append(nombre)
    pagos = [n for n in cargados if n.startswith("pagos")]
    if pagos:
        st.session_state["activo"] = pagos[0]
    return cargados


def motor() -> MotorSQL:
    """Motor DuckDB de la sesión; se reconstruye cuando cambian los datos o el mapeo."""
    version = st.session_state["version_datos"]
    guardado = st.session_state.get("_motor")
    if guardado is None or guardado[0] != version:
        if guardado is not None:
            guardado[1].cerrar()
        tablas = {nombre: c.tabla_sql() for nombre, c in conjuntos().items()}
        activo_actual = activo()
        if activo_actual is not None and "datos" not in tablas:
            tablas["datos"] = tablas[activo_actual.nombre]
        st.session_state["_motor"] = (version, MotorSQL(tablas))
    return st.session_state["_motor"][1]


def requiere_datos() -> ConjuntoDatos:
    """Detiene la página con una guía si aún no hay datos cargados."""
    conjunto = activo()
    if conjunto is None:
        st.info("Primero carga un archivo o los datos de demostración.", icon=":material/upload_file:")
        st.page_link("vistas/datos.py", label="Ir a Cargar y mapear datos", icon=":material/arrow_forward:")
        st.stop()
    return conjunto


def _activo_cambiado() -> None:
    st.session_state["activo"] = st.session_state["_widget_activo"]
    # La tabla "datos" del explorador SQL apunta al conjunto activo: hay que reconstruir el motor.
    st.session_state["version_datos"] += 1


def _auditor_cambiado() -> None:
    st.session_state["auditor"] = st.session_state["_widget_auditor"]


def barra_lateral() -> None:
    # Los widgets usan claves propias y copian su valor al estado canónico; así las páginas pueden
    # cambiar el conjunto activo sin chocar con un widget ya dibujado.
    st.session_state["_widget_activo"] = st.session_state["activo"]
    st.session_state["_widget_auditor"] = st.session_state["auditor"]
    with st.sidebar:
        if conjuntos():
            st.selectbox("Conjunto de datos activo", list(conjuntos()), key="_widget_activo",
                         format_func=lambda n: f"{n} ({conjuntos()[n].filas:,} filas)".replace(",", "."),
                         on_change=_activo_cambiado)
        st.text_input("Auditor", key="_widget_auditor", placeholder="Tu nombre", on_change=_auditor_cambiado,
                      help="Se registra en los papeles de trabajo exportados.")
