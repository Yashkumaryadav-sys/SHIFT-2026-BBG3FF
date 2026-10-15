"""Convert the downloaded McMaster MATLAB SOC examples into a flat CSV.

The exported feature values are preserved as provided by the dataset. This
script does not infer physical units or convert these cell-level samples into
vehicle range labels.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
from scipy.io import loadmat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "Machine_learning/datasets/mcmaster_tesla/raw/Python_Examples/Data"
DEFAULT_OUTPUT = PROJECT_ROOT / "Machine_learning/datasets/mcmaster_tesla/processed/mcmaster_soc_samples.csv"
SPLITS = ("Train", "Validation", "Test")


def _feature_rows(x: np.ndarray, y: np.ndarray, source: Path):
    """Yield paired 3-feature rows and scalar SOC targets from X/Y arrays."""
    x = np.asarray(x, dtype=float).squeeze()
    y = np.asarray(y, dtype=float).squeeze()
    if x.ndim != 2:
        raise ValueError(f"{source}: expected a 2D X array, got shape {x.shape}")
    if x.shape[1] == 3:
        features = x
    elif x.shape[0] == 3:
        features = x.T
    else:
        raise ValueError(f"{source}: expected X with 3 columns or 3 rows, got {x.shape}")
    targets = y.reshape(-1)
    if len(features) != len(targets):
        raise ValueError(f"{source}: X has {len(features)} samples but Y has {len(targets)}")
    if not np.isfinite(features).all() or not np.isfinite(targets).all():
        raise ValueError(f"{source}: X/Y contains NaN or infinite values")
    return features, targets


def convert(data_root: Path = DATA_ROOT, output: Path = DEFAULT_OUTPUT) -> dict[str, int]:
    """Convert all X/Y MATLAB examples and return sample counts by split."""
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {split: 0 for split in SPLITS}
    files = [(split, path) for split in SPLITS for path in sorted((data_root / split).rglob("*.mat"))]
    if not files:
        raise FileNotFoundError(f"No .mat files found under {data_root}; download/extract the official Python examples first.")

    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("split", "source_file", "current_feature", "voltage_feature", "temperature_feature", "soc_target_as_provided"))
        for split, path in files:
            mat = loadmat(path)
            if "X" not in mat or "Y" not in mat:
                raise ValueError(f"{path}: expected X and Y variables")
            features, targets = _feature_rows(mat["X"], mat["Y"], path)
            writer.writerows((split, path.name, *row, target) for row, target in zip(features, targets))
            counts[split] += len(targets)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    counts = convert(args.data_root, args.output)
    print("Converted McMaster cell-level SOC samples:")
    for split, count in counts.items():
        print(f"  {split}: {count:,}")
    print(f"  Total: {sum(counts.values()):,}")
    print(f"  CSV: {args.output.resolve()}")
    print("Feature and SOC values are preserved as provided; they are not scooter range labels.")


if __name__ == "__main__":
    main()
