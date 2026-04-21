/**
 * Leads API — typed endpoint functions
 *
 * All functions accept clientId as first argument.
 * URL paths match backend FastAPI routes at /api/v1/leads/*.
 */

import { apiFetch } from './client'
import type { Lead, CreateLeadPayload } from './types'

/**
 * GET /api/v1/leads?client_id=<clientId>
 * Returns all leads for a client.
 */
export async function fetchLeads(clientId: string): Promise<Lead[]> {
  return apiFetch<Lead[]>(`/api/v1/leads?client_id=${encodeURIComponent(clientId)}`)
}

/**
 * GET /api/v1/leads/:leadId
 * Returns a single lead by ID.
 */
export async function fetchLead(clientId: string, leadId: string): Promise<Lead> {
  return apiFetch<Lead>(
    `/api/v1/leads/${encodeURIComponent(leadId)}?client_id=${encodeURIComponent(clientId)}`
  )
}

/**
 * POST /api/v1/leads?client_id=<clientId>
 * Creates a new lead for a client.
 */
export async function createLead(
  clientId: string,
  payload: CreateLeadPayload
): Promise<Lead> {
  return apiFetch<Lead>(`/api/v1/leads?client_id=${encodeURIComponent(clientId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
