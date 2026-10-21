"""Fase 2: almacén, visualizaciones guardables y páginas de asistente, tableros y hallazgos."""
import anthropic
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from core import visual
from core.almacen import Almacen
from tests.test_asistente import ClienteFalso, herramienta, respuesta, texto
from tests.test_ui import RAIZ, estado_demo


class TestAlmacen:
    def test_tableros_y_widgets(self):
        a = Almacen(":memory:")
        t = a.crear_tablero("Pagos")
        ids = [a.agregar_widget(t, f"W{i}", "SELECT 1", {"tipo": "tabla"}) for i in range(3)]
        a.mover_widget(ids[2], -1)
        assert [w["titulo"] for w in a.widgets(t)] == ["W0", "W2", "W1"]
        a.mover_widget(ids[0], -1)  # ya es el primero: no cambia
        assert [w["titulo"] for w in a.widgets(t)] == ["W0", "W2", "W1"]
        a.eliminar_tablero(t)
        assert a.widgets(t) == [] and a.tableros() == []

    def test_hallazgos_codigos_unicos(self):
        a = Almacen(":memory:")
        h1 = a.guardar_hallazgo({"titulo": "Uno", "severidad": "Alta"})
        h2 = a.guardar_hallazgo({"titulo": "Dos"})
        a.eliminar_hallazgo(h1)
        h3 = a.guardar_hallazgo({"titulo": "Tres"})
        assert [a.hallazgo(h)["codigo"] for h in (h2, h3)] == ["H-002", "H-003"]
        a.guardar_hallazgo({"estado": "Cerrado", "responsable": "Tesorería"}, h2)
        assert a.hallazgo(h2)["estado"] == "Cerrado" and a.hallazgo(h2)["titulo"] == "Dos"
        with pytest.raises(ValueError):
            a.guardar_hallazgo({"titulo": "x", "severidad": "Gravísima"})
        with pytest.raises(ValueError):
            a.guardar_hallazgo({"titulo": "  "})

    def test_espacios_separados(self, tmp_path):
        ruta = tmp_path / "db.sqlite"
        Almacen(ruta, "empresa_a").guardar_hallazgo({"titulo": "Solo A"})
        assert Almacen(ruta, "empresa_b").hallazgos() == []
        assert len(Almacen(ruta, "empresa_a").hallazgos()) == 1


class TestVisual:
    datos = pd.DataFrame({"mes": ["2025-01", "2025-01", "2025-02"], "tercero": ["A", "B", "A"],
                          "valor": [10.0, 5.0, 7.0]})

    @pytest.mark.parametrize("tipo", ["barras", "barras_horizontales", "lineas", "dispersion"])
    def test_figuras(self, tipo):
        fig = visual.figura(self.datos, {"tipo": tipo, "x": "mes", "y": "valor", "agregacion": "suma"})
        assert len(fig.data) == 1

    def test_series_y_kpi(self):
        fig = visual.figura(self.datos, {"tipo": "lineas", "x": "mes", "y": "valor", "serie": "tercero",
                                         "agregacion": "suma"})
        assert {t.name for t in fig.data} == {"A", "B"}
        assert visual.valor_kpi(self.datos, {"tipo": "kpi", "y": "valor", "agregacion": "suma"}) == 22.0

    def test_mas_de_ocho_series_se_agrupan(self):
        df = pd.DataFrame({"x": ["a"] * 12, "s": [f"s{i}" for i in range(12)], "y": range(12)})
        fig = visual.figura(df, {"tipo": "barras", "x": "x", "y": "y", "serie": "s", "agregacion": "suma"})
        assert len(fig.data) == 8 and "Otros" in {t.name for t in fig.data}

    def test_columna_inexistente(self):
        with pytest.raises(ValueError, match="no está en el resultado"):
            visual.validar({"tipo": "barras", "x": "mes", "y": "nada"}, self.datos.columns)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAUDIT_DB", str(tmp_path / "dataudit.db"))
    return {**estado_demo(), "activo": "pagos_proveedores_2025"}


def pagina(ruta: str, estado: dict) -> AppTest:
    app = AppTest.from_file(str(RAIZ / ruta), default_timeout=60)
    for clave, valor in estado.items():
        app.session_state[clave] = valor
    return app


def test_asistente_sin_clave_explica_como_configurarla(entorno, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = pagina("vistas/asistente.py", entorno).run()
    assert not app.exception and "console.anthropic.com" in app.info[0].value


def test_asistente_conversacion_completa(entorno, monkeypatch):
    sql = 'SELECT "Razón social" AS tercero, SUM("Valor") AS total FROM datos GROUP BY 1 ORDER BY 2 DESC LIMIT 5'
    falso = ClienteFalso([
        respuesta(herramienta("t1", "consultar_sql", {"sql": sql, "proposito": "Top 5 proveedores"})),
        respuesta(herramienta("t2", "crear_grafica", {"resultado_id": "R1", "tipo": "barras", "x": "tercero",
                                                      "y": "total", "serie": "", "agregacion": "ninguna",
                                                      "titulo": "Top 5"}),
                  herramienta("t3", "proponer_hallazgo", {
                      "titulo": "Concentración en proveedores", "condicion": "5 proveedores concentran el valor",
                      "criterio": "", "causa": "", "efecto": "", "recomendacion": "Revisar contratos",
                      "severidad": "Media", "valor_afectado": 0, "conjunto": "pagos_proveedores_2025",
                      "evidencia_id": "R1"})),
        respuesta(texto("Los 5 principales proveedores concentran la mayor parte de los pagos.")),
    ])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prueba")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: falso)
    app = pagina("vistas/asistente.py", entorno).run()
    assert not app.exception
    app.chat_input[0].set_value("¿Quiénes son los 5 proveedores con más pagos?").run()
    assert not app.exception, app.exception
    assert [a.id for a in app.session_state["chat_artefactos"].values()] == ["R1", "G1", "H1"]
    assert any("concentran" in m.value for m in app.markdown)
    assert app.session_state["chat_uso"]["pasos"] == 3

    # Guardar el borrador en el registro y fijar la gráfica en un tablero nuevo.
    next(b for b in app.button if b.label.startswith("Guardar en el registro")).click().run()
    assert not app.exception, app.exception
    assert app.session_state["chat_artefactos"]["H1"].datos["codigo"] == "H-001"
    next(b for b in app.button if b.key == "fijar_art_G1").click().run()
    assert not app.exception, app.exception

    tableros = pagina("vistas/tableros.py", {**entorno, "version_datos": 0}).run()
    assert not tableros.exception, tableros.exception
    assert any(s.label == "Tablero" for s in tableros.selectbox)
    assert len(tableros.get("plotly_chart")) == 1

    hallazgos = pagina("vistas/hallazgos.py", entorno).run()
    assert not hallazgos.exception, hallazgos.exception
    assert hallazgos.metric[0].value == "1"


def test_registrar_hallazgo_desde_prueba(entorno):
    app = pagina("vistas/pruebas.py", {**entorno, "prueba_activa": "duplicados"}).run()
    next(b for b in app.button if b.label == "Ejecutar prueba").click().run()
    next(b for b in app.button if b.label == "Guardar en el registro").click().run()
    assert not app.exception, app.exception
    hallazgos = pagina("vistas/hallazgos.py", {**entorno, "hallazgo_edicion": 1}).run()
    assert not hallazgos.exception, hallazgos.exception
    assert any("Evidencia adjunta" in e.label for e in hallazgos.expander)


def test_explorar_fija_grafica(entorno):
    app = pagina("vistas/explorar.py", entorno).run()
    app.text_area(key="sql_editor").set_value(
        'SELECT strftime("Fecha", \'%Y-%m\') AS mes, SUM("Valor") AS total FROM datos GROUP BY 1 ORDER BY 1')
    next(b for b in app.button if b.label == "Ejecutar").click().run()
    assert not app.exception, app.exception
    next(b for b in app.button if b.key == "fijar_explorar_grafica").click().run()
    assert not app.exception, app.exception
    tableros = pagina("vistas/tableros.py", entorno).run()
    assert not tableros.exception and len(tableros.get("plotly_chart")) == 1
