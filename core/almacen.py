"""Persistencia de tableros y hallazgos en SQLite.

Cada fila lleva un `espacio` (hoy siempre "local") para separar empresas cuando llegue el
modo multiempresa; el paso a PostgreSQL solo debería tocar este módulo.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.datasets import ahora

SEVERIDADES = ("Alta", "Media", "Baja")
ESTADOS = ("Abierto", "En seguimiento", "Cerrado")
CAMPOS_HALLAZGO = (
    "titulo", "conjunto", "prueba", "condicion", "criterio", "causa", "efecto", "recomendacion",
    "severidad", "estado", "responsable", "fecha_compromiso", "valor_afectado", "comentarios",
    "evidencia_json", "huella_datos", "origen", "creado_por",
)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS tableros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    espacio TEXT NOT NULL DEFAULT 'local',
    nombre TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS widgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tablero_id INTEGER NOT NULL REFERENCES tableros(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    sql TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    orden INTEGER NOT NULL,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hallazgos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    espacio TEXT NOT NULL DEFAULT 'local',
    codigo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    conjunto TEXT NOT NULL DEFAULT '',
    prueba TEXT NOT NULL DEFAULT '',
    condicion TEXT NOT NULL DEFAULT '',
    criterio TEXT NOT NULL DEFAULT '',
    causa TEXT NOT NULL DEFAULT '',
    efecto TEXT NOT NULL DEFAULT '',
    recomendacion TEXT NOT NULL DEFAULT '',
    severidad TEXT NOT NULL DEFAULT 'Media',
    estado TEXT NOT NULL DEFAULT 'Abierto',
    responsable TEXT NOT NULL DEFAULT '',
    fecha_compromiso TEXT NOT NULL DEFAULT '',
    valor_afectado REAL,
    comentarios TEXT NOT NULL DEFAULT '',
    evidencia_json TEXT NOT NULL DEFAULT '',
    huella_datos TEXT NOT NULL DEFAULT '',
    origen TEXT NOT NULL DEFAULT 'Manual',
    creado_por TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
"""


class Almacen:
    def __init__(self, ruta: str | Path, espacio: str = "local"):
        self.ruta = str(ruta)
        self.espacio = espacio
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._memoria = sqlite3.connect(":memory:", check_same_thread=False) if self.ruta == ":memory:" else None
        with self._con() as con:
            con.executescript(_ESQUEMA)

    @contextmanager
    def _con(self):
        con = self._memoria or sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            if self._memoria is None:
                con.close()

    @staticmethod
    def _momento() -> str:
        return ahora().strftime("%Y-%m-%d %H:%M")

    # --- Tableros ---------------------------------------------------------------------------
    def tableros(self) -> list[dict]:
        with self._con() as con:
            filas = con.execute("SELECT * FROM tableros WHERE espacio = ? ORDER BY id", (self.espacio,))
            return [dict(f) for f in filas]

    def crear_tablero(self, nombre: str, descripcion: str = "") -> int:
        with self._con() as con:
            cursor = con.execute("INSERT INTO tableros (espacio, nombre, descripcion, creado) VALUES (?, ?, ?, ?)",
                                 (self.espacio, nombre.strip() or "Tablero", descripcion, self._momento()))
            return cursor.lastrowid

    def renombrar_tablero(self, tablero_id: int, nombre: str, descripcion: str) -> None:
        with self._con() as con:
            con.execute("UPDATE tableros SET nombre = ?, descripcion = ? WHERE id = ? AND espacio = ?",
                        (nombre.strip() or "Tablero", descripcion, tablero_id, self.espacio))

    def eliminar_tablero(self, tablero_id: int) -> None:
        with self._con() as con:
            con.execute("DELETE FROM tableros WHERE id = ? AND espacio = ?", (tablero_id, self.espacio))

    def widgets(self, tablero_id: int) -> list[dict]:
        with self._con() as con:
            filas = con.execute(
                "SELECT w.* FROM widgets w JOIN tableros t ON t.id = w.tablero_id "
                "WHERE w.tablero_id = ? AND t.espacio = ? ORDER BY w.orden, w.id", (tablero_id, self.espacio))
            return [{**dict(f), "spec": json.loads(f["spec_json"])} for f in filas]

    def agregar_widget(self, tablero_id: int, titulo: str, sql: str, spec: dict) -> int:
        with self._con() as con:
            orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM widgets WHERE tablero_id = ?",
                                (tablero_id,)).fetchone()[0]
            cursor = con.execute(
                "INSERT INTO widgets (tablero_id, titulo, sql, spec_json, orden, creado) VALUES (?, ?, ?, ?, ?, ?)",
                (tablero_id, titulo.strip() or "Sin título", sql, json.dumps(spec, ensure_ascii=False, sort_keys=True),
                 orden, self._momento()))
            return cursor.lastrowid

    def eliminar_widget(self, widget_id: int) -> None:
        with self._con() as con:
            con.execute("DELETE FROM widgets WHERE id = ?", (widget_id,))

    def mover_widget(self, widget_id: int, paso: int) -> None:
        """Intercambia el widget con su vecino (paso -1 = antes, +1 = después)."""
        with self._con() as con:
            actual = con.execute("SELECT tablero_id FROM widgets WHERE id = ?", (widget_id,)).fetchone()
            if actual is None:
                return
            ids = [f[0] for f in con.execute("SELECT id FROM widgets WHERE tablero_id = ? ORDER BY orden, id",
                                             (actual[0],))]
            i = ids.index(widget_id)
            j = i + paso
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
                con.executemany("UPDATE widgets SET orden = ? WHERE id = ?",
                                [(posicion, wid) for posicion, wid in enumerate(ids, start=1)])

    # --- Hallazgos --------------------------------------------------------------------------
    def hallazgos(self) -> list[dict]:
        with self._con() as con:
            filas = con.execute("SELECT * FROM hallazgos WHERE espacio = ? ORDER BY id DESC", (self.espacio,))
            return [dict(f) for f in filas]

    def hallazgo(self, hallazgo_id: int) -> dict | None:
        with self._con() as con:
            fila = con.execute("SELECT * FROM hallazgos WHERE id = ? AND espacio = ?",
                               (hallazgo_id, self.espacio)).fetchone()
            return dict(fila) if fila else None

    def guardar_hallazgo(self, datos: dict, hallazgo_id: int | None = None) -> int:
        """Crea (sin id) o actualiza un hallazgo. Devuelve su id."""
        valores = {c: datos.get(c) for c in CAMPOS_HALLAZGO if c in datos}
        if "severidad" in valores and valores["severidad"] not in SEVERIDADES:
            raise ValueError(f"Severidad inválida: {valores['severidad']}")
        if "estado" in valores and valores["estado"] not in ESTADOS:
            raise ValueError(f"Estado inválido: {valores['estado']}")
        if not hallazgo_id and not str(valores.get("titulo") or "").strip():
            raise ValueError("El hallazgo necesita un título.")
        momento = self._momento()
        with self._con() as con:
            if hallazgo_id:
                asignaciones = ", ".join(f"{c} = ?" for c in valores)
                con.execute(f"UPDATE hallazgos SET {asignaciones}, actualizado = ? WHERE id = ? AND espacio = ?",
                            (*valores.values(), momento, hallazgo_id, self.espacio))
                return hallazgo_id
            # Máximo + 1 (no conteo) para no repetir códigos después de eliminar un hallazgo.
            consecutivo = con.execute(
                "SELECT COALESCE(MAX(CAST(SUBSTR(codigo, 3) AS INTEGER)), 0) + 1 FROM hallazgos WHERE espacio = ?",
                (self.espacio,)).fetchone()[0]
            columnas = ["espacio", "codigo", *valores, "creado", "actualizado"]
            cursor = con.execute(
                f"INSERT INTO hallazgos ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
                (self.espacio, f"H-{consecutivo:03d}", *valores.values(), momento, momento))
            return cursor.lastrowid

    def eliminar_hallazgo(self, hallazgo_id: int) -> None:
        with self._con() as con:
            con.execute("DELETE FROM hallazgos WHERE id = ? AND espacio = ?", (hallazgo_id, self.espacio))
