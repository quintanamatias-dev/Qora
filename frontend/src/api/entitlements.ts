/**
 * Entitlements API — plan, effective features/limits and usage per client.
 *
 * Backend: backend/app/entitlements/router.py
 */

import { apiFetch } from './client'
import type { ClientEntitlements, PlanCatalog, UpdateEntitlementsPayload } from './types'

/** GET /api/v1/clients/:clientId/entitlements */
export async function fetchEntitlements(clientId: string): Promise<ClientEntitlements> {
  return apiFetch<ClientEntitlements>(`/api/v1/clients/${encodeURIComponent(clientId)}/entitlements`)
}

/** PUT /api/v1/clients/:clientId/entitlements — superadmin only */
export async function updateEntitlements(
  clientId: string,
  payload: UpdateEntitlementsPayload,
): Promise<ClientEntitlements> {
  return apiFetch<ClientEntitlements>(`/api/v1/clients/${encodeURIComponent(clientId)}/entitlements`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

/** GET /api/v1/entitlements/plans — superadmin only */
export async function fetchPlanCatalog(): Promise<PlanCatalog> {
  return apiFetch<PlanCatalog>('/api/v1/entitlements/plans')
}
