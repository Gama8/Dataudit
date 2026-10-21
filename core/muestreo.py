"""Muestreo de auditoría (NIA 530).

Toda selección usa una semilla explícita: con el mismo archivo, parámetros y semilla
se obtiene exactamente la misma muestra (reejecución por un revisor).
"""
from __future__ import annotations

import math
import secrets
from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.graficas import entero, pesos, porcentaje

METODOS = {
    "aleatorio": "Aleatorio simple",
    "sistematico": "Sistemático",
    "mus": "Unidad monetaria (MUS)",
    "estratificado": "Estratificado por valor",
}
CONFIANZAS = (0.90, 0.95, 0.99)
# Factores de confiabilidad (Poisson, cero errores) y de expansión usados en MUS (guía AICPA).
_FACTOR_CONFIABILIDAD = {0.90: 2.31, 0.95: 3.00, 0.99: 4.61}
_FACTOR_EXPANSION = {0.90: 1.5, 0.95: 1.6, 0.99: 1.9}


def nueva_semilla() -> int:
    return secrets.randbelow(1_000_000)


def _binomial_acumulada(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def tamano_atributos(confianza: float, tasa_tolerable: float, tasa_esperada: float = 0.0) -> int:
    """Tamaño para pruebas de controles: menor n tal que, con las desviaciones esperadas,
    la probabilidad de que la tasa real supere la tolerable sea a lo sumo 1 - confianza (binomial)."""
    if not 0 < tasa_tolerable < 1:
        raise ValueError("La tasa tolerable debe estar entre 0 % y 100 %.")
    if tasa_esperada >= tasa_tolerable:
        raise ValueError("La tasa esperada de desviación debe ser menor que la tolerable.")
    riesgo = 1 - confianza
    for n in range(1, 5001):
        k = math.ceil(n * tasa_esperada - 1e-9)
        if _binomial_acumulada(k, n, tasa_tolerable) <= riesgo:
            return n
    raise ValueError("El tamaño de muestra supera 5.000 elementos; revise los parámetros.")


def tamano_mus(valor_libros: float, error_tolerable: float, error_esperado: float, confianza: float) -> tuple[int, float]:
    """(tamaño, intervalo) para muestreo por unidad monetaria."""
    if valor_libros <= 0:
        raise ValueError("El valor en libros debe ser positivo.")
    denominador = error_tolerable - error_esperado * _FACTOR_EXPANSION[confianza]
    if denominador <= 0:
        raise ValueError("El error esperado es demasiado alto frente al error tolerable.")
    n = max(1, math.ceil(valor_libros * _FACTOR_CONFIABILIDAD[confianza] / denominador))
    return n, valor_libros / n


@dataclass
class ResultadoMuestra:
    muestra: pd.DataFrame
    parametros: dict[str, str]
    resumen: str


def seleccionar(std: pd.DataFrame, metodo: str, n: int, semilla: int, umbral_clave: float | None = None,
                estratos: int = 4) -> ResultadoMuestra:
    """Selecciona la muestra. Las partidas clave (monto >= umbral) se incluyen al 100 % fuera del muestreo."""
    if metodo not in METODOS:
        raise ValueError(f"Método desconocido: {metodo}")
    if metodo in ("mus", "estratificado") or umbral_clave:
        if "monto" not in std:
            raise ValueError("Este método requiere el campo «Valor / monto» mapeado.")
    rng = np.random.default_rng(semilla)
    poblacion = std.sort_values("fila")
    clave = poblacion.iloc[0:0]
    if umbral_clave:
        es_clave = poblacion["monto"].abs() >= umbral_clave
        clave, poblacion = poblacion[es_clave], poblacion[~es_clave]
    notas = []
    if metodo == "mus":
        excluidas = poblacion[~(poblacion["monto"] > 0)]
        poblacion = poblacion[poblacion["monto"] > 0]
        if len(excluidas):
            notas.append(f"{entero(len(excluidas))} partidas con valor cero, negativo o vacío quedan fuera del MUS; "
                         "evalúelas por separado.")
    elif metodo == "estratificado" and poblacion["monto"].isna().any():
        notas.append(f"{entero(int(poblacion['monto'].isna().sum()))} partidas sin valor quedan fuera de los estratos.")
        poblacion = poblacion.dropna(subset=["monto"])
    n = int(min(n, len(poblacion)))
    if n <= 0 and clave.empty:
        raise ValueError("No hay elementos para seleccionar.")

    seleccion = poblacion.iloc[0:0].copy()
    if n > 0:
        if metodo == "aleatorio":
            posiciones = np.sort(rng.choice(len(poblacion), size=n, replace=False))
            seleccion = poblacion.iloc[posiciones].copy()
        elif metodo == "sistematico":
            intervalo = len(poblacion) / n
            inicio = rng.uniform(0, intervalo)
            posiciones = np.floor(inicio + np.arange(n) * intervalo).astype(int)
            seleccion = poblacion.iloc[posiciones].copy()
            notas.append(f"Intervalo de {intervalo:.2f} elementos con inicio aleatorio en {inicio:.2f}.")
        elif metodo == "mus":
            total = poblacion["monto"].sum()
            intervalo = total / n
            inicio = rng.uniform(0, intervalo)
            puntos = inicio + np.arange(n) * intervalo
            posiciones = np.searchsorted(poblacion["monto"].cumsum().to_numpy(), puntos, side="left")
            aciertos = pd.Series(posiciones).value_counts().sort_index()
            seleccion = poblacion.iloc[aciertos.index].copy()
            seleccion["unidades_seleccionadas"] = aciertos.to_numpy()
            notas.append(f"Intervalo monetario de {pesos(intervalo)} con inicio aleatorio en {pesos(inicio)}; "
                         f"{entero(len(seleccion))} partidas distintas para {entero(n)} unidades monetarias.")
        else:  # estratificado
            estrato = pd.qcut(poblacion["monto"].rank(method="first"), q=min(estratos, n), labels=False) + 1
            valores = poblacion["monto"].abs().groupby(estrato).sum()
            tamanos = estrato.value_counts().sort_index()
            asignacion = _asignar_proporcional(n, valores, tamanos)
            partes = []
            for e, cantidad in asignacion.items():
                miembros = poblacion[estrato == e]
                posiciones = np.sort(rng.choice(len(miembros), size=cantidad, replace=False))
                partes.append(miembros.iloc[posiciones].assign(estrato=e))
            seleccion = pd.concat(partes)
            rangos = poblacion["monto"].groupby(estrato).agg(["min", "max"])
            notas.append("Estratos por valor: " + "; ".join(
                f"E{e}: {pesos(r['min'])} a {pesos(r['max'])} ({asignacion[e]} de {tamanos[e]})"
                for e, r in rangos.iterrows()))
        seleccion.insert(1, "motivo", "Muestra")
    if len(clave):
        clave = clave.copy()
        clave.insert(1, "motivo", "Partida clave (100 %)")
        notas.insert(0, f"{entero(len(clave))} partidas clave de {pesos(umbral_clave)} o más se examinan al 100 %.")
    muestra = pd.concat([clave, seleccion]).sort_values("fila")

    parametros = {
        "Método": METODOS[metodo],
        "Semilla": str(semilla),
        "Tamaño solicitado": entero(n),
        "Partidas clave desde": pesos(umbral_clave) if umbral_clave else "No aplica",
        "Población (elementos)": entero(len(std)),
    }
    if "monto" in std:
        valor_poblacion = std["monto"].abs().sum()
        valor_muestra = muestra["monto"].abs().sum()
        parametros["Población (valor absoluto)"] = pesos(valor_poblacion)
        parametros["Cobertura de valor"] = porcentaje(valor_muestra / valor_poblacion) if valor_poblacion else "—"
    resumen = f"Se seleccionaron {entero(len(muestra))} elementos con el método «{METODOS[metodo]}»."
    if notas:
        resumen += " " + " ".join(notas)
    return ResultadoMuestra(muestra, parametros, resumen)


def _asignar_proporcional(n: int, valores: pd.Series, tamanos: pd.Series) -> dict[int, int]:
    """Reparte n entre estratos en proporción a su valor (resto mayor), con al menos 1 y sin exceder el estrato."""
    cuota = valores / valores.sum() * n if valores.sum() else tamanos / tamanos.sum() * n
    asignacion = np.floor(cuota).clip(lower=1).astype(int).clip(upper=tamanos)
    while asignacion.sum() < n:
        holgura = (cuota - asignacion).where(asignacion < tamanos, -np.inf)
        asignacion[holgura.idxmax()] += 1
    while asignacion.sum() > n:
        asignacion[(asignacion - cuota).where(asignacion > 1, -np.inf).idxmax()] -= 1
    return asignacion.to_dict()
