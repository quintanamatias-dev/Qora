/**
 * Ensure an ISO date string is parsed as UTC.
 *
 * The backend serializes UTC datetimes via Python's `datetime.isoformat()`
 * which omits the `Z` suffix. Without it, `new Date()` interprets the
 * string as local time. This helper appends `Z` when no timezone indicator
 * is present.
 *
 * Safe to call on strings that already carry timezone info — they pass through
 * unchanged.
 */
export function parseUTC(iso: string): Date {
  // Already has timezone info: trailing Z/z, or +HH:MM / -HH:MM offset
  if (/[Zz]$/.test(iso) || /[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso)
  }
  return new Date(iso + 'Z')
}
