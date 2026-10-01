/**
 * API Client — base fetch function with typed error handling
 *
 * Design decisions:
 * - VITE_API_BASE_URL defaults to "" (same-origin) — works with Vite proxy
 * - Every request always sends X-Qora-Client: web and credentials: 'same-origin'
 *   (multi-tenant-auth §9). Authentication is carried by the httpOnly session
 *   cookie set by the backend at login — no client-side token handling.
 * - ApiError extends Error so try/catch instanceof checks work
 * - apiFetch is generic: apiFetch<T>(path) → Promise<T>
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

const AUTH_PATH_PREFIX = '/api/v1/auth/'

type UnauthorizedHandler = () => void

function defaultUnauthorizedHandler(): void {
  const returnTo = window.location.pathname + window.location.search
  window.location.assign(`/login?return_to=${encodeURIComponent(returnTo)}`)
}

let unauthorizedHandler: UnauthorizedHandler = defaultUnauthorizedHandler

/** Overrides the 401 handler — used by tests to avoid real navigation. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler
}

/** Restores the default (redirect to /login) unauthorized handler. */
export function resetUnauthorizedHandler(): void {
  unauthorizedHandler = defaultUnauthorizedHandler
}

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

  /**
   * Machine-readable error code from the canonical envelope
   * ({error: {reason}}), e.g. "plan_limit_reached" or "tenant_forbidden".
   * Undefined when the backend sent no code.
   */
  get reason(): string | undefined {
    const envelope = (this.body as { error?: unknown } | null)?.error
    if (envelope && typeof envelope === 'object' && 'reason' in envelope) {
      const reason = (envelope as { reason: unknown }).reason
      if (typeof reason === 'string') return reason
    }
    return undefined
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Merge headers explicitly before spreading the rest of init.
  // Spread order: defaults → caller overrides (caller wins on conflict).
  const mergedHeaders = {
    'Content-Type': 'application/json',
    'X-Qora-Client': 'web',
    ...(init?.headers as Record<string, string> | undefined),
  }

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: mergedHeaders,
    // Always same-origin: the session cookie is httpOnly and never sent cross-origin.
    credentials: 'same-origin',
  })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    // Auth endpoints report their own 401s as part of the login flow (e.g. an
    // expired login attempt) — they must not trigger the global redirect loop.
    if (res.status === 401 && !path.startsWith(AUTH_PATH_PREFIX)) {
      unauthorizedHandler()
    }
    throw new ApiError(res.status, body)
  }

  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}
