// Calls to the admin API, turning FastAPI error bodies into readable messages
import { formatClock, formatDate, isSameDay } from '../lib/time';

export { request as api } from '../lib/request';

export const CONTENT_TYPE_LABELS = {
  course: 'Courses',
  'faculty-staff': 'Faculty & staff',
  page: 'Pages',
  program: 'Programs',
  department: 'Departments',
  college: 'Colleges',
  post: 'Posts',
};

export const typeLabel = (type) => CONTENT_TYPE_LABELS[type] || type;

// Times are shown in the viewer's own time zone (see lib/time.js)
export const formatTime = formatClock;

export const formatDay = (value) =>
  formatDate(value, {
    month: 'short',
    day: 'numeric',
    ...(formatDate(value, { year: 'numeric' }) !== formatDate(new Date(), { year: 'numeric' }) && { year: 'numeric' }),
  });

export const formatWhen = (value) => {
  if (!value) return '—';
  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 3600 * 1000);
  if (isSameDay(value, now)) return `Today, ${formatClock(value)}`;
  if (isSameDay(value, yesterday)) return `Yesterday, ${formatClock(value)}`;
  return `${formatDay(value)}, ${formatClock(value)}`;
};

export { isSameDay };

export const plural = (n, one, many = `${one}s`) => `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
