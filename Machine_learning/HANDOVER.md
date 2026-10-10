# RangeTrue ML handover

What the ML side provides, and how the backend uses it.

## Files
| File | What it is |
|---|---|
| `models/age_model.json`, `models/meta.json` | Trained models: battery ageing (XGBoost) and temperature curve |
| `range_core.py` | Inference and physics. No web code. Copy into `Backend` and import it |
| `api_example.py` | Reference FastAPI app showing the two endpoints |
| `build_dataset.py`, `calce_loader.py`, `train_model.py` | Rebuild everything from the public datasets |

`range_core.py` finds the models by itself: `models/` next to it, or `../Machine_learning/models` when it sits in `Backend`. Set `RANGETRUE_MODELS` to override.

## Backend use
```python
import range_core as core
models = core.Models(core.default_models_dir())          # once, at startup
result = core.predict(models, params)                    # one call per request
check  = core.re_estimate(result, km_done, wh_used)      # mid-ride warning
```

### `predict` input (dict)
`soc_percent`, `cycles_used`, `cycles_to_80pct` (pack's rated life, default 800), `temp_c`, `rider_kg`, `vehicle_kg`,
`pack_wh`, `rated_range_km`, `trip_km`, `safety_margin` (0.15 to 0.20), and either `route` (`flat`, `rolling`, `hill`)
or `elevations_m` (list, equal spacing) with `step_m`.

### `predict` output (main fields)
`dashboard_range_km`, `real_range_km`, `safe_range_km`, `verdict` (`reachable`, `inside_margin`, `not_reachable`),
`energy_needed_wh`, `energy_left_on_arrival_wh`, `usable_fraction`, `age_factor`, `temp_factor`,
`range_lost_km` (battery_age_and_temperature, load, terrain), and `profile` (elevation and cumulative Wh for charts).
Drop the keys starting with `_` before sending JSON (the example does).

### `re_estimate` output
`use_vs_forecast_percent`, `projected_left_on_arrival_wh`, `status` (`on_track`, `dips_into_reserve`, `will_not_arrive`),
and `charge_before_km` when not on track.

## Retrain
```
pip install pandas numpy scipy openpyxl xgboost scikit-learn
python build_dataset.py "Nasa"              # NASA .mat files -> nasa_discharge_all.csv
python calce_loader.py "A123_BAT"           # CALCE .xlsx files -> calce_runs.csv
python train_model.py                       # -> models/
```
Raw data is not in the repo. NASA: Prognostics Center of Excellence battery set (B0005, B0006, B0007, B0018).
CALCE: A123 dynamic profile files at 0, 10, 25, 40 and 50 C (https://calce.umd.edu/battery-data).

## What is real and what is assumed
- Ageing: learned from four NASA 18650 cells at 24 C. Life used = cycles / cycles to 80% capacity. Unseen-cell error is about 2.4 points of battery health.
- Temperature: from a small CALCE LiFePO4 test (0 to 50 C). Noisy between cells. Heat is capped at 1.0. Below 0 C the 0 C value is used.
- Hills: grade-force physics (mass x g x sin(slope)). Sample routes are for the demo; real routes need Open-Elevation.
- Flat energy per km comes from pack Wh divided by rated range. No real fleet trip data was used.
