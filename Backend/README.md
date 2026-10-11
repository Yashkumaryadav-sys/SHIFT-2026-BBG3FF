# Backend upstream-service behavior

`POST /route-range` calls OSRM for road geometry and Open-Elevation for the elevation profile.

## Reliability controls

- Successful route responses are cached in memory for 15 minutes by default.
- Successful elevation profiles are cached in memory for 24 hours by default.
- Temporary timeouts, network failures, HTTP 429 responses, and upstream 5xx responses are retried twice with a short exponential delay. The delay honors numeric `Retry-After` values up to five seconds.
- If retries are exhausted, timeouts return HTTP 504 and other upstream errors return HTTP 502. A route that the router cannot find returns HTTP 422.
- Failed or incomplete upstream responses are never cached.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OSRM_URL` | `https://router.project-osrm.org` | OSRM base URL |
| `OPEN_ELEVATION_URL` | `https://api.open-elevation.com/api/v1/lookup` | Open-Elevation lookup URL |
| `UPSTREAM_TIMEOUT_SECONDS` | `20` | Per-request upstream timeout |
| `UPSTREAM_RETRIES` | `2` | Retries after the initial request; set to `0` to disable |
| `ROUTE_CACHE_TTL_SECONDS` | `900` | Route cache lifetime; set to `0` to disable |
| `ELEVATION_CACHE_TTL_SECONDS` | `86400` | Elevation cache lifetime; set to `0` to disable |
| `UPSTREAM_CACHE_MAX_ENTRIES` | `512` | Maximum cached route/profile entries |

The cache is process-local and is cleared when the backend restarts. If deploying multiple workers or instances, use a shared cache such as Redis so they share entries. These controls improve resilience but do not replace production monitoring or an operational SLA for the public upstream services.

## Local development and production security

Local development defaults to `APP_ENV=development`; the API key is not required and Swagger remains enabled. For production, the app requires:

- `APP_ENV=production`
- `RANGETRUE_API_KEY` with at least 32 characters
- Explicit `CORS_ORIGINS` for the deployed frontend; `*` is rejected

Send the key on every API request (except `GET /health`) as `X-API-Key`. Production disables Swagger, ReDoc, and the OpenAPI schema. The public health response only reports `ok` or `degraded`; it does not expose model details. Keep the key in the hosting provider's secret store, not in frontend source code. A browser frontend cannot safely hold a shared secret, so a public web app should put an authenticated user-facing service between browsers and this API before exposing it broadly.

The API does not implement distributed rate limiting. Configure request limits at the hosting platform, API gateway, or reverse proxy. Terminate HTTPS at that platform/proxy. The included SQLite database and in-memory cache are intended for a single API worker/instance; use a managed database and shared Redis cache before horizontal scaling.

## Docker deployment

From the repository root, copy `Backend/env.example` to `Backend/.env`, replace the API key and frontend origin, then run. To generate a random key in PowerShell:

```powershell
$keyBytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($keyBytes)
[Convert]::ToBase64String($keyBytes)
```

Paste the generated value into `RANGETRUE_API_KEY` in `Backend/.env`. Then:

```powershell
Copy-Item Backend/env.example Backend/.env
docker compose up --build -d
docker compose logs -f api
```

The container runs as a non-root user, listens on port 8000, and stores calibration SQLite data in the persistent `rangetrue-data` volume. The Docker build context intentionally excludes raw datasets and local virtual environments; it includes only `Machine_learning/models` for inference.

## Deploying this Docker service on Render

Push the deployment files to the Git branch Render will deploy. In Render, create a **Web Service** from that repository and set:

- Runtime: **Docker**
- Root directory / Docker context: repository root (`.`), because the Dockerfile copies `Machine_learning/models`
- Dockerfile path: `Backend/Dockerfile`
- Health check path: `/health`
- Environment variables: `APP_ENV=production`, a newly generated `RANGETRUE_API_KEY` (at least 32 random characters), and explicit `CORS_ORIGINS`
- Database path: `RANGETRUE_DB_PATH=/data/rangetrue.sqlite3`

The Docker command reads Render's `PORT` variable and falls back to port 8000 locally. Set `CORS_ORIGINS` to the actual frontend origin when the frontend is deployed; use the Render service's own URL temporarily if the API is deployed before the frontend.

**Calibration persistence:** this API stores vehicle calibrations in SQLite. Render's default filesystem is ephemeral, so calibrations can disappear after restarts or deploys unless `/data` is on a persistent disk. Render persistent disks are available for paid services. For a free service, deploy only as a temporary demo with disposable calibration records, or first migrate SQLite storage to a managed database. See [Render persistent disk docs](https://render.com/docs/disks).
