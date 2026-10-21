"""Motor de consultas sobre DuckDB, de solo lectura.

Toda consulta (escrita por el usuario o generada por IA) pasa por `validar_select`
y se ejecuta en una conexión sin acceso a archivos externos y con la configuración
bloqueada, con límite de filas y de tiempo.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import duckdb
import pandas as pd
import pyarrow as pa
import sqlglot
from sqlglot import exp

LIMITE_FILAS = 10_000
TIEMPO_MAXIMO_S = 30

_NODOS_PROHIBIDOS = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Copy, exp.Set, exp.Pragma, exp.Use, exp.Transaction, exp.Commit, exp.Rollback,
)


class ConsultaInvalida(ValueError):
    """La consulta no es un SELECT permitido o falló al ejecutarse."""


@dataclass
class ResultadoConsulta:
    datos: pd.DataFrame
    truncado: bool
    sql: str


def validar_select(sql: str) -> str:
    """Devuelve la consulta limpia si es un único SELECT; si no, lanza ConsultaInvalida."""
    texto = (sql or "").strip().rstrip(";").strip()
    if not texto:
        raise ConsultaInvalida("La consulta está vacía.")
    try:
        arboles = [a for a in sqlglot.parse(texto, read="duckdb") if a is not None]
    except sqlglot.errors.ParseError as error:
        raise ConsultaInvalida(f"No se pudo interpretar la consulta: {error}") from error
    if len(arboles) != 1:
        raise ConsultaInvalida("Escribe una sola consulta a la vez.")
    arbol = arboles[0]
    if not isinstance(arbol, exp.Query) or any(arbol.find_all(*_NODOS_PROHIBIDOS)):
        raise ConsultaInvalida("Solo se permiten consultas de lectura (SELECT / WITH).")
    return texto


class MotorSQL:
    """Una conexión DuckDB en memoria con los conjuntos de datos registrados como tablas."""

    def __init__(self, tablas: dict[str, pd.DataFrame]):
        self.tablas = dict(tablas)
        self.con = duckdb.connect(":memory:")
        for nombre, df in self.tablas.items():
            self.con.register(nombre, df)
        # Sin lectura de archivos/URLs del servidor y sin posibilidad de reactivarla desde SQL.
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def esquema(self) -> dict[str, list[tuple[str, str]]]:
        """{tabla: [(columna, tipo), ...]} tal como los ve DuckDB."""
        resultado = {}
        for nombre in self.tablas:
            filas = self.con.execute(f'DESCRIBE "{nombre}"').fetchall()
            resultado[nombre] = [(f[0], f[1]) for f in filas]
        return resultado

    def ejecutar(self, sql: str, limite: int = LIMITE_FILAS, tiempo_maximo: float = TIEMPO_MAXIMO_S) -> ResultadoConsulta:
        consulta = validar_select(sql)
        temporizador = threading.Timer(tiempo_maximo, self.con.interrupt)
        temporizador.start()
        try:
            lector = self.con.execute(consulta).to_arrow_reader(min(limite + 1, 100_000))
            lotes, filas = [], 0
            for lote in lector:
                lotes.append(lote)
                filas += lote.num_rows
                if filas > limite:
                    break
            tabla = pa.Table.from_batches(lotes, schema=lector.schema)
        except duckdb.InterruptException as error:
            raise ConsultaInvalida(f"La consulta superó el tiempo máximo de {tiempo_maximo:.0f} s.") from error
        except duckdb.PermissionException as error:
            raise ConsultaInvalida("La consulta intenta leer archivos del servidor; solo puedes consultar "
                                   "los conjuntos de datos cargados.") from error
        except duckdb.Error as error:
            raise ConsultaInvalida(str(error).split("\n")[0]) from error
        finally:
            temporizador.cancel()
        truncado = tabla.num_rows > limite
        return ResultadoConsulta(tabla.slice(0, limite).to_pandas(), truncado, consulta)

    def cerrar(self) -> None:
        self.con.close()
