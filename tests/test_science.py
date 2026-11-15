import unittest
from datetime import datetime, timedelta, timezone
from math import sin

from lunar_analyzer.science import (
    analyze_site,
    compare_sites,
    find_windows,
    solar_ephemeris,
    surface_illumination,
    thermal_balance,
    timeline,
)


SITE = {
    "id": "test-site",
    "name": "Sitio de prueba",
    "latitude": -89.5,
    "longitude": 0.0,
    "kind": "candidate",
    "terrain": {"slope_deg": 4.0, "albedo": 0.12, "emissivity": 0.95},
    "science": "Datos de prueba",
}
WHEN = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


class ScienceModelTests(unittest.TestCase):
    def test_radiative_balance_reports_consistent_fluxes_and_units(self):
        balance = thermal_balance(0.2, albedo=0.1, emissivity=0.95)
        self.assertGreater(balance["incident_w_m2"], 0)
        self.assertAlmostEqual(balance["absorbed_w_m2"], balance["incident_w_m2"] * 0.9, places=1)
        self.assertAlmostEqual(balance["temperature_c"], balance["temperature_k"] - 273.15, places=2)
        self.assertAlmostEqual(balance["emitted_w_m2"], balance["absorbed_w_m2"], delta=0.1)

    def test_site_analysis_marks_estimates_and_exposes_missing_data(self):
        result = analyze_site(SITE, WHEN)
        self.assertIn(result["verdict"]["label"], {"Favorable", "Precaución", "Desfavorable"})
        self.assertIn("equilibrium_c", result["thermal"])
        self.assertIn("sin mediciones", result["sources"]["diviner"].lower())
        self.assertTrue(result["verdict"]["missing"])
        self.assertIn("sun_vector_lunar", result["solar"])
        self.assertFalse(result["terrain"]["topographic_shadow_available"])
        self.assertAlmostEqual(
            result["thermal"]["incident_w_m2"],
            result["illumination"]["incident_irradiance_w_m2"],
            delta=0.01,
        )

    def test_solar_ephemeris_normalizes_lunar_frame_vector_and_corrects_distance(self):
        solar = solar_ephemeris(WHEN)
        vector = solar["sun_vector_lunar"]
        self.assertAlmostEqual(sum(component**2 for component in vector), 1.0, places=8)
        later = solar_ephemeris(WHEN + timedelta(days=1))
        self.assertNotEqual(vector, later["sun_vector_lunar"])
        self.assertAlmostEqual(
            solar["solar_irradiance_w_m2"],
            1361.0 / solar["sun_moon_distance_au"] ** 2,
            delta=0.01,
        )
        self.assertEqual(solar["global_illuminated_surface_percent"], 50.0)
        self.assertGreater(solar["sun_moon_distance_km"], 140_000_000)
        self.assertLess(solar["sun_moon_distance_km"], 160_000_000)

    def test_local_incidence_uses_surface_normal_dot_sun_vector(self):
        solar = solar_ephemeris(WHEN)
        subsolar = surface_illumination(
            solar["subsolar_latitude_deg"],
            solar["subsolar_longitude_deg"],
            WHEN,
            solar,
        )
        antipode = surface_illumination(
            -solar["subsolar_latitude_deg"],
            solar["subsolar_longitude_deg"] + 180,
            WHEN,
            solar,
        )
        self.assertGreater(subsolar["mu"], 0.99999)
        self.assertGreater(subsolar["incident_irradiance_w_m2"], 1300)
        self.assertLess(antipode["mu"], -0.99999)
        self.assertEqual(antipode["incident_irradiance_w_m2"], 0.0)
        self.assertIsNone(subsolar["topographic_shadow"])

    def test_thermal_balance_accepts_distance_adjusted_solar_irradiance(self):
        standard = thermal_balance(0.5)
        adjusted = thermal_balance(0.5, solar_irradiance_w_m2=1300.0)
        self.assertLess(adjusted["incident_w_m2"], standard["incident_w_m2"])
        self.assertAlmostEqual(adjusted["incident_w_m2"], 1300 * sin(0.5), places=2)

    def test_timeline_and_windows_are_date_anchored(self):
        points = timeline(SITE, WHEN)["points"]
        windows = find_windows(SITE, WHEN)["points"]
        self.assertEqual(len(points), 37)
        self.assertEqual(points[0]["time"], WHEN.isoformat())
        self.assertEqual(points[-1]["time"], "2026-11-17T12:00:00+00:00")
        self.assertIn("sun_vector_lunar", points[0]["solar"])
        self.assertIn("incident_irradiance_w_m2", points[0])
        self.assertTrue(windows)
        self.assertTrue(all(0 <= point["score"] <= 100 for point in windows))

    def test_comparison_returns_one_row_per_site(self):
        other = {**SITE, "id": "other", "name": "Otro sitio", "longitude": 12}
        result = compare_sites([SITE, other], WHEN)
        self.assertEqual([item["id"] for item in result["sites"]], ["test-site", "other"])


if __name__ == "__main__":
    unittest.main()
