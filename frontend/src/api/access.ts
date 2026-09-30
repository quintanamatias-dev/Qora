/**
 * Access admin API — superadmin WorkOS organization linking (multi-tenant-auth §8)
 *
 * URL paths match backend FastAPI routes at
 * /api/v1/clients/{client_id}/access/*.
 */

import { apiFetch } from './client'

export interface AccessMember {
  user_id: string
  email: string
  name: string | null
}

export interface Invitation {
  id: string
  email: string
  state: string
  expires_at: string
}

export interface AccessState {
  organization_id: string | null
  members: AccessMember[]
  invitations: Invitation[]
}

/** GET /api/v1/clients/:clientId/access */
export function fetchAccessState(clientId: string): Promise<AccessState> {
  return apiFetch<AccessState>(`/api/v1/clients/${encodeURIComponent(clientId)}/access`)
}

/** POST /api/v1/clients/:clientId/access/organization — idempotent */
export function linkOrganization(clientId: string): Promise<AccessState> {
  return apiFetch<AccessState>(`/api/v1/clients/${encodeURIComponent(clientId)}/access/organization`, {
    method: 'POST',
  })
}

/** POST /api/v1/clients/:clientId/access/invitations */
export function createInvitation(clientId: string, email: string): Promise<Invitation> {
  return apiFetch<Invitation>(`/api/v1/clients/${encodeURIComponent(clientId)}/access/invitations`, {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

/** DELETE /api/v1/clients/:clientId/access/invitations/:invitationId */
export function revokeInvitation(clientId: string, invitationId: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/access/invitations/${encodeURIComponent(invitationId)}`,
    { method: 'DELETE' },
  )
}
