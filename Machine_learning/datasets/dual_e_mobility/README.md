# Public e-scooter example profile

The backend profile `xiaomi_pro2_public` is based on the e-scooter trip summary
in the [Dual E-Mobility Data repository](https://github.com/SFIEssential/DualEMobilityData-datasets).
The repository describes 30 real-world trips on a Xiaomi Mi Electric Scooter
Pro 2 and provides GPS, altitude, speed, SOC, and trip-level energy-use data.
The dataset repository is MIT licensed; retain attribution to its authors when
redistributing derived results.

The built-in profile uses the reported median of the 30 trip-summary Wh/km
values (19.8676 Wh/km) as a consumption baseline. Battery capacity (446 Wh),
rated range (45 km), and vehicle mass (14.2 kg) come from Xiaomi's
[official product page](https://www.mi.com/uk/mi-electric-scooter-Pro2/).
The median consumption is normalized using the backend's existing mass
adjustment formula and the dataset's median rider-weight band (90–100 kg).
For context, the 25th and 75th percentile trip consumptions are 14.751 and
30.905 Wh/km. The API converts those into a `range_sensitivity_km` interval by
re-running the route estimate at both consumption levels. This interval shows
the spread of observed conditions; it is not a statistical confidence bound.

This is a **public-data demonstration profile**, not a calibration for a
different scooter. The source has 30 trips and measured consumption varies
substantially (8.92–43.08 Wh/km); it does not supply battery cycle age for the
profile. `cycles_used` and `temp_c` remain request inputs. Do not present its
predictions as validated for another vehicle or as production accuracy.
