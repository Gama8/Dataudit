"""Asistente de auditoría y BI con Claude (Anthropic).

Es un agente: Claude decide qué herramientas usar (ver el esquema, consultar SQL, graficar,
ejecutar pruebas del catálogo, muestrear, proponer hallazgos), las herramientas corren aquí
sobre el motor de solo lectura, y el bucle continúa hasta que Claude responde.

Privacidad (Ley 1581 de 2012): a Anthropic se envían el esquema, hasta 3 valores de ejemplo
por columna y como máximo FILAS_AL_MODELO filas de cada resultado; nunca el archivo completo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd

from core import muestreo, visual
from core.almacen import SEVERIDADES
from core.datasets import ConjuntoDatos
from core.engine import ConsultaInvalida, MotorSQL
from core.mapping import CAMPOS, normalizar
from core.pruebas import REGISTRO

MODELO_POR_DEFECTO = "claude-opus-5-5"
ESFUERZO_POR_DEFECTO = "high"
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")
# Si el modelo declina una solicitud, la API la reintenta en el modelo que Anthropic recomienda.
BETAS = ["server-side-fallback-2026-07-01"]
MAX_PASOS = 15
FILAS_AL_MODELO = 50
# USD por millón de tokens: entrada, salida, lectura de caché (precios publicados por Anthropic, oct-2026).
PRECIOS = {"claude-opus-5-5": (4.00, 20.00, 0.20), "claude-sonnet-5-5": (2.00, 10.00, 0.20)}


def costo_aproximado(modelo: str, uso: dict) -> float | None:
    """Costo estimado en USD (no incluye la escritura inicial de la caché)."""
    if modelo not in PRECIOS:
        return None
    entrada, salida, cache = PRECIOS[modelo]
    return (uso["entrada"] * entrada + uso["salida"] * salida + uso["cache"] * cache) / 1_000_000


@dataclass
class Artefacto:
    """Resultado visible para el auditor (tabla, gráfica, prueba, muestra o borrador de hallazgo)."""
    id: str
    tipo: str
    titulo: str
    datos: Any = None
    sql: str = ""
    spec: dict | None = None
    conjunto: str = ""


@dataclass
class Evento:
    tipo: str  # texto | razonamiento | reinicio | herramienta | error_herramienta | artefacto | error | fin
    texto: str = ""
    artefacto: Artefacto | None = None
    detalle: dict = field(default_factory=dict)


class ErrorHerramienta(Exception):
    """Error que se devuelve a Claude como tool_result con is_error para que se corrija."""


class Contexto:
    """Lo que las herramientas pueden tocar: los conjuntos cargados, el motor y los artefactos."""

    def __init__(self, conjuntos: dict[str, ConjuntoDatos], motor: MotorSQL, artefactos: dict[str, Artefacto],
                 activo: str | None = None):
        self.conjuntos = conjuntos
        self.motor = motor
        self.artefactos = artefactos
        self.activo = activo

    def nuevo_id(self, prefijo: str) -> str:
        usados = [int(a[len(prefijo):]) for a in self.artefactos if a.startswith(prefijo) and a[len(prefijo):].isdigit()]
        return f"{prefijo}{max(usados, default=0) + 1}"

    def agregar(self, artefacto: Artefacto) -> Artefacto:
        self.artefactos[artefacto.id] = artefacto
        return artefacto


# --- Definición de herramientas ------------------------------------------------------------------

def _herramienta(nombre: str, descripcion: str, propiedades: dict, requeridas: list[str] | None = None) -> dict:
    return {
        "name": nombre,
        "description": descripcion,
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": propiedades,
                         "required": requeridas if requeridas is not None else list(propiedades),
                         "additionalProperties": False},
    }


HERRAMIENTAS = [
    _herramienta(
        "ver_esquema",
        "Lista los conjuntos de datos cargados: nombre de la tabla SQL, archivo, filas, columnas con su tipo, "
        "valores de ejemplo y qué columna corresponde a cada campo de auditoría (fecha, valor, NIT...).",
        {}),
    _herramienta(
        "consultar_sql",
        "Ejecuta una consulta SELECT de solo lectura (dialecto DuckDB) y muestra la tabla completa al auditor. "
        f"Tú recibes las primeras {FILAS_AL_MODELO} filas y un id de resultado (R1, R2...) para graficarlo.",
        {"sql": {"type": "string", "description": "Una sola consulta SELECT o WITH."},
         "proposito": {"type": "string", "description": "Qué responde la consulta, en pocas palabras (título visible)."}}),
    _herramienta(
        "crear_grafica",
        "Dibuja para el auditor un resultado de consultar_sql. Barras para comparar categorías, barras horizontales "
        "si las etiquetas son largas, líneas para evolución en el tiempo, dispersión para relación entre dos números, "
        "kpi para una sola cifra destacada.",
        {"resultado_id": {"type": "string", "description": "Id devuelto por consultar_sql, p. ej. R1."},
         "tipo": {"type": "string", "enum": list(visual.TIPOS)},
         "x": {"type": "string", "description": "Columna del eje X o de categorías (vacío para kpi o tabla)."},
         "y": {"type": "string", "description": "Columna numérica a representar."},
         "serie": {"type": "string", "description": "Columna para separar series por color, o vacío."},
         "agregacion": {"type": "string", "enum": list(visual.AGREGACIONES)},
         "titulo": {"type": "string"}}),
    _herramienta(
        "ejecutar_prueba",
        "Ejecuta una prueba del catálogo de auditoría de Dataudit sobre un conjunto de datos y muestra al auditor "
        "el resultado completo (métricas, gráficas y excepciones). Prefiérela a reescribir la prueba en SQL.",
        {"clave": {"type": "string", "enum": sorted(REGISTRO)},
         "conjunto": {"type": "string", "description": "Nombre del conjunto (tabla SQL)."},
         "parametros_json": {"type": "string",
                             "description": "Objeto JSON con los parámetros a cambiar, p. ej. {\"umbral\": 5000000}. "
                                            "Usa {} para los valores por defecto. Porcentajes como fracción (0.3)."}}),
    _herramienta(
        "seleccionar_muestra",
        "Selecciona una muestra de auditoría (NIA 530) con semilla reproducible y la muestra al auditor.",
        {"conjunto": {"type": "string"},
         "metodo": {"type": "string", "enum": list(muestreo.METODOS)},
         "tamano": {"type": "integer", "description": "Número de elementos a seleccionar."},
         "semilla": {"type": "integer", "description": "0 para generar una semilla nueva."},
         "umbral_clave": {"type": "number",
                          "description": "Partidas de este valor o más se examinan al 100 %. 0 para no usarlo."}}),
    _herramienta(
        "proponer_hallazgo",
        "Presenta al auditor un borrador de hallazgo de auditoría. No lo guarda: el auditor lo revisa y decide.",
        {"titulo": {"type": "string"},
         "condicion": {"type": "string", "description": "Lo que se encontró, con cifras."},
         "criterio": {"type": "string", "description": "Norma, política o práctica que debería cumplirse."},
         "causa": {"type": "string", "description": "Causa probable (indica si es una hipótesis)."},
         "efecto": {"type": "string", "description": "Riesgo o impacto."},
         "recomendacion": {"type": "string"},
         "severidad": {"type": "string", "enum": list(SEVERIDADES)},
         "valor_afectado": {"type": "number", "description": "Valor en pesos involucrado, o 0."},
         "conjunto": {"type": "string"},
         "evidencia_id": {"type": "string",
                          "description": "Id del resultado que respalda el hallazgo (P1, R2...), o vacío."}}),
]


def _catalogo() -> str:
    lineas = []
    for p in REGISTRO.values():
        requeridos = ", ".join(CAMPOS[c].etiqueta for c in p.requeridos) or "campos que elija el auditor"
        parametros = "; ".join(f"{x.clave} ({x.tipo}, por defecto {x.defecto!r}"
                               + (f", opciones {list(x.opciones)}" if x.opciones else "") + ")" for x in p.parametros)
        lineas.append(f"- {p.clave}: {p.nombre} [{p.categoria}; {p.nia}]. {p.objetivo} Requiere: {requeridos}."
                      + (f" Parámetros: {parametros}." if parametros else ""))
    return "\n".join(lineas)


SISTEMA = f"""Eres el asistente de Dataudit, una plataforma de auditoría de datos y BI para pymes colombianas. \
Trabajas junto a un auditor, a menudo sin conocimientos técnicos, sobre los conjuntos de datos que cargó en la sesión.

Cómo trabajar:
- Si aún no conoces las tablas en esta conversación, usa ver_esquema antes de escribir SQL.
- Toda cifra que afirmes debe salir de una herramienta usada en esta conversación. Si algo no se puede calcular con \
los datos cargados, dilo en lugar de suponer.
- Si una consulta falla, lee el error y corrígela.
- Cuando una gráfica aclare el resultado, créala con crear_grafica. Una sola cifra se muestra como kpi, no como \
gráfica de una barra.
- Para lo que ya cubre el catálogo de pruebas, usa ejecutar_prueba: queda documentado con su NIA y parámetros.
- Propón un hallazgo con proponer_hallazgo solo cuando la evidencia lo sustente; el auditor decide si lo registra.
- El auditor ya ve las tablas, gráficas y resultados que generan tus herramientas: no las repitas en el texto; \
interprétalas.
- Responde en español, breve y claro: primero la conclusión y luego el detalle. Pesos colombianos con punto de miles \
($ 1.234.567). Menciona la NIA cuando ayude a decidir.
- Solo tienes acceso a los conjuntos cargados; no tienes internet.

SQL (DuckDB): solo SELECT o WITH. Escribe los nombres de columna entre comillas dobles. Las columnas mapeadas a un \
campo de auditoría ya están convertidas (fechas como TIMESTAMP, valores como DOUBLE); las demás son texto. \
La tabla `datos` es siempre el conjunto activo. Funciones útiles: date_trunc('month', col), strftime(col, '%Y-%m'), \
dayofweek(col), round(x, 2).

Catálogo de pruebas de auditoría:
{_catalogo()}
"""


# --- Implementación de herramientas ---------------------------------------------------------------

def _texto(entrada: dict, clave: str, obligatorio: bool = True) -> str:
    valor = entrada.get(clave, "")
    if not isinstance(valor, str):
        raise ErrorHerramienta(f"«{clave}» debe ser texto.")
    if obligatorio and not valor.strip():
        raise ErrorHerramienta(f"Falta «{clave}».")
    return valor.strip()


def _numero(entrada: dict, clave: str) -> float:
    valor = entrada.get(clave, 0)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorHerramienta(f"«{clave}» debe ser un número.")
    return float(valor)


def _conjunto(contexto: Contexto, nombre: str) -> ConjuntoDatos:
    nombre = contexto.activo if nombre == "datos" and contexto.activo else nombre
    if nombre not in contexto.conjuntos:
        raise ErrorHerramienta(f"No existe el conjunto «{nombre}». Disponibles: {', '.join(contexto.conjuntos)}.")
    return contexto.conjuntos[nombre]


def _csv(df: pd.DataFrame, filas: int = FILAS_AL_MODELO) -> str:
    return df.head(filas).to_csv(index=False, float_format="%.2f", date_format="%Y-%m-%d")


def ver_esquema(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    if not contexto.conjuntos:
        return "No hay conjuntos de datos cargados.", None
    esquema = contexto.motor.esquema()
    partes = []
    for nombre, conjunto in contexto.conjuntos.items():
        tabla = contexto.motor.tablas.get(nombre)
        inverso = {col: CAMPOS[c].etiqueta for c, col in conjunto.mapeo.items() if col}
        lineas = [f'Tabla "{nombre}"' + (" (activa, también disponible como `datos`)" if nombre == contexto.activo else "")
                  + f" · archivo {conjunto.archivo} · {conjunto.filas} filas"]
        for columna, tipo in esquema.get(nombre, []):
            ejemplos = tabla[columna].dropna().astype(str).unique()[:3] if tabla is not None else []
            campo = f" = campo «{inverso[columna]}»" if columna in inverso else ""
            lineas.append(f'  - "{columna}" {tipo}{campo}; ejemplos: {", ".join(repr(e[:40]) for e in ejemplos)}')
        partes.append("\n".join(lineas))
    return "\n\n".join(partes), None


def consultar_sql(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    sql = _texto(entrada, "sql")
    proposito = _texto(entrada, "proposito", obligatorio=False) or "Consulta"
    try:
        resultado = contexto.motor.ejecutar(sql)
    except ConsultaInvalida as error:
        raise ErrorHerramienta(f"La consulta falló: {error}") from error
    artefacto = contexto.agregar(Artefacto(contexto.nuevo_id("R"), "tabla", proposito, resultado.datos, sql=resultado.sql))
    datos = resultado.datos
    columnas = ", ".join(f"{c} ({t})" for c, t in datos.dtypes.astype(str).items())
    cantidad = f"{len(datos)} filas" + (" (recortado: hay más)" if resultado.truncado else "")
    texto = f"Resultado {artefacto.id}: {cantidad}. Columnas: {columnas}."
    if len(datos):
        texto += f"\nPrimeras {min(len(datos), FILAS_AL_MODELO)} filas (CSV):\n{_csv(datos)}"
    return texto, artefacto


def crear_grafica(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    fuente = contexto.artefactos.get(_texto(entrada, "resultado_id"))
    if fuente is None or fuente.tipo != "tabla":
        raise ErrorHerramienta("resultado_id debe ser un resultado de consultar_sql (R1, R2...).")
    spec = {clave: entrada.get(clave, "") for clave in ("tipo", "x", "y", "serie", "agregacion", "titulo")}
    try:
        spec = visual.validar(spec, fuente.datos.columns)
        visual.figura(fuente.datos, spec)  # comprueba que se puede dibujar antes de mostrarla
    except (ValueError, KeyError, TypeError) as error:
        raise ErrorHerramienta(f"No se pudo crear la gráfica: {error}") from error
    artefacto = contexto.agregar(Artefacto(contexto.nuevo_id("G"), "grafica", spec["titulo"] or fuente.titulo,
                                           fuente.datos, sql=fuente.sql, spec=spec))
    return f"Gráfica {artefacto.id} mostrada al auditor.", artefacto


def _campos(valor, conjunto: ConjuntoDatos) -> list[str]:
    """Acepta claves (`monto`), nombres de columna (`Valor`) o etiquetas (`Valor / monto`) y devuelve claves."""
    valores = [valor] if isinstance(valor, str) else list(valor or [])
    por_nombre = {normalizar(col): clave for clave, col in conjunto.mapeo.items() if col}
    por_nombre.update({normalizar(CAMPOS[c].etiqueta): c for c in CAMPOS})
    claves = []
    for v in valores:
        clave = v if v in CAMPOS else por_nombre.get(normalizar(v))
        if clave is None or clave not in conjunto.campos_mapeados:
            raise ValueError(f"«{v}» no es un campo mapeado; usa claves de esta lista: "
                             f"{', '.join(conjunto.campos_mapeados)}")
        claves.append(clave)
    return claves


def _parametros(prueba, texto_json: str, conjunto: ConjuntoDatos) -> dict:
    try:
        recibidos = json.loads(texto_json or "{}")
    except json.JSONDecodeError as error:
        raise ErrorHerramienta(f"parametros_json no es JSON válido: {error}") from error
    if not isinstance(recibidos, dict):
        raise ErrorHerramienta("parametros_json debe ser un objeto JSON.")
    definidos = {p.clave: p for p in prueba.parametros}
    desconocidos = set(recibidos) - set(definidos)
    if desconocidos:
        raise ErrorHerramienta(f"Parámetros desconocidos: {', '.join(desconocidos)}. Válidos: {', '.join(definidos)}.")
    valores = prueba.valores_defecto()
    for clave, valor in recibidos.items():
        p = definidos[clave]
        try:
            if p.tipo == "entero":
                valor = int(valor)
            elif p.tipo == "numero":
                valor = float(valor)
            elif p.tipo == "porcentaje":
                valor = float(valor)
                valor = valor / 100 if valor > 1 else valor
            elif p.tipo == "fecha":
                valor = pd.Timestamp(valor) if valor else None
            elif p.tipo == "opcion" and valor not in p.opciones:
                raise ValueError(f"opciones válidas: {list(p.opciones)}")
            elif p.tipo == "campos":
                valor = _campos(valor, conjunto)
        except (TypeError, ValueError) as error:
            raise ErrorHerramienta(f"Valor inválido para «{clave}»: {error}") from error
        valores[clave] = valor
    return valores


def ejecutar_prueba(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    clave = _texto(entrada, "clave")
    if clave not in REGISTRO:
        raise ErrorHerramienta(f"Prueba desconocida: {clave}.")
    prueba = REGISTRO[clave]
    conjunto = _conjunto(contexto, _texto(entrada, "conjunto"))
    faltan = prueba.faltantes(conjunto.campos_mapeados)
    if faltan:
        raise ErrorHerramienta(f"El conjunto «{conjunto.nombre}» no tiene mapeados: "
                               f"{', '.join(CAMPOS[c].etiqueta for c in faltan)}. Pide al auditor que los mapee.")
    parametros = _parametros(prueba, entrada.get("parametros_json", "{}"), conjunto)
    try:
        resultado = prueba.ejecutar(conjunto.std, parametros)
    except ValueError as error:
        raise ErrorHerramienta(str(error)) from error
    artefacto = contexto.agregar(Artefacto(contexto.nuevo_id("P"), "prueba", prueba.nombre, resultado,
                                           conjunto=conjunto.nombre, spec={"clave": clave, "parametros": parametros}))
    lineas = [f"Prueba {artefacto.id} ({prueba.nombre}, {prueba.nia}) sobre {conjunto.nombre}: {resultado.resumen}",
              "Métricas: " + "; ".join(f"{k}: {v}" for k, v in resultado.metricas.items()),
              f"Excepciones: {len(resultado.hallazgos)} filas."]
    if len(resultado.hallazgos):
        lineas.append(f"Primeras excepciones (CSV):\n{_csv(resultado.hallazgos, 15)}")
    for titulo, tabla in resultado.tablas.items():
        lineas.append(f"Tabla «{titulo}» (primeras filas):\n{_csv(tabla, 10)}")
    return "\n".join(lineas), artefacto


def seleccionar_muestra(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    conjunto = _conjunto(contexto, _texto(entrada, "conjunto"))
    metodo = _texto(entrada, "metodo")
    tamano = int(_numero(entrada, "tamano"))
    semilla = int(_numero(entrada, "semilla")) or muestreo.nueva_semilla()
    umbral = _numero(entrada, "umbral_clave") or None
    if tamano <= 0:
        raise ErrorHerramienta("El tamaño debe ser mayor que cero.")
    try:
        resultado = muestreo.seleccionar(conjunto.std, metodo, tamano, semilla, umbral)
    except ValueError as error:
        raise ErrorHerramienta(str(error)) from error
    artefacto = contexto.agregar(Artefacto(contexto.nuevo_id("M"), "muestra", f"Muestra {muestreo.METODOS[metodo]}",
                                           resultado, conjunto=conjunto.nombre))
    parametros = "; ".join(f"{k}: {v}" for k, v in resultado.parametros.items())
    return f"Muestra {artefacto.id}: {resultado.resumen} Parámetros: {parametros}.", artefacto


def proponer_hallazgo(entrada: dict, contexto: Contexto) -> tuple[str, Artefacto | None]:
    severidad = _texto(entrada, "severidad")
    if severidad not in SEVERIDADES:
        raise ErrorHerramienta(f"Severidad debe ser una de {list(SEVERIDADES)}.")
    borrador = {clave: _texto(entrada, clave, obligatorio=clave in ("titulo", "condicion"))
                for clave in ("titulo", "condicion", "criterio", "causa", "efecto", "recomendacion", "conjunto")}
    borrador["severidad"] = severidad
    borrador["valor_afectado"] = _numero(entrada, "valor_afectado") or None
    evidencia_id = _texto(entrada, "evidencia_id", obligatorio=False)
    evidencia = None
    if evidencia_id:
        fuente = contexto.artefactos.get(evidencia_id)
        if fuente is None:
            raise ErrorHerramienta(f"No existe el resultado {evidencia_id}.")
        evidencia = fuente.datos.hallazgos if fuente.tipo == "prueba" else (
            fuente.datos.muestra if fuente.tipo == "muestra" else fuente.datos)
        borrador["prueba"] = (fuente.spec or {}).get("clave", "") if fuente.tipo == "prueba" else ""
        borrador["conjunto"] = borrador["conjunto"] or fuente.conjunto
    artefacto = contexto.agregar(Artefacto(contexto.nuevo_id("H"), "hallazgo", borrador["titulo"],
                                           {"borrador": borrador, "evidencia": evidencia,
                                            "evidencia_id": evidencia_id},
                                           conjunto=borrador["conjunto"]))
    return f"Borrador {artefacto.id} presentado. El auditor decide si lo guarda en el registro de hallazgos.", artefacto


_IMPLEMENTACIONES = {
    "ver_esquema": ver_esquema,
    "consultar_sql": consultar_sql,
    "crear_grafica": crear_grafica,
    "ejecutar_prueba": ejecutar_prueba,
    "seleccionar_muestra": seleccionar_muestra,
    "proponer_hallazgo": proponer_hallazgo,
}


def ejecutar_herramienta(nombre: str, entrada: Any, contexto: Contexto) -> tuple[str, Artefacto | None]:
    if nombre not in _IMPLEMENTACIONES:
        raise ErrorHerramienta(f"Herramienta desconocida: {nombre}.")
    if not isinstance(entrada, dict):
        raise ErrorHerramienta("La entrada de la herramienta debe ser un objeto JSON.")
    return _IMPLEMENTACIONES[nombre](entrada, contexto)


def ejecutar_llamadas(llamadas: list[tuple[str, Any]], contexto: Contexto):
    """Ejecuta las llamadas (nombre, entrada) de un paso, emitiendo eventos para la interfaz.

    Generador común a todos los proveedores: produce Evento y retorna [(texto, es_error), ...]
    en el mismo orden de las llamadas (úsalo con `resultados = yield from ejecutar_llamadas(...)`).
    """
    resultados = []
    for nombre, entrada in llamadas:
        yield Evento("herramienta", nombre, detalle=entrada if isinstance(entrada, dict) else {})
        try:
            texto, artefacto = ejecutar_herramienta(nombre, entrada, contexto)
        except ErrorHerramienta as error:
            yield Evento("error_herramienta", str(error), detalle={"herramienta": nombre})
            resultados.append((str(error), True))
            continue
        if artefacto is not None:
            yield Evento("artefacto", artefacto=artefacto)
        resultados.append((texto, False))
    return resultados


# --- Bucle del agente --------------------------------------------------------------------------------

def _para_historial(bloques: list) -> list:
    """Tras un cambio de modelo a mitad de respuesta, descarta los bloques internos previos al corte."""
    tipos = [b.type for b in bloques]
    if "fallback" not in tipos:
        return list(bloques)
    corte = max(i for i, t in enumerate(tipos) if t == "fallback")
    internos = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(bloques) if i >= corte or b.type not in internos]


def mensaje_usuario(texto: str) -> dict:
    return {"role": "user", "content": texto}


def responder(cliente, mensajes: list, contexto: Contexto, modelo: str = MODELO_POR_DEFECTO,
              esfuerzo: str = ESFUERZO_POR_DEFECTO) -> Iterator[Evento]:
    """Ejecuta un turno del agente sobre `mensajes` (que debe terminar en el mensaje del auditor).

    El historial solo crece (nunca se editan turnos anteriores) y siempre queda válido para el
    siguiente turno, aunque ocurra un error a mitad del camino.
    """
    uso = {"entrada": 0, "salida": 0, "cache": 0, "pasos": 0}
    for _ in range(MAX_PASOS):
        reintentos = 0
        while True:
            try:
                with cliente.beta.messages.stream(
                    model=modelo,
                    max_tokens=64000,
                    system=SISTEMA,
                    tools=HERRAMIENTAS,
                    messages=mensajes,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": esfuerzo},
                    cache_control={"type": "ephemeral"},
                    betas=BETAS,
                    fallbacks="default",
                ) as stream:
                    for evento in stream:
                        if evento.type == "text":
                            yield Evento("texto", evento.text)
                        elif evento.type == "thinking":
                            yield Evento("razonamiento", evento.thinking)
                    respuesta = stream.get_final_message()
                break
            except ValueError:
                # JSON de herramienta que el SDK no pudo interpretar: se repite el paso (acotado).
                reintentos += 1
                if reintentos > 2:
                    raise
                yield Evento("reinicio")
        uso["pasos"] += 1
        uso["entrada"] += respuesta.usage.input_tokens or 0
        uso["salida"] += respuesta.usage.output_tokens or 0
        uso["cache"] += getattr(respuesta.usage, "cache_read_input_tokens", 0) or 0

        if respuesta.stop_reason == "refusal":
            yield Evento("error", "Claude no puede ayudar con esta solicitud. Intenta reformularla.", detalle=uso)
            return
        mensajes.append({"role": "assistant", "content": _para_historial(respuesta.content)})
        if respuesta.stop_reason == "pause_turn":
            continue
        usos = [b for b in respuesta.content if b.type == "tool_use"]
        if not usos:
            yield Evento("fin", detalle=uso)
            return

        if respuesta.stop_reason == "max_tokens":
            # La entrada quedó cortada: no se ejecuta, pero se responde para mantener el historial válido.
            salidas = [("La entrada de la herramienta quedó incompleta; inténtalo de nuevo.", True)] * len(usos)
        else:
            salidas = yield from ejecutar_llamadas([(b.name, b.input) for b in usos], contexto)
        mensajes.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": texto, **({"is_error": True} if error else {})}
            for b, (texto, error) in zip(usos, salidas)]})
    yield Evento("error", f"Se alcanzó el máximo de {MAX_PASOS} pasos en esta pregunta. Pide que continúe "
                          "o divide la pregunta.", detalle=uso)
