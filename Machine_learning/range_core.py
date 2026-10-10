"""RangeTrue core: trained battery models + hill physics. No web code here, so it can be tested on its own."""
import json
import math
import os
from pathlib import Path
import numpy as np

G = 9.81
ETA = 0.80          # drivetrain efficiency when climbing
REGEN = 0.30        # share of descent energy given back
REF_MASS = 175.0    # kg (rider + vehicle) the rated range is assumed for
STEP_KM = 0.25
STEP_M = STEP_KM * 1000


# ------------------------------------------------------------------ models
class Models:
    def __init__(self, models_dir):
        self.dir = Path(models_dir)
        meta = json.loads((self.dir / "meta.json").read_text())
        self.meta = meta
        self.life_grid = np.array(meta["age_curve"]["life"], dtype=float)
        self.soh_curve = np.array(meta["age_curve"]["soh"], dtype=float)
        self.temp_x = np.array(meta["temp_curve"]["temp_c"], dtype=float)
        self.temp_f = np.array(meta["temp_curve"]["factor"], dtype=float)
        self.age_source = "saved curve"
        self.booster = None
        try:                                              # prefer the trained XGBoost model itself
            import xgboost as xgb
            b = xgb.Booster()
            b.load_model(str(self.dir / "age_model.json"))
            self._xgb = xgb
            self.booster = b
            self.age_source = "XGBoost model"
        except Exception:
            pass                                          # fall back to the curve saved at training time

    def age_factor(self, life):
        life = float(min(max(life, 0.0), float(self.life_grid[-1])))
        if self.booster is not None:
            try:
                d = self._xgb.DMatrix(np.array([[life]], dtype=float))
                p0 = float(self.booster.predict(self._xgb.DMatrix(np.array([[0.0]], dtype=float)))[0])
                return float(min(1.0, self.booster.predict(d)[0] / p0))
            except Exception:
                pass
        return float(np.interp(life, self.life_grid, self.soh_curve))

    def temp_factor(self, temp_c):
        return float(np.interp(temp_c, self.temp_x, self.temp_f))        # clamps to the tested range

    def usable_fraction(self, cycles_used, cycles_to_80, temp_c):
        life = cycles_used / max(cycles_to_80, 1.0)
        a, t = self.age_factor(life), self.temp_factor(temp_c)
        return a * t, a, t

    def info(self):
        lo, hi = self.meta["temp_range_c"]
        return {"age_source": self.age_source, "temp_range_c": [lo, hi],
                "age_cv_mae_soh": [round(c["mae_soh"], 4) for c in self.meta.get("age_cv", [])],
                "notes": self.meta.get("notes", [])}


# ------------------------------------------------------------------ routes
def _interp_cos(pts, x):
    for i in range(len(pts) - 1):
        if x <= pts[i + 1][0]:
            t = (x - pts[i][0]) / (pts[i + 1][0] - pts[i][0])
            s = (1 - math.cos(math.pi * t)) / 2
            return pts[i][1] + (pts[i + 1][1] - pts[i][1]) * s
    return pts[-1][1]


_HILL = [[0, 0], [3, 6], [6, 92], [8, 172], [10, 188], [16, 192], [24, 92], [34, 32], [44, 30], [60, 20]]
SAMPLE_ROUTES = {
    "flat": lambda x: 2.5 * math.sin(0.35 * x) + 1.5 * math.sin(1.1 * x),
    "rolling": lambda x: 4 * x + 28 * math.sin(1.15 * x),
    "hill": lambda x: _interp_cos(_HILL, x),
}


def sample_route(name, length_km=60.0):
    f = SAMPLE_ROUTES[name]
    n = int(round(length_km / STEP_KM))
    return [f(i * STEP_KM) for i in range(n + 1)], STEP_M


# ------------------------------------------------------------------ physics
def segment_energy(elev_m, step_m, mass_kg, flat_wh_per_km):
    """Wh for each route piece: flat energy + climbing work / efficiency (descents give back a share)."""
    el = np.asarray(elev_m, dtype=float)
    dh = np.diff(el)
    theta = np.arctan2(dh, step_m)
    grade_wh = mass_kg * G * np.sin(theta) * step_m / 3600.0
    grade_wh = np.where(grade_wh >= 0, grade_wh / ETA, grade_wh * REGEN)
    flat_wh = flat_wh_per_km * step_m / 1000.0
    return np.maximum(flat_wh + grade_wh, 0.1 * flat_wh)


def km_at_energy(cum, step_km, energy_wh):
    if energy_wh <= 0:
        return 0.0
    if energy_wh >= cum[-1]:
        return (len(cum) - 1) * step_km
    i = int(np.searchsorted(cum, energy_wh, side="right") - 1)
    return (i + (energy_wh - cum[i]) / (cum[i + 1] - cum[i])) * step_km


def energy_at_km(cum, step_km, km):
    km = min(max(km, 0.0), (len(cum) - 1) * step_km)
    i = min(int(km / step_km), len(cum) - 2)
    f = (km - i * step_km) / step_km
    return float(cum[i] + (cum[i + 1] - cum[i]) * f)


def predict(models, p):
    """p: dict with soc_percent, cycles_used, cycles_to_80pct, temp_c, rider_kg, vehicle_kg, pack_wh,
    rated_range_km, trip_km, safety_margin, and either route (name) or elevations_m (+ step_m)."""
    mass = max(30.0, p["rider_kg"] + p["vehicle_kg"])
    soc = p["soc_percent"] / 100.0
    pack, rated = p["pack_wh"], p["rated_range_km"]
    flat_rate = pack / rated * (0.45 + 0.55 * mass / REF_MASS)

    if p.get("elevations_m") and len(p["elevations_m"]) >= 2:
        elev, step_m = p["elevations_m"], float(p.get("step_m") or STEP_M)
    else:
        elev, step_m = sample_route(p.get("route") or "rolling")
    step_km = step_m / 1000.0
    seg = segment_energy(elev, step_m, mass, flat_rate)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    route_km = (len(cum) - 1) * step_km

    uf, age_f, temp_f = models.usable_fraction(p["cycles_used"], p["cycles_to_80pct"], p["temp_c"])
    usable = pack * soc * uf
    dash_range = soc * rated
    flat_range = usable / flat_rate
    real_range = km_at_energy(cum, step_km, usable)
    margin = p["safety_margin"]
    budget = usable * (1 - margin)
    safe_range = km_at_energy(cum, step_km, budget)
    trip = min(p["trip_km"], route_km)
    need = energy_at_km(cum, step_km, trip)
    left = usable - need

    r_age_temp = dash_range * uf                 # dashboard range after battery age and cold
    r_mass = flat_range                          # after the effect of rider and vehicle weight
    loss_batt = max(0.0, dash_range - r_age_temp)
    loss_load = max(0.0, r_age_temp - r_mass)
    loss_terrain = max(0.0, r_mass - real_range)
    if need <= budget:
        verdict = "reachable"
    elif need <= usable:
        verdict = "inside_margin"
    else:
        verdict = "not_reachable"
    return {
        "dashboard_range_km": round(float(dash_range), 2),
        "real_range_km": round(float(real_range), 2),
        "safe_range_km": round(float(safe_range), 2),
        "range_without_hills_km": round(float(flat_range), 2),
        "usable_energy_wh": round(usable, 1),
        "usable_fraction": round(uf, 4),
        "age_factor": round(age_f, 4),
        "temp_factor": round(temp_f, 4),
        "flat_wh_per_km": round(flat_rate, 2),
        "avg_wh_per_km_on_route": round(float(cum[-1]) / route_km, 2),
        "trip_km": round(trip, 2),
        "energy_needed_wh": round(float(need), 1),
        "energy_left_on_arrival_wh": round(float(left), 1),
        "reserve_wh": round(usable * margin, 1),
        "verdict": verdict,
        "can_reach": verdict == "reachable",
        "range_lost_km": {"battery_age_and_temperature": round(float(loss_batt), 2),
                          "load": round(float(loss_load), 2), "terrain": round(float(loss_terrain), 2)},
        "route_km": round(float(route_km), 2),
        "trip_clipped": bool(p["trip_km"] > route_km),
        "profile": {"step_km": step_km, "elevation_m": [round(float(e), 1) for e in elev],
                    "cumulative_wh": [round(float(c), 2) for c in cum]},
        "model": models.info(),
        "_cum_wh": cum.tolist(), "_step_km": step_km,
    }


def re_estimate(base, km_done, wh_used):
    """Mid-ride check. base = result of predict() for the same trip. Rescales the forecast by actual use."""
    cum, step_km = base["_cum_wh"], base["_step_km"]
    predicted_so_far = energy_at_km(np.array(cum), step_km, km_done)
    ratio = wh_used / predicted_so_far if predicted_so_far > 0.5 else 1.0
    need_total = energy_at_km(np.array(cum), step_km, base["trip_km"])
    projected = wh_used + (need_total - predicted_so_far) * ratio
    usable = base["usable_energy_wh"]
    arrive = usable - projected
    status = "on_track" if arrive >= base["reserve_wh"] else ("dips_into_reserve" if arrive > 0 else "will_not_arrive")
    out = {"use_vs_forecast_percent": round(float((ratio - 1) * 100), 1), "projected_use_wh": round(float(projected), 1),
           "projected_left_on_arrival_wh": round(float(arrive), 1), "status": status}
    if status != "on_track":
        budget = usable - base["reserve_wh"]
        target = predicted_so_far + (budget - wh_used) / ratio
        out["charge_before_km"] = round(float(km_done if target <= predicted_so_far else km_at_energy(np.array(cum), step_km, target)), 1)
    return out


def default_models_dir():
    env = os.environ.get("RANGETRUE_MODELS")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "Machine_learning" / "models", here / "models"):
        if (cand / "meta.json").exists():
            return cand
    return here.parent / "Machine_learning" / "models"
