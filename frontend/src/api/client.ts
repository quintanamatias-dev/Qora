/**
 * API Client — base fetch function with typed error handling
 *
 * Design decisions:
 * - VITE_API_BASE_URL defaults to "" (same-origin) — works with Vite proxy
 * - ApiError extends Error so try/catch instanceof checks work
 * - apiFetch is generic: apiFetch<T>(path) → Promise<T>
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

function errorMessageFromBody(status: number, body: unknown): string {
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
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    ...init,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body)
  }

  return res.json() as Promise<T>
}
