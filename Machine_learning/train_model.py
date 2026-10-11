import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb

NASA_CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("nasa_discharge_all.csv")
CALCE_RUNS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("calce_runs.csv")
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("models")
EOL_SOH = 0.80          
   # end of life = 80% of original capacity (industry convention)
REF_TEMP = 25.0
OUT.mkdir(parents=True, exist_ok=True)


def pav_increasing(y, w):
    """Weighted isotonic regression (pool adjacent violators), non-decreasing."""
    blocks = [[float(v), float(wt), 1] for v, wt in zip(y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            v1, w1, n1 = blocks[i]
            v2, w2, n2 = blocks[i + 1]
            blocks[i:i + 2] = [[(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2]]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for v, _, n in blocks:
        out += [v] * n
    return np.array(out)


# ---------------------------------------------------------------- age model (NASA)
def prepare_nasa(path):
    df = pd.read_csv(path)
    df = df[(df["ambient_temp"] >= 20) & (df["ambient_temp"] <= 28)].copy()      # room-temperature cells only
    rows, info = [], []
    for b, g in df.sort_values("cycle_number").groupby("battery"):
        g = g.reset_index(drop=True)
        if len(g) < 30:
            continue
        cap0 = g["capacity_ah"].head(3).median()
        g["soh"] = g["capacity_ah"] / cap0
        smooth = g["soh"].rolling(5, min_periods=1).median()
        below = g.index[smooth < EOL_SOH]
        if len(below) == 0:
            print(f"  skip {b}: capacity never fell below {EOL_SOH:.0%} (last SoH {g['soh'].iloc[-1]:.2f})")
            continue
        eol = float(g.loc[below[0], "cycle_number"])
        g["life"] = g["cycle_number"] / eol
        info.append({"battery": b, "cycles": len(g), "initial_ah": round(cap0, 3),
                     "final_soh": round(float(g["soh"].iloc[-1]), 3), "eol_cycle": int(eol)})
        rows.append(g[["battery", "life", "soh"]])
    if not rows:
        sys.exit("No NASA battery usable for the age model. Check nasa_discharge_all.csv")
    return pd.concat(rows, ignore_index=True), info


def fit_age(X, y):
    m = xgb.XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, min_child_weight=5,
                         monotone_constraints="(-1)", random_state=0)
    m.fit(X.reshape(-1, 1), y)
    return m


print("== Age model (NASA) ==")
age, info = prepare_nasa(NASA_CSV)
print(pd.DataFrame(info).to_string(index=False))
batteries = sorted(age["battery"].unique())
cv = []
if len(batteries) >= 2:
    for held in batteries:                              # leave one battery out
        tr, te = age[age["battery"] != held], age[age["battery"] == held]
        m = fit_age(tr["life"].values, tr["soh"].values)
        pred = m.predict(te["life"].values.reshape(-1, 1))
        cv.append({"held_out": held, "mae_soh": float(np.abs(pred - te["soh"].values).mean())})
    print("Leave-one-battery-out error (SoH, 1.00 = 100%):")
    print(pd.DataFrame(cv).round(4).to_string(index=False))
model = fit_age(age["life"].values, age["soh"].values)
model.save_model(str(OUT / "age_model.json"))
grid = np.round(np.arange(0, 1.51, 0.05), 2)
curve = np.minimum.accumulate(model.predict(grid.reshape(-1, 1)).astype(float))
curve = curve / curve[0]                                  # a new battery is 100%

# ---------------------------------------------------------------- temperature curve (CALCE)
print("\n== Temperature curve (CALCE A123) ==")
runs = pd.read_csv(CALCE_RUNS)
runs["temp_c"] = runs["file"].str.extract(r"FUDS-(-?\d+)")[0].astype(float)       # chamber setting from filename
runs = runs.dropna(subset=["temp_c"])
t = runs.groupby("temp_c").agg(wh=("wh_out", "median"), n=("wh_out", "size")).reset_index().sort_values("temp_c")
t["raw_factor"] = t["wh"] / np.interp(REF_TEMP, t["temp_c"], t["wh"])
smooth = pav_increasing(t["raw_factor"].values, t["n"].values)                     # colder never gives more
smooth = smooth / np.interp(REF_TEMP, t["temp_c"], smooth)
t["factor"] = np.minimum(smooth, 1.0)                                              # no bonus for heat: stay conservative
print(t.round(3).to_string(index=False))

# ---------------------------------------------------------------- save
meta = {
    "ref_temp_c": REF_TEMP, "eol_soh": EOL_SOH,
    "age_curve": {"life": grid.tolist(), "soh": np.round(curve, 4).tolist()},
    "temp_curve": {"temp_c": t["temp_c"].tolist(), "factor": np.round(t["factor"], 4).tolist()},
    "temp_range_c": [float(t["temp_c"].min()), float(t["temp_c"].max())],
    "nasa_batteries": info, "age_cv": cv,
    "notes": ["Age: NASA 18650 cells at about 24 C; life = cycles used / cycles to 80% capacity.",
              "Temperature: CALCE A123 LiFePO4 cell, usable energy under DST/US06/FUDS, noisy between cells.",
              "Outside the tested temperature range the nearest tested value is used."],
}
(OUT / "meta.json").write_text(json.dumps(meta, indent=2))


def usable_fraction(life, temp_c):
    a = float(np.interp(life, grid, curve))
    tf = float(np.interp(temp_c, t["temp_c"], t["factor"]))
    return a * tf, a, tf


print("\n== Example usable fraction of nominal energy ==")
for life, temp in [(0.0, 25), (0.5, 25), (0.5, 10), (0.8, 10), (0.8, 0), (1.0, 40)]:
    u, a, tf = usable_fraction(life, temp)
    print(f"  life used {life:.0%}, {temp:>2} C -> age {a:.3f} x temp {tf:.3f} = {u:.3f}")
print(f"\nSaved: {OUT / 'age_model.json'}, {OUT / 'meta.json'}")
