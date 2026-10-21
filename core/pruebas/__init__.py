"""Catálogo de pruebas de auditoría precargadas.

Para agregar una prueba: escribe una función `(std, parametros) -> ResultadoPrueba`
en el módulo de su categoría y decórala con `@prueba(...)`.
"""
from core.pruebas import ciclos, fraude, integridad  # noqa: F401  (registran sus pruebas al importarse)
from core.pruebas.base import CATEGORIAS, REGISTRO, Parametro, Prueba, ResultadoPrueba


def por_categoria() -> dict[str, list[Prueba]]:
    return {c: [p for p in REGISTRO.values() if p.categoria == c] for c in CATEGORIAS}


__all__ = ["CATEGORIAS", "REGISTRO", "Parametro", "Prueba", "ResultadoPrueba", "por_categoria"]
