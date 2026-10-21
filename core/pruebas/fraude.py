"""Pruebas orientadas a riesgo de fraude (NIA 240)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from core import colombia
from core.graficas import SERIE_1, SERIE_2, barras, entero, estilo, pesos, porcentaje
from core.pruebas.base import Parametro, ResultadoPrueba, columnas_salida, prueba

CATEGORIA = "Detección de fraude"

# Umbrales de conformidad por desviación absoluta media (Nigrini, 2012).
_UMBRALES_MAD = {
    1: ((0.006, "Conformidad cercana"), (0.012, "Conformidad aceptable"), (0.015, "Conformidad marginal")),
    2: ((0.0012, "Conformidad cercana"), (0.0018, "Conformidad aceptable"), (0.0022, "Conformidad marginal")),
}


def _primeros_digitos(valores: np.ndarray, cantidad: int) -> np.ndarray:
    exponente = np.floor(np.log10(valores)) - (cantidad - 1)
    digitos = np.floor(valores / 10.0 ** exponente)
    # Corrige errores de redondeo de log10 cerca de potencias exactas de 10.
    exponente = np.where(digitos >= 10 ** cantidad, exponente + 1,
                         np.where(digitos < 10 ** (cantidad - 1), exponente - 1, exponente))
    return np.floor(valores / 10.0 ** exponente).astype(int)


@prueba(
    clave="benford",
    nombre="Ley de Benford",
    categoria=CATEGORIA,
    nia="NIA 240 · NIA 520",
    objetivo="Detectar montos que se apartan de la distribución natural de dígitos, señal de cifras inventadas o manipuladas.",
    interpretacion=(
        "En poblaciones grandes y naturales (pagos, ventas, gastos) los dígitos iniciales siguen la ley de Benford. "
        "Excesos en un dígito específico suelen deberse a montos repetidos, topes de autorización o cifras inventadas. "
        "Una no conformidad no prueba un fraude: oriente la revisión hacia los dígitos señalados y sus terceros. "
        "La prueba pierde confiabilidad con menos de 300 registros o con montos asignados (tarifas, cuotas fijas)."
    ),
    requeridos=("monto",),
    parametros=(
        Parametro("digitos", "Prueba", "opcion", "Primer dígito", opciones=("Primer dígito", "Primeros dos dígitos")),
        Parametro("monto_minimo", "Excluir montos menores a", "numero", 10.0,
                  "Los montos muy pequeños distorsionan la prueba.", minimo=0),
    ),
)
def benford(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    cantidad = 1 if p["digitos"] == "Primer dígito" else 2
    base = std.dropna(subset=["monto"])
    base = base[base["monto"].abs() >= max(p["monto_minimo"], 10 ** (cantidad - 1))].copy()
    if base.empty:
        raise ValueError("No hay montos que cumplan el mínimo para la prueba.")
    base["digito"] = _primeros_digitos(base["monto"].abs().to_numpy(), cantidad)
    digitos = np.arange(10 ** (cantidad - 1), 10 ** cantidad)
    n = len(base)
    esperada = np.log10(1 + 1 / digitos)
    observados = base["digito"].value_counts().reindex(digitos, fill_value=0).to_numpy()
    observada = observados / n
    z = (np.abs(observada - esperada) - 1 / (2 * n)) / np.sqrt(esperada * (1 - esperada) / n)
    z = np.clip(z, 0, None)
    mad = float(np.mean(np.abs(observada - esperada)))
    conclusion = next((texto for limite, texto in _UMBRALES_MAD[cantidad] if mad <= limite), "No conformidad")

    tabla = pd.DataFrame({"Dígito": digitos, "Registros": observados, "% observado": observada,
                          "% esperado": esperada, "Estadístico Z": z.round(2)})
    tabla["Señalado"] = np.where((tabla["Estadístico Z"] > 1.96) & (observada > esperada), "Sí", "")
    señalados = tabla.loc[tabla["Señalado"] == "Sí", "Dígito"].tolist()
    hallazgos = base[base["digito"].isin(señalados)].sort_values("monto", ascending=False)
    hallazgos = hallazgos[["digito"] + columnas_salida(hallazgos)]

    fig = go.Figure()
    fig.add_bar(x=digitos, y=observada, name="Observado", marker_color=SERIE_1,
                hovertemplate="Dígito %{x}: %{y:.1%}<extra>Observado</extra>")
    fig.add_scatter(x=digitos, y=esperada, name="Esperado (Benford)", mode="lines+markers",
                    line=dict(color=SERIE_2, width=2), marker=dict(size=8 if cantidad == 1 else 5),
                    hovertemplate="Dígito %{x}: %{y:.1%}<extra>Esperado</extra>")
    estilo(fig, f"{p['digitos']}: observado vs. esperado", "Dígito", "% de registros", ".0%")
    fig.update_layout(hovermode="x unified")
    if cantidad == 1:
        fig.update_xaxes(dtick=1)

    tabla_formato = tabla.assign(**{"% observado": tabla["% observado"].map(porcentaje),
                                    "% esperado": tabla["% esperado"].map(porcentaje)})
    resumen = f"{conclusion} con la ley de Benford (MAD = {mad:.4f}) sobre {entero(n)} montos.".replace(".", ",", 1)
    if señalados:
        resumen += f" Dígitos con exceso significativo: {', '.join(map(str, señalados))}."
    if n < 300:
        resumen += " Atención: con menos de 300 registros la prueba es poco concluyente."
    return ResultadoPrueba(resumen, hallazgos,
                           {"Montos analizados": entero(n), "MAD": f"{mad:.4f}".replace(".", ","),
                            "Dígitos señalados": entero(len(señalados))},
                           {"Distribución de dígitos": tabla_formato}, [fig],
                           hay_excepciones=conclusion in ("Conformidad marginal", "No conformidad") or bool(señalados))


@prueba(
    clave="montos_redondos",
    nombre="Montos redondos",
    categoria=CATEGORIA,
    nia="NIA 240",
    objetivo="Identificar transacciones con valores exactos (p. ej. $ 5.000.000), típicos de estimaciones o pagos sin soporte.",
    interpretacion=(
        "Los pagos con cifras exactas son normales en anticipos, arriendos o préstamos, pero son poco comunes en compras "
        "con IVA y retenciones. Concentre la revisión en terceros con muchos montos redondos y solicite facturas y "
        "contratos que justifiquen el valor."
    ),
    requeridos=("monto",),
    parametros=(
        Parametro("multiplo", "Múltiplo de", "numero", 100_000.0, "Un monto es redondo si es múltiplo exacto de este valor.",
                  minimo=1),
        Parametro("monto_minimo", "Monto mínimo", "numero", 1_000_000.0, "Ignora montos menores.", minimo=0),
    ),
)
def montos_redondos(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    base = std.dropna(subset=["monto"])
    base = base[base["monto"].abs() >= p["monto_minimo"]]
    redondos = base[np.isclose(np.mod(base["monto"].abs(), p["multiplo"]), 0)]
    hallazgos = redondos.sort_values("monto", ascending=False)[columnas_salida(redondos)]
    tablas, graficas = {}, []
    if "tercero" in redondos and len(redondos):
        por_tercero = (redondos.groupby("tercero")["monto"].agg(["count", "sum"])
                       .sort_values(["count", "sum"], ascending=False).head(15).reset_index())
        tablas["Terceros con más montos redondos"] = por_tercero.rename(
            columns={"tercero": "Tercero", "count": "Montos redondos", "sum": "Valor"})
        graficas.append(barras(por_tercero["tercero"], por_tercero["count"], "Terceros con más montos redondos",
                               horizontal=True, texto_hover="%{y}: %{x} montos redondos<extra></extra>"))
    proporcion = len(redondos) / len(base) if len(base) else 0
    valor = redondos["monto"].abs().sum()
    resumen = (f"{entero(len(redondos))} transacciones ({porcentaje(proporcion)} de las analizadas) son múltiplos "
               f"exactos de {pesos(p['multiplo'])}, por {pesos(valor)}.")
    return ResultadoPrueba(resumen, hallazgos,
                           {"Analizadas": entero(len(base)), "Montos redondos": entero(len(redondos)),
                            "% del total": porcentaje(proporcion), "Valor": pesos(valor)},
                           tablas, graficas, hay_excepciones=bool(len(redondos)))


_DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


@prueba(
    clave="dias_no_habiles",
    nombre="Registros en días no hábiles",
    categoria=CATEGORIA,
    nia="NIA 240 (asientos de diario)",
    objetivo="Detectar transacciones fechadas en fines de semana o festivos de Colombia.",
    interpretacion=(
        "La NIA 240 pide examinar asientos registrados en momentos inusuales. Transacciones en domingos o festivos "
        "pueden indicar registros fuera de los controles normales, fechas alteradas o accesos no autorizados. "
        "Confirme con el usuario que registró y con el soporte de la operación."
    ),
    requeridos=("fecha",),
    opcionales=("usuario",),
    parametros=(
        Parametro("incluir_sabados", "Incluir sábados", "opcion", "Sí", opciones=("Sí", "No")),
    ),
)
def dias_no_habiles(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    base = std.dropna(subset=["fecha"]).copy()
    dia = base["fecha"].dt.dayofweek
    festivo = base["fecha"].map(colombia.nombre_festivo)
    motivo = pd.Series(pd.NA, index=base.index, dtype="object")
    if p["incluir_sabados"] == "Sí":
        motivo[dia == 5] = "Sábado"
    motivo[dia == 6] = "Domingo"
    motivo[festivo.notna()] = "Festivo: " + festivo[festivo.notna()]
    base["motivo"] = motivo
    marcados = base[base["motivo"].notna()]
    hallazgos = marcados.sort_values("fecha")[["motivo"] + columnas_salida(marcados)]
    if "usuario" in marcados:
        hallazgos.insert(1, "usuario", marcados["usuario"])

    por_dia = dia.value_counts().reindex(range(7), fill_value=0)
    colores = [SERIE_2 if (d == 6 or (d == 5 and p["incluir_sabados"] == "Sí")) else SERIE_1 for d in range(7)]
    fig = barras(list(_DIAS), por_dia.values, "Transacciones por día de la semana", "Día", "Transacciones",
                 texto_hover="%{x}: %{y:,.0f} transacciones<extra></extra>", colores=colores)
    tablas = {}
    if festivo.notna().any():
        conteo = festivo.dropna().value_counts()
        tablas["Festivos con movimientos"] = pd.DataFrame({"Festivo": conteo.index, "Transacciones": conteo.values})
    if "usuario" in marcados and len(marcados):
        conteo = marcados["usuario"].fillna("(sin usuario)").value_counts()
        tablas["Usuarios que registraron en días no hábiles"] = pd.DataFrame(
            {"Usuario": conteo.index, "Transacciones": conteo.values})
    metricas = {"Transacciones": entero(len(base)), "En días no hábiles": entero(len(marcados)),
                "En festivos": entero(int(festivo.notna().sum()))}
    if "monto" in marcados:
        metricas["Valor"] = pesos(marcados["monto"].abs().sum())
    resumen = (f"{entero(len(marcados))} transacciones ({porcentaje(len(marcados) / len(base) if len(base) else 0)}) "
               f"están fechadas en días no hábiles, {entero(int(festivo.notna().sum()))} de ellas en festivos.")
    return ResultadoPrueba(resumen, hallazgos, metricas, tablas, [fig], hay_excepciones=bool(len(marcados)))


@prueba(
    clave="fraccionamiento",
    nombre="Fraccionamiento de compras",
    categoria=CATEGORIA,
    nia="NIA 240 · NIA 330",
    objetivo="Detectar pagos a un mismo tercero divididos para quedar por debajo de un tope de autorización.",
    interpretacion=(
        "Cada grupo reúne pagos al mismo tercero, todos por debajo del tope, hechos en pocos días y que juntos lo "
        "superan. Es la forma típica de evadir una aprobación de nivel superior o un proceso de cotización. "
        "Revise quién aprobó cada pago y si correspondían a una sola necesidad."
    ),
    requeridos=("fecha", "monto", "tercero"),
    parametros=(
        Parametro("umbral", "Tope de autorización", "numero", 10_000_000.0,
                  "Valor a partir del cual se requiere una aprobación adicional.", minimo=1),
        Parametro("ventana_dias", "Ventana de días", "entero", 7, "Días máximos entre el primer y último pago del grupo.",
                  minimo=1, maximo=90),
        Parametro("proporcion_minima", "Cada pago debe ser al menos", "porcentaje", 0.25,
                  "Porcentaje del tope. Excluye pagos pequeños y rutinarios que no reflejan una compra dividida.",
                  minimo=0, maximo=0.99),
    ),
)
def fraccionamiento(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    umbral, ventana = p["umbral"], np.timedelta64(int(p["ventana_dias"]), "D")
    base = std.dropna(subset=["fecha", "monto", "tercero"])
    base = base[(base["monto"] >= umbral * p["proporcion_minima"]) & (base["monto"] < umbral)]
    base = base[base["monto"] > 0].sort_values(["tercero", "fecha"])
    grupo_de: dict = {}
    siguiente = 1
    for _, g in base.groupby("tercero", sort=False):
        fechas, montos, indices = g["fecha"].to_numpy(), g["monto"].to_numpy(), g.index.to_numpy()
        inicio = 0
        for fin in range(len(g)):
            while fechas[fin] - fechas[inicio] > ventana:
                inicio += 1
            if fin > inicio and montos[inicio:fin + 1].sum() >= umbral:
                existentes = [grupo_de[i] for i in indices[inicio:fin + 1] if i in grupo_de]
                gid = existentes[0] if existentes else siguiente
                siguiente += 0 if existentes else 1
                for i in indices[inicio:fin + 1]:
                    grupo_de.setdefault(i, gid)
    marcados = base.loc[list(grupo_de)].copy()
    marcados["grupo"] = pd.Series(grupo_de)
    resumen_grupos = (marcados.groupby("grupo")
                      .agg(Tercero=("tercero", "first"), Desde=("fecha", "min"), Hasta=("fecha", "max"),
                           Pagos=("monto", "size"), Total=("monto", "sum"), Promedio=("monto", "mean"))
                      .reset_index().rename(columns={"grupo": "Grupo"}))
    # Primero los grupos cuyos pagos se acercan más al tope: el patrón más típico de fraccionamiento.
    resumen_grupos["Promedio vs. tope"] = resumen_grupos.pop("Promedio") / umbral
    resumen_grupos = resumen_grupos.sort_values("Promedio vs. tope", ascending=False)
    orden = {g: i for i, g in enumerate(resumen_grupos["Grupo"])}
    resumen_grupos["Promedio vs. tope"] = resumen_grupos["Promedio vs. tope"].map(porcentaje)
    marcados = marcados.sort_values(["grupo", "fecha"], key=lambda s: s.map(orden) if s.name == "grupo" else s)
    hallazgos = marcados[["grupo"] + columnas_salida(marcados)]
    grupos = len(resumen_grupos)
    resumen = (f"{entero(grupos)} grupos de pagos ({entero(len(marcados))} transacciones) superan juntos el tope de "
               f"{pesos(umbral)} en {p['ventana_dias']} días o menos." if grupos else
               f"No se encontraron pagos fraccionados por debajo de {pesos(umbral)}.")
    return ResultadoPrueba(resumen, hallazgos,
                           {"Grupos sospechosos": entero(grupos), "Transacciones": entero(len(marcados)),
                            "Valor total": pesos(marcados["monto"].sum())},
                           {"Resumen por grupo": resumen_grupos} if grupos else {}, hay_excepciones=bool(grupos))
