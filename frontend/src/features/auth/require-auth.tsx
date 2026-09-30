/**
 * RequireAuth — session gate for every route except /login (multi-tenant-auth §9)
 *
 * Loads the caller identity via useMe(); shows a loading state while pending,
 * and redirects to /login?return_to=<current path+search> on a 401. Any other
 * query error is unexpected (not part of the auth contract) and is thrown so
 * it surfaces as a real error rather than a silent redirect loop.
 */

import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from '@/api/auth'
import { ApiError } from '@/api/client'

export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { data, isLoading, isError, error } = useMe()

  if (isLoading) {
    return (
      <div data-testid="auth-loading" className="flex min-h-screen items-center justify-center bg-pearl">
        <p className="text-sm text-ink-3">Cargando…</p>
      </div>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 401) {
      const returnTo = location.pathname + location.search
      return <Navigate to={`/login?return_to=${encodeURIComponent(returnTo)}`} replace />
    }
    throw error
  }

  if (!data) return null

  return <>{children}</>
}
