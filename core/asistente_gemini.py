"""Proveedor Gemini (Google) para el asistente: mismo agente, mismas herramientas e instrucciones.

Usa generate_content sin estado: Google no guarda la conversación en su servidor; el historial
vive en la sesión de la app. Ojo: en el nivel gratuito, según los términos de Google, lo que se
envía puede usarse para mejorar sus productos; úsalo con datos de demostración o anonimizados.
"""
from __future__ import annotations

from typing import Iterator

from google.genai import types

from core.asistente import HERRAMIENTAS, MAX_PASOS, SISTEMA, Contexto, Evento, ejecutar_llamadas

MODELO_POR_DEFECTO = "gemini-3.8-flash"
_NIVELES = {"low": types.ThinkingLevel.LOW, "medium": types.ThinkingLevel.MEDIUM, "high": types.ThinkingLevel.HIGH,
            "xhigh": types.ThinkingLevel.HIGH, "max": types.ThinkingLevel.HIGH}
_BLOQUEOS = {types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT, types.FinishReason.BLOCKLIST,
             types.FinishReason.SPII, types.FinishReason.RECITATION}
MAX_REINTENTOS = 2


def _herramientas() -> list[types.Tool]:
    declaraciones = []
    for h in HERRAMIENTAS:
        esquema = h["input_schema"]
        declaraciones.append(types.FunctionDeclaration(
            name=h["name"], description=h["description"],
            parameters_json_schema=esquema if esquema["properties"] else None))
    return [types.Tool(function_declarations=declaraciones)]


def configuracion(esfuerzo: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SISTEMA,
        tools=_herramientas(),
        # El bucle es nuestro: las herramientas corren aquí, sobre el motor de solo lectura.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(include_thoughts=True,
                                             thinking_level=_NIVELES.get(esfuerzo, types.ThinkingLevel.HIGH)),
    )


def mensaje_usuario(texto: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=texto)])


def responder(cliente, contenidos: list, contexto: Contexto, modelo: str = MODELO_POR_DEFECTO,
              esfuerzo: str = "high") -> Iterator[Evento]:
    """Ejecuta un turno del agente sobre `contenidos` (que debe terminar en el mensaje del auditor).

    Las partes del modelo se guardan tal como llegan (con sus firmas de pensamiento) y el
    historial solo crece, como exige Gemini para continuar un razonamiento con herramientas.
    """
    uso = {"entrada": 0, "salida": 0, "cache": 0, "pasos": 0}
    config = configuracion(esfuerzo)
    for _ in range(MAX_PASOS):
        reintentos = 0
        while True:
            partes, motivo, bloqueo, metadatos = [], None, None, None
            for fragmento in cliente.models.generate_content_stream(model=modelo, contents=contenidos, config=config):
                metadatos = fragmento.usage_metadata or metadatos
                if fragmento.prompt_feedback and fragmento.prompt_feedback.block_reason:
                    bloqueo = fragmento.prompt_feedback.block_reason
                if not fragmento.candidates:
                    continue
                candidato = fragmento.candidates[0]
                motivo = candidato.finish_reason or motivo
                for parte in (candidato.content.parts or []) if candidato.content else []:
                    partes.append(parte)
                    if parte.text:
                        yield Evento("razonamiento" if parte.thought else "texto", parte.text)
            if motivo == types.FinishReason.MALFORMED_FUNCTION_CALL and reintentos < MAX_REINTENTOS:
                reintentos += 1
                yield Evento("reinicio")
                continue
            break

        uso["pasos"] += 1
        if metadatos:
            cache = metadatos.cached_content_token_count or 0
            uso["entrada"] += (metadatos.prompt_token_count or 0) - cache
            uso["cache"] += cache
            uso["salida"] += (metadatos.candidates_token_count or 0) + (metadatos.thoughts_token_count or 0)

        if bloqueo or motivo in _BLOQUEOS:
            yield Evento("error", "Gemini bloqueó esta solicitud por sus filtros de seguridad. Intenta reformularla.",
                         detalle=uso)
            return
        if motivo == types.FinishReason.MALFORMED_FUNCTION_CALL:
            yield Evento("error", "Gemini no logró formular la llamada a una herramienta. Intenta con una pregunta "
                                  "más concreta.", detalle=uso)
            return
        if not partes:
            yield Evento("fin", detalle=uso)
            return
        contenidos.append(types.Content(role="model", parts=partes))
        llamadas = [p.function_call for p in partes if p.function_call]
        if not llamadas:
            yield Evento("fin", detalle=uso)
            return

        if motivo == types.FinishReason.MAX_TOKENS:
            salidas = [("La llamada quedó incompleta; inténtalo de nuevo.", True)] * len(llamadas)
        else:
            salidas = yield from ejecutar_llamadas([(c.name, dict(c.args or {})) for c in llamadas], contexto)
        respuestas = []
        for llamada, (texto, error) in zip(llamadas, salidas):
            parte = types.Part.from_function_response(name=llamada.name,
                                                      response={"error": texto} if error else {"resultado": texto})
            if llamada.id:
                parte.function_response.id = llamada.id
            respuestas.append(parte)
        contenidos.append(types.Content(role="user", parts=respuestas))
    yield Evento("error", f"Se alcanzó el máximo de {MAX_PASOS} pasos en esta pregunta. Pide que continúe "
                          "o divide la pregunta.", detalle=uso)
