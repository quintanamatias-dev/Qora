/**
 * API Hooks — TanStack Query hooks wrapping endpoint functions
 *
 * REQ-5.3: Each hook uses a stable queryKey including clientId.
 *
 * Design: hooks live in api/hooks.ts for the scaffold phase.
 * In Phase 4 features they will move to src/hooks/queries/*.
 */

import { useQuery } from '@tanstack/react-query'
import { fetchMetrics, fetchCallSessions, fetchTranscript } from './calls'
import { fetchLeads, fetchLead } from './leads'
import { fetchClient } from './clients'
import type { CallMetricsResponse, Lead, CallSession, SessionTranscript, Client } from './types'

interface MetricsParams {
  date_from?: string
  date_to?: string
}

/**
 * useMetrics — fetches call metrics for a client
 * queryKey: ['metrics', clientId]
 */
export function useMetrics(clientId: string, params?: MetricsParams) {
  return useQuery<CallMetricsResponse>({
    queryKey: ['metrics', clientId, params],
    queryFn: () => fetchMetrics(clientId, params),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  })
}

/**
 * useLeads — fetches all leads for a client
 * queryKey: ['leads', clientId]
 */
export function useLeads(clientId: string) {
  return useQuery<Lead[]>({
    queryKey: ['leads', clientId],
    queryFn: () => fetchLeads(clientId),
    enabled: Boolean(clientId),
  })
}

/**
 * useLead — fetches a single lead by ID
 * queryKey: ['lead', clientId, leadId]
 */
export function useLead(clientId: string, leadId: string) {
  return useQuery<Lead>({
    queryKey: ['lead', clientId, leadId],
    queryFn: () => fetchLead(clientId, leadId),
    enabled: Boolean(clientId) && Boolean(leadId),
  })
}

/**
 * useCallSessions — fetches call sessions for a client, optionally filtered by leadId
 * queryKey: ['call-sessions', clientId, leadId]
 *
 * REQ-5.3: hook accepts optional leadId parameter to filter sessions by lead.
 */
export function useCallSessions(clientId: string, leadId?: string) {
  return useQuery<CallSession[]>({
    queryKey: ['call-sessions', clientId, leadId],
    queryFn: () => fetchCallSessions(clientId, leadId),
    enabled: Boolean(clientId),
  })
}

/**
 * useClient — fetches a single client by ID
 * queryKey: ['client', clientId]
 *
 * REQ-5.3: client query hook must exist.
 */
export function useClient(clientId: string) {
  return useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => fetchClient(clientId),
    enabled: Boolean(clientId),
  })
}

/**
 * useTranscript — fetches transcript for a session
 * queryKey: ['transcript', sessionId]
 */
export function useTranscript(sessionId: string) {
  return useQuery<SessionTranscript>({
    queryKey: ['transcript', sessionId],
    queryFn: () => fetchTranscript(sessionId),
    enabled: Boolean(sessionId),
  })
}
