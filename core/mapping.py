"""Mapeo de columnas del cliente a campos semánticos de auditoría.

El auditor indica una sola vez qué columna es la fecha, el monto, el NIT, etc.
A partir de ahí cualquier prueba del catálogo puede ejecutarse sin escribir SQL.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Campo:
    clave: str
    etiqueta: str
    tipo: str  # "fecha" | "numero" | "texto"
    ayuda: str
    sinonimos: tuple[str, ...]


CAMPOS: dict[str, Campo] = {c.clave: c for c in (
    Campo("fecha", "Fecha", "fecha", "Fecha del documento, transacción o asiento.",
          ("fecha", "fecha_documento", "fecha_doc", "fecha_factura", "fecha_contable", "fecha_pago",
           "fecha_elaboracion", "fec", "date")),
    Campo("monto", "Valor / monto", "numero", "Importe de la transacción en pesos.",
          ("monto", "valor", "valor_total", "total", "importe", "valor_pagado", "valor_neto", "saldo",
           "ventas", "amount")),
    Campo("tercero", "Tercero (nombre)", "texto", "Cliente, proveedor, empleado o beneficiario.",
          ("tercero", "nombre_tercero", "razon_social", "proveedor", "cliente", "beneficiario", "nombre",
           "empleado")),
    Campo("nit", "NIT / identificación", "texto", "NIT o cédula del tercero (con o sin dígito de verificación).",
          ("nit", "nit_tercero", "identificacion", "cedula", "num_identificacion", "documento_tercero", "cc_nit")),
    Campo("dv", "Dígito de verificación", "texto", "Solo si el DV viene en una columna aparte del NIT.",
          ("dv", "digito_verificacion", "digito")),
    Campo("documento", "Número de documento", "texto", "Número de factura, comprobante, consecutivo o egreso.",
          ("numero_documento", "num_documento", "no_documento", "documento", "factura", "numero_factura",
           "no_factura", "comprobante", "consecutivo", "numero", "egreso", "folio")),
    Campo("cuenta", "Cuenta contable (PUC)", "texto", "Código de la cuenta según el Plan Único de Cuentas.",
          ("cuenta", "cuenta_contable", "codigo_cuenta", "puc", "cod_cuenta")),
    Campo("descripcion", "Descripción / concepto", "texto", "Detalle o concepto del movimiento.",
          ("descripcion", "concepto", "detalle", "observaciones", "glosa")),
    Campo("usuario", "Usuario que registró", "texto", "Usuario del sistema que creó o aprobó el registro.",
          ("usuario", "elaborado_por", "creado_por", "registrado_por", "user")),
    Campo("fecha_vencimiento", "Fecha de vencimiento", "fecha", "Vencimiento de la factura (cartera o cuentas por pagar).",
          ("fecha_vencimiento", "vencimiento", "fecha_vence", "fecha_venc", "due_date")),
)}

_RE_MILES_PUNTO = re.compile(r"^\d{1,3}(\.\d{3})+$")
_RE_MILES_COMA = re.compile(r"^\d{1,3}(,\d{3})+$")


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-z]+", "_", texto.lower()).strip("_")


def sugerir_mapeo(columnas) -> dict[str, str | None]:
    """Propone una columna para cada campo. Primero coincidencias exactas, luego por palabra contenida."""
    normalizadas = {col: normalizar(col) for col in columnas}
    # Los sinónimos más largos van primero para que "fecha_vencimiento" no termine como "fecha".
    pares = sorted(((s, c.clave) for c in CAMPOS.values() for s in c.sinonimos), key=lambda p: -len(p[0]))
    asignado: dict[str, str] = {}
    usadas: set[str] = set()
    for exacto in (True, False):
        for sinonimo, clave in pares:
            if clave in asignado:
                continue
            for col, norm in normalizadas.items():
                if col in usadas:
                    continue
                coincide = norm == sinonimo if exacto else f"_{sinonimo}_" in f"_{norm}_"
                if coincide:
                    asignado[clave] = col
                    usadas.add(col)
                    break
    return {clave: asignado.get(clave) for clave in CAMPOS}


def _texto_a_numero(valor) -> float:
    texto = str(valor).strip()
    negativo = texto.startswith("-") or texto.endswith("-") or (texto.startswith("(") and texto.endswith(")"))
    texto = re.sub(r"[^\d.,]", "", texto)
    if not texto:
        return np.nan
    if "," in texto and "." in texto:
        # El separador que aparece de último es el decimal: 1.234.567,89 o 1,234,567.89
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", "") if _RE_MILES_COMA.match(texto) else texto.replace(",", ".")
    elif _RE_MILES_PUNTO.match(texto):
        texto = texto.replace(".", "")
    try:
        numero = float(texto)
    except ValueError:
        return np.nan
    return -numero if negativo else numero


def a_numero(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)
    valores = serie.dropna().unique()
    conversion = {v: _texto_a_numero(v) for v in valores}
    return serie.map(conversion).astype(float)


def a_fecha(serie: pd.Series) -> pd.Series:
    """Prueba varios formatos (ISO, dd/mm/aaaa, ...) y se queda con el que convierte más valores."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie.dt.tz_localize(None) if getattr(serie.dt, "tz", None) else serie
    texto = serie.astype("string").str.strip()
    formatos = ("ISO8601", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y%m%d")
    candidatos = [pd.to_datetime(texto, format=f, errors="coerce") for f in formatos]
    candidatos.append(pd.to_datetime(texto, format="mixed", dayfirst=True, errors="coerce"))
    return max(candidatos, key=lambda c: c.notna().sum())


def a_texto(serie: pd.Series) -> pd.Series:
    texto = serie.astype("string").str.strip()
    return texto.mask(texto == "")


_CONVERSORES = {"fecha": a_fecha, "numero": a_numero, "texto": a_texto}


def aplicar_mapeo(df: pd.DataFrame, mapeo: dict[str, str | None]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (datos estandarizados, reporte de conversión).

    Los datos estandarizados conservan el índice del original y agregan `fila`,
    el número de fila en el archivo (encabezado = fila 1), para rastrear cada hallazgo.
    """
    std = pd.DataFrame(index=df.index)
    std["fila"] = df.index + 2
    reporte = []
    for clave, columna in mapeo.items():
        if not columna or clave not in CAMPOS:
            continue
        campo = CAMPOS[clave]
        origen = df[columna]
        convertida = _CONVERSORES[campo.tipo](origen)
        std[clave] = convertida
        con_valor = int(a_texto(origen.astype("string")).notna().sum())
        convertidos = int(convertida.notna().sum())
        reporte.append({
            "Campo": campo.etiqueta,
            "Columna del archivo": columna,
            "Con valor": con_valor,
            "Convertidos": convertidos,
            "No convertidos": con_valor - convertidos,
        })
    return std, pd.DataFrame(reporte)
