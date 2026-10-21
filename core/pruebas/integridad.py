"""Pruebas de integridad de datos (NIA 500: fiabilidad de la información generada por la entidad)."""
from __future__ import annotations

import pandas as pd

from core import colombia
from core.graficas import barras, entero, pesos, porcentaje
from core.mapping import CAMPOS, normalizar
from core.pruebas.base import Parametro, ResultadoPrueba, columnas_salida, prueba

CATEGORIA = "Integridad de datos"


@prueba(
    clave="duplicados",
    nombre="Registros duplicados",
    categoria=CATEGORIA,
    nia="NIA 240 · NIA 500",
    objetivo="Identificar pagos, facturas o asientos registrados más de una vez.",
    interpretacion=(
        "Cada grupo contiene registros idénticos en los campos elegidos. Verifique contra el soporte si se trata "
        "de un pago doble, un error de digitación o una operación legítima repetida (p. ej. cuotas iguales). "
        "Pruebe varias combinaciones: tercero + valor + fecha detecta pagos dobles; tercero + documento detecta "
        "la misma factura contabilizada dos veces aunque cambie el valor."
    ),
    requeridos=(),
    parametros=(
        Parametro("campos", "Campos que deben coincidir", "campos", ("tercero", "monto", "fecha"),
                  "Un registro es duplicado si coincide en TODOS estos campos."),
    ),
)
def duplicados(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    campos = [c for c in p["campos"] if c in std.columns]
    if not campos:
        raise ValueError("Selecciona al menos un campo mapeado para comparar.")
    base = std.dropna(subset=campos)
    repetidos = base[base.duplicated(subset=campos, keep=False)].copy()
    repetidos["grupo"] = repetidos.groupby(campos, sort=False).ngroup() + 1
    repetidos = repetidos.sort_values(["grupo", "fila"])
    grupos = repetidos["grupo"].nunique()
    exceso = len(repetidos) - grupos
    etiquetas = ", ".join(CAMPOS[c].etiqueta.lower() for c in campos)
    metricas = {"Grupos duplicados": entero(grupos), "Registros involucrados": entero(len(repetidos)),
                "Registros en exceso": entero(exceso)}
    if "monto" in repetidos:
        valor_exceso = repetidos["monto"].sum() - repetidos.groupby("grupo")["monto"].first().sum()
        metricas["Valor en exceso"] = pesos(valor_exceso)
    resumen = (f"Se encontraron {entero(grupos)} grupos de registros que coinciden en {etiquetas} "
               f"({entero(exceso)} registros de más)." if grupos else
               f"No hay registros que coincidan en {etiquetas}.")
    return ResultadoPrueba(resumen, repetidos[["grupo"] + columnas_salida(repetidos)], metricas,
                           hay_excepciones=bool(grupos))


@prueba(
    clave="huecos_consecutivo",
    nombre="Huecos en la numeración",
    categoria=CATEGORIA,
    nia="NIA 500 · NIA 330",
    objetivo="Verificar que la numeración de facturas, comprobantes o egresos esté completa (integridad).",
    interpretacion=(
        "Un hueco es un número que no aparece en el archivo. Puede corresponder a documentos anulados "
        "(solicite el soporte de anulación), a documentos no registrados (riesgo de omisión de ingresos) o a un "
        "cambio de resolución de facturación DIAN. Los números repetidos indican posibles duplicados."
    ),
    requeridos=("documento",),
    parametros=(
        Parametro("salto_maximo", "Salto máximo a reportar como hueco", "entero", 1000,
                  "Saltos mayores se reportan aparte como posible cambio de resolución o de rango.", minimo=1),
    ),
)
def huecos_consecutivo(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    partes = std["documento"].dropna().str.extract(r"^(?P<prefijo>.*?)(?P<numero>\d+)\D*$")
    partes = partes.dropna(subset=["numero"])
    partes["numero"] = partes["numero"].astype("int64")
    partes["prefijo"] = partes["prefijo"].fillna("").str.strip(" -_/")
    huecos, repetidos = [], []
    for prefijo, grupo in partes.groupby("prefijo"):
        numeros = grupo["numero"].sort_values()
        conteo = numeros.value_counts()
        repetidos += [{"Prefijo": prefijo or "(sin prefijo)", "Número": n, "Veces": v}
                      for n, v in conteo[conteo > 1].items()]
        unicos = numeros.drop_duplicates()
        for anterior, siguiente in zip(unicos.iloc[:-1], unicos.iloc[1:]):
            if siguiente - anterior > 1:
                faltantes = siguiente - anterior - 1
                huecos.append({
                    "Prefijo": prefijo or "(sin prefijo)", "Desde": anterior + 1, "Hasta": siguiente - 1,
                    "Faltantes": faltantes,
                    "Tipo": "Hueco" if faltantes <= p["salto_maximo"] else "Salto grande (¿cambio de rango?)",
                })
    huecos = pd.DataFrame(huecos, columns=["Prefijo", "Desde", "Hasta", "Faltantes", "Tipo"])
    repetidos = pd.DataFrame(repetidos, columns=["Prefijo", "Número", "Veces"])
    solo_huecos = huecos[huecos["Tipo"] == "Hueco"]
    total_faltantes = int(solo_huecos["Faltantes"].sum())
    sin_numero = int(std["documento"].notna().sum() - len(partes))
    metricas = {"Documentos analizados": entero(len(partes)), "Huecos": entero(len(solo_huecos)),
                "Números faltantes": entero(total_faltantes), "Números repetidos": entero(len(repetidos))}
    resumen = (f"Faltan {entero(total_faltantes)} números en {entero(len(solo_huecos))} huecos de la secuencia"
               if total_faltantes else "La numeración no presenta huecos")
    if len(repetidos):
        resumen += (" y 1 número aparece repetido." if len(repetidos) == 1
                    else f" y {entero(len(repetidos))} números aparecen repetidos.")
    else:
        resumen += "."
    if sin_numero:
        resumen += f" {entero(sin_numero)} documentos no tienen parte numérica y no se analizaron."
    tablas = {"Números repetidos": repetidos} if len(repetidos) else {}
    return ResultadoPrueba(resumen, huecos, metricas, tablas,
                           hay_excepciones=bool(total_faltantes or len(repetidos)))


@prueba(
    clave="calidad_datos",
    nombre="Calidad de los datos",
    categoria=CATEGORIA,
    nia="NIA 500",
    objetivo="Evaluar si la información es completa y exacta antes de usarla como evidencia.",
    interpretacion=(
        "Antes de confiar en un reporte del sistema, la NIA 500 exige evaluar su exactitud e integridad. "
        "Campos vacíos, valores en cero o negativos y fechas futuras suelen indicar errores de extracción, "
        "registros incompletos o manipulaciones. Documente las causas con el área responsable."
    ),
    requeridos=(),
    parametros=(
        Parametro("fecha_limite", "Fecha de corte", "fecha", None,
                  "Fechas posteriores se reportan como futuras. Vacío = hoy."),
    ),
)
def calidad_datos(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    campos = [c for c in ("fecha", "monto", "tercero", "nit", "documento") if c in std.columns]
    if not campos:
        raise ValueError("Mapea al menos uno de estos campos: fecha, valor, tercero, NIT o documento.")
    problemas = pd.Series([[] for _ in range(len(std))], index=std.index)

    def marcar(mascara: pd.Series, texto: str):
        for i in mascara[mascara].index:
            problemas.at[i].append(texto)

    for campo in campos:
        marcar(std[campo].isna(), f"{CAMPOS[campo].etiqueta} vacío")
    if "monto" in std:
        marcar(std["monto"] == 0, "Valor en cero")
        marcar(std["monto"] < 0, "Valor negativo")
    if "fecha" in std:
        limite = pd.Timestamp(p.get("fecha_limite") or pd.Timestamp.today().normalize())
        marcar(std["fecha"] > limite, "Fecha futura")
    con_problema = problemas[problemas.map(len) > 0]
    hallazgos = std.loc[con_problema.index, columnas_salida(std)].copy()
    hallazgos.insert(1, "problemas", con_problema.map("; ".join))
    conteo = pd.Series([t for lista in con_problema for t in lista]).value_counts()
    tabla = pd.DataFrame({"Problema": conteo.index, "Registros": conteo.values})
    tabla["% del total"] = (tabla["Registros"] / len(std)).map(porcentaje)
    graficas = [barras(tabla["Problema"], tabla["Registros"], "Registros por tipo de problema", horizontal=True,
                       texto_hover="%{y}: %{x:,.0f} registros<extra></extra>")] if len(tabla) else []
    proporcion = len(con_problema) / len(std) if len(std) else 0
    resumen = (f"{entero(len(con_problema))} registros ({porcentaje(proporcion)}) tienen al menos un problema."
               if len(con_problema) else "No se encontraron problemas de calidad en los campos mapeados.")
    return ResultadoPrueba(resumen, hallazgos,
                           {"Registros": entero(len(std)), "Con problemas": entero(len(con_problema)),
                            "% con problemas": porcentaje(proporcion)},
                           {"Resumen por problema": tabla}, graficas, hay_excepciones=bool(len(con_problema)))


@prueba(
    clave="nit_invalido",
    nombre="Validación de NIT",
    categoria=CATEGORIA,
    nia="NIA 500 · NIA 240",
    objetivo="Detectar NIT con dígito de verificación errado y terceros con identificación inconsistente.",
    interpretacion=(
        "Un dígito de verificación incorrecto indica un NIT mal digitado o inexistente; confírmelo en el RUT. "
        "Un mismo NIT con varios nombres, o un mismo nombre con varios NIT, puede indicar terceros ficticios, "
        "pagos desviados o una base de terceros sin depurar."
    ),
    requeridos=("nit",),
    opcionales=("dv", "tercero"),
    parametros=(
        Parametro("incluir_sin_dv", "Reportar NIT sin dígito de verificación", "opcion", "No", opciones=("No", "Sí")),
    ),
)
def nit_invalido(std: pd.DataFrame, p: dict) -> ResultadoPrueba:
    dv = std["dv"] if "dv" in std else pd.Series(None, index=std.index, dtype="object")
    pares = pd.DataFrame({"nit": std["nit"], "dv": dv})
    estados = {par: colombia.validar_nit(*par) for par in pares.drop_duplicates().itertuples(index=False, name=None)}
    estado = pd.Series([estados[par] for par in pares.itertuples(index=False, name=None)], index=std.index)
    excluidos = {colombia.ESTADO_VALIDO, colombia.ESTADO_VACIO}
    if p["incluir_sin_dv"] == "No":
        excluidos.add(colombia.ESTADO_SIN_DV)
    malos = estado[~estado.isin(excluidos)]
    hallazgos = std.loc[malos.index, columnas_salida(std)].copy()
    hallazgos.insert(1, "estado_nit", malos)
    if (malos == colombia.ESTADO_DV_INCORRECTO).any():
        numeros = std.loc[malos.index, "nit"].map(lambda v: colombia.separar_nit(v)[0])
        hallazgos["dv_correcto"] = [colombia.calcular_dv(n) if n and len(n) >= 5 else None for n in numeros]

    conteo = estado.value_counts()
    tablas = {"Estado de los NIT": pd.DataFrame({"Estado": conteo.index, "Registros": conteo.values})}
    inconsistentes = 0
    if "tercero" in std:
        terceros = pd.DataFrame({
            "nit": std["nit"].map(lambda v: colombia.separar_nit(v)[0]),
            "tercero": std["tercero"],
            "nombre": std["tercero"].map(lambda t: normalizar(t) if pd.notna(t) else None),
        }).dropna()
        varios_nombres = terceros.groupby("nit").agg(nombres=("nombre", "nunique"),
                                                   variantes=("tercero", lambda s: " | ".join(sorted(set(s)))))
        varios_nombres = varios_nombres[varios_nombres["nombres"] > 1].reset_index()
        varios_nit = terceros.groupby("nombre").agg(nits=("nit", "nunique"), tercero=("tercero", "first"),
                                                  lista=("nit", lambda s: ", ".join(sorted(set(s)))))
        varios_nit = varios_nit[varios_nit["nits"] > 1].reset_index(drop=True)
        inconsistentes = len(varios_nombres) + len(varios_nit)
        if len(varios_nombres):
            tablas["Un NIT con varios nombres"] = varios_nombres.rename(
                columns={"nit": "NIT", "nombres": "Nombres distintos", "variantes": "Variantes"})
        if len(varios_nit):
            tablas["Un nombre con varios NIT"] = varios_nit[["tercero", "nits", "lista"]].rename(
                columns={"tercero": "Tercero", "nits": "NIT distintos", "lista": "NIT"})
    nits_distintos = std.loc[malos.index, "nit"].nunique()
    resumen = f"{entero(len(malos))} registros ({entero(nits_distintos)} NIT distintos) tienen un NIT con problemas"
    resumen += f" y hay {entero(inconsistentes)} inconsistencias entre NIT y nombre." if "tercero" in std else "."
    return ResultadoPrueba(
        resumen, hallazgos,
        {"NIT con problemas": entero(nits_distintos),
         "Registros afectados": entero(len(malos)),
         "Inconsistencias NIT-nombre": entero(inconsistentes)},
        tablas, hay_excepciones=bool(len(malos) or inconsistentes))
