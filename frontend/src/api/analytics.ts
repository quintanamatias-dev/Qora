/**
 * Analytics API — typed fetch functions for analytics endpoints
 *
 * All endpoints follow the pattern:
 *   GET /api/v1/analytics/{clientId}/{endpoint}?period=...&[agent_id=...]
 */

import { apiFetch } from './client'
import type {
  AnalyticsParams,
  AnalyticsOverviewResponse,
  AnalyticsServiceIssuesResponse,
  AnalyticsInterestsResponse,
  AnalyticsAgentStatsResponse,
} from './types'

/**
 * Build shared URLSearchParams for analytics endpoints.
 */
function buildAnalyticsParams(params: AnalyticsParams): URLSearchParams {
  const qs = new URLSearchParams({ period: params.period })
  if (params.agentId) qs.set('agent_id', params.agentId)
  if (params.startDate) qs.set('start_date', params.startDate)
  if (params.endDate) qs.set('end_date', params.endDate)
  return qs
}

/**
 * GET /api/v1/analytics/{clientId}/overview
 * Returns aggregated call metrics for the given period.
 */
export async function fetchAnalyticsOverview(
  clientId: string,
  params: AnalyticsParams
): Promise<AnalyticsOverviewResponse> {
  const qs = buildAnalyticsParams(params)
  return apiFetch<AnalyticsOverviewResponse>(
    `/api/v1/analytics/${encodeURIComponent(clientId)}/overview?${qs}`
  )
}

/**
 * GET /api/v1/analytics/{clientId}/service-issues
 * Returns ranked service issues for the given period.
 */
export async function fetchAnalyticsServiceIssues(
  clientId: string,
  params: AnalyticsParams
): Promise<AnalyticsServiceIssuesResponse> {
  const qs = buildAnalyticsParams(params)
  return apiFetch<AnalyticsServiceIssuesResponse>(
    `/api/v1/analytics/${encodeURIComponent(clientId)}/service-issues?${qs}`
  )
}

/**
 * GET /api/v1/analytics/{clientId}/interests
 * Returns top interests with trend direction.
 */
export async function fetchAnalyticsInterests(
  clientId: string,
  params: AnalyticsParams
): Promise<AnalyticsInterestsResponse> {
  const qs = buildAnalyticsParams(params)
  return apiFetch<AnalyticsInterestsResponse>(
    `/api/v1/analytics/${encodeURIComponent(clientId)}/interests?${qs}`
  )
}

/**
 * GET /api/v1/analytics/{clientId}/agent-stats
 * Returns per-agent call statistics.
 */
export async function fetchAnalyticsAgentStats(
  clientId: string,
  params: AnalyticsParams
): Promise<AnalyticsAgentStatsResponse> {
  const qs = buildAnalyticsParams(params)
  return apiFetch<AnalyticsAgentStatsResponse>(
    `/api/v1/analytics/${encodeURIComponent(clientId)}/agent-stats?${qs}`
  )
}
