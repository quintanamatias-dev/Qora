/**
 * Leads API — typed endpoint functions
 *
 * All functions accept clientId as first argument.
 * URL paths match backend FastAPI routes at /api/v1/leads/*.
 */

import { apiFetch } from './client'
import type { Lead, CreateLeadPayload, LeadContextPreview, DimensionRollups, CallTriggerResponse } from './types'

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

/**
 * GET /api/v1/leads/:leadId/dimension-rollups?client_id=<clientId>
 * Returns lead-level dimension rollup counts from call_analyses.
 * Provides ranked lists for detected interests, service issues, objections, and pain points.
 * client_id is required by the backend for tenant scoping and ownership verification.
 */
export async function fetchLeadDimensionRollups(
  clientId: string,
  leadId: string
): Promise<DimensionRollups> {
  return apiFetch<DimensionRollups>(
    `/api/v1/leads/${encodeURIComponent(leadId)}/dimension-rollups?client_id=${encodeURIComponent(clientId)}`
  )
}

/**
 * POST /api/v1/clients/{clientId}/leads/{leadId}/call
 * Manually triggers an outbound ElevenLabs/Telnyx call for a lead.
 *
 * Guards (enforced by backend):
 * - 403: ENABLE_OUTBOUND_CALLS flag is off
 * - 409: concurrent active CallSession or in_progress ScheduledCall
 * - 422: lead phone number is not valid E.164
 * - 429: call attempt too soon after last attempt (10-second cooldown)
 *
 * On success returns { status, call_session_id }.
 * On error throws ApiError with the corresponding HTTP status.
 *
 * IMPORTANT: This function must NEVER be called without an explicit operator
 * confirmation step in the UI — real telephony charges apply (~$0.21/min).
 */
export async function triggerCall(
  clientId: string,
  leadId: string
): Promise<CallTriggerResponse> {
  return apiFetch<CallTriggerResponse>(
    `/api/v1/clients/${encodeURIComponent(clientId)}/leads/${encodeURIComponent(leadId)}/call`,
    { method: 'POST' }
  )
}
