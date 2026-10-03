// JSON calls to the app's own API, turning FastAPI error bodies into readable messages
import { authHeaders, authRequired } from './adminAuth';

export const request = async (path, { method = 'GET', body, signal } = {}) => {
  const response = await fetch(path, {
    method,
    headers: { ...(body !== undefined && { 'Content-Type': 'application/json' }), ...authHeaders() },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) authRequired();
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
      : detail || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return data;
};
