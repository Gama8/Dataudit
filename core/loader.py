"""Lectura de archivos CSV / Excel tal como los exportan los ERPs y paquetes contables."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata

import pandas as pd

EXTENSIONES = ("csv", "txt", "xlsx")
_CODIFICACIONES = ("utf-8-sig", "cp1252", "latin-1")


def huella(contenido: bytes) -> str:
    """SHA-256 del archivo: permite demostrar que la evidencia no cambió."""
    return hashlib.sha256(contenido).hexdigest()


def hojas_excel(contenido: bytes) -> list[str]:
    return pd.ExcelFile(io.BytesIO(contenido)).sheet_names


def _decodificar(contenido: bytes) -> str:
    for codificacion in _CODIFICACIONES:
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1", errors="replace")


def _separador(texto: str) -> str:
    muestra = "\n".join(texto.splitlines()[:50])
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def leer_archivo(nombre: str, contenido: bytes, hoja: str | None = None) -> pd.DataFrame:
    """Lee un CSV o Excel. Todo el texto se conserva tal cual; la conversión de tipos ocurre en el mapeo."""
    extension = nombre.rsplit(".", 1)[-1].lower()
    if extension == "xlsx":
        df = pd.read_excel(io.BytesIO(contenido), sheet_name=hoja or 0)
    elif extension in ("csv", "txt"):
        texto = _decodificar(contenido)
        df = pd.read_csv(io.StringIO(texto), sep=_separador(texto), dtype=str, keep_default_na=False,
                         na_values=[""], skipinitialspace=True)
    else:
        raise ValueError(f"Formato no soportado: .{extension}. Usa {', '.join(EXTENSIONES)}.")
    df.columns = [str(c).strip() or f"columna_{i + 1}" for i, c in enumerate(df.columns)]
    # Se conserva el índice original para que cada hallazgo apunte a su fila real en el archivo.
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("El archivo no tiene filas con datos.")
    return df


def nombre_tabla(texto: str) -> str:
    """Convierte un nombre de archivo en un identificador SQL simple (pagos_2025.xlsx -> pagos_2025)."""
    base = texto.rsplit(".", 1)[0] if "." in texto else texto
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^0-9a-zA-Z]+", "_", base).strip("_").lower()
    if not base or base[0].isdigit():
        base = f"t_{base}"
    return base
