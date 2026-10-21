"""Utilidades específicas de Colombia: NIT (DIAN) y festivos nacionales."""
from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

# Pesos oficiales de la DIAN para el dígito de verificación, aplicados de derecha a izquierda.
_PESOS_NIT = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)

ESTADO_VALIDO = "Válido"
ESTADO_DV_INCORRECTO = "DV incorrecto"
ESTADO_SIN_DV = "Sin dígito de verificación"
ESTADO_FORMATO = "Formato inválido"
ESTADO_VACIO = "Vacío"


def calcular_dv(nit: str | int) -> int:
    """Calcula el dígito de verificación de un NIT según el algoritmo módulo 11 de la DIAN."""
    digitos = re.sub(r"\D", "", str(nit))
    if not digitos or len(digitos) > len(_PESOS_NIT):
        raise ValueError(f"NIT inválido: {nit!r}")
    suma = sum(int(d) * p for d, p in zip(reversed(digitos), _PESOS_NIT))
    residuo = suma % 11
    return residuo if residuo in (0, 1) else 11 - residuo


def separar_nit(valor, dv=None) -> tuple[str | None, int | None]:
    """Devuelve (número, dv) a partir de '800197268-4', '800.197.268-4' o número + DV en otra columna."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None, None
    texto = str(valor).strip()
    if isinstance(valor, float) and valor.is_integer():
        texto = str(int(valor))
    if "-" in texto:
        numero, _, digito = texto.rpartition("-")
        numero = re.sub(r"\D", "", numero)
        digito = re.sub(r"\D", "", digito)
        return (numero or None), (int(digito) if len(digito) == 1 else None)
    numero = re.sub(r"\D", "", texto)
    digito = None
    if dv is not None and not pd.isna(dv):
        digito_txt = re.sub(r"\D", "", str(int(dv) if isinstance(dv, float) else dv))
        digito = int(digito_txt) if len(digito_txt) == 1 else None
    return (numero or None), digito


def validar_nit(valor, dv=None) -> str:
    """Clasifica un NIT en uno de los estados ESTADO_*."""
    numero, digito = separar_nit(valor, dv)
    if numero is None:
        return ESTADO_VACIO
    if not 5 <= len(numero) <= len(_PESOS_NIT):
        return ESTADO_FORMATO
    if digito is None:
        return ESTADO_SIN_DV
    return ESTADO_VALIDO if calcular_dv(numero) == digito else ESTADO_DV_INCORRECTO


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano de Meeus/Jones/Butcher)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _lunes_siguiente(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


@lru_cache(maxsize=None)
def festivos(anio: int) -> dict[date, str]:
    """Festivos nacionales de Colombia para un año (incluye traslados de la Ley 51 de 1983)."""
    fijos = {
        date(anio, 1, 1): "Año Nuevo",
        date(anio, 5, 1): "Día del Trabajo",
        date(anio, 7, 20): "Día de la Independencia",
        date(anio, 8, 7): "Batalla de Boyacá",
        date(anio, 12, 8): "Inmaculada Concepción",
        date(anio, 12, 25): "Navidad",
    }
    trasladables = {
        date(anio, 1, 6): "Reyes Magos",
        date(anio, 3, 19): "San José",
        date(anio, 6, 29): "San Pedro y San Pablo",
        date(anio, 8, 15): "Asunción de la Virgen",
        date(anio, 10, 12): "Día de la Raza",
        date(anio, 11, 1): "Todos los Santos",
        date(anio, 11, 11): "Independencia de Cartagena",
    }
    pascua = _pascua(anio)
    religiosos = {
        pascua - timedelta(days=3): "Jueves Santo",
        pascua - timedelta(days=2): "Viernes Santo",
        pascua + timedelta(days=43): "Ascensión del Señor",
        pascua + timedelta(days=64): "Corpus Christi",
        pascua + timedelta(days=71): "Sagrado Corazón",
    }
    resultado: dict[date, str] = {}
    # Dos festivos pueden caer el mismo lunes (p. ej. 30/06/2025); se conservan ambos nombres.
    for d, nombre in [*fijos.items(), *((_lunes_siguiente(d), n) for d, n in trasladables.items()),
                      *religiosos.items()]:
        resultado[d] = f"{resultado[d]} / {nombre}" if d in resultado else nombre
    return dict(sorted(resultado.items()))


def nombre_festivo(d) -> str | None:
    """Nombre del festivo si la fecha lo es; None en otro caso."""
    if d is None or pd.isna(d):
        return None
    d = pd.Timestamp(d).date()
    return festivos(d.year).get(d)
