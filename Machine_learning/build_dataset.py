import sys
from pathlib import Path
import numpy as np
import pandas as pd
import scipy.io

DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")   # folder holding the .mat files
OUT_CSV = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("nasa_discharge_all.csv")
NOMINAL_AH = 2.0       # nominal capacity of the NASA 18650 cells
MIN_CAP_AH = 0.3       # below this the cell hit its voltage cutoff immediately; not usable data
MIN_CYCLES = 30        # drop batteries with fewer usable discharge cycles than this
trapz = getattr(np, "trapezoid", None) or np.trapz


def scalar(x):
    return float(np.asarray(x, dtype=float).ravel()[0])


def load_battery(path):
    mat = scipy.io.loadmat(str(path), simplify_cells=True)
    key = next(k for k in mat if not k.startswith("__"))
    rows, n_dis = [], 0
    for c in mat[key]["cycle"]:
        if c["type"] != "discharge":
            continue
        n_dis += 1                                   # age = position among discharge cycles
        d = c["data"]
        try:
            t = np.asarray(d["Time"], dtype=float)
            v = np.asarray(d["Voltage_measured"], dtype=float)
            i = np.abs(np.asarray(d["Current_measured"], dtype=float))
            cap = scalar(d["Capacity"])
            amb = scalar(c["ambient_temperature"])
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        active = i[i > 0.2]                          # ignore rest samples before and after the discharge
        if active.size == 0:
            continue
        rows.append({
            "battery": path.stem,
            "cycle_number": n_dis,
            "ambient_temp": amb,
            "discharge_current": round(float(np.median(active)) * 2) / 2,
            "avg_voltage": float(v[i > 0.2].mean()),
            "duration_s": float(t[-1] - t[0]),
            "energy_wh": float(trapz(v * i, t) / 3600),
            "capacity_ah": cap,
        })
    return pd.DataFrame(rows)


def clean(df):
    n0 = len(df)
    df = df[(df["capacity_ah"] >= MIN_CAP_AH) & (df["capacity_ah"] < 2.6)].copy()
    dropped = n0 - len(df)
    keep = []
    # spike filter inside each regime (same temperature and current)
    for _, g in df.sort_values("cycle_number").groupby(["ambient_temp", "discharge_current"]):
        med = g["capacity_ah"].rolling(5, center=True, min_periods=1).median()
        keep.append(g[(g["capacity_ah"] - med).abs() <= 0.15 * med])
    df = pd.concat(keep).sort_values("cycle_number") if keep else df.iloc[0:0]
    df["usable_fraction"] = df["capacity_ah"] / NOMINAL_AH      # model target
    return df, dropped


def main():
    files = sorted(DATA_DIR.rglob("*.mat"))
    if not files:
        sys.exit(f"No .mat files found under {DATA_DIR.resolve()}")
    frames, skipped, dropped_total = [], [], {}
    for f in files:
        try:
            df = load_battery(f)
            if df.empty:
                skipped.append((f.name, "no discharge cycles"))
                continue
            df, dropped = clean(df)
        except Exception as e:
            skipped.append((f.name, str(e)[:70]))
            continue
        dropped_total[f.stem] = dropped
        if len(df) < MIN_CYCLES:
            skipped.append((f.name, f"only {len(df)} usable cycles"))
            continue
        frames.append(df)
    if not frames:
        sys.exit("No battery passed the filters.")

    data = pd.concat(frames, ignore_index=True)
    data.to_csv(OUT_CSV, index=False)

    summary = (data.groupby(["battery", "ambient_temp", "discharge_current"])
               .agg(cycles=("cycle_number", "count"),
                    first_cycle=("cycle_number", "min"), last_cycle=("cycle_number", "max"),
                    cap_first_ah=("capacity_ah", "first"), cap_last_ah=("capacity_ah", "last"))
               .round(2))
    print(summary.to_string())
    print()
    print(f"Kept {data['battery'].nunique()} batteries, {len(data)} discharge cycles -> {OUT_CSV}")
    print("Temperatures (C):", sorted(float(x) for x in data["ambient_temp"].round().unique()))
    print("Discharge currents (A):", sorted(float(x) for x in data["discharge_current"].unique()))
    print("Cycles removed as unusable:", {k: v for k, v in dropped_total.items() if v})
    for name, why in skipped:
        print("skipped:", name, "-", why)


if __name__ == "__main__":
    main()