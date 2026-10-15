# McMaster Tesla 2170 cell drive-cycle data

## Source and license

- Dataset: [Tesla Model 3 2170 Li-ion Cell Dataset and Battery SOC Estimation Blind Modeling Tool](https://doi.org/10.5683/SP3/ZVTR4B)
- Repository: Borealis, McMaster University
- License: CC BY 4.0. Cite the dataset and its authors when publishing results.
- Official dataset page: https://battery.mcmaster.ca/research/datasets-and-algorithms/

## Local files

The downloaded official training-example archive is kept locally as
`3-Neural-Network-Training-Examples.zip`. The selected Python example data and
its README are extracted under `raw/Python_Examples/`. Both the archive and raw
data are excluded from Git because they are large; download them again from the
official Borealis record when setting up another machine.

The example package contains MATLAB `.mat` files with `X`/`Y` pairs. The
McMaster example code describes the three input columns as current, voltage,
and temperature, with SOC as the target. These are prepared cell-level SOC
training examples, not scooter telemetry or complete vehicle-trip records.

To flatten the local examples into a CSV for SOC experiments, from the project
root run:

```powershell
Backend\.venv\Scripts\python.exe Machine_learning\mcmaster_loader.py
```

This writes the ignored generated file
`Machine_learning/datasets/mcmaster_tesla/processed/mcmaster_soc_samples.csv`.
The values are preserved as provided by the examples; the loader does not
assign physical units or turn cell-level samples into vehicle-range labels.

## Intended use and limits

This is the closest dataset on the linked site to EV drive-cycle battery data,
but it is **not a scooter dataset**. It can support a future SOC-estimation
experiment. It does not provide the scooter's pack-level Wh/km, route distance,
road elevation, or a validated scooter range label, so do not use these samples
as direct range-calibration values or feed them into `/rides/calibrate` as if
they were a real scooter ride. The current range endpoint continues to use the
measured per-vehicle baseline or its rated-range fallback.

The official release includes open and blinded data portions. Only the
downloaded Python training-example package is present locally; this is not the
full 705 MB open-data archive.

## Citation

P. J. Kollmeyer, F. Khanum, M. Naguib, and A. Emadi, “Tesla Model 3 2170 Li-ion
Cell Dataset and Battery SOC Estimation Blind Modeling Tool,” Borealis, 2023,
doi: [10.5683/SP3/ZVTR4B](https://doi.org/10.5683/SP3/ZVTR4B).
