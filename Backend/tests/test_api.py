"""Initial API regression tests; run with `python -m unittest discover -s tests -v`."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

import main


class FakeModels:
    """Deterministic model substitute so API tests don't depend on model packages."""

    def usable_fraction(self, cycles_used, cycles_to_80, temp_c):
        return 0.95, 0.95, 1.0

    def info(self):
        return {"age_source": "test model"}


class RangeApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.models_patch = patch.object(main, "MODELS", FakeModels())
        self.models_patch.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(main, "DB_PATH", Path(self.temp_dir.name) / "test.sqlite3")
        self.db_patch.start()
        transport = httpx.ASGITransport(app=main.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.db_patch.stop()
        self.temp_dir.cleanup()
        self.models_patch.stop()

    @staticmethod
    def range_payload(**overrides):
        payload = {
            "soc_percent": 80,
            "cycles_used": 200,
            "cycles_to_80pct": 800,
            "temp_c": 25,
            "rider_kg": 65,
            "vehicle_kg": 110,
            "pack_wh": 1800,
            "rated_range_km": 80,
            "trip_km": 10,
            "safety_margin": 0.175,
            "route": "flat",
        }
        payload.update(overrides)
        return payload

    async def test_battery_status_reports_power_and_direction(self):
        response = await self.client.post("/battery/status", json={
            "voltage_v": 48, "current_a": 10, "temp_c": 30, "soc_percent": 80,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["power_w"], 480)
        self.assertEqual(response.json()["state"], "discharging")

        regen = await self.client.post("/battery/status", json={
            "voltage_v": 48, "current_a": -2, "temp_c": 30, "soc_percent": 80,
        })
        self.assertEqual(regen.json()["state"], "regenerating")

    async def test_calibration_returns_mass_adjusted_baseline(self):
        response = await self.client.post("/calibrate-baseline", json={
            "energy_used_wh": 200,
            "distance_km": 10,
            "rider_kg": 65,
            "vehicle_kg": 110,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["observed_wh_per_km"], 20)
        self.assertEqual(response.json()["mass_adjusted_wh_per_km"], 20)

    async def test_calibration_is_saved_and_used_by_vehicle_id(self):
        calibrated = await self.client.post("/calibrate-baseline", json={
            "vehicle_id": "scooter-001",
            "energy_used_wh": 200,
            "distance_km": 10,
            "rider_kg": 65,
            "vehicle_kg": 110,
        })
        self.assertEqual(calibrated.status_code, 200)
        self.assertEqual(calibrated.json()["saved_for_vehicle"], "scooter-001")

        stored = await self.client.get("/vehicles/scooter-001/calibration")
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(stored.json()["mass_adjusted_wh_per_km"], 20)

        prediction = await self.client.post("/predict-range", json=self.range_payload(
            vehicle_id="scooter-001",
        ))
        self.assertEqual(prediction.status_code, 200)
        self.assertEqual(prediction.json()["flat_wh_per_km"], 20)
        self.assertEqual(prediction.json()["consumption_baseline"], "measured_calibration")

    async def test_unknown_vehicle_id_returns_not_found(self):
        response = await self.client.post("/predict-range", json=self.range_payload(
            vehicle_id="not-calibrated",
        ))
        self.assertEqual(response.status_code, 404)

    async def test_ride_telemetry_integrates_power_and_saves_calibration(self):
        response = await self.client.post("/rides/calibrate", json={
            "vehicle_id": "logged-scooter",
            "distance_km": 0.1,
            "rider_kg": 65,
            "vehicle_kg": 110,
            "samples": [
                {"sampled_at": "2026-01-01T00:00:00Z", "voltage_v": 48, "current_a": 120 / 48},
                {"sampled_at": "2026-01-01T00:01:00Z", "voltage_v": 48, "current_a": 120 / 48},
            ],
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["energy_measurement"], "integrated_voltage_current_samples")
        self.assertEqual(body["telemetry_samples"], 2)
        self.assertEqual(body["observed_wh_per_km"], 20)
        self.assertEqual(body["mass_adjusted_wh_per_km"], 20)
        self.assertEqual(body["saved_for_vehicle"], "logged-scooter")

    async def test_ride_telemetry_rejects_large_sample_gaps(self):
        response = await self.client.post("/rides/calibrate", json={
            "vehicle_id": "logged-scooter",
            "distance_km": 1,
            "samples": [
                {"sampled_at": "2026-01-01T00:00:00Z", "voltage_v": 48, "current_a": 2},
                {"sampled_at": "2026-01-01T00:06:00Z", "voltage_v": 48, "current_a": 2},
            ],
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("sample gap exceeds 5 minutes", response.json()["detail"])

    async def test_prediction_uses_supplied_calibration(self):
        response = await self.client.post("/predict-range", json=self.range_payload(
            mass_adjusted_wh_per_km=20,
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["flat_wh_per_km"], 20)
        self.assertEqual(response.json()["consumption_baseline"], "measured_calibration")

    async def test_prediction_falls_back_to_rated_range(self):
        response = await self.client.post("/predict-range", json=self.range_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["flat_wh_per_km"], 22.5)
        self.assertEqual(response.json()["consumption_baseline"], "rated_range_estimate")

    async def test_invalid_soc_is_rejected(self):
        response = await self.client.post("/predict-range", json=self.range_payload(soc_percent=101))
        self.assertEqual(response.status_code, 422)

    async def test_reestimate_rejects_distance_beyond_trip(self):
        response = await self.client.post("/re-estimate", json=self.range_payload(
            km_done=11,
            wh_used=100,
        ))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "km_done cannot exceed trip_km")

    async def test_route_range_uses_mocked_route_and_elevation_services(self):
        with patch.object(main, "_fetch_route", new=AsyncMock(return_value=(1000, [[82.0, 25.0], [82.01, 25.01]]))) as route_mock, \
             patch.object(main, "_fetch_elevations", new=AsyncMock(return_value=[80.0, 85.0, 82.0])) as elevation_mock:
            response = await self.client.post("/route-range", json=self.range_payload(
                start_lat=25.0,
                start_lon=82.0,
                end_lat=25.01,
                end_lon=82.01,
                mass_adjusted_wh_per_km=20,
            ))

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["route_distance_km"], 1)
        self.assertEqual(body["trip_km"], 1)
        self.assertEqual(body["consumption_baseline"], "measured_calibration")
        self.assertEqual(body["route_source"], "OSRM / OpenStreetMap road network")
        route_mock.assert_awaited_once()
        elevation_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
