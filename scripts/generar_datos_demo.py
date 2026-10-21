"""Genera los datos de demostración en datos_demo/ con anomalías sembradas a propósito.

    python scripts/generar_datos_demo.py

Los terceros son ficticios. Las anomalías sembradas permiten comprobar que cada prueba
del catálogo detecta lo que debe (ver tests/test_demo.py).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from core.colombia import calcular_dv, festivos  # noqa: E402

SEMILLA = 2025
# Parámetro de Dirichlet para repartir pagos entre proveedores: más alto = reparto más parejo.
CONCENTRACION = 3.0
# Montos de pagos rutinarios: lognormal con mediana ~ $ 630.000 (sigue Benford por su dispersión amplia).
MEDIA_LOG, DESVIACION_LOG = 13.2, 1.8
DESTINO = RAIZ / "datos_demo"

PROVEEDORES = [
    "Distribuidora El Roble SAS", "Ferretería La Esperanza Ltda", "Transportes Andinos SAS",
    "Papelería Central del Valle SAS", "Servicios Integrales JM SAS", "Aseo Total Bogotá SAS",
    "Comercializadora Rionegro SAS", "Soluciones TIC del Caribe SAS", "Metalmecánica Sabana SAS",
    "Consultores Asociados Medellín SAS", "Logística Pacífico SAS", "Empaques Flexibles Cali SAS",
    "Insumos Agrícolas Huila SAS", "Vigilancia Privada Centinela Ltda", "Cafetería Don Aurelio",
    "Combustibles La Ruta SAS", "Publicidad Creativa Norte SAS", "Mantenimientos Industriales MI SAS",
    "Arrendamientos Torre 93 SAS", "Software Contable Andino SAS", "Textiles Boyacá SAS",
    "Químicos y Reactivos Antioquia SAS", "Seguridad Electrónica Delta SAS", "Restaurante Sabor Criollo",
    "Mensajería Express Llanos SAS", "Construcciones Bahía SAS", "Eléctricos del Eje SAS",
    "Abogados Ruiz & Asociados SAS", "Imprenta Moderna Pereira SAS", "Laboratorio Clínico Vida SAS",
]
USUARIOS = ["jperez", "mrodriguez", "agomez", "lcastro"]
CUENTAS = {"220505": "Proveedores nacionales", "233525": "Honorarios", "233550": "Servicios públicos",
           "233595": "Otros costos y gastos por pagar", "220510": "Proveedores del exterior"}


def nit_con_dv(numero: int, dv_correcto: bool = True) -> str:
    dv = calcular_dv(str(numero))
    return f"{numero}-{dv if dv_correcto else (dv + 3) % 10}"


def formato_colombiano(valor: float) -> str:
    entero_txt, decimales = f"{abs(valor):,.2f}".split(".")
    texto = entero_txt.replace(",", ".") + "," + decimales
    return f"-{texto}" if valor < 0 else texto


def dias_habiles(anio: int) -> list[date]:
    no_habiles = set(festivos(anio))
    inicio, fin = date(anio, 1, 2), date(anio, 12, 31)
    return [inicio + timedelta(d) for d in range((fin - inicio).days + 1)
            if (inicio + timedelta(d)).weekday() < 5 and (inicio + timedelta(d)) not in no_habiles]


def generar_pagos(rng: np.random.Generator) -> pd.DataFrame:
    terceros = pd.DataFrame({"tercero": PROVEEDORES,
                             "numero": rng.choice(np.arange(800_000_000, 901_999_999), len(PROVEEDORES), replace=False)})
    terceros["nit"] = [nit_con_dv(n) for n in terceros["numero"]]
    # NIT con dígito de verificación errado.
    for i in (7, 15, 23):
        terceros.loc[i, "nit"] = nit_con_dv(terceros.loc[i, "numero"], dv_correcto=False)
    terceros["cuenta"] = rng.choice(list(CUENTAS), len(terceros), p=[0.55, 0.15, 0.1, 0.15, 0.05])
    habiles = dias_habiles(2025)

    filas = []

    def pago(t, fecha, valor, usuario=None):
        tercero = terceros.iloc[t]
        filas.append({"fecha": fecha, "tercero": tercero["tercero"], "nit": tercero["nit"],
                      "cuenta": tercero["cuenta"], "valor": round(float(valor), 2),
                      "usuario": usuario or USUARIOS[int(rng.integers(len(USUARIOS)))]})

    pesos_tercero = rng.dirichlet(np.ones(len(terceros)) * CONCENTRACION)
    for _ in range(1850):
        pago(int(rng.choice(len(terceros), p=pesos_tercero)), habiles[int(rng.integers(len(habiles)))],
             rng.lognormal(mean=MEDIA_LOG, sigma=DESVIACION_LOG))
    # Montos redondos concentrados en dos terceros.
    for _ in range(35):
        pago(int(rng.choice([4, 18])), habiles[int(rng.integers(len(habiles)))], int(rng.integers(1, 15)) * 1_000_000)
    # Pagos justo por debajo del tope de autorización de $ 10.000.000 (exceso de 9 en Benford).
    for _ in range(45):
        pago(int(rng.choice([2, 9, 25])), habiles[int(rng.integers(len(habiles)))], rng.uniform(9_500_000, 9_990_000))
    # Fraccionamiento: tres grupos de pagos que juntos superan el tope en menos de una semana.
    for t, inicio, montos in ((11, date(2025, 3, 10), (4_200_000, 4_500_000, 3_900_000)),
                              (17, date(2025, 7, 14), (6_100_000, 5_800_000)),
                              (26, date(2025, 10, 6), (3_300_000, 3_450_000, 3_200_000, 2_900_000))):
        for k, monto in enumerate(montos):
            pago(t, inicio + timedelta(days=k), monto + rng.uniform(0, 50_000))
    # Registros en fines de semana y festivos, casi todos por el mismo usuario.
    fines = [d for d in (date(2025, 1, 1) + timedelta(n) for n in range(365)) if d.weekday() >= 5]
    for _ in range(22):
        pago(int(rng.integers(len(terceros))), fines[int(rng.integers(len(fines)))], rng.lognormal(14.6, 1.0),
             usuario="admin")
    for festivo in list(festivos(2025))[2:9]:
        pago(int(rng.integers(len(terceros))), festivo, rng.lognormal(14.6, 1.0), usuario="admin")
    # Diciembre: un proveedor triplica sus pagos y aparece uno nuevo.
    diciembre = [d for d in habiles if d.month == 12]
    for _ in range(8):
        pago(13, diciembre[int(rng.integers(len(diciembre)))], rng.uniform(15_000_000, 22_000_000))

    pagos = pd.DataFrame(filas)
    nuevo = {"fecha": date(2025, 12, 18), "tercero": "Asesorías Express Global SAS", "nit": nit_con_dv(901_777_123),
             "cuenta": "233525", "valor": 48_000_000.0, "usuario": "admin"}
    pagos = pd.concat([pagos, pd.DataFrame([nuevo])], ignore_index=True)
    pagos = pagos.sort_values("fecha", kind="stable").reset_index(drop=True)

    # Pagos dobles: misma fecha, tercero y valor con otro comprobante.
    dobles = pagos.sample(6, random_state=SEMILLA)
    pagos = pd.concat([pagos, dobles], ignore_index=True).sort_values("fecha", kind="stable").reset_index(drop=True)

    pagos["comprobante"] = [f"CE-{1001 + i}" for i in range(len(pagos))]
    # Huecos: comprobantes que no aparecen (se eliminan filas) y un número repetido.
    pagos = pagos.drop(index=[120, 121, 122, 640, 1333, 1790]).reset_index(drop=True)
    pagos.loc[900, "comprobante"] = pagos.loc[899, "comprobante"]
    # Variantes de nombre para un mismo NIT y dos NIT para un mismo nombre.
    variante = pagos.index[pagos["tercero"] == PROVEEDORES[4]][:5]
    pagos.loc[variante, "tercero"] = "Servicios Integrales J.M. S.A.S."
    otro_nit = pagos.index[pagos["tercero"] == PROVEEDORES[14]][:3]
    pagos.loc[otro_nit, "nit"] = nit_con_dv(79_456_123)
    # Problemas de calidad: valores en cero, terceros vacíos y una fecha futura.
    pagos.loc[[50, 51, 52], "valor"] = 0.0
    pagos.loc[[300, 301], "tercero"] = None
    pagos.loc[1500, "fecha"] = date(2026, 12, 15)

    pagos["descripcion"] = "Pago factura FV-" + pd.Series(rng.integers(1000, 99999, len(pagos))).astype(str)
    salida = pd.DataFrame({
        "Fecha": [d.strftime("%d/%m/%Y") for d in pagos["fecha"]],
        "Comprobante": pagos["comprobante"],
        "NIT": pagos["nit"],
        "Razón social": pagos["tercero"],
        "Cuenta": pagos["cuenta"],
        "Concepto": pagos["descripcion"],
        "Valor": [formato_colombiano(v) for v in pagos["valor"]],
        "Elaborado por": pagos["usuario"],
    })
    return salida


def generar_cartera(rng: np.random.Generator) -> pd.DataFrame:
    clientes = [f"Cliente {nombre}" for nombre in (
        "Almacenes La 14 Sur", "Droguería San Rafael", "Hotel Mirador", "Colegio Los Pinos", "Clínica del Norte",
        "Supermercado La Economía", "Constructora Altos", "Taller Automotriz Ruta 45", "Panadería Trigo Fino",
        "Hacienda El Paraíso", "Gimnasio Fuerza Vital", "Cooperativa Agraria del Sur")]
    corte = date(2025, 12, 31)
    filas = []
    for i in range(420):
        c = int(rng.integers(len(clientes)))
        antiguedad = int(rng.exponential(70 if c not in (3, 9) else 400))
        emision = corte - timedelta(days=min(antiguedad, 900))
        plazo = int(rng.choice([30, 60, 90]))
        filas.append({
            "No. Factura": f"FE{5000 + i}",
            "Cliente": clientes[c],
            "Fecha factura": emision,
            "Fecha vencimiento": emision + timedelta(days=plazo),
            "Saldo pendiente": round(float(rng.lognormal(15.2, 1.0)), 0),
        })
    return pd.DataFrame(filas).sort_values("Fecha factura").reset_index(drop=True)


def main():
    rng = np.random.default_rng(SEMILLA)
    DESTINO.mkdir(exist_ok=True)
    pagos = generar_pagos(rng)
    pagos.to_csv(DESTINO / "pagos_proveedores_2025.csv", sep=";", index=False, encoding="utf-8-sig")
    cartera = generar_cartera(rng)
    cartera.to_excel(DESTINO / "cartera_clientes_2025.xlsx", index=False, sheet_name="Cartera")
    print(f"Pagos: {len(pagos)} filas · Cartera: {len(cartera)} filas -> {DESTINO}")


if __name__ == "__main__":
    main()
