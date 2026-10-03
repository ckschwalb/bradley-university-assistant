import { describe, it, expect } from 'vitest';
import { parseTime, formatClock, isSameDay } from '../time';
import { formatDay, formatWhen } from '../../admin/api';

// The test run's time zone is America/Chicago (see setupTests.js), standing in for the viewer's
describe('time handling', () => {
  it('reads UTC times from the API as the right instant', () => {
    expect(parseTime('2026-01-15T18:00:00Z').toISOString()).toBe('2026-01-15T18:00:00.000Z');
    expect(parseTime('2026-01-15T18:00:00+00:00').toISOString()).toBe('2026-01-15T18:00:00.000Z');
    expect(parseTime('2026-01-15T12:00:00-06:00').toISOString()).toBe('2026-01-15T18:00:00.000Z');
  });

  it('reads a time without an offset as UTC, not local time', () => {
    expect(parseTime('2026-07-15T17:00:00').toISOString()).toBe('2026-07-15T17:00:00.000Z');
    expect(parseTime('2026-07-15 17:00:00.123456').toISOString()).toBe('2026-07-15T17:00:00.123Z');
  });

  it("shows times in the viewer's zone, winter and summer", () => {
    expect(formatClock('2026-01-16T02:15:00Z')).toBe('8:15 PM'); // CST, UTC-6
    expect(formatClock('2026-07-16T01:15:00Z')).toBe('8:15 PM'); // CDT, UTC-5
  });

  it("decides \"same day\" by the viewer's calendar, not UTC", () => {
    // 11 PM in Chicago on the 15th is already the 16th in UTC
    expect(isSameDay('2026-01-16T05:00:00Z', '2026-01-15T14:00:00Z')).toBe(true);
    expect(isSameDay('2026-01-16T05:00:00Z', '2026-01-16T07:00:00Z')).toBe(false);
  });

  it('labels days and relative times', () => {
    expect(formatDay('2020-02-03T16:00:00Z')).toBe('Feb 3, 2020');
    expect(formatWhen(null)).toBe('—');
    expect(formatWhen(new Date().toISOString())).toMatch(/^Today, /);
  });
});
