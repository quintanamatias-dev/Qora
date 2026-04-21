/**
 * Clients API — typed endpoint functions
 *
 * REQ-5.2: Typed functions matching backend API surface for client resources.
 * URL paths match backend FastAPI routes at /api/v1/clients/*.
 */

import { apiFetch } from './client'
import type { Client } from './types'

/**
 * GET /api/v1/clients/:clientId
 * Returns a single client by ID.
 */
export async function fetchClient(clientId: string): Promise<Client> {
  return apiFetch<Client>(`/api/v1/clients/${encodeURIComponent(clientId)}`)
}
