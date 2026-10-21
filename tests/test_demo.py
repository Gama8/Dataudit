"""Cada prueba del catálogo debe encontrar las anomalías sembradas en datos_demo/."""
import io
from pathlib import Path

import pandas as pd
import pytest

from core import loader, papeles
from core.datasets import ConjuntoDatos
from core.pruebas import REGISTRO

DEMO = Path(__file__).resolve().parents[1] / "datos_demo"


def cargar(nombre: str) -> ConjuntoDatos:
    contenido = (DEMO / nombre).read_bytes()
    return ConjuntoDatos(loader.nombre_tabla(nombre), nombre, loader.huella(contenido),
                         loader.leer_archivo(nombre, contenido))


@pytest.fixture(scope="module")
def pagos() -> ConjuntoDatos:
    return cargar("pagos_proveedores_2025.csv")


@pytest.fixture(scope="module")
def cartera() -> ConjuntoDatos:
    return cargar("cartera_clientes_2025.xlsx")


def ejecutar(clave: str, datos: ConjuntoDatos, **parametros):
    prueba = REGISTRO[clave]
    assert not prueba.faltantes(datos.campos_mapeados)
    return prueba.ejecutar(datos.std, {**prueba.valores_defecto(), **parametros})


def test_mapeo_automatico(pagos, cartera):
    assert pagos.mapeo["fecha"] == "Fecha" and pagos.mapeo["monto"] == "Valor"
    assert pagos.mapeo["tercero"] == "Razón social" and pagos.mapeo["usuario"] == "Elaborado por"
    assert pagos.reporte_mapeo["No convertidos"].sum() == 0
    texto = pagos.original["Valor"]  # formato colombiano: 1.234.567,89
    assert texto.str.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}").all()
    esperado = texto.str.replace(".", "").str.replace(",", ".").astype(float)
    assert (pagos.std["monto"] == esperado).all()
    assert pagos.original["Fecha"].iloc[0] == "02/01/2025" and pagos.std["fecha"].iloc[0] == pd.Timestamp("2025-01-02")
    assert cartera.mapeo["fecha_vencimiento"] == "Fecha vencimiento" and cartera.mapeo["tercero"] == "Cliente"


def test_duplicados(pagos):
    r = ejecutar("duplicados", pagos)
    assert r.hallazgos["grupo"].nunique() >= 6
    assert r.hallazgos["fila"].iloc[0] >= 2


def test_huecos(pagos):
    r = ejecutar("huecos_consecutivo", pagos)
    assert r.hallazgos["Faltantes"].sum() >= 6
    assert len(r.tablas["Números repetidos"]) == 1


def test_calidad(pagos):
    r = ejecutar("calidad_datos", pagos, fecha_limite=pd.Timestamp("2025-12-31"))
    problemas = " ".join(r.hallazgos["problemas"])
    assert problemas.count("Valor en cero") == 3 and "Fecha futura" in problemas


def test_nit(pagos):
    r = ejecutar("nit_invalido", pagos)
    assert set(r.hallazgos["estado_nit"]) == {"DV incorrecto"}
    assert "Un NIT con varios nombres" in r.tablas and "Un nombre con varios NIT" in r.tablas


def test_benford(pagos):
    r = ejecutar("benford", pagos)
    assert 9 in r.hallazgos["digito"].unique()
    r2 = ejecutar("benford", pagos, digitos="Primeros dos dígitos")
    assert len(r2.tablas["Distribución de dígitos"]) == 90


def test_redondos(pagos):
    r = ejecutar("montos_redondos", pagos)
    assert len(r.hallazgos) >= 30


def test_dias_no_habiles(pagos):
    r = ejecutar("dias_no_habiles", pagos)
    assert (r.hallazgos["usuario"] == "admin").sum() >= 25
    assert "Festivos con movimientos" in r.tablas


def test_fraccionamiento(pagos):
    r = ejecutar("fraccionamiento", pagos)
    terceros = set(r.tablas["Resumen por grupo"]["Tercero"])
    assert {"Empaques Flexibles Cali SAS", "Mantenimientos Industriales MI SAS", "Eléctricos del Eje SAS"} <= terceros
    # Los pagos justo por debajo del tope encabezan la lista.
    primero = r.tablas["Resumen por grupo"].iloc[0]["Tercero"]
    assert primero in {"Transportes Andinos SAS", "Consultores Asociados Medellín SAS", "Construcciones Bahía SAS"}


def test_antiguedad(cartera):
    r = ejecutar("antiguedad_saldos", cartera)
    assert len(r.tablas["Saldos por rango"]) == 7
    assert r.hallazgos["dias_vencido"].min() > 90


def test_variacion(pagos):
    r = ejecutar("variacion_analitica", pagos, hasta=pd.Timestamp("2025-12-31"))
    terceros = set(r.hallazgos["Tercero (nombre)"])
    assert "Asesorías Express Global SAS" in terceros and "Vigilancia Privada Centinela Ltda" in terceros


@pytest.mark.parametrize("clave", sorted(REGISTRO))
def test_papel_de_trabajo(pagos, cartera, clave):
    datos = cartera if clave == "antiguedad_saldos" else pagos
    r = ejecutar(clave, datos)
    contenido = papeles.papel_de_trabajo(REGISTRO[clave].nombre, datos.ficha(),
                                         {"Hallazgos": r.hallazgos, **r.tablas}, r.resumen, "Sin observaciones.")
    libro = pd.ExcelFile(io.BytesIO(contenido))
    assert libro.sheet_names[0] == "Resumen" and "Hallazgos" in libro.sheet_names
