/**
 * Times are stored in UTC and shown in the viewer's own time zone.
 *
 * The backend sends every time with its offset ("2026-03-03T20:15:00Z" or "...+00:00"), which
 * `new Date` reads as the right instant. A time without an offset is read as UTC too, never as
 * local time, since that's what the server stores.
 */

const NO_OFFSET = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export const parseTime = (value) => {
  if (value instanceof Date) return value;
  if (typeof value === 'string' && NO_OFFSET.test(value)) return new Date(`${value.replace(' ', 'T')}Z`);
  return new Date(value);
};

export const formatClock = (value) =>
  parseTime(value).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

export const formatDate = (value, options) => parseTime(value).toLocaleDateString('en-US', options);

export const formatDateTime = (value) => parseTime(value).toLocaleString('en-US');

// Calendar day in the viewer's time zone, for "is this today?" checks
export const dayKey = (value) => formatDate(value, { year: 'numeric', month: '2-digit', day: '2-digit' });

export const isSameDay = (a, b) => dayKey(a) === dayKey(b);

// The viewer's IANA time zone, so the server can group by the viewer's days
export const viewerTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
