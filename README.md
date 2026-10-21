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

### Asistente (Gemini o Claude)

El Asistente es el mismo agente con dos proveedores. Copia `.streamlit/secrets.toml.example` como
`.streamlit/secrets.toml` (en Streamlit Community Cloud: *Settings → Secrets*) y agrega una clave:

| Proveedor | Clave | Dónde se crea | Costo |
|---|---|---|---|
| Gemini (Google) | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → *Get API key* | Nivel gratuito con límites de uso |
| Claude (Anthropic) | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Pago por uso (créditos prepagos) |

Si están las dos claves se usa Claude. Opciones:

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATAUDIT_PROVEEDOR` | según la clave disponible | `gemini` o `anthropic` |
| `DATAUDIT_MODELO` | `gemini-3.8-flash` / `claude-opus-5-5` | Con Claude, `claude-sonnet-5-5` cuesta la mitad por token |
| `DATAUDIT_ESFUERZO` | `high` | `medium` o `low` responden más rápido y gastan menos |
| `DATAUDIT_DB` | `datos_app/dataudit.db` | Base SQLite de tableros y hallazgos |

Privacidad (Ley 1581 de 2012): al proveedor se envían las preguntas, el esquema, hasta 3 valores de
ejemplo por columna y como máximo 50 filas de cada resultado; nunca el archivo completo. Las
herramientas se ejecutan en tu servidor sobre el motor de solo lectura. **En el nivel gratuito de
Gemini, según los términos de Google, lo enviado puede usarse para mejorar sus productos: úsalo con
datos de demostración o anonimizados.** Anthropic no usa los datos de su API para entrenar.

En Streamlit Community Cloud el disco no es permanente: los tableros y hallazgos se pierden al
reiniciar la app hasta que la Fase 3 los lleve a PostgreSQL.

## Qué incluye

**Fase 2: BI + IA**

| Módulo | Contenido |
|---|---|
| Asistente | Agente con Gemini o Claude, al estilo de Cortex Code: revisa el esquema, escribe y corrige SQL, grafica, ejecuta pruebas del catálogo, selecciona muestras y redacta borradores de hallazgos, mostrando cada paso |
| Tableros | Gráficas, tablas y KPI fijados desde el Asistente o Explorar; guardan la consulta y se recalculan con los datos actuales |
| Hallazgos | Registro con condición, criterio, causa, efecto, recomendación, severidad, estado, responsable y evidencia adjunta; informe en Excel |

**Fase 1: núcleo de auditoría**

| Módulo | Contenido |
|---|---|
| Carga y mapeo | CSV/Excel de cualquier ERP; detecta `;`, codificación latin-1, fechas `dd/mm/aaaa` y valores `1.234.567,89`. El auditor asigna una vez qué columna es la fecha, el valor, el NIT, etc. |
| Integridad de datos | Duplicados configurables, huecos en la numeración, calidad de datos, validación de NIT (dígito de verificación DIAN e inconsistencias NIT-nombre) |
| Detección de fraude | Ley de Benford (1 y 2 dígitos, MAD de Nigrini), montos redondos, registros en fines de semana y festivos de Colombia, fraccionamiento de compras |
| Análisis por ciclo | Antigüedad de saldos (cartera / CxP), variación entre periodos por tercero o cuenta |
| Muestreo (NIA 530) | Tamaño por atributos (binomial) y MUS; selección aleatoria, sistemática, MUS y estratificada; partidas clave; semilla reproducible |
| Papeles de trabajo | Excel con objetivo, NIA, archivo de origen, huella SHA-256, mapeo, parámetros, semilla, resultado, conclusión y firmas |
| Explorar con SQL | SQL de solo lectura sobre DuckDB y gráficas rápidas |

## Estructura

```
app.py                 navegación de Streamlit
vistas/                páginas (inicio, asistente, datos, pruebas, muestreo, hallazgos, tableros, explorar)
ui/                    estado de sesión y componentes de interfaz
core/                  lógica sin Streamlit (reutilizable en una API futura)
  asistente.py         agente: herramientas, instrucciones comunes y bucle con Claude
  asistente_gemini.py  bucle del mismo agente con Gemini
  almacen.py           SQLite para tableros y hallazgos (con `espacio` para multiempresa)
  visual.py            visualizaciones como especificación guardable
  loader.py            lectura de archivos y huella SHA-256
  mapping.py           campos semánticos y conversión de formatos colombianos
  datasets.py          conjunto de datos + mapeo + ficha de trazabilidad
  engine.py            DuckDB de solo lectura: un solo SELECT, sin acceso a archivos, límite de filas y tiempo
  colombia.py          dígito de verificación del NIT y festivos (Ley 51 de 1983)
  muestreo.py          tamaños y métodos de selección
  papeles.py           exportación a Excel
  pruebas/             catálogo de pruebas de auditoría
datos_demo/            datos ficticios (regenerables con scripts/generar_datos_demo.py)
tests/                 pruebas automatizadas (núcleo, datos demo, interfaz y asistente con cliente simulado)
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
