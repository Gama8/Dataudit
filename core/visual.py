"""Visualizaciones descritas como especificación (dict) para poder guardarlas y redibujarlas.

Una especificación más una consulta SQL es todo lo que necesita un tablero: al abrirlo
se vuelve a ejecutar la consulta sobre los datos actuales y se dibuja igual.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.graficas import CATEGORICA, estilo

TIPOS = {
    "barras": "Barras",
    "barras_horizontales": "Barras horizontales",
    "lineas": "Líneas",
    "dispersion": "Dispersión",
    "kpi": "Indicador (KPI)",
    "tabla": "Tabla",
}
AGREGACIONES = {"ninguna": None, "suma": "sum", "promedio": "mean", "conteo": "count"}
MAX_CATEGORIAS = 25
MAX_SERIES = len(CATEGORICA)


def validar(spec: dict, columnas) -> dict:
    """Normaliza la especificación y verifica que las columnas existan en el resultado."""
    tipo = spec.get("tipo", "tabla")
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de visualización desconocido: {tipo}. Usa uno de: {', '.join(TIPOS)}.")
    limpio = {"tipo": tipo, "titulo": str(spec.get("titulo") or "").strip(),
              "x": spec.get("x") or "", "y": spec.get("y") or "", "serie": spec.get("serie") or "",
              "agregacion": spec.get("agregacion") or "ninguna"}
    if limpio["agregacion"] not in AGREGACIONES:
        raise ValueError(f"Agregación desconocida: {limpio['agregacion']}.")
    requeridas = {"tabla": (), "kpi": ("y",)}.get(tipo, ("x", "y"))
    for campo in requeridas:
        if limpio[campo] not in columnas:
            raise ValueError(f"La columna «{limpio[campo]}» ({campo}) no está en el resultado. "
                             f"Columnas disponibles: {', '.join(map(str, columnas))}.")
    if limpio["serie"] and limpio["serie"] not in columnas:
        raise ValueError(f"La columna de serie «{limpio['serie']}» no está en el resultado.")
    return limpio


def preparar(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Aplica la agregación y los recortes que hacen legible la gráfica."""
    x, y, serie, tipo = spec["x"], spec["y"], spec["serie"], spec["tipo"]
    claves = [c for c in (x, serie) if c]
    funcion = AGREGACIONES[spec["agregacion"]]
    datos = df[[*claves, y]].copy()
    if funcion and tipo != "dispersion":
        datos = datos.groupby(claves, dropna=False)[y].agg(funcion).reset_index()
    if serie:
        # Las series más grandes conservan su color; el resto se agrupa en "Otros".
        totales = datos.groupby(serie)[y].sum().sort_values(ascending=False)
        if len(totales) > MAX_SERIES:
            principales = set(totales.index[:MAX_SERIES - 1])
            datos[serie] = datos[serie].where(datos[serie].isin(principales), "Otros")
            datos = datos.groupby(claves, dropna=False)[y].sum().reset_index()
    if tipo in ("barras", "barras_horizontales") and not serie:
        datos = datos.sort_values(y, ascending=False).head(MAX_CATEGORIAS)
    elif tipo == "lineas":
        datos = datos.sort_values(x)
    return datos


def figura(df: pd.DataFrame, spec: dict) -> go.Figure | None:
    """Figura de Plotly para la especificación; None para KPI y tabla (se dibujan aparte)."""
    spec = validar(spec, df.columns)
    if spec["tipo"] in ("kpi", "tabla"):
        return None
    datos = preparar(df, spec)
    x, y, serie, tipo = spec["x"], spec["y"], spec["serie"], spec["tipo"]
    grupos = [(None, datos)] if not serie else list(datos.groupby(serie, sort=False))
    fig = go.Figure()
    for i, (nombre, parte) in enumerate(grupos):
        color = CATEGORICA[i % len(CATEGORICA)]
        etiqueta = str(nombre) if nombre is not None else y
        if tipo == "barras":
            fig.add_bar(x=parte[x].astype(str), y=parte[y], name=etiqueta, marker_color=color,
                        hovertemplate="%{x}: %{y:,.2f}<extra>" + etiqueta + "</extra>")
        elif tipo == "barras_horizontales":
            fig.add_bar(x=parte[y], y=parte[x].astype(str), orientation="h", name=etiqueta, marker_color=color,
                        hovertemplate="%{y}: %{x:,.2f}<extra>" + etiqueta + "</extra>")
        elif tipo == "lineas":
            fig.add_scatter(x=parte[x], y=parte[y], mode="lines+markers", name=etiqueta,
                            line=dict(color=color, width=2), marker=dict(size=8))
        else:
            fig.add_scatter(x=parte[x], y=parte[y], mode="markers", name=etiqueta,
                            marker=dict(color=color, size=8, line=dict(width=2, color="white")))
    if tipo == "barras_horizontales":
        fig.update_yaxes(autorange="reversed")
    if serie and tipo in ("barras", "barras_horizontales"):
        fig.update_layout(barmode="group")
    eje_x, eje_y = (y, x) if tipo == "barras_horizontales" else (x, y)
    return estilo(fig, spec["titulo"] or None, eje_x, eje_y, alto=400)


def valor_kpi(df: pd.DataFrame, spec: dict) -> float | None:
    spec = validar(spec, df.columns)
    serie = pd.to_numeric(df[spec["y"]], errors="coerce").dropna()
    if serie.empty:
        return None
    funcion = AGREGACIONES[spec["agregacion"]]
    return float(serie.agg(funcion)) if funcion else float(serie.iloc[0])
