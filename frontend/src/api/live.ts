/**
 * Live Calls API — typed endpoint function for the "en vivo" dashboard view.
 *
 * URL path matches backend FastAPI route at /api/v1/calls/active.
 * READ-ONLY — never triggers or mutates calls.
 */

import { apiFetch } from './client'

export interface LiveCall {
  session_id: string
  lead_id: string | null
  lead_first_name: string | null
  agent_id: string | null
  agent_name: string | null
  telephony_status: 'queued' | 'dialing' | 'ringing' | 'connected'
  started_at: string
}

export interface LiveRecentFact {
  text: string
  lead_first_name: string | null
  duration_seconds: number | null
}

export interface LiveToday {
  calls_total: number
  completed: number
}

export interface LiveCallsResponse {
  server_time: string
  calls: LiveCall[]
  /** True number of in-flight sessions; `calls` is capped server-side. */
  active_total: number
  today: LiveToday
  recent_facts: LiveRecentFact[]
  memory_total: number
}

/**
 * GET /api/v1/calls/active?client_id=<clientId>
 * Returns in-flight call sessions and today's counters for the live view.
 */
export async function fetchActiveCalls(clientId: string): Promise<LiveCallsResponse> {
  const qs = new URLSearchParams({ client_id: clientId })
  return apiFetch<LiveCallsResponse>(`/api/v1/calls/active?${qs.toString()}`)
}
