"""Regresiones de la migración a paquetes."""
import importlib
import unittest
from pathlib import Path


class CompatibilidadPaquetes(unittest.TestCase):
    def test_modulos_compatibles(self):
        pares = {
            "modulo_modelo_medicion": "dpi.medicion.modelo",
            "modulo_calculo_medicion": "dpi.medicion.calculo",
            "modulo_marcas_medicion": "dpi.medicion.marcas",
            "modulo_datos_medicion": "dpi.medicion.datos",
            "modulo_sesion_medicion": "dpi.medicion.sesion",
            "modulo_ewlw": "dpi.medicion.ewlw",
            "modulo_pith_nucleo": "dpi.medicion.pith",
            "modulo_intensidad_nucleo": "dpi.medicion.intensidad",
            "modulo_grafico_medicion": "dpi.medicion.grafico",
            "modulo_modelo_series": "dpi.series.modelo",
            "json_seguro": "dpi.infraestructura.json_seguro",
            "modulo_imagen": "dpi.infraestructura.imagen",
            "modulo_autodeteccion": "dpi.medicion.autodeteccion",
        }
        for anterior, nuevo in pares.items():
            with self.subTest(modulo=anterior):
                self.assertIs(importlib.import_module(anterior),
                              importlib.import_module(nuevo))

    def test_formatos_compatibles(self):
        import modulo_formatos as anterior
        for modulo, nombres in {
            "pos": ("leer_pos", "escribir_pos"),
            "wid": ("leer_wid",),
            "tucson": ("leer_tucson_multi", "escribir_tucson"),
            "compacto": ("leer_formato_compacto",),
            "planillas": ("_leer_planilla", "_escribir_excel"),
            "tabular": ("leer_tabular", "escribir_tabla"),
            "cronologias": ("_leer_cronologia_guardada",),
            "deteccion": ("leer_dendro_auto", "leer_series_auto"),
            "exportacion": ("exportar_serie_2col",),
        }.items():
            nuevo = importlib.import_module("dpi.formatos." + modulo)
            for nombre in nombres:
                self.assertIs(getattr(anterior, nombre), getattr(nuevo, nombre))

    def test_cronologia_compatible(self):
        from dpi.ciencia import cronologia, tendencias, autorregresion, estabilizacion
        self.assertIs(cronologia._spline_cook, tendencias._spline_cook)
        self.assertIs(cronologia._residualizar_indice, autorregresion._residualizar_indice)
        self.assertIs(cronologia.estabilizar_varianza, estabilizacion.estabilizar_varianza)

    def test_perfiles_fabrica(self):
        from dpi.medicion.autodeteccion import RUTA_PERFILES_FABRICA
        self.assertEqual(Path(RUTA_PERFILES_FABRICA).resolve(),
                         Path(__file__).resolve().parents[1] / "species_profiles.json")
        self.assertTrue(Path(RUTA_PERFILES_FABRICA).is_file())
