"""El agente con Gemini, usando un cliente simulado que devuelve tipos reales del SDK de Google."""
from types import SimpleNamespace

import pytest
from google import genai
from google.genai import types
from streamlit.testing.v1 import AppTest

from core import asistente_gemini
from core.asistente import Contexto
from core.engine import MotorSQL
from tests.test_asistente import pagos  # noqa: F401  (fixture)
from tests.test_ui import RAIZ, estado_demo

STOP = types.FinishReason.STOP


def texto(t, pensamiento=False):
    return types.Part(text=t, thought=pensamiento or None)


def llamada(nombre, argumentos, id_=None):
    return types.Part(function_call=types.FunctionCall(name=nombre, args=argumentos, id=id_),
                      thought_signature=b"firma")


def paso(*partes, motivo=STOP, bloqueo=None):
    """Un paso del modelo, entregado en dos fragmentos como en el streaming real."""
    fragmentos = [list(partes[:1]), list(partes[1:])] if len(partes) > 1 else [list(partes)]
    salida = []
    for i, grupo in enumerate(fragmentos):
        ultimo = i == len(fragmentos) - 1
        salida.append(SimpleNamespace(
            candidates=[SimpleNamespace(content=types.Content(role="model", parts=grupo),
                                        finish_reason=motivo if ultimo else None)],
            usage_metadata=SimpleNamespace(prompt_token_count=1000, cached_content_token_count=400,
                                           candidates_token_count=50, thoughts_token_count=30) if ultimo else None,
            prompt_feedback=SimpleNamespace(block_reason=bloqueo) if bloqueo else None))
    return salida


class GeminiFalso:
    def __init__(self, guion):
        self.guion = list(guion)
        self.solicitudes = []
        self.models = SimpleNamespace(generate_content_stream=self._stream)

    def _stream(self, *, model, contents, config):
        self.solicitudes.append({"model": model, "contents": list(contents), "config": config})
        return iter(self.guion.pop(0))


@pytest.fixture
def contexto(pagos):  # noqa: F811
    motor = MotorSQL({"pagos": pagos.tabla_sql(), "datos": pagos.tabla_sql()})
    return Contexto({"pagos": pagos}, motor, {}, activo="pagos")


def turno(cliente, contexto, pregunta="¿Qué pasa con los pagos?"):
    contenidos = [asistente_gemini.mensaje_usuario(pregunta)]
    return contenidos, list(asistente_gemini.responder(cliente, contenidos, contexto))


def test_configuracion_valida():
    config = asistente_gemini.configuracion("medium")
    nombres = [d.name for d in config.tools[0].function_declarations]
    assert nombres == ["ver_esquema", "consultar_sql", "crear_grafica", "ejecutar_prueba", "seleccionar_muestra",
                       "proponer_hallazgo"]
    assert config.automatic_function_calling.disable is True
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    assert "benford" in config.system_instruction
    # La configuración se serializa como la enviaría el SDK.
    assert config.model_dump(exclude_none=True)["tools"][0]["function_declarations"][1]["parameters_json_schema"]


def test_flujo_con_herramientas(contexto):
    sql = 'SELECT "Razón social" AS tercero, SUM("Valor") AS total FROM pagos GROUP BY 1 ORDER BY 2 DESC LIMIT 3'
    cliente = GeminiFalso([
        paso(texto("Voy a revisar.", pensamiento=True), llamada("consultar_sql", {"sql": sql, "proposito": "Top 3"},
                                                                 "c1")),
        paso(llamada("crear_grafica", {"resultado_id": "R1", "tipo": "barras", "x": "tercero", "y": "total",
                                       "serie": "", "agregacion": "ninguna", "titulo": "Top 3"}),
             llamada("ejecutar_prueba", {"clave": "benford", "conjunto": "pagos", "parametros_json": "{}"})),
        paso(texto("Los tres principales "), texto("concentran el valor.")),
    ])
    contenidos, eventos = turno(cliente, contexto)
    tipos = [e.tipo for e in eventos]
    assert tipos[0] == "razonamiento" and tipos[-1] == "fin" and "error_herramienta" not in tipos
    assert [a for a in contexto.artefactos] == ["R1", "G1", "P1"]
    assert "".join(e.texto for e in eventos if e.tipo == "texto") == "Los tres principales concentran el valor."
    # Historial: usuario, modelo (con firma), respuestas de función, modelo, respuestas, modelo final.
    assert [c.role for c in contenidos] == ["user", "model", "user", "model", "user", "model"]
    assert contenidos[1].parts[1].thought_signature == b"firma"
    respuesta = contenidos[2].parts[0].function_response
    assert respuesta.name == "consultar_sql" and respuesta.id == "c1" and "resultado" in respuesta.response
    assert len(contenidos[4].parts) == 2  # las dos llamadas paralelas se responden juntas
    assert eventos[-1].detalle == {"entrada": 1800, "cache": 1200, "salida": 240, "pasos": 3}
    assert cliente.solicitudes[0]["model"] == "gemini-3.8-flash"


def test_numeros_como_decimales_y_errores(contexto):
    # Gemini puede enviar enteros como 60.0; una consulta inválida vuelve como error para que se corrija.
    cliente = GeminiFalso([
        paso(llamada("seleccionar_muestra", {"conjunto": "pagos", "metodo": "aleatorio", "tamano": 10.0,
                                             "semilla": 7.0, "umbral_clave": 0.0}),
             llamada("consultar_sql", {"sql": "DELETE FROM pagos", "proposito": "x"})),
        paso(texto("Listo.")),
    ])
    contenidos, eventos = turno(cliente, contexto)
    respuestas = contenidos[2].parts
    assert "resultado" in respuestas[0].function_response.response
    assert "error" in respuestas[1].function_response.response
    assert len(contexto.artefactos["M1"].datos.muestra) == 10


def test_bloqueo_de_seguridad(contexto):
    cliente = GeminiFalso([paso(texto(""), motivo=types.FinishReason.SAFETY)])
    contenidos, eventos = turno(cliente, contexto)
    assert eventos[-1].tipo == "error" and "seguridad" in eventos[-1].texto and len(contenidos) == 1


def test_llamada_mal_formada_se_reintenta(contexto):
    cliente = GeminiFalso([
        paso(texto("..."), motivo=types.FinishReason.MALFORMED_FUNCTION_CALL),
        paso(texto("Respuesta final.")),
    ])
    contenidos, eventos = turno(cliente, contexto)
    assert "reinicio" in [e.tipo for e in eventos] and eventos[-1].tipo == "fin"
    assert len(contenidos) == 2


def test_pagina_usa_gemini_con_su_clave(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "clave-prueba")
    monkeypatch.setenv("DATAUDIT_DB", str(tmp_path / "db.sqlite"))
    falso = GeminiFalso([paso(llamada("ver_esquema", {})), paso(texto("Tienes dos tablas cargadas."))])
    monkeypatch.setattr(genai, "Client", lambda **kwargs: falso)
    app = AppTest.from_file(str(RAIZ / "vistas/asistente.py"), default_timeout=60)
    for clave, valor in {**estado_demo(), "activo": "pagos_proveedores_2025"}.items():
        app.session_state[clave] = valor
    app.run()
    assert not app.exception and any("Gemini" in w.value for w in app.warning)
    app.chat_input[0].set_value("¿Qué tablas tengo?").run()
    assert not app.exception, app.exception
    assert any("dos tablas" in m.value for m in app.markdown)
    assert app.session_state["chat_proveedor"] == "gemini"
