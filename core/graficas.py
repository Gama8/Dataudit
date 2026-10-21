"""Estilo común para las gráficas de Dataudit (Plotly).

Colores: primeros espacios de una paleta categórica validada para daltonismo.
Regla: una sola serie = un solo color; los colores de marca no se usan como series.
"""
from __future__ import annotations

import plotly.graph_objects as go

SERIE_1 = "#2a78d6"  # azul
SERIE_2 = "#eb6834"  # naranja
SERIE_3 = "#1baf7a"  # aguamarina
# Orden fijo validado (nunca se recicla): a partir de la novena serie se agrupa en "Otros".
CATEGORICA = (SERIE_1, SERIE_2, SERIE_3, "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
POLO_NEGATIVO = "#2a78d6"  # divergente: disminuciones
POLO_POSITIVO = "#e34948"  # divergente: aumentos
TINTA_TENUE = "#898781"
RETICULA = "rgba(137, 135, 129, 0.22)"
LINEA_BASE = "rgba(137, 135, 129, 0.55)"


def estilo(fig: go.Figure, titulo: str | None = None, eje_x: str | None = None, eje_y: str | None = None,
           formato_y: str | None = None, alto: int = 380) -> go.Figure:
    fig.update_layout(
        title=dict(text=titulo, x=0, xanchor="left", font=dict(size=15)) if titulo else None,
        height=alto,
        margin=dict(l=8, r=8, t=56 if titulo else 16, b=8),
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12),
        bargap=0.18,
        barcornerradius=4,
        hovermode="x unified" if any(t.type == "scatter" for t in fig.data) else "closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=None),
        showlegend=len(fig.data) > 1,
    )
    fig.update_xaxes(title=eje_x, showgrid=False, linecolor=LINEA_BASE, ticks="", tickfont=dict(color=TINTA_TENUE))
    fig.update_yaxes(title=eje_y, gridcolor=RETICULA, griddash="solid", zeroline=True, zerolinecolor=LINEA_BASE,
                     tickformat=formato_y, tickfont=dict(color=TINTA_TENUE))
    return fig


def barras(x, y, titulo: str, eje_x: str | None = None, eje_y: str | None = None, formato_y: str | None = None,
           texto_hover: str = "%{x}: %{y:,.0f}<extra></extra>", horizontal: bool = False, colores=None) -> go.Figure:
    color = colores if colores is not None else SERIE_1
    if horizontal:
        traza = go.Bar(x=y, y=x, orientation="h", marker_color=color, hovertemplate=texto_hover)
    else:
        traza = go.Bar(x=x, y=y, marker_color=color, hovertemplate=texto_hover)
    fig = go.Figure(traza)
    if horizontal:
        fig.update_yaxes(autorange="reversed")
    return estilo(fig, titulo, eje_x, eje_y, formato_y)


def pesos(valor: float) -> str:
    """Formato de pesos colombianos: $ 1.234.567"""
    if valor is None:
        return "—"
    signo = "-" if valor < 0 else ""
    return f"{signo}$ {abs(valor):,.0f}".replace(",", ".")


def entero(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")


def porcentaje(valor: float, decimales: int = 1) -> str:
    return f"{valor * 100:.{decimales}f} %".replace(".", ",")
