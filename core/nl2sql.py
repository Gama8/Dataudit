"""Preguntas en lenguaje natural -> SQL (DuckDB).

Privacidad (Ley 1581 de 2012): al modelo solo se envía el esquema y, si el usuario lo
permite, hasta 3 valores de ejemplo por columna; nunca el conjunto de datos completo.
"""
from __future__ import annotations

import re

import pandas as pd

from core.engine import validar_select

MODELO_POR_DEFECTO = "gpt-4o-mini"

_INSTRUCCIONES = """Eres un asistente que traduce preguntas de auditores a SQL para DuckDB.
Reglas:
- Responde SOLO con una consulta SELECT (o WITH ... SELECT), sin explicaciones ni comentarios.
- Usa exclusivamente las tablas y columnas listadas; escribe los nombres entre comillas dobles.
- Las columnas de texto pueden contener números con formato colombiano (1.234.567,89); si necesitas operar
  con ellas usa TRY_CAST(REPLACE(REPLACE("col", '.', ''), ',', '.') AS DOUBLE).
- Para fechas en texto usa TRY_STRPTIME o TRY_CAST(... AS DATE).
- Si la pregunta pide un listado, limita a 500 filas salvo que se indique otra cantidad.
- Pon alias claros en español a las columnas calculadas."""


def describir_tablas(tablas: dict[str, pd.DataFrame], incluir_ejemplos: bool = True) -> str:
    partes = []
    for nombre, df in tablas.items():
        lineas = [f'Tabla "{nombre}" ({len(df)} filas):']
        for columna in df.columns:
            linea = f'  - "{columna}" ({df[columna].dtype})'
            if incluir_ejemplos:
                ejemplos = df[columna].dropna().astype(str).unique()[:3]
                linea += f" ejemplos: {', '.join(repr(e[:40]) for e in ejemplos)}"
            lineas.append(linea)
        partes.append("\n".join(lineas))
    return "\n\n".join(partes)


def extraer_sql(texto: str) -> str:
    bloque = re.search(r"```(?:sql)?\s*(.*?)```", texto, flags=re.S | re.I)
    return (bloque.group(1) if bloque else texto).strip().rstrip(";").strip()


def generar_sql(cliente, pregunta: str, tablas: dict[str, pd.DataFrame], modelo: str = MODELO_POR_DEFECTO,
                incluir_ejemplos: bool = True) -> str:
    """Devuelve un SELECT validado. `cliente` es un openai.OpenAI ya configurado."""
    respuesta = cliente.chat.completions.create(
        model=modelo,
        temperature=0,
        max_tokens=600,
        messages=[
            {"role": "system", "content": _INSTRUCCIONES},
            {"role": "user", "content": f"{describir_tablas(tablas, incluir_ejemplos)}\n\nPregunta: {pregunta}"},
        ],
    )
    return validar_select(extraer_sql(respuesta.choices[0].message.content or ""))
