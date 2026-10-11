const allowedMethodsByPath = new Map([
  ['health', ['GET', 'HEAD']],
  ['vehicle-profiles', ['GET']],
  ['route-range', ['POST']],
  ['predict-range', ['POST']],
  ['battery/status', ['POST']],
  ['calibrate-baseline', ['POST']],
  ['rides/calibrate', ['POST']],
  ['re-estimate', ['POST']],
]);

function isAllowed(path, method) {
  const methods = allowedMethodsByPath.get(path);
  if (methods?.includes(method)) return true;
  return method === 'GET' && /^vehicles\/[A-Za-z0-9._~-]+\/calibration$/.test(path);
}

export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Allow', 'GET, HEAD, POST, OPTIONS');
    return res.status(204).end();
  }

  const pathParts = Array.isArray(req.query.path) ? req.query.path : [req.query.path].filter(Boolean);
  const backendPath = pathParts.join('/');
  if (!isAllowed(backendPath, req.method)) {
    return res.status(404).json({ detail: 'API route not found' });
  }

  const backendUrl = process.env.RANGETRUE_BACKEND_URL?.replace(/\/$/, '');
  const apiKey = process.env.RANGETRUE_API_KEY;
  if (!backendUrl || !apiKey) {
    return res.status(503).json({ detail: 'Backend proxy is not configured. Set server-side Vercel environment variables.' });
  }

  const query = new URL(req.url, 'https://vercel.local').search;
  const headers = { Accept: 'application/json', 'X-API-Key': apiKey };
  let body;
  if (!['GET', 'HEAD'].includes(req.method)) {
    headers['Content-Type'] = 'application/json';
    body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body ?? {});
  }

  try {
    const upstream = await fetch(`${backendUrl}/${backendPath}${query}`, {
      method: req.method,
      headers,
      ...(body !== undefined ? { body } : {}),
      signal: AbortSignal.timeout(30_000),
    });
    const responseBody = await upstream.text();
    res.status(upstream.status);
    res.setHeader('Content-Type', upstream.headers.get('content-type') || 'application/json');
    return res.send(responseBody);
  } catch (error) {
    console.error('RangeTrue backend proxy failed:', error.message);
    return res.status(502).json({ detail: 'The range backend is temporarily unavailable. Please retry.' });
  }
}
