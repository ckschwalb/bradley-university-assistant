import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { request } from '../request';
import { AUTH_REQUIRED_EVENT, getAdminToken, setAdminToken } from '../adminAuth';

const reply = (status, body) => vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });

describe('request', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it('sends the saved admin token and a JSON body', async () => {
    setAdminToken('s3cret');
    vi.stubGlobal('fetch', reply(200, { ok: true }));
    await request('/api/admin/x', { method: 'POST', body: { a: 1 } });
    const [, options] = fetch.mock.calls[0];
    expect(options.headers).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer s3cret' });
    expect(options.body).toBe('{"a":1}');
  });

  it('sends no Authorization header when there is no token', async () => {
    vi.stubGlobal('fetch', reply(200, {}));
    await request('/api/status');
    expect(fetch.mock.calls[0][1].headers).toEqual({});
  });

  it('forgets a refused token and announces that one is needed', async () => {
    setAdminToken('wrong');
    const needed = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, needed);
    vi.stubGlobal('fetch', reply(401, { detail: 'Admin token required' }));
    await expect(request('/api/admin/x')).rejects.toThrow('Admin token required');
    window.removeEventListener(AUTH_REQUIRED_EVENT, needed);
    expect(getAdminToken()).toBe('');
    expect(needed).toHaveBeenCalledTimes(1);
  });

  it('turns validation errors into one readable message', async () => {
    vi.stubGlobal('fetch', reply(422, { detail: [{ msg: 'String should have at most 1000 characters' }] }));
    await expect(request('/chat', { method: 'POST', body: {} })).rejects.toThrow('at most 1000 characters');
  });
});
