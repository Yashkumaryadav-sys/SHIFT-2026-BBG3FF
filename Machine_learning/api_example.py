"""Example RangeTrue API (reference for the backend). Run from the folder that holds range_core.py and models/:
   python -m uvicorn api_example:app --reload --port 8000
The backend developer can copy range_core.py into Backend and reuse these endpoints."""
from typing import List, Optional, Literal
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import range_core as core

app = FastAPI(title="RangeTrue API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])   # open for the hackathon demo

try:
    MODELS = core.Models(core.default_models_dir())
    MODEL_ERROR = None
except Exception as e:                                   # keep the server up so /health can say what is wrong
    MODELS, MODEL_ERROR = None, str(e)


_EXAMPLE = {"soc_percent": 50, "cycles_used": 200, "cycles_to_80pct": 800, "temp_c": 20, "rider_kg": 65, "vehicle_kg": 110,
            "pack_wh": 1800, "rated_range_km": 80, "trip_km": 20, "safety_margin": 0.175, "route": "rolling"}


class RangeRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _EXAMPLE})
    soc_percent: float = Field(50, ge=0, le=100, description="Charge shown on the dashboard")
    cycles_used: float = Field(0, ge=0, description="Full charge cycles the pack has done")
    cycles_to_80pct: float = Field(800, ge=100, le=5000, description="Cycles the pack is rated for before it falls to 80% capacity")
    temp_c: float = Field(25, ge=-30, le=60)
    rider_kg: float = Field(65, ge=20, le=200)
    vehicle_kg: float = Field(110, ge=5, le=400, description="Vehicle plus cargo")
    pack_wh: float = Field(1800, ge=100, le=10000)
    rated_range_km: float = Field(80, ge=5, le=400, description="Claimed range of a new pack on flat ground")
    trip_km: float = Field(20, ge=0.5, le=200)
    safety_margin: float = Field(0.175, ge=0.05, le=0.30)
    route: Literal["flat", "rolling", "hill"] = "rolling"
    elevations_m: Optional[List[float]] = Field(None, min_length=2, max_length=20000, description="Optional. Elevation at equal spacing along the route (from Open-Meteo / Copernicus GLO-90). Leave out to use the sample route")
    step_m: Optional[float] = Field(None, ge=10, le=2000, description="Spacing of elevations_m in metres")


class ReEstimateRequest(RangeRequest):
    model_config = ConfigDict(json_schema_extra={"example": {**_EXAMPLE, "km_done": 8, "wh_used": 300}})
    km_done: float = Field(..., ge=0, description="Distance ridden so far")
    wh_used: float = Field(..., ge=0, description="Energy used so far (from the battery readings)")


def _need_models():
    if MODELS is None:
        raise HTTPException(503, f"Models not loaded: {MODEL_ERROR}. Run train_model.py in Machine_learning first.")
    return MODELS


def _clean(result):
    return {k: v for k, v in result.items() if not k.startswith("_")}


@app.get("/health")
def health():
    if MODELS is None:
        return {"status": "models_missing", "detail": MODEL_ERROR}
    return {"status": "ok", "models": MODELS.info()}


@app.get("/routes")
def routes():
    return {"routes": list(core.SAMPLE_ROUTES.keys()), "length_km": 60}


@app.post("/predict-range")
def predict_range(req: RangeRequest):
    m = _need_models()
    return _clean(core.predict(m, req.model_dump()))


@app.post("/re-estimate")
def re_estimate(req: ReEstimateRequest):
    m = _need_models()
    p = req.model_dump()
    km_done, wh_used = p.pop("km_done"), p.pop("wh_used")
    base = core.predict(m, p)
    if km_done > base["trip_km"]:
        raise HTTPException(422, "km_done is beyond the trip distance")
    return core.re_estimate(base, km_done, wh_used)
