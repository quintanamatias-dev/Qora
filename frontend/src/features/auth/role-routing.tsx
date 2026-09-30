/**
 * Role-based routing (multi-tenant-auth §9):
 *  - `/` and `*` (RoleHome): superadmin → /admin; client → /app/{client_ids[0]}/dashboard
 *  - `/admin/*` (AdminRoleGuard): superadmin only; client → own dashboard
 *  - `/app/:clientId/*` (AppRoleGuard): superadmin any client; client only for a
 *    clientId in their own client_ids, else their own dashboard
 *
 * A client identity with no client_ids is a contract gap (see design.md §4 —
 * mapping only ever produces client_ids: [<one client>] or no session at all).
 * Treated as no access rather than crashing or looping.
 */

import type { ReactNode } from 'react'
import { Navigate, useParams } from 'react-router'
import { useMe } from '@/api/auth'

function ownDashboardOrLogin(clientIds: string[]): string {
  const clientId = clientIds[0]
  return clientId ? `/app/${clientId}/dashboard` : '/login'
}

/** Element for `/` and `*` — sends each role to its home. */
export function RoleHome() {
  const { data } = useMe()
  if (!data) return null
  if (data.role === 'superadmin') return <Navigate to="/admin" replace />
  return <Navigate to={ownDashboardOrLogin(data.client_ids)} replace />
}

export function AdminRoleGuard({ children }: { children: ReactNode }) {
  const { data } = useMe()
  if (!data) return null
  if (data.role !== 'superadmin') {
    return <Navigate to={ownDashboardOrLogin(data.client_ids)} replace />
  }
  return <>{children}</>
}

export function AppRoleGuard({ children }: { children: ReactNode }) {
  const { clientId } = useParams<{ clientId: string }>()
  const { data } = useMe()
  if (!data) return null
  if (data.role === 'superadmin') return <>{children}</>
  if (clientId && data.client_ids.includes(clientId)) return <>{children}</>
  return <Navigate to={ownDashboardOrLogin(data.client_ids)} replace />
}
