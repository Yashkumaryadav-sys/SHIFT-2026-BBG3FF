import re
import sys
from pathlib import Path
from tracemalloc import start
import numpy as np
import pandas as pd

IN_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
MIN_RUN_AH = 0.2            # a discharge run must remove at least this much to count
CHARGE_STEP_AH = 0.2        # a step that puts in at least this much counts as a charge step
MAX_DT = 60.0               # seconds; caps the time step so a logging gap cannot inflate the integral
PROFILES = ["DST", "US06", "FUDS"]   # CALCE notes: the three profiles run in this order in every file


def pick(cols, start):
    for c in cols:
        if c.lower().replace(" ", "").startswith(start):
            return c
    return None


def open_excel(path):
    """Read every sheet; give a clear reason when a file is not a real .xlsx."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    size_kb = path.stat().st_size / 1024
    if len(head) == 0:
        raise ValueError("empty file (0 KB). If it is on OneDrive, right-click it > Always keep on this device, or download it again")
    if head[:2] == b"PK":
        return pd.read_excel(path, sheet_name=None, engine="openpyxl")
    if head[:4] == b"\xd0\xcf\x11\xe0":
        try:
            return pd.read_excel(path, sheet_name=None, engine="xlrd")      # old .xls saved with an .xlsx name
        except ImportError:
            raise ValueError("old .xls format. Run: pip install xlrd   then run again")
    raise ValueError(f"not a real Excel file ({size_kb:.0f} KB, starts with {head[:6]!r}). "
                     "Likely a partial download or an OneDrive online-only placeholder. Download it again")


def read_file(path):
    sheets = open_excel(path)
    parts = []
    for name, df in sheets.items():
        df.columns = [str(c).strip() for c in df.columns]
        cols = {"t": pick(df.columns, "test_time"), "step": pick(df.columns, "step_index"),
                "i": pick(df.columns, "current"), "v": pick(df.columns, "voltage"),
                "temp": pick(df.columns, "temperature")}
        if cols["t"] and cols["i"] and cols["v"] and cols["step"]:
            sub = pd.DataFrame({k: pd.to_numeric(df[c], errors="coerce") for k, c in cols.items() if c})
            parts.append(sub)
    if not parts:
        raise ValueError("no sheet with Test_Time, Step_Index, Current and Voltage columns")
    d = pd.concat(parts, ignore_index=True).dropna(subset=["t", "i", "v"]).sort_values("t", kind="stable")
    if "temp" not in d:
        d["temp"] = np.nan
    d = d.reset_index(drop=True)
    d["dt"] = d["t"].diff().fillna(0).clip(0, MAX_DT)
    d["ah"] = d["i"] * d["dt"] / 3600            # signed: negative = discharge
    d["wh"] = d["i"] * d["v"] * d["dt"] / 3600
    return d


def step_table(d):
    g = (d["step"] != d["step"].shift()).cumsum()
    d["blk"] = g                                   # block number of each row
    t = d.groupby(g).agg(step=("step", "first"), rows=("t", "size"), start_s=("t", "first"),
                         dur_s=("dt", "sum"), mean_i=("i", "mean"), ah=("ah", "sum"),
                         v_start=("v", "first"), v_end=("v", "last"))
    return t.reset_index(drop=True)


def discharge_runs(d, steps):
    """A run = everything between two charge steps (the cell is full at the start of a run)."""
    is_charge = steps["ah"] >= CHARGE_STEP_AH
    runs, cur = [], None
    for k in range(len(steps)):
        if is_charge[k]:
            if cur is not None:
                runs.append(cur)
            cur = {"first_step": k + 1, "last_step": k}
        elif cur is not None:
            cur["last_step"] = k
    if cur is not None:
        runs.append(cur)
    out = []
    for r in runs:
        if r["last_step"] < r["first_step"]:
            continue
        s = steps.loc[r["first_step"]:r["last_step"]]
        ah_net = -s["ah"].sum()                       # net charge removed from the cell
        if ah_net < MIN_RUN_AH:
            continue
        seg = d[d["blk"].between(r["first_step"] + 1, r["last_step"] + 1)]
        out.append({"ah_out": ah_net, "wh_out": -seg["wh"].sum(),
                    "duration_min": (seg["t"].iloc[-1] - seg["t"].iloc[0]) / 60,
                    "v_min": seg["v"].min(), "v_end": seg["v"].iloc[-1],
                    "mean_temp": seg["temp"].mean() if seg["temp"].notna().any() else np.nan})
    out = pd.DataFrame(out)
    if len(out) == len(PROFILES):                     # label only when the count matches the three profiles
        out.insert(0, "profile", PROFILES)
    elif len(out):
        out.insert(0, "profile", "run" + (out.index + 1).astype(str))
    return out


def ambient_of(d, path):
    start = d["temp"].head(50).median() if d["temp"].notna().any() else np.nan
    m = re.search(r"FUDS-(-?\d+)", path.stem)         # e.g. A1-007-DST-US06-FUDS-0-20120813 -> 0
    name_temp = float(m.group(1)) if m else np.nan
    amb = name_temp if np.isfinite(name_temp) else round(start / 5) * 5      # the filename is the chamber setting
    return amb, start, name_temp


def main():
    files = sorted(p for p in IN_DIR.rglob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        sys.exit(f"No .xlsx files found under {IN_DIR.resolve()}")
    all_runs, skipped = [], []
    for n, f in enumerate(files):
        try:
            d = read_file(f)
            steps = step_table(d)
            amb, start_temp, name_temp = ambient_of(d, f)
            runs = discharge_runs(d, steps)
        except Exception as e:
            skipped.append((f, str(e)))
            print(f"\n!!! SKIPPED {f.name}: {e}")
            continue
        print(f"\n=== {f.name}: {len(d)} rows, {len(steps)} steps, start temp {start_temp:.1f} C "
              f"(filename says {name_temp}) -> ambient {amb} C")
        if runs.empty:
            print("  no discharge runs found in this file")
            skipped.append((f, "no discharge runs"))
            continue
        runs.insert(0, "file", f.name)
        runs.insert(1, "ambient_temp", amb)
        all_runs.append(runs)
        print(runs.round(3).to_string(index=False))
    if not all_runs:
        sys.exit("Nothing extracted.")

    runs = pd.concat(all_runs, ignore_index=True)
    summ = (runs.groupby("ambient_temp")
            .agg(files=("file", "nunique"), runs=("ah_out", "size"),
                 ah_median=("ah_out", "median"), ah_min=("ah_out", "min"), ah_max=("ah_out", "max"),
                 wh_median=("wh_out", "median"))
            .reset_index())
    ref = summ.loc[(summ["ambient_temp"] - 25).abs().idxmin()]
    summ["ah_factor"] = summ["ah_median"] / ref["ah_median"]         # 1.00 at the reference temperature
    summ["wh_factor"] = summ["wh_median"] / ref["wh_median"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summ.to_csv(OUT_DIR / "calce_temp_summary.csv", index=False)
    runs.to_csv(OUT_DIR / "calce_runs.csv", index=False)
    print("\n=== TEMPERATURE SUMMARY (reference = %s C) ===" % ref["ambient_temp"])
    print(summ.round(3).to_string(index=False))
    if skipped:
        print("\nFILES SKIPPED (fix or re-download these):")
        for f, why in skipped:
            print(" -", f.name, "->", why)


if __name__ == "__main__":
    main()