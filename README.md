# Dataudit

Plataforma de BI y auditoría de datos para pymes colombianas. Un auditor sin conocimientos técnicos
carga los reportes de su cliente, ejecuta pruebas de auditoría precargadas, selecciona muestras
estadísticas y exporta papeles de trabajo con trazabilidad completa.

## Ejecutar

```bash
pip install -r requirements.txt
streamlit run app.py
```

En la página de inicio, **Cargar datos de demostración** carga un año de pagos a proveedores y una
cartera de clientes ficticios, con anomalías sembradas para que cada prueba encuentre algo.

Para las preguntas en lenguaje natural, copia `.streamlit/secrets.toml.example` como
`.streamlit/secrets.toml` y agrega tu `OPENAI_API_KEY`. Al modelo solo se envían el esquema y hasta
3 valores de ejemplo por columna, nunca los datos completos.

## Qué incluye (Fase 1)

| Módulo | Contenido |
|---|---|
| Carga y mapeo | CSV/Excel de cualquier ERP; detecta `;`, codificación latin-1, fechas `dd/mm/aaaa` y valores `1.234.567,89`. El auditor asigna una vez qué columna es la fecha, el valor, el NIT, etc. |
| Integridad de datos | Duplicados configurables, huecos en la numeración, calidad de datos, validación de NIT (dígito de verificación DIAN e inconsistencias NIT-nombre) |
| Detección de fraude | Ley de Benford (1 y 2 dígitos, MAD de Nigrini), montos redondos, registros en fines de semana y festivos de Colombia, fraccionamiento de compras |
| Análisis por ciclo | Antigüedad de saldos (cartera / CxP), variación entre periodos por tercero o cuenta |
| Muestreo (NIA 530) | Tamaño por atributos (binomial) y MUS; selección aleatoria, sistemática, MUS y estratificada; partidas clave; semilla reproducible |
| Papeles de trabajo | Excel con objetivo, NIA, archivo de origen, huella SHA-256, mapeo, parámetros, semilla, resultado, conclusión y firmas |
| Explorar (BI) | SQL de solo lectura sobre DuckDB, preguntas en lenguaje natural y gráficas rápidas |

## Estructura

```
app.py                 navegación de Streamlit
vistas/                páginas (inicio, datos, pruebas, muestreo, explorar)
ui/                    estado de sesión y componentes de interfaz
core/                  lógica sin Streamlit (reutilizable en una API futura)
  loader.py            lectura de archivos y huella SHA-256
  mapping.py           campos semánticos y conversión de formatos colombianos
  datasets.py          conjunto de datos + mapeo + ficha de trazabilidad
  engine.py            DuckDB de solo lectura: un solo SELECT, sin acceso a archivos, límite de filas y tiempo
  nl2sql.py            lenguaje natural -> SQL validado
  colombia.py          dígito de verificación del NIT y festivos (Ley 51 de 1983)
  muestreo.py          tamaños y métodos de selección
  papeles.py           exportación a Excel
  pruebas/             catálogo de pruebas de auditoría
datos_demo/            datos ficticios (regenerables con scripts/generar_datos_demo.py)
tests/                 pruebas automatizadas (núcleo, datos demo e interfaz)
```

## Agregar una prueba al catálogo

Escribe una función en el módulo de su categoría (`core/pruebas/integridad.py`, `fraude.py` o
`ciclos.py`) y decórala con `@prueba(...)`. La interfaz, los parámetros y la exportación se generan
solos:

```python
@prueba(
    clave="mi_prueba", nombre="Mi prueba", categoria="Detección de fraude", nia="NIA 240",
    objetivo="Qué busca la prueba.", interpretacion="Cómo leer el resultado.",
    requeridos=("fecha", "monto"),
    parametros=(Parametro("umbral", "Umbral", "numero", 1_000_000.0),),
)
def mi_prueba(std, p):
    hallazgos = std[std["monto"] > p["umbral"]]
    return ResultadoPrueba(f"{len(hallazgos)} registros superan el umbral.", hallazgos,
                           hay_excepciones=bool(len(hallazgos)))
```

## Pruebas automatizadas

```bash
pip install -r requirements-dev.txt
pytest
```
