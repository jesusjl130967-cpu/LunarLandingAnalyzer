import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lunar_analyzer.integrations import (
    IntegrationError,
    SPICE_META_KERNEL_ENV,
    _parse_horizons_vector,
    _resolve_ephemeris,
    search_lro_products,
)


WHEN = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


class IntegrationTests(unittest.TestCase):
    def tearDown(self):
        _resolve_ephemeris.cache_clear()

    def test_horizons_vector_parser_reads_scientific_notation(self):
        vector = _parse_horizons_vector(
            {"result": "X = 1.25D+08 Y = -2.0E+04 Z = 3.5"}
        )
        self.assertEqual(vector, (125_000_000.0, -20_000.0, 3.5))

    def test_horizons_data_is_used_and_spice_stays_explicitly_inactive(self):
        _resolve_ephemeris.cache_clear()
        with patch.dict(os.environ, {}, clear=True), patch(
            "lunar_analyzer.integrations._horizons_vector",
            side_effect=[(149_000_000.0, 1_000.0, 2_000.0), (-384_000.0, 1_000.0, 2_000.0)],
        ):
            solar, status = _resolve_ephemeris(WHEN.isoformat())
        self.assertIn("JPL Horizons", solar["ephemeris_model"])
        self.assertTrue(status["horizons"]["available"])
        self.assertFalse(status["spice"]["available"])
        self.assertGreater(solar["sun_moon_distance_km"], 148_000_000)
        self.assertAlmostEqual(sum(value * value for value in solar["sun_vector_lunar"]), 1.0, places=8)

    def test_fallback_is_reported_when_horizons_fails(self):
        _resolve_ephemeris.cache_clear()
        with patch.dict(os.environ, {}, clear=True), patch(
            "lunar_analyzer.integrations._horizons_vector",
            side_effect=IntegrationError("El servicio respondió HTTP 404."),
        ):
            solar, status = _resolve_ephemeris(WHEN.isoformat())
        self.assertIn("fallback sin conexión", solar["ephemeris_model"])
        self.assertFalse(status["horizons"]["available"])
        self.assertIn("HTTP 404", status["horizons"]["message"])

    def test_invalid_spice_meta_kernel_is_reported_without_claiming_spice_results(self):
        _resolve_ephemeris.cache_clear()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {SPICE_META_KERNEL_ENV: str(Path(directory) / "missing.tm")}, clear=True
        ), patch(
            "lunar_analyzer.integrations._horizons_vector",
            side_effect=IntegrationError("Horizons no disponible."),
        ):
            solar, status = _resolve_ephemeris(WHEN.isoformat())
        self.assertTrue(status["spice"]["meta_kernel_configured"])
        self.assertFalse(status["spice"]["available"])
        self.assertIn("No se encontró", status["spice"]["message"])
        self.assertIn("fallback sin conexión", solar["ephemeris_model"])

    def test_pds_search_uses_lro_instrument_types_and_coordinate_box(self):
        product = {
            "Observation_time": "2020-01-01T00:00:00",
            "ProductURL": "https://ode.rsl.wustl.edu/product?product_id=LRO_TEST_RDR4",
            "FilesURL": "https://ode.rsl.wustl.edu/files",
        }
        with patch(
            "lunar_analyzer.integrations._get_json",
            return_value={"ODEResults": {"Count": "1", "Products": {"Product": [product]}}},
        ) as get_json:
            response = search_lro_products(90, 180)

        self.assertEqual([item["instrument"] for item in response["results"]], ["Diviner", "LOLA"])
        self.assertTrue(all(item["available"] for item in response["results"]))
        self.assertEqual(response["results"][0]["products"][0]["product_id"], "LRO_TEST_RDR4")
        self.assertEqual(response["search_area"]["latitude_max"], 90)
        self.assertEqual(response["search_area"]["longitude_east"], 180)
        self.assertEqual(get_json.call_count, 2)
        parameters = get_json.call_args_list[0].args[1]
        self.assertEqual((parameters["ihid"], parameters["iid"], parameters["pt"]), ("LRO", "DLRE", "RDR4"))
        self.assertEqual(parameters["loc"], "b")
        self.assertIn("no se descargaron", response["results"][0]["message"])


if __name__ == "__main__":
    unittest.main()
