import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useApi } from './useApi';

const answers = (map) => vi.fn((path) => new Promise((resolve) => {
  const [delay, body] = map[path];
  setTimeout(() => resolve({ ok: true, status: 200, json: async () => body }), delay);
}));

describe('useApi', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads the path, and loads again on reload', async () => {
    let n = 0;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ n: ++n }) })));
    const { result } = renderHook(() => useApi('/api/a'));
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.data).toEqual({ n: 1 }));
    await act(() => result.current.reload());
    expect(result.current.data).toEqual({ n: 2 });
  });

  it('shows the failure message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ detail: 'Boom' }) })));
    const { result } = renderHook(() => useApi('/api/a'));
    await waitFor(() => expect(result.current.error).toBe('Boom'));
  });

  it('ignores a slow answer for a path that is no longer shown', async () => {
    vi.stubGlobal('fetch', answers({ '/api/slow': [60, 'slow'], '/api/fast': [0, 'fast'] }));
    const { result, rerender } = renderHook(({ path }) => useApi(path), { initialProps: { path: '/api/slow' } });
    rerender({ path: '/api/fast' });
    await waitFor(() => expect(result.current.data).toBe('fast'));
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(result.current.data).toBe('fast');
  });

  it('can keep the previous data while the next path loads', async () => {
    vi.stubGlobal('fetch', answers({ '/api/1': [0, 'one'], '/api/2': [30, 'two'] }));
    const { result, rerender } = renderHook(({ path }) => useApi(path, { keepPrevious: true }), { initialProps: { path: '/api/1' } });
    await waitFor(() => expect(result.current.data).toBe('one'));
    rerender({ path: '/api/2' });
    expect(result.current.data).toBe('one');
    await waitFor(() => expect(result.current.data).toBe('two'));
  });

  it('fetches nothing without a path', () => {
    vi.stubGlobal('fetch', vi.fn());
    const { result } = renderHook(() => useApi(null));
    expect(result.current.data).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
