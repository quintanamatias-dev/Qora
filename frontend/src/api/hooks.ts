/**
 * API Hooks — TanStack Query hooks wrapping endpoint functions
 *
 * REQ-5.3: Each hook uses a stable queryKey including clientId.
 *
 * Design: hooks live in api/hooks.ts for the scaffold phase.
 * In Phase 4 features they will move to src/hooks/queries/*.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from './client'
import { fetchMetrics, fetchCallSessions, fetchTranscript, fetchCallAnalysis } from './calls'
import { fetchLeads, fetchLead, fetchLeadContextPreview, fetchLeadDimensionRollups } from './leads'
import { fetchClient, fetchClients, createClient, updateClient, deactivateClient } from './clients'
import { fetchAgents, createAgent, updateAgent, deactivateAgent, makeAgentDefault } from './agents'
import {
  fetchAnalyticsOverview,
  fetchAnalyticsServiceIssues,
  fetchAnalyticsInterests,
  fetchAnalyticsAgentStats,
} from './analytics'
import {
  fetchIntegrations,
  updateIntegration,
  testIntegrationConnection,
  fetchAvailableIntegrations,
  connectIntegration,
  disconnectIntegration,
  fetchIntegrationFields,
  saveIntegrationMappings,
} from './integrations'
import type {
  CallAnalysis,
  CallMetricsResponse,
  Lead,
  CallSession,
  SessionTranscript,
  Client,
  Agent,
  CreateClientPayload,
  UpdateClientPayload,
  CreateAgentPayload,
  UpdateAgentPayload,
  AnalyticsParams,
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
  IntegrationConfig,
  UpdateIntegrationPayload,
  IntegrationTestResult,
  AvailableIntegration,
  ConnectIntegrationPayload,
  DisconnectResult,
  AirtableFieldsResponse,
  SaveMappingsPayload,
  LeadContextPreview,
  DimensionRollups,
} from './types'

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
 * useLeadContextPreview — fetches the next-call context preview for a lead (Phase A)
 * queryKey: ['lead-context-preview', clientId, leadId]
 * Only loads when leadId is explicitly provided (not auto-loaded with lead).
 */
export function useLeadContextPreview(clientId: string, leadId: string, enabled = true) {
  return useQuery<LeadContextPreview>({
    queryKey: ['lead-context-preview', clientId, leadId],
    queryFn: () => fetchLeadContextPreview(clientId, leadId),
    enabled: Boolean(clientId) && Boolean(leadId) && enabled,
    staleTime: 30_000,
  })
}

/**
 * useLeadDimensionRollups — fetches lead-level dimension rollup counts
 * queryKey: ['lead-dimension-rollups', clientId, leadId]
 *
 * Provides ranked lists for detected interests (interest, #, category),
 * service issues (issue, #, strength), objections, and pain points.
 * All sourced from call_analyses — not CallSession.extracted_facts.
 */
export function useLeadDimensionRollups(clientId: string, leadId: string) {
  return useQuery<DimensionRollups>({
    queryKey: ['lead-dimension-rollups', clientId, leadId],
    queryFn: () => fetchLeadDimensionRollups(clientId, leadId),
    enabled: Boolean(clientId) && Boolean(leadId),
    staleTime: 30_000,
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

/**
 * useCallAnalysis — fetches the full analysis (all 12 dimensions) for a session
 * queryKey: ['call-analysis', sessionId]
 *
 * Returns null (not an error) ONLY when the session genuinely has no analysis (404).
 * Any other failure (500, network, etc.) is rethrown so the UI surfaces a real
 * error state instead of masquerading a server fault as "No analysis available".
 */
export function useCallAnalysis(sessionId: string) {
  return useQuery<CallAnalysis | null>({
    queryKey: ['call-analysis', sessionId],
    queryFn: async () => {
      try {
        return await fetchCallAnalysis(sessionId)
      } catch (err) {
        // 404 means no analysis yet — return null instead of throwing.
        // Every other status (e.g. 500 from a backend/DB fault) MUST surface
        // as an error so we never silently hide existing analysis behind an
        // empty state.
        if (err instanceof ApiError && err.status === 404) {
          return null
        }
        throw err
      }
    },
    enabled: Boolean(sessionId),
    staleTime: 30_000,
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// Admin Query Hooks
// ──────────────────────────────────────────────────────────────────────────────

/**
 * useClients — fetches all clients
 * queryKey: ['clients']
 */
export function useClients() {
  return useQuery<Client[]>({
    queryKey: ['clients'],
    queryFn: fetchClients,
  })
}

/**
 * useAgents — fetches all agents for a client
 * queryKey: ['agents', clientId]
 */
export function useAgents(clientId: string) {
  return useQuery<Agent[]>({
    queryKey: ['agents', clientId],
    queryFn: () => fetchAgents(clientId),
    enabled: Boolean(clientId),
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// Admin Mutation Hooks — Client
// ──────────────────────────────────────────────────────────────────────────────

/**
 * useCreateClient — creates a new client, invalidates ['clients'] on success
 */
export function useCreateClient() {
  const queryClient = useQueryClient()
  return useMutation<Client, Error, CreateClientPayload>({
    mutationFn: createClient,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] })
    },
  })
}

/**
 * useUpdateClient — updates a client, invalidates ['clients'] on success
 */
export function useUpdateClient() {
  const queryClient = useQueryClient()
  return useMutation<Client, Error, { clientId: string; payload: UpdateClientPayload }>({
    mutationFn: ({ clientId, payload }) => updateClient(clientId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] })
    },
  })
}

/**
 * useDeactivateClient — deactivates a client, invalidates ['clients'] on success
 */
export function useDeactivateClient() {
  const queryClient = useQueryClient()
  return useMutation<Client, Error, string>({
    mutationFn: deactivateClient,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] })
    },
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// Admin Mutation Hooks — Agent
// ──────────────────────────────────────────────────────────────────────────────

/**
 * useCreateAgent — creates a new agent, invalidates ['agents', clientId] on success
 */
export function useCreateAgent(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<Agent, Error, CreateAgentPayload>({
    mutationFn: (payload) => createAgent(clientId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', clientId] })
    },
  })
}

/**
 * useUpdateAgent — updates an agent, invalidates ['agents', clientId] on success
 */
export function useUpdateAgent(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<Agent, Error, { agentId: string; payload: UpdateAgentPayload }>({
    mutationFn: ({ agentId, payload }) => updateAgent(clientId, agentId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', clientId] })
    },
  })
}

/**
 * useDeactivateAgent — deactivates an agent, invalidates ['agents', clientId] on success
 */
export function useDeactivateAgent(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<Agent, Error, string>({
    mutationFn: (agentId) => deactivateAgent(clientId, agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', clientId] })
    },
  })
}

/**
 * useMakeAgentDefault — sets agent as default, invalidates ['agents', clientId] on success
 */
export function useMakeAgentDefault(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<Agent, Error, string>({
    mutationFn: (agentId) => makeAgentDefault(clientId, agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', clientId] })
    },
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// Analytics Query Hooks
// ──────────────────────────────────────────────────────────────────────────────

/**
 * useAnalyticsOverview — fetches overview metrics for a client
 * queryKey: ['analytics-overview', clientId, params]
 * Disabled when clientId is empty/undefined.
 */
export function useAnalyticsOverview(clientId: string, params: AnalyticsParams) {
  return useQuery<AnalyticsOverviewResponse>({
    queryKey: ['analytics-overview', clientId, params],
    queryFn: () => fetchAnalyticsOverview(clientId, params),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  })
}

/**
 * useAnalyticsServiceIssues — fetches ranked service issues for a client
 * queryKey: ['analytics-service-issues', clientId, params]
 * Disabled when clientId is empty/undefined.
 */
export function useAnalyticsServiceIssues(clientId: string, params: AnalyticsParams) {
  return useQuery<AnalyticsServiceIssuesResponse>({
    queryKey: ['analytics-service-issues', clientId, params],
    queryFn: () => fetchAnalyticsServiceIssues(clientId, params),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  })
}

/**
 * useAnalyticsInterests — fetches top interests with trends for a client
 * queryKey: ['analytics-interests', clientId, params]
 * Disabled when clientId is empty/undefined.
 */
export function useAnalyticsInterests(clientId: string, params: AnalyticsParams) {
  return useQuery<AnalyticsInterestsResponse>({
    queryKey: ['analytics-interests', clientId, params],
    queryFn: () => fetchAnalyticsInterests(clientId, params),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  })
}

/**
 * useAnalyticsAgentStats — fetches per-agent statistics for a client
 * queryKey: ['analytics-agent-stats', clientId, params]
 * Disabled when clientId is empty/undefined.
 */
export function useAnalyticsAgentStats(clientId: string, params: AnalyticsParams) {
  return useQuery<AnalyticsAgentStatsResponse>({
    queryKey: ['analytics-agent-stats', clientId, params],
    queryFn: () => fetchAnalyticsAgentStats(clientId, params),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  })
}

// ──────────────────────────────────────────────────────────────────────────────
// Integration Hooks
// ──────────────────────────────────────────────────────────────────────────────

/**
 * useIntegrations — fetches all integrations for a client
 * queryKey: ['integrations', clientId]
 * Disabled when clientId is empty/undefined.
 */
export function useIntegrations(clientId: string) {
  return useQuery<IntegrationConfig[]>({
    queryKey: ['integrations', clientId],
    queryFn: () => fetchIntegrations(clientId),
    enabled: Boolean(clientId),
    staleTime: 30_000,
  })
}

/**
 * useUpdateIntegration — updates an integration config, invalidates on success
 */
export function useUpdateIntegration(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<
    IntegrationConfig,
    Error,
    { provider: string; payload: UpdateIntegrationPayload }
  >({
    mutationFn: ({ provider, payload }) => updateIntegration(clientId, provider, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations', clientId] })
    },
  })
}

/**
 * useTestIntegration — tests an integration connection
 * queryKey is not cached — this is a one-shot mutation
 */
export function useTestIntegration(clientId: string) {
  return useMutation<IntegrationTestResult, Error, string>({
    mutationFn: (provider) => testIntegrationConnection(clientId, provider),
  })
}

/**
 * useAvailableIntegrations — fetches all supported providers with connection status
 * queryKey: ['integrations-available', clientId]
 * Disabled when clientId is empty/undefined.
 */
export function useAvailableIntegrations(clientId: string) {
  return useQuery<AvailableIntegration[]>({
    queryKey: ['integrations-available', clientId],
    queryFn: () => fetchAvailableIntegrations(clientId),
    enabled: Boolean(clientId),
    staleTime: 30_000,
  })
}

/**
 * useConnectIntegration — creates a new integration config, invalidates on success
 */
export function useConnectIntegration(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<
    IntegrationConfig,
    Error,
    { provider: string; payload: ConnectIntegrationPayload }
  >({
    mutationFn: ({ provider, payload }) => connectIntegration(clientId, provider, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations-available', clientId] })
      queryClient.invalidateQueries({ queryKey: ['integrations', clientId] })
    },
  })
}

/**
 * useDisconnectIntegration — removes an integration config, invalidates on success
 */
export function useDisconnectIntegration(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<DisconnectResult, Error, string>({
    mutationFn: (provider) => disconnectIntegration(clientId, provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations-available', clientId] })
      queryClient.invalidateQueries({ queryKey: ['integrations', clientId] })
    },
  })
}

export function useIntegrationFields(clientId: string, provider: string, enabled = true) {
  return useQuery<AirtableFieldsResponse>({
    queryKey: ['integration-fields', clientId, provider],
    queryFn: () => fetchIntegrationFields(clientId, provider),
    enabled: Boolean(clientId) && Boolean(provider) && enabled,
    staleTime: 30_000,
  })
}

export function useSaveIntegrationMappings(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation<
    IntegrationConfig,
    Error,
    { provider: string; payload: SaveMappingsPayload }
  >({
    mutationFn: ({ provider, payload }) => saveIntegrationMappings(clientId, provider, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations', clientId] })
      queryClient.invalidateQueries({ queryKey: ['integrations-available', clientId] })
    },
  })
}
