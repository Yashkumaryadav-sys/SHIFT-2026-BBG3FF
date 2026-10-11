"""RangeTrue FastAPI backend.

Run from this directory with: python -m uvicorn main:app --reload
"""
from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import time
from collections import OrderedDict
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import hmac
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import range_core as core
from vehicle_profiles import get_vehicle_profile, list_vehicle_profiles

APP_VERSION = "1.0.0"
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
ELEVATION_URL = os.getenv("OPEN_METEO_ELEVATION_URL", "https://api.open-meteo.com/v1/elevation")
ELEVATION_FALLBACK_URL = os.getenv("OPENTOPO_ELEVATION_URL", "https://api.opentopodata.org/v1/srtm90m")
HTTP_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "20"))
UPSTREAM_RETRIES = max(0, int(os.getenv("UPSTREAM_RETRIES", "2")))
ROUTE_CACHE_TTL_SECONDS = max(0, int(os.getenv("ROUTE_CACHE_TTL_SECONDS", "900")))
ELEVATION_CACHE_TTL_SECONDS = max(0, int(os.getenv("ELEVATION_CACHE_TTL_SECONDS", "86400")))
CACHE_MAX_ENTRIES = max(1, int(os.getenv("UPSTREAM_CACHE_MAX_ENTRIES", "512")))
ELEVATION_BATCH_SIZE = 100
DB_PATH = Path(os.getenv("RANGETRUE_DB_PATH", str(Path(__file__).with_name("rangetrue.sqlite3"))))
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
API_KEY = os.getenv("RANGETRUE_API_KEY", "")
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS")

if APP_ENV not in {"development", "production"}:
    raise RuntimeError("APP_ENV must be either 'development' or 'production'")
if APP_ENV == "production":
    if len(API_KEY) < 32 or API_KEY.lower().startswith("replace-"):
        raise RuntimeError("Set RANGETRUE_API_KEY to a random secret of at least 32 characters in production")
    if not CORS_ORIGINS_RAW:
        raise RuntimeError("Set CORS_ORIGINS explicitly in production")
    if "*" in [origin.strip() for origin in CORS_ORIGINS_RAW.split(",")]:
        raise RuntimeError("Wildcard CORS_ORIGINS is not allowed in production")


class TTLCache:
    """Small process-local LRU/TTL cache for successful upstream responses."""

    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple, tuple[float, object]] = OrderedDict()

    def get(self, key: tuple, ttl_seconds: int):
        if ttl_seconds <= 0:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return deepcopy(value)

    def set(self, key: tuple, value: object, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        self._entries[key] = (time.monotonic() + ttl_seconds, deepcopy(value))
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


UPSTREAM_CACHE = TTLCache(CACHE_MAX_ENTRIES)


async def _upstream_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Retry transient network, timeout, rate-limit, and server errors."""
    for attempt in range(UPSTREAM_RETRIES + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < UPSTREAM_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 5.0) if retry_after else min(0.25 * (2 ** attempt), 2.0)
                    except ValueError:
                        delay = min(0.25 * (2 ** attempt), 2.0)
                    await asyncio.sleep(max(0, delay))
                    continue
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            if attempt >= UPSTREAM_RETRIES:
                raise
        except httpx.TransportError:
            if attempt >= UPSTREAM_RETRIES:
                raise
        if attempt < UPSTREAM_RETRIES:
            await asyncio.sleep(min(0.25 * (2 ** attempt), 2.0))
    raise RuntimeError("Upstream request retry loop ended unexpectedly")

app = FastAPI(
    title="RangeTrue EV Range API",
    version=APP_VERSION,
    description="Estimate EV range from battery condition, load, and route elevation.",
    docs_url=None if APP_ENV == "production" else "/docs",
    redoc_url=None if APP_ENV == "production" else "/redoc",
    openapi_url=None if APP_ENV == "production" else "/openapi.json",
)
origins = [x.strip() for x in (CORS_ORIGINS_RAW or "http://localhost:3000,http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def require_api_key(request, call_next):
    """Require a configured API key outside development; keep health and CORS preflight public."""
    if APP_ENV == "production" and request.method != "OPTIONS" and request.url.path != "/health":
        supplied_key = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied_key, API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API key"})
    return await call_next(request)

try:
    MODELS = core.Models(core.default_models_dir())
    MODEL_ERROR = None
except Exception as exc:  # Keep basic health information available when model files are missing.
    MODELS, MODEL_ERROR = None, str(exc)


class BatteryStatus(BaseModel):
    """Live or manually entered readings. SOC must come from the BMS/dashboard."""
    voltage_v: float = Field(..., gt=0, le=1000)
    current_a: float = Field(..., ge=-1000, le=1000, description="Positive while discharging; negative while regenerating")
    temp_c: float = Field(..., ge=-40, le=100)
    soc_percent: float = Field(..., ge=0, le=100)
    sampled_at: str | None = Field(None, description="ISO-8601 timestamp supplied by the vehicle or client")


class BaselineRequest(BaseModel):
    vehicle_id: str | None = Field(None, min_length=1, max_length=100)
    energy_used_wh: float = Field(..., gt=0)
    distance_km: float = Field(..., gt=0.01, le=1000)
    rider_kg: float = Field(65, ge=20, le=200)
    vehicle_kg: float = Field(110, ge=5, le=400)


class TelemetrySample(BaseModel):
    sampled_at: datetime
    voltage_v: float = Field(..., gt=0, le=1000)
    current_a: float = Field(..., ge=-1000, le=1000, description="Positive while discharging; negative while regenerating")


class RideCalibrationRequest(BaseModel):
    vehicle_id: str = Field(..., min_length=1, max_length=100)
    distance_km: float = Field(..., gt=0.01, le=1000)
    rider_kg: float = Field(65, ge=20, le=200)
    vehicle_kg: float = Field(110, ge=5, le=400)
    samples: list[TelemetrySample] = Field(..., min_length=2, max_length=10000)


class RangeRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "vehicle_profile": "xiaomi_pro2_public", "soc_percent": 80,
        "cycles_used": 0, "cycles_to_80pct": 800, "temp_c": 25,
        "trip_km": 10, "safety_margin": 0.175, "route": "flat",
    }})
    soc_percent: float = Field(..., ge=0, le=100, description="Prefer the BMS/dashboard SOC, not voltage-only estimation")
    cycles_used: float = Field(0, ge=0)
    cycles_to_80pct: float = Field(800, ge=100, le=5000)
    temp_c: float = Field(25, ge=-30, le=60)
    vehicle_profile: Literal["xiaomi_pro2_public"] | None = Field(
        None, description="Optional public-data demo profile; supplies scooter specs and a dataset median baseline."
    )
    rider_kg: float | None = Field(None, ge=20, le=200)
    vehicle_kg: float | None = Field(None, ge=5, le=400, description="Vehicle plus cargo")
    pack_wh: float | None = Field(None, ge=100, le=100000)
    rated_range_km: float | None = Field(None, ge=5, le=1000)
    vehicle_id: str | None = Field(None, min_length=1, max_length=100,
                                   description="Previously calibrated vehicle identifier")
    mass_adjusted_wh_per_km: float | None = Field(
        None, gt=0, le=1000,
        description="Optional custom baseline; omit to use the selected public profile, saved vehicle calibration, or pack_wh / rated_range_km.",
    )
    trip_km: float = Field(..., ge=0.5, le=1000)
    safety_margin: float = Field(0.175, ge=0.05, le=0.30)
    route: Literal["flat", "rolling", "hill"] = "rolling"
    elevations_m: list[float] | None = Field(None, min_length=2, max_length=20000)
    step_m: float | None = Field(None, ge=10, le=2000)


class ReEstimateRequest(RangeRequest):
    km_done: float = Field(..., ge=0)
    wh_used: float = Field(..., ge=0)


class RouteRangeRequest(RangeRequest):
    model_config = ConfigDict(json_schema_extra={"example": {
        "vehicle_profile": "xiaomi_pro2_public", "soc_percent": 80,
        "cycles_used": 0, "cycles_to_80pct": 800, "temp_c": 25,
        "trip_km": 1.2, "safety_margin": 0.175, "route": "flat",
        "start_lat": 53.391607, "start_lon": -6.263688,
        "end_lat": 53.385628, "end_lon": -6.257041,
    }})
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    end_lat: float = Field(..., ge=-90, le=90)
    end_lon: float = Field(..., ge=-180, le=180)
    # The detailed elevation profile comes from Open-Meteo, so no sample route is used.
    route: Literal["flat", "rolling", "hill"] = "flat"


def _models():
    if MODELS is None:
        raise HTTPException(503, f"Battery models unavailable: {MODEL_ERROR}")
    return MODELS


@app.get("/vehicle-profiles")
def vehicle_profiles():
    """List built-in profiles, including their data provenance and limitations."""
    return {"profiles": list_vehicle_profiles()}


def _public(result: dict) -> dict:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def _connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_calibrations (
            vehicle_id TEXT PRIMARY KEY,
            observed_wh_per_km REAL NOT NULL,
            mass_adjusted_wh_per_km REAL NOT NULL,
            calibration_distance_km REAL NOT NULL,
            rider_kg REAL NOT NULL,
            vehicle_kg REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    return connection


@contextmanager
def _database():
    connection = _connect_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _save_calibration(vehicle_id: str, values: dict):
    with _database() as connection:
        connection.execute("""
            INSERT INTO vehicle_calibrations (
                vehicle_id, observed_wh_per_km, mass_adjusted_wh_per_km,
                calibration_distance_km, rider_kg, vehicle_kg, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vehicle_id) DO UPDATE SET
                observed_wh_per_km = excluded.observed_wh_per_km,
                mass_adjusted_wh_per_km = excluded.mass_adjusted_wh_per_km,
                calibration_distance_km = excluded.calibration_distance_km,
                rider_kg = excluded.rider_kg,
                vehicle_kg = excluded.vehicle_kg,
                updated_at = excluded.updated_at
        """, (
            vehicle_id, values["observed_wh_per_km"], values["mass_adjusted_wh_per_km"],
            values["calibration_distance_km"], values["rider_kg"], values["vehicle_kg"],
            datetime.now(timezone.utc).isoformat(),
        ))


def _load_calibration(vehicle_id: str):
    with _database() as connection:
        row = connection.execute(
            "SELECT * FROM vehicle_calibrations WHERE vehicle_id = ?", (vehicle_id,)
        ).fetchone()
    return dict(row) if row else None


def _prediction_params(request: RangeRequest):
    params = request.model_dump()
    profile_id = params.get("vehicle_profile")
    profile = get_vehicle_profile(profile_id) if profile_id else None
    if profile_id and profile is None:
        raise HTTPException(422, f"Unknown vehicle_profile '{profile_id}'")

    if profile:
        params["pack_wh"] = params["pack_wh"] or profile["pack_wh"]
        params["rated_range_km"] = params["rated_range_km"] or profile["rated_range_km"]
        params["rider_kg"] = params["rider_kg"] or profile["rider_kg"]
        params["vehicle_kg"] = params["vehicle_kg"] or profile["vehicle_kg"]
        if params.get("mass_adjusted_wh_per_km") is None:
            profile_mass = profile["rider_kg"] + profile["vehicle_kg"]
            profile_mass_factor = 0.45 + 0.55 * profile_mass / core.REF_MASS
            params["mass_adjusted_wh_per_km"] = (
                profile["observed_wh_per_km_median"] / profile_mass_factor
            )
            params["consumption_baseline_source"] = profile["baseline_source"]
    else:
        params["rider_kg"] = params["rider_kg"] if params["rider_kg"] is not None else 65.0
        params["vehicle_kg"] = params["vehicle_kg"] if params["vehicle_kg"] is not None else 110.0
        if params["pack_wh"] is None or params["rated_range_km"] is None:
            raise HTTPException(422, "Provide pack_wh and rated_range_km, or select vehicle_profile='xiaomi_pro2_public'")

    vehicle_id = params.get("vehicle_id")
    if params.get("mass_adjusted_wh_per_km") is None and vehicle_id:
        calibration = _load_calibration(vehicle_id)
        if calibration is None:
            raise HTTPException(404, f"No saved calibration for vehicle_id '{vehicle_id}'")
        params["mass_adjusted_wh_per_km"] = calibration["mass_adjusted_wh_per_km"]
    return params


def _attach_profile_info(result: dict, params: dict) -> dict:
    profile_id = params.get("vehicle_profile")
    if profile_id:
        profile = get_vehicle_profile(profile_id)
        reference_mass_factor = 0.45 + 0.55 * (
            profile["rider_kg"] + profile["vehicle_kg"]
        ) / core.REF_MASS
        sensitivity_ranges = []
        for wh_per_km in (
            profile["observed_wh_per_km_q25"],
            profile["observed_wh_per_km_q75"],
        ):
            sensitivity_params = dict(params)
            sensitivity_params["mass_adjusted_wh_per_km"] = wh_per_km / reference_mass_factor
            sensitivity_params["consumption_baseline_source"] = profile["baseline_source"]
            sensitivity_ranges.append(core.predict(_models(), sensitivity_params)["real_range_km"])
        result["vehicle_profile"] = {
            "id": profile_id,
            "name": profile["name"],
            "source": profile["dataset_url"],
            "trip_count": profile["trip_count"],
            "dataset_median_wh_per_km": profile["observed_wh_per_km_median"],
            "dataset_wh_per_km_interquartile_range": [
                profile["observed_wh_per_km_q25"], profile["observed_wh_per_km_q75"]
            ],
            "note": profile["limitations"],
        }
        result["range_sensitivity_km"] = {
            "lower": round(min(sensitivity_ranges), 2),
            "median_baseline": result["real_range_km"],
            "upper": round(max(sensitivity_ranges), 2),
            "basis": "Observed 25th–75th percentile consumption spread across 30 public scooter trips; not a confidence interval.",
        }
    return result


@app.get("/health")
def health():
    status = "ok" if MODELS else "degraded"
    if APP_ENV == "production":
        return {"status": status}
    return {"status": status, "model_error": MODEL_ERROR,
            "models": MODELS.info() if MODELS else None}


@app.post("/battery/status")
def battery_status(reading: BatteryStatus):
    """Normalize telemetry into useful power readings. Does not guess SOC from voltage."""
    power_w = reading.voltage_v * reading.current_a
    return {
        "voltage_v": reading.voltage_v,
        "current_a": reading.current_a,
        "temp_c": reading.temp_c,
        "soc_percent": reading.soc_percent,
        "power_w": round(power_w, 2),
        "state": "regenerating" if power_w < 0 else "discharging" if power_w > 0 else "idle",
        "sampled_at": reading.sampled_at,
    }


@app.post("/calibrate-baseline")
def calibrate_baseline(request: BaselineRequest):
    """Calculate observed Wh/km on a measured, preferably flat calibration ride."""
    wh_per_km = request.energy_used_wh / request.distance_km
    reference_mass = 175.0
    mass = request.rider_kg + request.vehicle_kg
    result = {
        "observed_wh_per_km": round(wh_per_km, 2),
        "mass_adjusted_wh_per_km": round(wh_per_km / (0.45 + 0.55 * mass / reference_mass), 2),
        "calibration_distance_km": request.distance_km,
        "note": "Use this measured baseline in place of pack_wh / rated_range_km when calibrating the range model.",
    }
    if request.vehicle_id:
        _save_calibration(request.vehicle_id, {
            **result,
            "rider_kg": request.rider_kg,
            "vehicle_kg": request.vehicle_kg,
        })
        result["saved_for_vehicle"] = request.vehicle_id
    return result


@app.post("/rides/calibrate")
def calibrate_from_ride(request: RideCalibrationRequest):
    """Integrate timestamped power samples, then save the resulting vehicle baseline."""
    samples = request.samples
    energy_wh = 0.0
    previous_time = samples[0].sampled_at
    previous_power_w = samples[0].voltage_v * samples[0].current_a

    for sample in samples[1:]:
        interval_s = (sample.sampled_at - previous_time).total_seconds()
        if interval_s <= 0:
            raise HTTPException(422, "samples must be ordered by sampled_at with no duplicate timestamps")
        if interval_s > 300:
            raise HTTPException(422, "sample gap exceeds 5 minutes; upload more frequent telemetry for reliable energy integration")
        power_w = sample.voltage_v * sample.current_a
        energy_wh += ((previous_power_w + power_w) / 2.0) * interval_s / 3600.0
        previous_time, previous_power_w = sample.sampled_at, power_w

    if energy_wh <= 0:
        raise HTTPException(422, "integrated net battery energy must be positive")

    calibration = calibrate_baseline(BaselineRequest(
        vehicle_id=request.vehicle_id,
        energy_used_wh=energy_wh,
        distance_km=request.distance_km,
        rider_kg=request.rider_kg,
        vehicle_kg=request.vehicle_kg,
    ))
    calibration["energy_measurement"] = "integrated_voltage_current_samples"
    calibration["telemetry_samples"] = len(samples)
    return calibration


@app.get("/vehicles/{vehicle_id}/calibration")
def get_vehicle_calibration(vehicle_id: str):
    calibration = _load_calibration(vehicle_id)
    if calibration is None:
        raise HTTPException(404, f"No saved calibration for vehicle_id '{vehicle_id}'")
    return calibration


@app.post("/predict-range")
def predict_range(request: RangeRequest):
    params = _prediction_params(request)
    result = _public(core.predict(_models(), params))
    return _attach_profile_info(result, params)


@app.post("/re-estimate")
def re_estimate(request: ReEstimateRequest):
    params = _prediction_params(request)
    km_done, wh_used = params.pop("km_done"), params.pop("wh_used")
    base = core.predict(_models(), params)
    if km_done > base["trip_km"]:
        raise HTTPException(422, "km_done cannot exceed trip_km")
    result = core.re_estimate(base, km_done, wh_used)
    return _attach_profile_info(result, params)


async def _fetch_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float):
    cache_key = ("route", OSRM_URL.rstrip("/"), round(start_lon, 6), round(start_lat, 6),
                 round(end_lon, 6), round(end_lat, 6))
    cached = UPSTREAM_CACHE.get(cache_key, ROUTE_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    url = f"{OSRM_URL.rstrip('/')}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await _upstream_request(
                client, "GET", url,
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Routing service timed out after retries; try again shortly") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Routing service request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "Routing service returned an invalid response")
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise HTTPException(422, "No drivable route was found for these coordinates")
    try:
        route = payload["routes"][0]
        coordinates = route.get("geometry", {}).get("coordinates", [])
        distance_m = float(route["distance"])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Routing service returned an invalid route payload") from exc
    if len(coordinates) < 2:
        raise HTTPException(502, "Routing service returned an incomplete route")
    result = (distance_m, coordinates)
    UPSTREAM_CACHE.set(cache_key, result, ROUTE_CACHE_TTL_SECONDS)
    return result


async def _fetch_opentopo_elevations(client: httpx.AsyncClient, selected: list[list[float]]) -> list[float]:
    """Fetch SRTM90m heights in public API batches (100 locations max per call)."""
    elevations: list[float] = []
    for start in range(0, len(selected), ELEVATION_BATCH_SIZE):
        if start:
            # OpenTopoData's public instance is intended for low-volume use.
            await asyncio.sleep(1)
        batch = selected[start:start + ELEVATION_BATCH_SIZE]
        locations = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in batch)
        response = await _upstream_request(
            client, "POST", ELEVATION_FALLBACK_URL,
            json={"locations": locations},
        )
        results = response.json().get("results", [])
        if len(results) != len(batch) or any(item.get("elevation") is None for item in results):
            raise HTTPException(502, "Fallback elevation service returned incomplete data")
        elevations.extend(float(item["elevation"]) for item in results)
    return elevations


async def _fetch_elevations(coordinates: list[list[float]], distance_m: float) -> tuple[list[float], str]:
    # Resample at equal distances because range_core expects equally spaced elevations.
    segment_m = []
    for a, b in zip(coordinates, coordinates[1:]):
        mean_lat = math.radians((a[1] + b[1]) / 2)
        dx = (b[0] - a[0]) * 111320 * math.cos(mean_lat)
        dy = (b[1] - a[1]) * 110540
        segment_m.append(math.hypot(dx, dy))
    cumulative = np.concatenate(([0.0], np.cumsum(segment_m)))
    count = max(1, math.ceil(distance_m / 250))
    sample_distances = np.linspace(0.0, cumulative[-1], count + 1)
    selected = []
    for position in sample_distances:
        index = min(int(np.searchsorted(cumulative, position, side="right") - 1), len(coordinates) - 2)
        span = cumulative[index + 1] - cumulative[index]
        fraction = (position - cumulative[index]) / span if span > 0 else 0.0
        a, b = coordinates[index], coordinates[index + 1]
        selected.append([a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1])])
    if len(selected) > 20000:
        raise HTTPException(422, "Route is too long to build an elevation profile")

    cache_key = ("elevation", ELEVATION_URL, ELEVATION_FALLBACK_URL,
                 tuple((round(lon, 6), round(lat, 6)) for lon, lat in selected))
    cached = UPSTREAM_CACHE.get(cache_key, ELEVATION_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    elevations: list[float] = []
    elevation_source = "Open-Meteo (Copernicus GLO-90)"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for start in range(0, len(selected), ELEVATION_BATCH_SIZE):
                batch = selected[start:start + ELEVATION_BATCH_SIZE]
                response = await _upstream_request(
                    client,
                    "GET",
                    ELEVATION_URL,
                    params={
                        "latitude": ",".join(str(lat) for _, lat in batch),
                        "longitude": ",".join(str(lon) for lon, _ in batch),
                    },
                )
                values = response.json().get("elevation", [])
                if len(values) != len(batch) or any(value is None for value in values):
                    raise HTTPException(502, "Elevation service returned incomplete data")
                elevations.extend(float(value) for value in values)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 429:
            raise HTTPException(502, f"Elevation service returned HTTP {exc.response.status_code}") from exc
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                elevations = await _fetch_opentopo_elevations(client, selected)
            elevation_source = "OpenTopoData SRTM 90m (fallback)"
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError, HTTPException) as fallback_exc:
            raise HTTPException(502, "Elevation providers are rate-limited or unavailable; wait briefly and retry") from fallback_exc
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Elevation service timed out after retries; try again shortly") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Elevation service request failed: {exc}") from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Elevation service returned invalid JSON or elevation values") from exc
    cached_result = (elevations, elevation_source)
    UPSTREAM_CACHE.set(cache_key, cached_result, ELEVATION_CACHE_TTL_SECONDS)
    return cached_result


@app.post("/route-range")
async def route_range(request: RouteRangeRequest):
    """Get a road route from OSRM and its elevation samples from Open-Meteo."""
    distance_m, coordinates = await _fetch_route(request.start_lon, request.start_lat,
                                                  request.end_lon, request.end_lat)
    elevations, elevation_source = await _fetch_elevations(coordinates, distance_m)
    step_m = distance_m / (len(elevations) - 1)
    params = _prediction_params(request)
    for key in ("start_lat", "start_lon", "end_lat", "end_lon"):
        params.pop(key, None)
    params.update({"trip_km": distance_m / 1000, "elevations_m": elevations, "step_m": step_m})
    prediction = _public(core.predict(_models(), params))
    _attach_profile_info(prediction, params)
    prediction["route_source"] = "OSRM / OpenStreetMap road network"
    prediction["elevation_source"] = elevation_source
    prediction["route_distance_km"] = round(distance_m / 1000, 2)
    return prediction
