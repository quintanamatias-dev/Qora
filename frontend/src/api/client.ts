/**
 * API Client — base fetch function with typed error handling
 *
 * Design decisions:
 * - VITE_API_BASE_URL defaults to "" (same-origin) — works with Vite proxy
 * - VITE_API_KEY is the admin Bearer token (Phase B5). Set in frontend/.env.
 *   Phase C: replaced by JWT from login flow — apiFetch signature unchanged.
 * - ApiError extends Error so try/catch instanceof checks work
 * - apiFetch is generic: apiFetch<T>(path) → Promise<T>
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

// Phase B5: static Bearer token for admin API access.
// Injected at build time from VITE_API_KEY env var.
// Phase C: swap for getAccessToken() from auth provider — zero call-site changes.
const API_KEY = import.meta.env.VITE_API_KEY ?? ''

function errorMessageFromBody(status: number, body: unknown): string {
  // Primary: parse canonical error envelope {error: {code, message, request_id}}
  // This is the format returned by the global exception handlers (B9 observability).
  if (body && typeof body === 'object' && 'error' in body) {
    const envelope = (body as { error: unknown }).error
    if (envelope && typeof envelope === 'object' && 'message' in envelope) {
      const message = (envelope as { message: unknown }).message
      if (typeof message === 'string' && message.length > 0) return message
    }
  }

  // Fallback: parse legacy FastAPI {detail: ...} shape for backward compatibility.
  // This handles any endpoints that do not yet go through the global handlers,
  // or responses from external services that still use the detail format.
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg)
          }
          return String(item)
        })
        .filter(Boolean)
      if (messages.length > 0) return messages.join(', ')
    }
    if (detail != null) return JSON.stringify(detail)
  }

  return `API ${status}`
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown
  ) {
    super(errorMessageFromBody(status, body))
    this.name = 'ApiError'
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Build Authorization header when API_KEY is configured.
  // Empty string means no key is set (dev without auth or public endpoint).
  const authHeaders: HeadersInit = API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {}

  // Merge headers explicitly before spreading the rest of init.
  // Spread order: defaults → auth → caller overrides (caller wins on conflict).
  // The merged headers object is assigned last so `...init` cannot overwrite it.
  const mergedHeaders = {
    'Content-Type': 'application/json',
    ...authHeaders,
    ...(init?.headers as Record<string, string> | undefined),
  }

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: mergedHeaders,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body)
  }

  return res.json() as Promise<T>
}
