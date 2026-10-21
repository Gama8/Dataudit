"""Análisis por ciclo de negocio: cartera, cuentas por pagar y procedimientos analíticos."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.graficas import POLO_NEGATIVO, POLO_POSITIVO, barras, entero, pesos, porcentaje
from core.mapping import CAMPOS
from core.pruebas.base import Parametro, ResultadoPrueba, columnas_salida, prueba

CATEGORIA = "Análisis por ciclo"

_RANGOS = ((0, "No vencido"), (30, "1 a 30 días"), (60, "31 a 60 días"), (90, "61 a 90 días"),
           (180, "91 a 180 días"), (360, "181 a 360 días"), (np.inf, "Más de 360 días"))


@prueba(
    clave="antiguedad_saldos",
    nombre="Antigüedad de saldos",
    categoria=CATEGORIA,
    nia="NIA 540 · NIA 505",
    objetivo="Clasificar cartera o cuentas por pagar por días de vencimiento para evaluar deterioro y seleccionar confirmaciones.",
    interpretacion=(
        "Los saldos con más días vencidos tienen mayor riesgo de no recuperarse. Compare el deterioro registrado "
        "por la entidad (NIIF para PYMES, sección 11) con los saldos de más de 90 y 360 días, y considere estos "
        "terceros para confirmación externa (NIA 505). Si no hay fecha de vencimiento, los días se cuentan desde "
        "la fecha del documento."
    ),
    requeridos=("fecha", "monto"),
    opcionales=("fecha_vencimiento", "tercero"),
    parametros=(
        Parametro("fecha_corte", "Fecha de corte", "fecha", None, "Vacío = la fecha más reciente del archivo."),
        Parametro("dias_alerta", "Reportar saldos vencidos a más de (días)", "entero", 90, minimo=0),
    ),
)
def antiguedad_saldos(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    base = std.dropna(subset=["fecha", "monto"])
    base = base[base["monto"] > 0].copy()
    if base.empty:
        raise ValueError("No hay saldos positivos para analizar.")
    corte = pd.Timestamp(p.get("fecha_corte") or base["fecha"].max())
    referencia = base["fecha"]
    if "fecha_vencimiento" in base:
        referencia = base["fecha_vencimiento"].fillna(base["fecha"])
    base["dias_vencido"] = (corte - referencia).dt.days
    limites = [-np.inf] + [r[0] for r in _RANGOS]
    etiquetas = [r[1] for r in _RANGOS]
    base["rango"] = pd.cut(base["dias_vencido"], bins=limites, labels=etiquetas, right=True)

    total = base["monto"].sum()
    por_rango = base.groupby("rango", observed=False)["monto"].agg(["size", "sum"]).reindex(etiquetas, fill_value=0)
    tabla = pd.DataFrame({"Rango": etiquetas, "Documentos": por_rango["size"].to_numpy(),
                          "Saldo": por_rango["sum"].to_numpy()})
    tabla["% del saldo"] = (tabla["Saldo"] / total).map(porcentaje)
    fig = barras(tabla["Rango"], tabla["Saldo"], f"Saldo por antigüedad al {corte:%Y-%m-%d}", None, "Saldo",
                 formato_y="~s", texto_hover="%{x}: $ %{y:,.0f}<extra></extra>")

    alerta = base[base["dias_vencido"] > p["dias_alerta"]].sort_values("dias_vencido", ascending=False)
    hallazgos = alerta[["dias_vencido", "rango"] + columnas_salida(alerta)]
    tablas = {"Saldos por rango": tabla}
    if "tercero" in base:
        por_tercero = (alerta.groupby("tercero")
                       .agg(Documentos=("monto", "size"), Saldo=("monto", "sum"), Maximo_dias=("dias_vencido", "max"))
                       .sort_values("Saldo", ascending=False).head(20).reset_index()
                       .rename(columns={"tercero": "Tercero", "Maximo_dias": "Máx. días vencido"}))
        tablas[f"Terceros con saldos de más de {p['dias_alerta']} días"] = por_tercero
    valor_alerta = alerta["monto"].sum()
    resumen = (f"Al {corte:%Y-%m-%d}, {pesos(valor_alerta)} ({porcentaje(valor_alerta / total)}) del saldo de "
               f"{pesos(total)} está vencido a más de {p['dias_alerta']} días.")
    return ResultadoPrueba(resumen, hallazgos,
                           {"Saldo total": pesos(total), "Documentos": entero(len(base)),
                            f"Vencido > {p['dias_alerta']} días": pesos(valor_alerta),
                            "% del saldo": porcentaje(valor_alerta / total)},
                           tablas, [fig], hay_excepciones=bool(len(alerta)))


_FRECUENCIAS = {"Mes": "M", "Trimestre": "Q", "Año": "Y"}


@prueba(
    clave="variacion_analitica",
    nombre="Variación entre periodos",
    categoria=CATEGORIA,
    nia="NIA 520",
    objetivo="Comparar los dos últimos periodos por tercero o cuenta y señalar variaciones significativas.",
    interpretacion=(
        "Como procedimiento analítico sustantivo (NIA 520), toda variación que supere el porcentaje y la materialidad "
        "definidos debe explicarse con la administración y corroborarse con evidencia. Terceros nuevos o que "
        "desaparecen merecen atención especial. Si el último periodo está incompleto, ajuste la fecha de los datos."
    ),
    requeridos=("fecha", "monto"),
    opcionales=("tercero", "cuenta"),
    parametros=(
        Parametro("dimension", "Comparar por", "opcion", "tercero", opciones=("tercero", "cuenta")),
        Parametro("periodo", "Periodo", "opcion", "Mes", opciones=tuple(_FRECUENCIAS)),
        Parametro("umbral_variacion", "Variación mínima", "porcentaje", 0.30, minimo=0),
        Parametro("materialidad", "Variación mínima en pesos", "numero", 5_000_000.0, minimo=0),
        Parametro("hasta", "Analizar hasta", "fecha", None,
                  "Excluye fechas posteriores. Vacío = hasta hoy (las fechas futuras se consideran errores)."),
    ),
)
def variacion_analitica(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    dimension = p["dimension"]
    if dimension not in std:
        raise ValueError(f"Mapea el campo «{CAMPOS[dimension].etiqueta}» para comparar por él.")
    base = std.dropna(subset=["fecha", "monto", dimension]).copy()
    hasta = pd.Timestamp(p.get("hasta") or pd.Timestamp.today().normalize())
    excluidos = int((base["fecha"] > hasta).sum())
    base = base[base["fecha"] <= hasta]
    base["periodo"] = base["fecha"].dt.to_period(_FRECUENCIAS[p["periodo"]])
    periodos = sorted(base["periodo"].unique())
    if len(periodos) < 2:
        raise ValueError("Se necesitan al menos dos periodos con datos para comparar.")
    anterior, actual = periodos[-2], periodos[-1]
    tabla = base.pivot_table(index=dimension, columns="periodo", values="monto", aggfunc="sum", fill_value=0)
    comparacion = pd.DataFrame({"anterior": tabla[anterior], "actual": tabla[actual]})
    comparacion["variacion"] = comparacion["actual"] - comparacion["anterior"]
    comparacion["variacion_pct"] = np.where(comparacion["anterior"] != 0,
                                            comparacion["variacion"] / comparacion["anterior"].abs(), np.inf)
    comparacion = comparacion[(comparacion["anterior"] != 0) | (comparacion["actual"] != 0)]
    comparacion["observacion"] = np.select(
        [comparacion["anterior"] == 0, comparacion["actual"] == 0], ["Nuevo en el periodo", "Sin movimiento"], "")
    significativas = comparacion[(comparacion["variacion_pct"].abs() >= p["umbral_variacion"])
                                 & (comparacion["variacion"].abs() >= p["materialidad"])]
    significativas = significativas.reindex(significativas["variacion"].abs().sort_values(ascending=False).index)
    hallazgos = significativas.reset_index().rename(columns={
        dimension: CAMPOS[dimension].etiqueta, "anterior": str(anterior), "actual": str(actual),
        "variacion": "Variación", "variacion_pct": "Variación %", "observacion": "Observación"})
    hallazgos["Variación %"] = significativas["variacion_pct"].map(
        lambda v: "Nuevo" if np.isinf(v) else porcentaje(v)).to_numpy()

    graficas = []
    if len(significativas):
        top = significativas.head(15)
        colores = [POLO_POSITIVO if v > 0 else POLO_NEGATIVO for v in top["variacion"]]
        graficas.append(barras(top.index.astype(str), top["variacion"],
                               f"Mayores variaciones: {actual} vs. {anterior}", horizontal=True, colores=colores,
                               texto_hover="%{y}: $ %{x:,.0f}<extra></extra>"))
    totales = base.groupby("periodo")["monto"].sum()
    graficas.append(barras(totales.index.astype(str), totales.values, f"Total por {p['periodo'].lower()}",
                           formato_y="~s", texto_hover="%{x}: $ %{y:,.0f}<extra></extra>"))
    total_anterior, total_actual = comparacion["anterior"].sum(), comparacion["actual"].sum()
    resumen = (f"{entero(len(significativas))} de {entero(len(comparacion))} "
               f"{'terceros' if dimension == 'tercero' else 'cuentas'} variaron más de "
               f"{porcentaje(p['umbral_variacion'], 0)} y {pesos(p['materialidad'])} entre {anterior} y {actual}.")
    if excluidos:
        resumen += f" Se excluyeron {entero(excluidos)} registros con fecha posterior al {hasta:%Y-%m-%d}."
    return ResultadoPrueba(resumen, hallazgos,
                           {f"Total {anterior}": pesos(total_anterior), f"Total {actual}": pesos(total_actual),
                            "Variación total": porcentaje((total_actual - total_anterior) / abs(total_anterior))
                            if total_anterior else "—",
                            "Variaciones significativas": entero(len(significativas))},
                           {}, graficas, hay_excepciones=bool(len(significativas)))
