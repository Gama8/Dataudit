"""Conjunto de datos cargado por el auditor: archivo original, huella y mapeo de campos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.mapping import CAMPOS, aplicar_mapeo, sugerir_mapeo

# Colombia no tiene horario de verano: UTC-5 todo el año.
HORA_COLOMBIA = timezone(timedelta(hours=-5), "COT")


def ahora() -> datetime:
    return datetime.now(HORA_COLOMBIA)


@dataclass
class ConjuntoDatos:
    nombre: str  # nombre de la tabla en SQL
    archivo: str
    huella: str
    original: pd.DataFrame
    hoja: str | None = None
    cargado: datetime = field(default_factory=ahora)
    mapeo: dict[str, str | None] = field(default_factory=dict)
    std: pd.DataFrame | None = None
    reporte_mapeo: pd.DataFrame | None = None

    def __post_init__(self):
        if not self.mapeo:
            self.aplicar_mapeo(sugerir_mapeo(self.original.columns))

    def aplicar_mapeo(self, mapeo: dict[str, str | None]) -> None:
        self.mapeo = {clave: (col if col in self.original.columns else None) for clave, col in mapeo.items()}
        self.std, self.reporte_mapeo = aplicar_mapeo(self.original, self.mapeo)

    def tabla_sql(self) -> pd.DataFrame:
        """Columnas originales; las mapeadas ya convertidas (número/fecha) para poder sumarlas o filtrarlas en SQL."""
        tabla = self.original.copy()
        for clave in self.campos_mapeados:
            tabla[self.mapeo[clave]] = self.std[clave]
        return tabla

    @property
    def campos_mapeados(self) -> list[str]:
        return [clave for clave in CAMPOS if self.mapeo.get(clave)]

    @property
    def filas(self) -> int:
        return len(self.original)

    def ficha(self) -> dict[str, str]:
        """Metadatos de trazabilidad que acompañan cada papel de trabajo."""
        return {
            "Conjunto de datos": self.nombre,
            "Archivo de origen": self.archivo + (f" (hoja: {self.hoja})" if self.hoja else ""),
            "Huella SHA-256": self.huella,
            "Filas": f"{self.filas:,}".replace(",", "."),
            "Cargado": self.cargado.strftime("%Y-%m-%d %H:%M %Z"),
            "Mapeo de campos": "; ".join(
                f"{CAMPOS[c].etiqueta} = {self.mapeo[c]}" for c in self.campos_mapeados) or "Sin mapeo",
        }
