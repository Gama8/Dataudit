"""Componentes de interfaz reutilizables."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.datasets import ahora
from core.mapping import CAMPOS
from core.papeles import papel_de_trabajo

_ETIQUETAS_EXTRA = {"fila": "Fila en archivo", "grupo": "Grupo", "motivo": "Motivo", "problemas": "Problemas",
                    "estado_nit": "Estado del NIT", "dv_correcto": "DV correcto", "digito": "Dígito",
                    "dias_vencido": "Días vencido", "rango": "Rango", "estrato": "Estrato",
                    "unidades_seleccionadas": "Unidades MUS"}


def etiqueta(columna: str) -> str:
    if columna in CAMPOS:
        return CAMPOS[columna].etiqueta
    return _ETIQUETAS_EXTRA.get(columna, columna)


def configurar_columnas(df: pd.DataFrame) -> dict:
    config = {}
    for columna in df.columns:
        nombre = etiqueta(str(columna))
        serie = df[columna]
        if pd.api.types.is_datetime64_any_dtype(serie):
            config[columna] = st.column_config.DatetimeColumn(nombre, format="YYYY-MM-DD")
        elif pd.api.types.is_float_dtype(serie):
            config[columna] = st.column_config.NumberColumn(nombre, format="localized")
        elif nombre != columna:
            config[columna] = st.column_config.Column(nombre)
    return config


def tabla(df: pd.DataFrame, alto: int | str = "auto", **kwargs) -> None:
    st.dataframe(df, hide_index=True, column_config=configurar_columnas(df), height=alto,
                 width="stretch", **kwargs)


def legible(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra columnas internas a etiquetas en español (para exportar)."""
    return df.rename(columns={c: etiqueta(str(c)) for c in df.columns})


def metricas(valores: dict[str, str]) -> None:
    if not valores:
        return
    columnas = st.columns(min(len(valores), 4))
    for i, (titulo, valor) in enumerate(valores.items()):
        with columnas[i % len(columnas)]:
            st.metric(titulo, valor, border=True)


def exportar_papel(titulo: str, encabezado: dict[str, str], hojas: dict[str, pd.DataFrame], resumen: str,
                   clave: str) -> None:
    """Conclusión del auditor + descarga del papel de trabajo en Excel."""
    with st.container(border=True):
        st.markdown("**Papel de trabajo**")
        conclusion = st.text_area("Conclusión del auditor", key=f"conclusion_{clave}",
                                  placeholder="Ej.: Se revisaron los 6 grupos con el área de tesorería; "
                                              "2 corresponden a pagos dobles ya reintegrados…")
        auditor = st.session_state.get("auditor") or "(sin nombre: complétalo en la barra lateral)"
        momento = ahora()
        cabecera = {"Prueba": titulo, **encabezado, "Ejecutado por": auditor,
                    "Fecha de ejecución": momento.strftime("%Y-%m-%d %H:%M %Z")}
        contenido = papel_de_trabajo(titulo, cabecera, {n: legible(df) for n, df in hojas.items()}, resumen,
                                     conclusion)
        nombre = f"PT_{clave}_{momento:%Y%m%d_%H%M}.xlsx"
        st.download_button("Descargar papel de trabajo (Excel)", contenido, file_name=nombre,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           icon=":material/download:", type="primary", key=f"descarga_{clave}")
