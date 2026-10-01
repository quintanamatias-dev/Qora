/**
 * returnTo sanitizing (multi-tenant-auth §5, §9) — mirrors the backend rule so
 * the frontend never builds a link that escapes the app or targets the API.
 *
 * Must start with a single '/', not '//' or '/\', and not '/api/'.
 */
export function sanitizeReturnTo(value: string | null | undefined): string {
  if (!value) return '/'
  if (!value.startsWith('/')) return '/'
  if (value.startsWith('//') || value.startsWith('/\\')) return '/'
  if (value.startsWith('/api/')) return '/'
  return value
}
