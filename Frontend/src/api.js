const storedBase = () => sessionStorage.getItem('rangetrue_api_url') || 'http://localhost:8000';
const storedKey = () => sessionStorage.getItem('rangetrue_api_key') || '';

export async function api(path, { method = 'GET', body, baseUrl = storedBase(), apiKey = storedKey() } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (apiKey) headers['X-API-Key'] = apiKey;
  let response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, {
      method,
      headers,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (error) {
    throw new Error(`Cannot reach the backend at ${baseUrl}. Check that the API is running and CORS allows this frontend. (${error.message})`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
    throw new Error(`${response.status}: ${detail || response.statusText}`);
  }
  return data;
}

export const getApiSettings = () => ({ baseUrl: storedBase(), apiKey: storedKey() });
export function saveApiSettings(baseUrl, apiKey) {
  sessionStorage.setItem('rangetrue_api_url', baseUrl.trim().replace(/\/$/, ''));
  if (apiKey) sessionStorage.setItem('rangetrue_api_key', apiKey);
  else sessionStorage.removeItem('rangetrue_api_key');
}
