"""Recorre las páginas con los datos demo y verifica que ninguna lance excepciones."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import loader
from core.datasets import ConjuntoDatos
from core.muestreo import METODOS
from core.pruebas import REGISTRO

RAIZ = Path(__file__).resolve().parents[1]
DEMO = RAIZ / "datos_demo"


def estado_demo() -> dict:
    conjuntos = {}
    for archivo in sorted(DEMO.glob("*.*")):
        contenido = archivo.read_bytes()
        nombre = loader.nombre_tabla(archivo.name)
        conjuntos[nombre] = ConjuntoDatos(nombre, archivo.name, loader.huella(contenido),
                                          loader.leer_archivo(archivo.name, contenido))
    return {"conjuntos": conjuntos, "version_datos": 0, "resultados": {}, "auditor": "Auditor de prueba"}


@pytest.fixture(scope="module")
def demo():
    return estado_demo()


def pagina(ruta: str, demo: dict, activo: str = "pagos_proveedores_2025", **extra) -> AppTest:
    app = AppTest.from_file(str(RAIZ / ruta), default_timeout=60)
    for clave, valor in {**demo, "activo": activo, **extra}.items():
        app.session_state[clave] = valor
    return app


def boton(app: AppTest, etiqueta: str):
    return next(b for b in app.button if b.label == etiqueta)


@pytest.mark.parametrize("clave", sorted(REGISTRO))
def test_cada_prueba_se_ejecuta(demo, clave):
    activo = "cartera_clientes_2025" if clave == "antiguedad_saldos" else "pagos_proveedores_2025"
    app = pagina("vistas/pruebas.py", demo, activo, prueba_activa=clave).run()
    assert not app.exception
    boton(app, "Ejecutar prueba").click().run()
    assert not app.exception, app.exception
    assert not app.error, [e.value for e in app.error]
    assert (activo, clave) in app.session_state["resultados"]
    assert any(b.label.startswith("Descargar papel") for b in app.get("download_button"))


@pytest.mark.parametrize("metodo", list(METODOS))
def test_muestreo(demo, metodo):
    app = pagina("vistas/muestreo.py", demo).run()
    assert not app.exception
    selector = next(s for s in app.selectbox if s.label == "Método")
    selector.set_value(metodo)
    boton(app, "Seleccionar muestra").click().run()
    assert not app.exception, app.exception
    assert app.session_state["muestra"][1].muestra.shape[0] > 0


def test_explorar_sql(demo):
    app = pagina("vistas/explorar.py", demo).run()
    assert not app.exception
    app.text_area(key="sql_editor").set_value(
        'SELECT "Razón social", SUM("Valor") AS total FROM datos GROUP BY 1 ORDER BY 2 DESC LIMIT 5')
    boton(app, "Ejecutar").click().run()
    assert not app.exception, app.exception
    assert len(app.session_state["resultado_sql"].datos) == 5


# app.py abre la página de inicio a través de st.navigation (necesaria para st.page_link).
@pytest.mark.parametrize("ruta", ["app.py", "vistas/datos.py"])
def test_paginas_cargan(demo, ruta):
    app = pagina(ruta, demo).run()
    assert not app.exception, app.exception
