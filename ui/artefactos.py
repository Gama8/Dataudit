"""Dibujo de visualizaciones guardables y de los artefactos que produce el asistente."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import papeles, visual
from core.asistente import Artefacto
from core.graficas import pesos
from core.pruebas import REGISTRO
from ui import estado
from ui.componentes import metricas, tabla


def dibujar_visual(df: pd.DataFrame, spec: dict, clave: str) -> None:
    """Dibuja una especificación de core.visual (gráfica, KPI o tabla)."""
    if spec["tipo"] == "kpi":
        valor = visual.valor_kpi(df, spec)
        st.metric(spec.get("titulo") or spec["y"], "—" if valor is None else
                  (pesos(valor) if abs(valor) >= 1000 else f"{valor:,.2f}".replace(",", "X").replace(".", ",")
                   .replace("X", ".")), border=True)
    elif spec["tipo"] == "tabla":
        tabla(df, alto=min(400, 40 + 35 * max(len(df), 1)))
    else:
        st.plotly_chart(visual.figura(df, spec), width="stretch", key=f"fig_{clave}")


def boton_fijar(titulo: str, sql: str, spec: dict, clave: str) -> None:
    """Guarda consulta + especificación en un tablero; al abrirlo se recalcula con los datos actuales."""
    with st.popover("Fijar en tablero", icon=":material/push_pin:"):
        almacen = estado.almacen()
        tableros = {t["id"]: t["nombre"] for t in almacen.tableros()}
        nuevo = "➕ Nuevo tablero"
        opciones = [*tableros, nuevo]
        elegido = st.selectbox("Tablero", opciones, key=f"tab_{clave}",
                               format_func=lambda o: tableros.get(o, o))
        nombre_nuevo = st.text_input("Nombre del tablero nuevo", value="Tablero principal",
                                     key=f"tabnom_{clave}") if elegido == nuevo else ""
        titulo_widget = st.text_input("Título", value=titulo, key=f"tit_{clave}")
        if st.button("Fijar", key=f"fijar_{clave}", type="primary"):
            tablero_id = almacen.crear_tablero(nombre_nuevo) if elegido == nuevo else elegido
            almacen.agregar_widget(tablero_id, titulo_widget, sql, {**spec, "titulo": titulo_widget})
            st.toast(f"Fijado en «{nombre_nuevo or tableros[elegido]}»", icon=":material/push_pin:")


def _descarga_excel(titulo: str, encabezado: dict, hojas: dict, resumen: str, clave: str) -> None:
    contenido = papeles.papel_de_trabajo(titulo, {**encabezado, "Ejecutado por": st.session_state.get("auditor")
                                                  or "(sin nombre)"}, hojas, resumen)
    st.download_button("Papel de trabajo (Excel)", contenido, file_name=f"PT_{clave}.xlsx", key=f"xls_{clave}",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:")


def guardar_hallazgo(borrador: dict, evidencia: pd.DataFrame | None, origen: str) -> str:
    """Registra un hallazgo con su evidencia (máx. 500 filas) y devuelve su código."""
    conjunto = estado.conjuntos().get(borrador.get("conjunto", ""))
    datos = {
        **borrador,
        "origen": origen,
        "creado_por": st.session_state.get("auditor", ""),
        "huella_datos": conjunto.huella if conjunto else "",
        "evidencia_json": evidencia.head(500).to_json(orient="records", date_format="iso", force_ascii=False)
        if evidencia is not None and len(evidencia) else "",
    }
    almacen = estado.almacen()
    hallazgo_id = almacen.guardar_hallazgo(datos)
    return almacen.hallazgo(hallazgo_id)["codigo"]


def mostrar_artefacto(artefacto: Artefacto) -> None:
    clave = f"art_{artefacto.id}"
    with st.container(border=True):
        if artefacto.tipo == "tabla":
            st.markdown(f"**{artefacto.titulo}** · `{artefacto.id}` · {len(artefacto.datos):,} filas".replace(",", "."))
            tabla(artefacto.datos, alto=min(320, 40 + 35 * max(len(artefacto.datos), 1)))
            columnas = st.columns([1, 1, 3])
            with columnas[0].popover("Ver SQL", icon=":material/code:"):
                st.code(artefacto.sql, language="sql")
            with columnas[1]:
                boton_fijar(artefacto.titulo, artefacto.sql, {"tipo": "tabla"}, clave)

        elif artefacto.tipo == "grafica":
            dibujar_visual(artefacto.datos, artefacto.spec, clave)
            columnas = st.columns([1, 1, 3])
            with columnas[0].popover("Ver SQL", icon=":material/code:"):
                st.code(artefacto.sql, language="sql")
            with columnas[1]:
                boton_fijar(artefacto.titulo, artefacto.sql, artefacto.spec, clave)

        elif artefacto.tipo == "prueba":
            resultado = artefacto.datos
            prueba = REGISTRO[artefacto.spec["clave"]]
            st.markdown(f"**{prueba.nombre}** · `{artefacto.id}` · {artefacto.conjunto} · {prueba.nia}")
            (st.warning if resultado.hay_excepciones else st.success)(resultado.resumen)
            metricas(resultado.metricas)
            for i, figura in enumerate(resultado.graficas):
                st.plotly_chart(figura, width="stretch", key=f"{clave}_g{i}")
            if len(resultado.hallazgos):
                with st.expander(f"Excepciones ({len(resultado.hallazgos):,})".replace(",", ".")):
                    tabla(resultado.hallazgos, alto=300)
            conjunto = estado.conjuntos().get(artefacto.conjunto)
            parametros = {f"Parámetro: {k}": str(v) for k, v in artefacto.spec["parametros"].items()}
            _descarga_excel(prueba.nombre, {"Referencia normativa": prueba.nia, **(conjunto.ficha() if conjunto else {}),
                                            **parametros, "Origen": "Asistente Dataudit"},
                            {"Excepciones": resultado.hallazgos, **resultado.tablas}, resultado.resumen, clave)

        elif artefacto.tipo == "muestra":
            resultado = artefacto.datos
            st.markdown(f"**{artefacto.titulo}** · `{artefacto.id}` · {artefacto.conjunto}")
            st.success(resultado.resumen)
            tabla(resultado.muestra, alto=300)
            conjunto = estado.conjuntos().get(artefacto.conjunto)
            _descarga_excel("Muestra de auditoría", {**(conjunto.ficha() if conjunto else {}), **resultado.parametros},
                            {"Muestra": resultado.muestra}, resultado.resumen, clave)

        elif artefacto.tipo == "hallazgo":
            borrador = artefacto.datos["borrador"]
            st.markdown(f"**Borrador de hallazgo** · `{artefacto.id}` · severidad **{borrador['severidad']}**")
            st.markdown(f"#### {borrador['titulo']}")
            for campo, etiqueta in (("condicion", "Condición"), ("criterio", "Criterio"), ("causa", "Causa"),
                                    ("efecto", "Efecto"), ("recomendacion", "Recomendación")):
                if borrador.get(campo):
                    st.markdown(f"**{etiqueta}:** {borrador[campo]}")
            if borrador.get("valor_afectado"):
                st.markdown(f"**Valor afectado:** {pesos(borrador['valor_afectado'])}")
            if artefacto.datos.get("codigo"):
                st.success(f"Guardado en el registro como {artefacto.datos['codigo']}.", icon=":material/check:")
            elif st.button("Guardar en el registro de hallazgos", key=f"guardar_{clave}", type="primary",
                           icon=":material/bookmark_add:"):
                artefacto.datos["codigo"] = guardar_hallazgo(borrador, artefacto.datos.get("evidencia"), "Asistente")
                st.rerun()
