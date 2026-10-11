"""Public-data-backed example vehicle profiles used for demos and evaluation."""

from __future__ import annotations


VEHICLE_PROFILES = {
    "xiaomi_pro2_public": {
        "name": "Xiaomi Mi Electric Scooter Pro 2 (public-data proxy)",
        "pack_wh": 446.0,
        "rated_range_km": 45.0,
        "vehicle_kg": 14.2,
        # Median rider-weight bin in the 30-trip scooter summary was 90–100 kg.
        "rider_kg": 95.0,
        "observed_wh_per_km_median": 19.8676,
        "observed_wh_per_km_q25": 14.751,
        "observed_wh_per_km_q75": 30.905,
        "trip_count": 30,
        "wh_per_km_min": 8.92,
        "wh_per_km_max": 43.08,
        "dataset_url": "https://github.com/SFIEssential/DualEMobilityData-datasets",
        "vehicle_specs_url": "https://www.mi.com/uk/mi-electric-scooter-Pro2/",
        "baseline_source": "public_dataset_median",
        "limitations": "30 Dublin-area trips; median trip energy use is a proxy, not this user's vehicle calibration.",
    }
}


def get_vehicle_profile(profile_id: str) -> dict | None:
    profile = VEHICLE_PROFILES.get(profile_id)
    return dict(profile) if profile else None


def list_vehicle_profiles() -> list[dict]:
    return [{"id": profile_id, **profile} for profile_id, profile in VEHICLE_PROFILES.items()]
