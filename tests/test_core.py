from datetime import date

import pandas as pd
import pytest

from core import colombia, muestreo
from core.engine import ConsultaInvalida, MotorSQL, validar_select
from core.mapping import a_fecha, a_numero, sugerir_mapeo


class TestColombia:
    def test_dv_nit_dian(self):
        assert colombia.calcular_dv("800197268") == 4  # NIT de la DIAN
        assert colombia.calcular_dv("860.034.313") == 7  # Davivienda

    @pytest.mark.parametrize("valor, dv, estado", [
        ("800197268-4", None, colombia.ESTADO_VALIDO),
        ("800.197.268-4", None, colombia.ESTADO_VALIDO),
        ("800197268-5", None, colombia.ESTADO_DV_INCORRECTO),
        ("800197268", "4", colombia.ESTADO_VALIDO),
        ("800197268", None, colombia.ESTADO_SIN_DV),
        ("12", None, colombia.ESTADO_FORMATO),
        (None, None, colombia.ESTADO_VACIO),
    ])
    def test_validar_nit(self, valor, dv, estado):
        assert colombia.validar_nit(valor, dv) == estado

    def test_festivos_2025(self):
        f = colombia.festivos(2025)
        # 18 festivos, pero en 2025 San Pedro y Sagrado Corazón coinciden el 30 de junio.
        assert len(f) == 17
        assert len(colombia.festivos(2024)) == 18
        assert f[date(2025, 1, 6)] == "Reyes Magos"
        assert f[date(2025, 3, 24)] == "San José"  # 19 de marzo trasladado al lunes
        assert f[date(2025, 4, 18)] == "Viernes Santo"
        assert f[date(2025, 6, 2)] == "Ascensión del Señor"
        assert f[date(2025, 6, 23)] == "Corpus Christi"
        assert f[date(2025, 6, 30)] == "San Pedro y San Pablo / Sagrado Corazón"
        assert f[date(2025, 11, 17)] == "Independencia de Cartagena"
        assert colombia.nombre_festivo(pd.Timestamp("2025-12-25")) == "Navidad"
        assert colombia.nombre_festivo(date(2025, 12, 26)) is None


class TestMapeo:
    def test_numeros_formato_colombiano_y_us(self):
        serie = pd.Series(["1.234.567,89", "1,234,567.89", "$ 2.500.000", "(1.000)", "1500", "abc", None])
        assert a_numero(serie).tolist()[:5] == [1234567.89, 1234567.89, 2500000.0, -1000.0, 1500.0]
        assert a_numero(serie).isna().tolist()[5:] == [True, True]

    def test_fechas_dia_primero(self):
        assert a_fecha(pd.Series(["01/08/2025", "15/08/2025"])).tolist() == [pd.Timestamp("2025-08-01"),
                                                                              pd.Timestamp("2025-08-15")]
        assert a_fecha(pd.Series(["2025-08-01"])).iloc[0] == pd.Timestamp("2025-08-01")

    def test_sugerencia(self):
        mapeo = sugerir_mapeo(["Fecha", "Fecha vencimiento", "Razón social", "NIT", "Valor", "Comprobante", "id"])
        assert mapeo["fecha"] == "Fecha"
        assert mapeo["fecha_vencimiento"] == "Fecha vencimiento"
        assert mapeo["tercero"] == "Razón social"
        assert mapeo["monto"] == "Valor"
        assert mapeo["documento"] == "Comprobante"
        assert mapeo["cuenta"] is None


class TestMotor:
    def setup_method(self):
        self.motor = MotorSQL({"datos": pd.DataFrame({"a": range(50), "b": ["x"] * 50})})

    def test_select_y_limite(self):
        r = self.motor.ejecutar("SELECT a FROM datos ORDER BY a DESC", limite=10)
        assert r.truncado and len(r.datos) == 10 and r.datos["a"].iloc[0] == 49

    @pytest.mark.parametrize("sql", ["DROP TABLE datos", "SELECT 1; SELECT 2", "COPY datos TO 'x.csv'",
                                     "SET enable_external_access = true", "ATTACH 'x.db'", ""])
    def test_rechaza_no_lectura(self, sql):
        with pytest.raises(ConsultaInvalida):
            validar_select(sql)

    def test_sin_acceso_a_archivos(self):
        with pytest.raises(ConsultaInvalida, match="archivos"):
            self.motor.ejecutar("SELECT * FROM read_csv('C:/Windows/win.ini')")


class TestMuestreo:
    def test_tamano_atributos_aicpa(self):
        assert muestreo.tamano_atributos(0.95, 0.05, 0.0) == 59
        assert muestreo.tamano_atributos(0.90, 0.05, 0.0) == 45
        with pytest.raises(ValueError):
            muestreo.tamano_atributos(0.95, 0.05, 0.05)

    def test_tamano_mus(self):
        n, intervalo = muestreo.tamano_mus(1_000_000_000, 50_000_000, 0, 0.95)
        assert n == 60 and intervalo == pytest.approx(1_000_000_000 / 60)

    @pytest.fixture
    def poblacion(self):
        montos = [float(m) for m in range(1, 201)] + [5_000.0]
        return pd.DataFrame({"fila": range(2, 203), "monto": montos})

    @pytest.mark.parametrize("metodo", list(muestreo.METODOS))
    def test_reproducible_con_semilla(self, poblacion, metodo):
        a = muestreo.seleccionar(poblacion, metodo, 20, semilla=123)
        b = muestreo.seleccionar(poblacion, metodo, 20, semilla=123)
        assert a.muestra["fila"].tolist() == b.muestra["fila"].tolist()
        assert 0 < len(a.muestra) <= 20

    def test_mus_incluye_partidas_mayores_al_intervalo(self, poblacion):
        r = muestreo.seleccionar(poblacion, "mus", 20, semilla=7)
        assert 202 in r.muestra["fila"].tolist()  # 5.000 es mayor que el intervalo (~1.255)

    def test_partidas_clave(self, poblacion):
        r = muestreo.seleccionar(poblacion, "aleatorio", 10, semilla=1, umbral_clave=1_000)
        clave = r.muestra[r.muestra["motivo"].str.startswith("Partida clave")]
        assert clave["fila"].tolist() == [202] and len(r.muestra) == 11

    def test_estratificado_respeta_tamano(self, poblacion):
        r = muestreo.seleccionar(poblacion, "estratificado", 25, semilla=3, estratos=4)
        assert len(r.muestra) == 25 and r.muestra["estrato"].nunique() == 4
