# RangeTrue testing guide

This guide covers the current React/Vite frontend, FastAPI backend, route/elevation integrations, and the current range/ML proxies. It is a test plan, not a claim that the estimates are validated for every real vehicle.

## 1. Start the app and check the services

Open PowerShell in the repository root (`SHIFT-IIT-BHU-2026`).

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
```

Expected: the `api` container is `healthy` and `/health` returns `status: ok` (or reports degraded if the model is unavailable). Start the frontend in a second PowerShell window:

```powershell
cd .\Frontend
npm run dev
```

Open the exact Local URL Vite prints, commonly `http://localhost:5173/` or `http://localhost:5174/`. If it chooses a different port, add that exact origin to `CORS_ORIGINS` in `Backend/.env`, then recreate the API container with `docker compose up -d --force-recreate api`.

Useful diagnostics:

```powershell
docker compose logs --tail 100 api
docker compose ps
Get-NetTCPConnection -LocalPort 5173,5174,8000 -State Listen -ErrorAction SilentlyContinue
```

Do not put the API key in source code or send it in chat. The production API requires `X-API-Key` for protected routes. Enter it only in the app's API connection settings for local browser testing. `/health` is public. Production mode intentionally disables `/docs`; Swagger is available only when running the backend in development mode.

## 2. Existing automated backend tests

From `Backend` in PowerShell:

```powershell
cd .\Backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The current suite has 11 tests covering battery power/direction, calibration save/use, input validation, model fallback, telemetry energy integration and sample-gap rejection, re-estimation limits, route/elevation mocking, and unknown vehicle IDs. These are backend tests; they do not test browser rendering or live upstream availability.

## 3. API checks

Use the frontend after entering the local API key, or use Swagger while running a development backend. For a direct PowerShell request, keep the key in a local variable and do not paste its value into a shared log or chat:

```powershell
$headers = @{ "X-API-Key" = "PASTE_LOCAL_KEY_HERE" }
Invoke-RestMethod -Headers $headers http://localhost:8000/vehicle-profiles
```

Check these cases:

| Endpoint                                 | Valid case                                                                | Invalid / boundary case to verify                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `GET /health`                            | Returns healthy/degraded status                                           | Stop API and confirm the UI explains it is unreachable                                                |
| `GET /vehicle-profiles`                  | Profile list loads with key                                               | No key/wrong key returns 401 in production                                                            |
| `POST /battery/status`                   | Positive current means discharge; negative means regen                    | Zero/negative voltage, invalid SOC, and out-of-range values return 422                                |
| `POST /calibrate-baseline`               | Positive energy and distance saves a baseline for the vehicle ID          | Tiny/zero distance or energy rejected; unknown ID lookup returns 404                                  |
| `POST /rides/calibrate`                  | Ordered timestamped samples integrate voltage × current and save baseline | Reversed timestamps, too few samples, or a sample gap over 300 seconds rejected                       |
| `GET /vehicles/{vehicle_id}/calibration` | Previously calibrated ID returns saved value                              | Unknown ID returns 404                                                                                |
| `POST /predict-range`                    | Uses selected public profile or pack/rated-range fallback                 | SOC below 0 or above 100, trip below 0.5 km, and missing both baseline options rejected               |
| `POST /route-range`                      | Route and elevation profile returned for valid coordinates                | Invalid coordinates or unroutable endpoints produce a clear client error; upstream failure is 502/504 |
| `POST /re-estimate`                      | Update after a portion of a trip                                          | `km_done` greater than original trip is rejected                                                      |

For production API-key checks, expected outcomes are: no key → 401, wrong key → 401, valid key → endpoint response. Do not weaken auth just to make the browser work; make sure the UI sends the key and that its origin is included in `CORS_ORIGINS`.

## 4. Frontend manual test pass

In the browser, test each item and note pass/fail plus a screenshot for any failure:

1. Load the page with backend running and confirm the API status changes to online.
2. Enter the API key in API connection settings; refresh and confirm protected profile/route requests work as intended.
3. Check the default Varanasi route labels and coordinates. Edit start/end coordinates and confirm the displayed route changes; labels are only descriptive unless reverse geocoding is implemented.
4. Calculate a route at SOC 80%, temperature 25°C, cycles 0, rider 65 kg, vehicle 110 kg, public proxy profile. Confirm range card, reachable verdict, route distance and elevation chart populate.
5. Change SOC to 20%, then 0%; estimates should fall and 0% should not imply usable range.
6. Increase rider/load mass; estimated range should not increase. Increase safety reserve; safe range should not increase.
7. Change route to a hillier route / different coordinates; check profile and route energy change where elevation changes.
8. Submit invalid values (e.g. SOC 120, negative mass, malformed coordinates); show validation feedback without freezing the page.
9. Test calibration form, submit a calibration, then use the same vehicle ID for a prediction and verify the saved baseline is applied. Use obviously synthetic/test values only.
10. Test API stopped, wrong key, and a temporary network disconnection. Error should explain the next action and provide a retry path; page should remain responsive.
11. Resize to mobile width and test navigation, forms, chart clipping, keyboard focus, and readable contrast.
12. Check browser DevTools Console and Network: no repeated request loop, no unhandled promise errors, no API key in URL, and requests go to the configured backend.

## 5. Range and ML sanity checks

Use deterministic input pairs and compare direction/trends rather than expecting arbitrary exact values:

- Same vehicle/route/SOC with higher rider+cargo mass should not yield more range.
- Same conditions with higher SOC should not yield less range.
- Increasing cycles used should not improve the age factor (subject to the model's documented behavior).
- Colder/hotter temperatures within tested support should affect usable energy consistently with the loaded temperature model; outside 0–50°C the current implementation clamps to the nearest tested value, so treat that as extrapolation/limitation.
- Higher elevation gain should generally increase estimated route energy; a downhill can recover at most the amount allowed by the model's regen assumptions.
- Increasing the safety margin should reduce safe range and the arrival reserve budget.
- Check energy accounting: usable energy, trip energy, arrival energy, and reserve should be numerically consistent and finite; no negative range or NaN/Infinity.
- Compare the estimate with the reported sensitivity band and label it as uncertainty from the dataset distribution, not a statistical confidence interval.

Current model/data limits: the age proxy is based on NASA 18650 cells; temperature behavior uses CALCE A123 LiFePO4 cell data; the scooter consumption proxy is 30 Dublin-area trips. These are not a validated Tata/e-scooter model or a substitute for vehicle BMS/ride measurements. Record this limitation in demos and do not present estimates as guaranteed range.

## 6. Route/elevation integration and failure testing

The automated route test mocks OSRM and Open-Elevation. To check real integrations, run one normal route request with internet access and inspect `route_source`, `elevation_source`, route distance, and profile sample count. Then verify:

- Repeat the identical request and check that response is still correct (successful route/profile data is cached in process).
- Temporarily disable internet or point service URLs to an invalid local URL in a disposable development environment; confirm retries stop and API returns 502/504 rather than hanging indefinitely.
- Try an unroutable/invalid coordinate pair and confirm a clear error.
- Restart API and repeat; caches are process-local, so a fresh upstream lookup is expected.

Do not stress public OSRM/Open-Elevation services with load tests; use mocks or self-hosted test services for repeated/high-volume checks.

## 7. Build, deployment, and security checks

Frontend production build:

```powershell
cd .\Frontend
npm run build
```

Docker smoke check:

```powershell
cd ..
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
docker compose logs --tail 100 api
```

Security/config checks before any public deployment:

- `Backend/.env`, database files, raw datasets, virtual environments, and secrets must not be staged in Git. Only safe examples such as `Backend/env.example` belong in a public repo.
- Confirm `APP_ENV=production`, a newly generated strong API key, and exact deployed frontend origin in `CORS_ORIGINS`.
- Verify protected APIs reject missing/wrong keys; health alone is public.
- The current shared API key in a browser is suitable only for local/demo testing. A public frontend needs user authentication or a backend-for-frontend so a shared secret is not shipped to every visitor.
- Confirm calibration persistence after container restart. The Compose volume should retain the SQLite file; test only with disposable records.
- Verify HTTPS, host-level rate limits, logs/monitoring, and backup/restore before production.

## 8. What the current tests do not prove

- No real BMS hardware/telemetry connection is verified.
- Public proxy data and NASA/CALCE models do not establish accuracy for a particular vehicle.
- Mocked upstream tests do not prove OSRM/Open-Elevation uptime or response quality.
- Existing backend tests do not cover every error, CORS deployment, authentication integration in the browser, or frontend UI behavior.
- No load, penetration, accessibility, or real-rider pilot test is currently established by the 11 unit/API tests.

Keep a simple test log: date, commit, environment (local/Docker), input, expected behavior, actual behavior, pass/fail, and issue/screenshot link. Start with sections 1–4; then do ML and external-service checks. Production/pilot validation needs real vehicle specifications and measured rides.
