from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import app, configured_database_path, initialize_database
from lunar_analyzer.science import solar_ephemeris


FALLBACK_EPHEMERIS = solar_ephemeris(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))


class DashboardTests(unittest.TestCase):
    def test_database_path_can_be_configured_for_persistent_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "persistent.sqlite3"
            with patch.dict("os.environ", {"LUNAR_DATABASE_PATH": str(database_path)}):
                self.assertEqual(configured_database_path(), database_path)

    def test_render_health_check_endpoint(self):
        response = app.test_client().get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_dashboard_contains_3d_mission_control_panels(self):
        response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="lunarGlobe"', response.data)
        self.assertIn(b'id="missionForm"', response.data)
        self.assertIn(b'id="telemetryTemperature"', response.data)
        self.assertIn(b'data-telemetry-tab="thermal"', response.data)

    def test_preview_calculates_dashboard_values_without_saving_history(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.DATABASE", Path(directory) / "test.sqlite3"), patch(
            "app.resolve_ephemeris", return_value=(FALLBACK_EPHEMERIS, {})
        ):
            initialize_database()
            client = app.test_client()
            payload = {
                "mission_name": "Vista previa",
                "site_id": "shackleton-demo",
                "latitude": -89.5,
                "longitude": 0,
                "mission_time": "2026-11-14T12:00:00Z",
            }
            before = len(client.get("/api/history").get_json())
            response = client.post("/api/preview", json=payload)
            after = len(client.get("/api/history").get_json())
            self.assertEqual(response.status_code, 200)
            result = response.get_json()
            self.assertIn("thermal", result)
            self.assertIn("solar", result)
            self.assertIn("sun_vector_lunar", result["solar"])
            self.assertIn("incident_irradiance_w_m2", result["illumination"])
            self.assertIsNone(result["illumination"]["topographic_shadow"])
            self.assertNotIn("evaluation_id", result)
            self.assertEqual(before, after)

    def test_custom_site_does_not_claim_a_slope_without_terrain_data(self):
        with patch("app.resolve_ephemeris", return_value=(FALLBACK_EPHEMERIS, {})):
            response = app.test_client().post(
                "/api/preview",
                json={
                    "mission_name": "Sitio sin DEM",
                    "site_id": "custom",
                    "latitude": -20,
                    "longitude": 35,
                    "mission_time": "2026-11-14T12:00:00Z",
                },
            )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertIsNone(result["terrain"]["slope_deg"])
        self.assertIn("dem validado", result["illumination"]["topographic_shadow_status"].lower())

    def test_saved_evaluation_exports_pdf_and_csv(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.DATABASE", Path(directory) / "test.sqlite3"), patch(
            "app.resolve_ephemeris", return_value=(FALLBACK_EPHEMERIS, {})
        ):
            initialize_database()
            client = app.test_client()
            payload = {
                "mission_name": "Prueba de informe",
                "site_id": "shackleton-demo",
                "latitude": -89.5,
                "longitude": 0,
                "mission_time": "2026-11-14T12:00:00Z",
            }
            response = client.post("/api/analyze", json=payload)
            self.assertEqual(response.status_code, 200)
            evaluation_id = response.get_json()["evaluation_id"]
            pdf = client.get(f"/report/{evaluation_id}.pdf")
            csv = client.get(f"/report/{evaluation_id}.csv")
            self.assertEqual(pdf.status_code, 200)
            self.assertEqual(pdf.mimetype, "application/pdf")
            self.assertTrue(pdf.data.startswith(b"%PDF"))
            self.assertEqual(csv.status_code, 200)
            self.assertIn("text/csv", csv.content_type)
            self.assertIn("Coeficiente de incidencia", csv.data.decode("utf-8-sig"))

    def test_pds_search_route_validates_coordinates(self):
        response = app.test_client().post("/api/data-products", json={"latitude": 91, "longitude": 0})
        self.assertEqual(response.status_code, 400)
        self.assertIn("latitud", response.get_json()["error"].lower())

    def test_pds_search_route_returns_instrument_metadata(self):
        expected = {"results": [{"instrument": "Diviner", "products": []}]}
        with patch("app.search_lro_products", return_value=expected) as search:
            response = app.test_client().post(
                "/api/data-products", json={"latitude": -89.5, "longitude": 0}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        search.assert_called_once_with(-89.5, 0.0)


if __name__ == "__main__":
    unittest.main()
