/**
 * RequireAuth — session gate for every route except /login (multi-tenant-auth §9)
 *
 * Loads the caller identity via useMe(); shows a loading state while pending,
 * and redirects to /login?return_to=<current path+search> on a 401. Any other
 * error (network, 5xx) is not an auth answer: if an identity is already known
 * the children keep rendering, otherwise a retryable error state is shown.
 */

import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from '@/api/auth'
import { ApiError } from '@/api/client'
import { Button } from '@/design/components'

export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { data, isLoading, isError, error, refetch, isFetching } = useMe()

  if (isLoading) {
    return (
      <div data-testid="auth-loading" className="flex min-h-screen items-center justify-center bg-pearl">
        <p className="text-sm text-ink-3">Cargando…</p>
      </div>
    )
  }

  if (isError && error instanceof ApiError && error.status === 401) {
    const returnTo = location.pathname + location.search
    return <Navigate to={`/login?return_to=${encodeURIComponent(returnTo)}`} replace />
  }

  if (data) return <>{children}</>

  if (isError) {
    return (
      <div data-testid="auth-error" className="flex min-h-screen flex-col items-center justify-center gap-3 bg-pearl">
        <p className="text-sm text-ink-3">No se pudo verificar la sesión.</p>
        <Button variant="secondary" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          Reintentar
        </Button>
      </div>
    )
  }

  return null
}
