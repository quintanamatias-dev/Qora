/**
 * Leads API — typed endpoint functions
 *
 * All functions accept clientId as first argument.
 * URL paths match backend FastAPI routes at /api/v1/leads/*.
 */

import { apiFetch } from './client'
import type { Lead, CreateLeadPayload, LeadContextPreview } from './types'

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
    body: JSON.stringify({ ...payload, client_id: clientId }),
  })
}

/**
 * GET /api/v1/leads/:leadId/context-preview
 * Returns structured next-call context preview for a lead (Phase A).
 * Shows what the agent will literally receive — system prompt is not included,
 * only its presence is indicated.
 */
export async function fetchLeadContextPreview(
  _clientId: string,
  leadId: string
): Promise<LeadContextPreview> {
  return apiFetch<LeadContextPreview>(
    `/api/v1/leads/${encodeURIComponent(leadId)}/context-preview`
  )
}
