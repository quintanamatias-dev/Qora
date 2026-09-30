/**
 * Auth API — WorkOS AuthKit session endpoints (multi-tenant-auth §7, §9)
 *
 * Identity is carried by an httpOnly session cookie set by the backend at
 * login; there is no client-side token to manage. `/auth/login` and
 * `/auth/callback` are full browser navigations handled server-side and are
 * not fetched from here.
 */

import { useQuery } from '@tanstack/react-query'
import { apiFetch, ApiError } from './client'

export type AuthRole = 'superadmin' | 'client'
export type AuthMethod = 'api_key' | 'session'

export interface AuthConfig {
  login_enabled: boolean
}

export interface CallerMe {
  auth_method: AuthMethod
  role: AuthRole
  email: string | null
  name: string | null
  client_ids: string[]
}

export interface LogoutResult {
  logout_url: string | null
}

/** GET /api/v1/auth/config */
export function getAuthConfig(): Promise<AuthConfig> {
  return apiFetch<AuthConfig>('/api/v1/auth/config')
}

/** GET /api/v1/auth/me */
export function getMe(): Promise<CallerMe> {
  return apiFetch<CallerMe>('/api/v1/auth/me')
}

/**
 * POST /api/v1/auth/logout, then navigates to the WorkOS logout URL when one
 * is known, or back to /login otherwise.
 */
export async function logout(): Promise<void> {
  const result = await apiFetch<LogoutResult>('/api/v1/auth/logout', { method: 'POST' })
  window.location.assign(result.logout_url ?? '/login')
}

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/** queryKey: ['auth', 'me']. Never retries a 401 — that means "not logged in". */
export function useMe() {
  return useQuery<CallerMe, ApiError>({
    queryKey: ['auth', 'me'],
    queryFn: getMe,
    retry: (failureCount, error) => !isUnauthorized(error) && failureCount < 1,
  })
}

/** queryKey: ['auth', 'config'] */
export function useAuthConfig() {
  return useQuery<AuthConfig, ApiError>({
    queryKey: ['auth', 'config'],
    queryFn: getAuthConfig,
  })
}
