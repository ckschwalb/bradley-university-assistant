import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from '../lib/request';

/**
 * GET `path` when the component mounts and whenever the path changes (a falsy path fetches nothing).
 *
 * Returns the response as `data` (null until it arrives), the failure message as `error`, `reload`
 * to fetch again (it resolves once the new data is in), and `setData` to update what's shown
 * without a request. Only the newest request's answer is used, so quick changes of `path` can't
 * leave older data on screen. By default `data` is null while a new path loads; pass
 * `keepPrevious` to keep showing the last response until the next one arrives.
 */
export const useApi = (path, { keepPrevious = false } = {}) => {
  const [result, setResult] = useState({ path: null, data: null });
  const [failure, setFailure] = useState({ path: null, message: '' });
  const latest = useRef(0);

  const reload = useCallback(async () => {
    if (!path) return;
    const ticket = ++latest.current;
    try {
      const data = await request(path);
      if (ticket === latest.current) {
        setResult({ path, data });
        setFailure({ path: null, message: '' });
      }
    } catch (e) {
      if (ticket === latest.current) setFailure({ path, message: e.message });
    }
  }, [path]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetching on mount; state is set when the response arrives
    reload();
    return () => {
      latest.current += 1; // an answer still on its way is for a path nobody is showing any more
    };
  }, [reload]);

  const setData = useCallback((next) => {
    setResult((r) => ({ path: r.path, data: typeof next === 'function' ? next(r.data) : next }));
  }, []);

  const setError = useCallback((message) => setFailure({ path, message }), [path]);
  const error = failure.path === path ? failure.message : '';
  const data = path && (result.path === path || keepPrevious) ? result.data : null;
  return { data, setData, error, setError, reload };
};
