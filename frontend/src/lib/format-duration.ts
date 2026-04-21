/**
 * formatDuration — Pure utility for formatting seconds to a human-readable string.
 *
 * Spec: sdd/qora-dashboard-metrics/spec
 *   < 3600s  → "M:SS"  (minutes:seconds, no leading zero on minutes)
 *   ≥ 3600s  → "Xh Ym" (hours and minutes)
 *   0 or negative → "0:00"
 */

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))

  if (s < 3600) {
    const minutes = Math.floor(s / 60)
    const secs = s % 60
    return `${minutes}:${String(secs).padStart(2, '0')}`
  }

  const hours = Math.floor(s / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  return `${hours}h ${minutes}m`
}
