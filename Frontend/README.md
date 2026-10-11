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

Local development can use **API connection** to change the backend base URL or supply a local API key. The deployed site always uses the same-origin Vercel serverless proxy at `/api`; it does not use a visitor's `localhost` or expose the backend key in browser code.

## Deploy on Vercel

Set these variables in **Vercel → Project → Settings → Environment Variables** for Production (and Preview if needed):

- `RANGETRUE_BACKEND_URL` = `https://shift-2026-bbg3ff.onrender.com`
- `RANGETRUE_API_KEY` = the same secret configured on the Render backend

Keep `RANGETRUE_API_KEY` server-side: do not prefix it with `VITE_`, add it to source files, or expose it as a frontend build variable. After saving the variables, redeploy the Vercel project. All deployed devices then use `/api` automatically and do not need a manually entered key. The proxy only forwards the known RangeTrue API endpoints. Add rate limiting or user authentication before opening the service to significant public traffic.

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

The static site is written to `dist/`. The Vercel serverless proxy handles production API calls, so browser requests use the same origin. Keep localhost in the backend's `CORS_ORIGINS` for direct local development.
