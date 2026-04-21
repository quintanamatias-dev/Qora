/**
 * Calls API — typed endpoint functions
 *
 * URL paths match backend FastAPI routes at /api/v1/calls/*.
 */

import { apiFetch } from './client'
import type { CallMetricsResponse, CallSession, SessionTranscript } from './types'

interface MetricsParams {
  date_from?: string
  date_to?: string
}

/**
 * GET /api/v1/calls/metrics?client_id=<clientId>[&date_from=...&date_to=...]
 * Returns call metrics for a client, optionally filtered by date range.
 */
export async function fetchMetrics(
  clientId: string,
  params?: MetricsParams
): Promise<CallMetricsResponse> {
  const qs = new URLSearchParams({ client_id: clientId })
  if (params?.date_from) qs.set('date_from', params.date_from)
  if (params?.date_to) qs.set('date_to', params.date_to)
  return apiFetch<CallMetricsResponse>(`/api/v1/calls/metrics?${qs.toString()}`)
}

/**
 * GET /api/v1/calls?client_id=<clientId>[&lead_id=<leadId>]
 * Returns all call sessions for a client, optionally filtered by lead.
 *
 * REQ-5.3: accepts optional leadId for filtering sessions by lead.
 */
export async function fetchCallSessions(clientId: string, leadId?: string): Promise<CallSession[]> {
  const qs = new URLSearchParams({ client_id: clientId })
  if (leadId) qs.set('lead_id', leadId)
  return apiFetch<CallSession[]>(`/api/v1/calls?${qs.toString()}`)
}

/**
 * GET /api/v1/calls/:sessionId/transcript
 * Returns the transcript for a specific session.
 */
export async function fetchTranscript(sessionId: string): Promise<SessionTranscript> {
  return apiFetch<SessionTranscript>(
    `/api/v1/calls/${encodeURIComponent(sessionId)}/transcript`
  )
}
