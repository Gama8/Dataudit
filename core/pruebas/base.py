"""Contrato común de las pruebas de auditoría del catálogo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go

CATEGORIAS = ("Integridad de datos", "Detección de fraude", "Análisis por ciclo")


@dataclass(frozen=True)
class Parametro:
    clave: str
    etiqueta: str
    tipo: str  # "entero" | "numero" | "porcentaje" | "fecha" | "opcion" | "campos"
    defecto: Any = None
    ayuda: str = ""
    opciones: tuple = ()
    minimo: float | None = None
    maximo: float | None = None


@dataclass
class ResultadoPrueba:
    resumen: str
    hallazgos: pd.DataFrame
    metricas: dict[str, str] = field(default_factory=dict)
    tablas: dict[str, pd.DataFrame] = field(default_factory=dict)
    graficas: list[go.Figure] = field(default_factory=list)
    hay_excepciones: bool = False


@dataclass(frozen=True)
class Prueba:
    clave: str
    nombre: str
    categoria: str
    nia: str
    objetivo: str
    interpretacion: str
    requeridos: tuple[str, ...]
    ejecutar: Callable[[pd.DataFrame, dict], ResultadoPrueba]
    opcionales: tuple[str, ...] = ()
    parametros: tuple[Parametro, ...] = ()

    def faltantes(self, campos_mapeados) -> list[str]:
        return [c for c in self.requeridos if c not in campos_mapeados]

    def valores_defecto(self) -> dict[str, Any]:
        return {p.clave: p.defecto for p in self.parametros}


REGISTRO: dict[str, Prueba] = {}


def prueba(**metadatos):
    """Decorador que registra una función como prueba del catálogo."""
    def registrar(funcion):
        if metadatos["categoria"] not in CATEGORIAS:
            raise ValueError(f"Categoría desconocida: {metadatos['categoria']}")
        REGISTRO[metadatos["clave"]] = Prueba(ejecutar=funcion, **metadatos)
        return funcion
    return registrar


def columnas_salida(std: pd.DataFrame, *extra: str) -> list[str]:
    """Columnas estándar para mostrar un hallazgo: fila del archivo + campos clave disponibles."""
    base = ["fila", "fecha", "documento", "nit", "tercero", "cuenta", "descripcion", "monto"]
    return [c for c in base if c in std.columns] + [c for c in extra if c not in base]
