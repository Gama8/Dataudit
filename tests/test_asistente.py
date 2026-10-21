"""El bucle del agente con un cliente simulado (sin llamadas reales a la API)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import asistente, loader
from core.asistente import Contexto, responder
from core.datasets import ConjuntoDatos
from core.engine import MotorSQL

DEMO = Path(__file__).resolve().parents[1] / "datos_demo"


def texto(t):
    return SimpleNamespace(type="text", text=t)


def herramienta(id_, nombre, entrada):
    return SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)


def respuesta(*bloques, stop="end_turn"):
    if stop == "end_turn" and any(b.type == "tool_use" for b in bloques):
        stop = "tool_use"
    return SimpleNamespace(content=list(bloques), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=50))


class _Stream:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for bloque in self.final.content:
            if bloque.type == "text":
                yield SimpleNamespace(type="text", text=bloque.text)

    def get_final_message(self):
        return self.final


class ClienteFalso:
    """Devuelve respuestas guionizadas y registra cada solicitud."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.solicitudes = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        # Copia del historial tal como se envió (el agente lo sigue extendiendo después).
        self.solicitudes.append({**kwargs, "messages": list(kwargs["messages"])})
        return _Stream(self.guion.pop(0))


@pytest.fixture(scope="module")
def pagos():
    contenido = (DEMO / "pagos_proveedores_2025.csv").read_bytes()
    return ConjuntoDatos("pagos", "pagos.csv", loader.huella(contenido),
                         loader.leer_archivo("pagos.csv", contenido))


@pytest.fixture
def contexto(pagos):
    motor = MotorSQL({"pagos": pagos.tabla_sql(), "datos": pagos.tabla_sql()})
    return Contexto({"pagos": pagos}, motor, {}, activo="pagos")


def turno(cliente, contexto, pregunta="¿Qué pasa con los pagos?"):
    mensajes = [{"role": "user", "content": pregunta}]
    eventos = list(responder(cliente, mensajes, contexto))
    return mensajes, eventos


def test_flujo_completo(contexto):
    sql = ('SELECT "Razón social" AS tercero, SUM("Valor") AS total FROM pagos '
           'GROUP BY 1 ORDER BY 2 DESC LIMIT 5')
    cliente = ClienteFalso([
        respuesta(texto("Reviso el esquema."), herramienta("t1", "ver_esquema", {})),
        respuesta(herramienta("t2", "consultar_sql", {"sql": sql, "proposito": "Top 5 proveedores"})),
        respuesta(herramienta("t3", "crear_grafica", {"resultado_id": "R1", "tipo": "barras_horizontales",
                                                      "x": "tercero", "y": "total", "serie": "",
                                                      "agregacion": "ninguna", "titulo": "Top 5"})),
        respuesta(herramienta("t4", "ejecutar_prueba", {"clave": "duplicados", "conjunto": "pagos",
                                                        "parametros_json": "{}"}),
                  herramienta("t5", "proponer_hallazgo", {
                      "titulo": "Pagos duplicados", "condicion": "6 grupos duplicados", "criterio": "Control de pagos",
                      "causa": "", "efecto": "Pérdida", "recomendacion": "Recuperar", "severidad": "Alta",
                      "valor_afectado": 1000000, "conjunto": "pagos", "evidencia_id": "P1"})),
        respuesta(texto("Hay 6 grupos de pagos duplicados.")),
    ])
    mensajes, eventos = turno(cliente, contexto)

    tipos = [e.tipo for e in eventos]
    assert tipos[-1] == "fin" and "error" not in tipos and "error_herramienta" not in tipos
    assert [a.id for a in contexto.artefactos.values()] == ["R1", "G1", "P1", "H1"]
    assert len(contexto.artefactos["R1"].datos) == 5
    assert contexto.artefactos["H1"].datos["borrador"]["prueba"] == "duplicados"
    assert len(contexto.artefactos["H1"].datos["evidencia"]) > 0
    # Historial válido: alterna usuario/asistente y cada tool_use tiene su tool_result en el siguiente turno.
    assert [m["role"] for m in mensajes] == ["user"] + ["assistant", "user"] * 4 + ["assistant"]
    for i, m in enumerate(mensajes):
        if m["role"] == "assistant":
            usados = {b.id for b in m["content"] if b.type == "tool_use"}
            if usados:
                respondidos = {r["tool_use_id"] for r in mensajes[i + 1]["content"]}
                assert usados == respondidos
    # Las dos herramientas paralelas se responden en un único mensaje.
    assert len(mensajes[-2]["content"]) == 2
    # El esquema enviado a Claude incluye el mapeo y la tabla activa.
    esquema = mensajes[2]["content"][0]["content"]
    assert 'Tabla "pagos" (activa' in esquema and "campo «Valor / monto»" in esquema


def test_parametros_de_la_solicitud(contexto):
    cliente = ClienteFalso([respuesta(texto("Hola"))])
    turno(cliente, contexto)
    s = cliente.solicitudes[0]
    assert s["model"] == "claude-opus-5-5" and s["fallbacks"] == "default"
    assert s["betas"] == ["server-side-fallback-2026-07-01"]
    assert s["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert s["output_config"] == {"effort": "high"} and s["cache_control"] == {"type": "ephemeral"}
    assert [h["name"] for h in s["tools"]] == ["ver_esquema", "consultar_sql", "crear_grafica", "ejecutar_prueba",
                                               "seleccionar_muestra", "proponer_hallazgo"]
    json.dumps(s["tools"])  # serializable
    assert "benford" in s["system"] and "duplicados" in s["system"]


def test_errores_se_devuelven_a_claude(contexto):
    cliente = ClienteFalso([
        respuesta(herramienta("t1", "consultar_sql", {"sql": "DROP TABLE pagos", "proposito": "x"}),
                  herramienta("t2", "consultar_sql", {"sql": "SELECT columna_inexistente FROM pagos", "proposito": "y"}),
                  herramienta("t3", "crear_grafica", {"resultado_id": "R9", "tipo": "barras", "x": "a", "y": "b",
                                                      "serie": "", "agregacion": "suma", "titulo": ""}),
                  herramienta("t4", "ejecutar_prueba", {"clave": "benford", "conjunto": "pagos",
                                                        "parametros_json": '{"inventado": 1}'})),
        respuesta(texto("Corrijo.")),
    ])
    mensajes, eventos = turno(cliente, contexto)
    resultados = mensajes[2]["content"]
    assert all(r.get("is_error") for r in resultados)
    assert "solo lectura" in resultados[0]["content"].lower() or "lectura" in resultados[0]["content"]
    assert "inventado" in resultados[3]["content"]
    assert sum(e.tipo == "error_herramienta" for e in eventos) == 4 and eventos[-1].tipo == "fin"


def test_rechazo_no_ensucia_el_historial(contexto):
    cliente = ClienteFalso([respuesta(stop="refusal")])
    mensajes, eventos = turno(cliente, contexto)
    assert eventos[-1].tipo == "error" and mensajes == [{"role": "user", "content": "¿Qué pasa con los pagos?"}]


def test_limite_de_pasos(contexto, monkeypatch):
    monkeypatch.setattr(asistente, "MAX_PASOS", 3)
    cliente = ClienteFalso([respuesta(herramienta(f"t{i}", "ver_esquema", {})) for i in range(3)])
    mensajes, eventos = turno(cliente, contexto)
    assert eventos[-1].tipo == "error" and "máximo" in eventos[-1].texto
    assert mensajes[-1]["role"] == "user"  # termina con tool_results: el siguiente turno sigue siendo válido


def test_entrada_cortada_por_max_tokens(contexto):
    cliente = ClienteFalso([
        respuesta(herramienta("t1", "consultar_sql", {"sql": "SELECT"}), stop="max_tokens"),
        respuesta(texto("Listo.")),
    ])
    mensajes, eventos = turno(cliente, contexto)
    assert mensajes[2]["content"][0]["is_error"] and not contexto.artefactos


def test_fallback_descarta_bloques_internos_previos():
    bloques = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text"), SimpleNamespace(type="tool_use"),
               SimpleNamespace(type="fallback"), SimpleNamespace(type="thinking"), SimpleNamespace(type="text")]
    assert [b.type for b in asistente._para_historial(bloques)] == ["text", "fallback", "thinking", "text"]
