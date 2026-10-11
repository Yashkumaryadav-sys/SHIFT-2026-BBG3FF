# RangeTrue frontend

React + Vite dashboard for the FastAPI backend in `../Backend`.

## Run locally

In PowerShell:

```powershell
cd "C:\Users\dell\Desktop\SHIFT IIT BHU\SHIFT-IIT-BHU-2026\Frontend"
npm install
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). Keep the backend running on `http://localhost:8000`. The backend's development CORS settings already allow the Vite origin.

If your backend is elsewhere, open **API connection** in the dashboard and change the base URL. In production, enter the API key there only for a private demo. It is stored in the current browser session and sent as `X-API-Key`; do not put a shared production key in a frontend `.env`, source file, or public static deployment. A public app needs user authentication or a server-side proxy.

## Backend features used

- `GET /health` and `GET /vehicle-profiles`
- `POST /route-range`
- `POST /battery/status`
- `POST /re-estimate`

The built-in Xiaomi scooter profile is a public-data proxy, not a reading from the rider's actual scooter. This frontend uses that public profile for estimates.

## Build for static hosting

```powershell
npm run build
```

The static site is written to `dist/`. Add its exact deployed origin to the backend's `CORS_ORIGINS`. Do not bundle a production API key into the site.
